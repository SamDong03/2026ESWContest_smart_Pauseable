

import argparse
import json
from pathlib import Path

from tools.verify_native_push import VerificationError, call_api, load_config
from tools.api_paths import add_api_to_path

add_api_to_path()

from app.local_render_proxy import RENDER_URL
from urllib import request, error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('render-web.secrets.json'))
    parser.add_argument('--remember', action='store_true')
    parser.add_argument('--restore-if-empty', action='store_true')
    args = parser.parse_args()
    try:
        base_url, patient_id, app_token = load_config(args.config)
        if base_url != RENDER_URL:
            raise VerificationError('Use the existing Render server')
        url = f'{base_url}/api/patients/{patient_id}/home-environment'
        current = call_api(url, app_token, 90)
        backup = Path('build/render-home-region-backup.json')
        if args.remember and current.get('region'):
            backup.parent.mkdir(exist_ok=True)
            backup.write_text(json.dumps({
                'patient_id': patient_id,
                'region_code': current['region']['code'],
                'auto_lighting_enabled': current.get('auto_lighting_enabled', False),
            }), encoding='utf-8')
        restored = False
        if args.restore_if_empty and current.get('region') is None and backup.is_file():
            saved = json.loads(backup.read_text(encoding='utf-8'))
            if saved.pop('patient_id') != patient_id:
                raise VerificationError('Backup patient does not match')
            update = request.Request(url, method='PUT', data=json.dumps(saved).encode(), headers={
                'Authorization': f'Bearer {app_token}', 'Content-Type': 'application/json',
            })
            from tools.verify_native_push import NoRedirect
            with request.build_opener(NoRedirect()).open(update, timeout=90) as response:
                if response.status != 200:
                    raise VerificationError('Region restore was not accepted')
            current = call_api(url, app_token, 90)
            restored = (current.get('region') or {}).get('code') == saved['region_code']
            if not restored:
                raise VerificationError('Region read-back did not match')
        print(json.dumps({
            'authenticated': True,
            'region_selected': current.get('region') is not None,
            'storage_backend': current.get('storage_backend', 'legacy-local'),
            'is_persistent': current.get('is_persistent', False),
            'restored_existing_region': restored,
        }))
    except (VerificationError, OSError, ValueError, KeyError, error.URLError):
        parser.exit(1, 'Render verification failed. Check the saved app config and connection. No credentials were printed.\n')


if __name__ == '__main__':
    main()
