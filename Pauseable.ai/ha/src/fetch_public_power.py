
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def fetch(url, destination, *, max_bytes, citation, license_name, partial=False):
    if urlparse(url).scheme != 'https' or max_bytes <= 0:
        raise ValueError('Use HTTPS and a positive byte limit')
    path = Path(destination)
    if path.exists() or path.with_suffix(path.suffix + '.source.json').exists():
        raise ValueError('Use a new download path')
    request = Request(url, headers={'User-Agent': 'HA-Public-Data-Research/1.0', 'Accept-Encoding': 'identity'})
    with urlopen(request, timeout=90) as response:
        data = response.read(max_bytes + 1)
        content_type = response.headers.get('Content-Type', '')
        if 'text/html' in content_type or data.lstrip().lower().startswith((b'<!doctype html', b'<html')):
            raise ValueError('Server returned HTML, not data')
        truncated = len(data) > max_bytes
        if truncated and not partial:
            raise ValueError('File exceeds byte limit; increase it or explicitly request a text prefix')
        if truncated:
            data = data[:max_bytes]
            newline = data.rfind(b'\n')
            if newline < 0:
                raise ValueError('No complete text lines within the byte limit')
            data = data[:newline + 1]
        metadata = {'requested_url': url, 'resolved_url': response.url,
                    'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
                    'server_content_length': response.headers.get('Content-Length'),
                    'etag': response.headers.get('ETag'), 'last_modified': response.headers.get('Last-Modified'),
                    'selection': 'first_complete_lines_byte_limited' if truncated else 'complete_file',
                    'partial': truncated, 'byte_limit': max_bytes, 'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest(), 'citation': citation,
                    'license': license_name, 'source_type': 'public'}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(data)
    path.with_suffix(path.suffix + '.source.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps(metadata, indent=2))
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-bytes', type=int, default=8_000_000)
    parser.add_argument('--citation', required=True)
    parser.add_argument('--license', required=True)
    parser.add_argument('--text-prefix', action='store_true')
    args = parser.parse_args()
    fetch(args.url, args.output, max_bytes=args.max_bytes, citation=args.citation,
          license_name=args.license, partial=args.text_prefix)


if __name__ == '__main__':
    main()
