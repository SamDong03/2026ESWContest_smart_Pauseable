from pathlib import Path
import hashlib
import json
import re
import sys
import zipfile

from lxml import etree as E
from pypdf import PdfReader

BUILD = Path(__file__).parent
PPTX, PDF = map(Path, sys.argv[1:3])
D = json.loads((BUILD / 'visual_data.json').read_text(encoding='utf-8'))
B = json.loads((BUILD / 'baseline_comparison.json').read_text(encoding='utf-8'))
specs = json.loads((BUILD / 'chart_specs.json').read_text(encoding='utf-8'))
NS = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart'}
with zipfile.ZipFile(PPTX) as archive:
    slide_parts = [n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)]
    assert len(slide_parts) == 5
    texts = []
    for part in slide_parts:
        root = E.fromstring(archive.read(part))
        texts.append(''.join(root.xpath('.//a:t/text()', namespaces=NS)))
    assert all('Pauseable' not in value for value in texts)
    assert all(not re.search(r'\d+\s*창', value) for value in texts)
    assert all(not re.search(r'(?<!\d)1/[67](?!\d)', value) for value in texts)
    assert '1일차' in texts[1] and '2일차' in texts[1]
    assert '개인화 적용 결과와 실사용 전 개선 과제' in texts[4]
    assert '검증된 운용 기능' in texts[4] and '실사용 전 개선 과제' in texts[4]
    assert '핵심 프로그램과 역할' not in texts[4]
    assert 'collect_ha_events_ws.py' not in texts[4]
    assert not E.fromstring(archive.read('ppt/slides/slide5.xml')).findall('.//a:tbl', NS)
    assert 'Baseline 설정 근거와 IF·AE 보완 구조' in texts[2]
    assert '임상 타당성은 미검증' in texts[2]
    assert 'Baseline 대비 IF·AE 추가 효과와 한계' in texts[3]
    checks = []
    for i, spec in enumerate(specs, 1):
        root = E.fromstring(archive.read(f'ppt/slides/charts/chart{i}.xml'))
        series = root.findall('.//c:ser', NS)
        assert len(series) == len(spec['series'])
        for source, native in zip(spec['series'], series):
            tag = 'yVal' if spec['type'] == 'scatter' else 'val'
            values = native.findall(f'c:{tag}/c:numRef/c:numCache/c:pt/c:v', NS)
            if not values:
                values = native.findall(f'c:{tag}/c:numLit/c:pt/c:v', NS)
            got = [float(value.text) for value in values]
            assert got == source['values'], (i, source['name'])
            if spec['type'] == 'scatter':
                values = native.findall('c:xVal/c:numRef/c:numCache/c:pt/c:v', NS)
                if not values:
                    values = native.findall('c:xVal/c:numLit/c:pt/c:v', NS)
                assert [float(value.text) for value in values] == source['xValues']
        checks.append({'chart': i, 'title': spec['title'], 'series': len(series)})
    matrices = E.fromstring(archive.read('ppt/slides/slide2.xml')).findall('.//a:tbl', NS)
    assert len(matrices) == 4
    assert len(matrices[0].findall('a:tr', NS)) == 8
    assert len(matrices[2].findall('a:tr', NS)) == 54
    assert all(len(row.findall('a:tc', NS)) == 48 for row in matrices[2].findall('a:tr', NS))
    timelines = E.fromstring(archive.read('ppt/slides/slide4.xml')).findall('.//a:tbl', NS)
    assert len(timelines) == 1 and len(timelines[0].findall('a:tr', NS)) == 4
    assert all(len(row.findall('a:tc', NS)) == 61 for row in timelines[0].findall('a:tr', NS))
    palette = {0: 'ADD9CC', 1: 'E6C45F', 2: 'DF9677'}
    for method, row in zip(['baseline', 'baseline_if', 'baseline_ae', 'hybrid'], timelines[0].findall('a:tr', NS)):
        actual = [cell.find('a:tcPr/a:solidFill/a:srgbClr', NS).get('val').upper() for cell in row.findall('a:tc', NS)]
        assert actual == [palette[value] for value in B['fridge']['five_minute_rechecks']['methods'][method]['timeline']]

reader = PdfReader(PDF)
assert len(reader.pages) == 5
pdf_text = '\n'.join(page.extract_text() or '' for page in reader.pages)
assert 'Pauseable' not in pdf_text
assert '합성' in pdf_text and '428' in pdf_text
assert not re.search(r'\d+\s*창', pdf_text)
assert sum(sum(row) for row in D['heatmaps']['event_matrix']) == 52
assert [sum(row) for row in D['heatmaps']['event_matrix']] == [12, 8, 12, 3, 3, 4, 4, 6]
assert D['repeat_decision_counts'] == {'normal': 5, 'attention': 25, 'risk': 31}
assert D['scenario_summary']['levels'] == {'normal': 36, 'attention': 16, 'risk': 38, 'unavailable': 6}
assert sum(D['scenario_summary']['levels'].values()) == 96
assert '사용 기술과 역할' not in pdf_text
assert not re.search(r'(?<!\d)1/[67](?!\d)', re.sub(r'\s+', '', pdf_text))
compact_pdf_text = re.sub(r'\s+', '', pdf_text)
assert '1일차' in compact_pdf_text and '2일차' in compact_pdf_text
assert D['optimizer']['iterations'] == 337
assert D['before_counts'] == {'normal': 564, 'attention': 6, 'risk': 6}
assert D['after_counts'] == {'normal': 570, 'risk': 6}
methods = ['baseline', 'baseline_if', 'baseline_ae', 'hybrid']
assert [B['fridge']['five_minute_rechecks']['methods'][m]['first_alert_elapsed_minutes'] for m in methods] == [26,26,5,5]
assert [B['families']['repetition_hypothesis'][m]['alert_cases'] for m in methods] == [16,18,24,24]
assert [B['families']['benign_context'][m]['alert_cases'] for m in methods] == [22,28,30,30]
assert B['same_repetition_gate'] and B['frozen_hybrid_reproduced_for_all_cases']
result = {
    'slides': 5, 'pdf_pages': 5, 'native_chart_values_match': checks,
    'heatmap_dimensions': [[8, 48], [54, 48]],
    'visible_pauseable_removed': True, 'awkward_window_units_removed': True,
    'example_calendar_dates_replaced_by_relative_days': True,
    'last_page_content': 'Personalization result, application conditions, verified operation and remaining validation; source-file table removed.',
    'baseline_comparison': {'same_repetition_gate': True, 'first_alert_minutes': [26,26,5,5],
                            'repetition_alert_cases': [16,18,24,24], 'benign_alert_cases': [22,28,30,30],
                            'clinical_validation': False},
    'pptx_sha256': hashlib.sha256(PPTX.read_bytes()).hexdigest(),
    'pdf_sha256': hashlib.sha256(PDF.read_bytes()).hexdigest(),
    'claim_boundary': 'Source-data and structure checks. Native visual review recorded separately.'
}
(BUILD / 'deliverable_checks.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
