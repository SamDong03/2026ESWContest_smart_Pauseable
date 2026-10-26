

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import os

import uvicorn

from tools.api_paths import add_api_to_path

add_api_to_path()

from app.local_render_proxy import LocalRenderSettings, RENDER_URL, create_local_render_proxy
from tools.verify_native_push import VerificationError, load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('render-web.secrets.json'))
    parser.add_argument('--port', type=int, default=18108)
    parser.add_argument('--flutter', default=shutil.which('flutter'))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--build', action='store_true', help='Build Flutter, then serve')
    modes.add_argument('--build-only', action='store_true', help='Prepare the token-free-of-Render web build')
    args = parser.parse_args()
    project = Path.cwd()
    build = project / 'build'
    session_file = build / 'local-render-session.json'
    if not 1024 <= args.port <= 65535:
        parser.error('Use an unprivileged loopback port')
    try:
        if args.build_only:

            patient_id, upstream_token = 'byunwoojin', ''
        else:
            base_url, patient_id, upstream_token = load_config(args.config)
            if base_url != RENDER_URL:
                raise VerificationError('Use the existing PAUSEABLE Render service')
        if args.build or args.build_only:
            if not args.flutter:
                raise VerificationError('Flutter SDK was not found; pass --flutter PATH')
            local_token = secrets.token_urlsafe(32)
            defines = {
                'API_BASE_URL': f'http://127.0.0.1:{args.port}',
                'PATIENT_ID': patient_id,
                'APP_TOKEN': local_token,
            }
            build.mkdir(exist_ok=True)
            defines_file = build / 'local-render.defines.json'
            defines_file.write_text(json.dumps(defines), encoding='utf-8')
            subprocess.run([
                args.flutter, 'build', 'web', '--release', '--no-pub',
                f'--dart-define-from-file={defines_file}',
            ], check=True, shell=os.name == 'nt')

            session_file.write_text(json.dumps(defines), encoding='utf-8')
            if args.build_only:
                print('Web build ready. No Render app token was bundled.')
                return
        session = json.loads(session_file.read_text(encoding='utf-8'))
        if (session['API_BASE_URL'] != f'http://127.0.0.1:{args.port}'
                or session['PATIENT_ID'] != patient_id):
            raise VerificationError('Rebuild the preview for this port and patient')
        settings = LocalRenderSettings(
            patient_id=patient_id, upstream_token=upstream_token,
            local_token=session['APP_TOKEN'], port=args.port,
        )
    except (VerificationError, OSError, ValueError, KeyError, subprocess.CalledProcessError):
        parser.exit(1, 'Preview setup failed. Check the private config and Flutter build; credentials are never printed.\n')
    print(f'Local preview: {settings.origin} -> {RENDER_URL}')
    print('Loopback/team testing only. Do not expose this server to a network or public tunnel.')
    uvicorn.run(
        create_local_render_proxy(settings, project / 'build/web'),
        host='127.0.0.1', port=args.port, access_log=False, proxy_headers=False,
    )


if __name__ == '__main__':
    main()
