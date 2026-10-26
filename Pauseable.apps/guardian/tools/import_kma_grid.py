

import hashlib
import json
import sys
from pathlib import Path

import openpyxl


def extract(path: Path) -> dict:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    headers = next(rows)
    expected = ('행정구역코드', '1단계', '2단계', '3단계', '격자 X', '격자 Y')
    if tuple(headers[1:7]) != expected:
        raise ValueError(f'Unexpected KMA columns: {headers[:7]}')
    regions = []
    for row in rows:
        if not row[1] or not row[2]:
            continue
        regions.append({
            'code': str(row[1]).strip(),
            'province': str(row[2]).strip(),
            'city': str(row[3] or '').strip(),
            'district': str(row[4] or '').strip(),
            'nx': int(row[5]), 'ny': int(row[6]),
            'longitude': float(row[13]), 'latitude': float(row[14]),
        })
    if len({r['code'] for r in regions}) != len(regions):
        raise ValueError('Duplicate region codes')
    sheet_name = sheet.title
    workbook.close()
    return {
        'source': path.name, 'sheet': sheet_name,
        'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'regions': regions,
    }


if __name__ == '__main__':
    print(json.dumps(extract(Path(sys.argv[1])), ensure_ascii=True, separators=(',', ':')))
