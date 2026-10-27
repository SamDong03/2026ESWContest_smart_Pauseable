import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = path.dirname(fileURLToPath(import.meta.url));
const esc = value => String(value).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const text = (x, y, value, size = 16, color = '#263e35', weight = 400) =>
  `<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-weight="${weight}">${esc(value)}</text>`;

// Original line pictograms keep the overview self-contained and font-independent.
function icon(kind, x, y, color) {
  const shapes = {
    home: '<path d="M3 19L22 3l19 16M8 15v27h28V15M18 42V28h9v14"/>',
    analysis: '<path d="M5 42V5M5 42h36M12 32l8-12 8 6L40 9"/><circle cx="20" cy="20" r="3"/><circle cx="28" cy="26" r="3"/>',
    central: '<rect x="9" y="9" width="28" height="28" rx="4"/><path d="M17 2v7m12-7v7M17 37v7m12-7v7M2 17h7m-7 12h7m28-12h7m-7 12h7M16 24l5 5 10-12"/>',
    output: '<path d="M3 20h8l11-9v30l-11-9H3zM27 18a12 12 0 010 16"/><rect x="35" y="5" width="16" height="37" rx="3"/><path d="M41 36h4"/>',
  };
  return `<g transform="translate(${x} ${y})" fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">${shapes[kind]}</g>`;
}

export async function buildOverview() {
  const stages = [
    { x: 28, n: '01', label: '생활 정보 수집', icon: 'home', color: '#29634c', fill: '#edf6ef',
      title: '가전 상태 · 실내 이동', lines: ['Home Assistant 상태 변경', 'mmWave 위치 · 추적 정보'], note: '관측 시각과 품질도 기록' },
    { x: 308, n: '02', label: '행동 분석', icon: 'analysis', color: '#31658f', fill: '#eef4fa',
      title: '반복행동 · 배회 의심', lines: ['가전: Baseline + IF · AE', '이동: 경로 형태 · 개인 이력'], note: '두 파이프라인은 독립 실행' },
    { x: 588, n: '03', label: '실행 결정', icon: 'central', color: '#245c45', fill: '#e8f2eb',
      title: 'Pi 5 / Central App', lines: ['출처 · 시각 · 중복 검사', 'Action Router로 출력 결정'], note: '잘못된 입력 · 재실행 제한' },
    { x: 868, n: '04', label: '안내와 보호자 연결', icon: 'output', color: '#147d80', fill: '#edf7f7',
      title: '음성 · 가전 · 앱', lines: ['Piper TTS · 가전 요청', 'API → Flutter 알림 · 이력'], note: '각 장치의 실제 출력 확인' },
  ];
  let body = text(28, 40, 'Memolink, 한눈에 보는 동작 흐름', 25, '#203b30', 700);
  body += text(28, 69, '생활 이력을 분석하고, 실행 조건을 확인한 뒤 안내와 보호자 연결로 이어집니다.', 15, '#60766c');
  body += '<path d="M28 91H1112" stroke="#d4e2d9"/>';
  for (const stage of stages) {
    const { x, color, fill } = stage;
    body += text(x, 124, `${stage.n}  ${stage.label}`, 16, color, 700);
    body += `<rect x="${x}" y="144" width="244" height="244" rx="6" fill="${fill}" stroke="#d4e2d9"/>`;
    body += icon(stage.icon, x + 20, 163, color);
    body += text(x + 20, 242, stage.title, 18, '#203b30', 700);
    stage.lines.forEach((line, index) => { body += text(x + 20, 280 + index * 27, line, 14.5); });
    body += `<path d="M${x + 20} 330H${x + 224}" stroke="#cdded4"/>`;
    body += text(x + 20, 362, stage.note, 13, '#60766c');
    if (stage.n !== '04') body += `<path d="M${x + 249} 263h24" stroke="#78988a" stroke-width="2" marker-end="url(#arrow)"/>`;
  }
  body += text(28, 432, '함께 연결되는 기능', 17, '#203b30', 700);
  body += text(28, 462, '출입 사진', 15, '#31658f', 700) + text(145, 462, 'Pi 4 카메라 → API → 보호자 앱', 15);
  body += text(600, 462, '환경 조명', 15, '#147d80', 700) + text(717, 462, '거주지역 · 날씨 · 태양 고도 → HA 조명', 15);
  body += text(28, 496, '보호자 음성', 15, '#29634c', 700) + text(145, 496, '동의 · 녹음 → GPU 학습 → 검증한 ONNX → Pi TTS', 15);
  body += text(28, 537, '작품 Memolink · 개발팀 PAUSEABLE', 12, '#60766c');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1140" height="562" viewBox="0 0 1140 562" role="img" aria-labelledby="title desc"><title id="title">Memolink 동작 개요 · 개발팀 PAUSEABLE</title><desc id="desc">가전과 이동 정보 수집, 독립 행동 분석, Central 검증과 실행 결정, 음성·가전·보호자 앱 연결. 카메라·환경 조명·음성 학습은 별도 경로입니다.</desc><defs><marker id="arrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0L6 3L0 6Z" fill="#78988a"/></marker></defs><rect width="1140" height="562" rx="8" fill="#f8fbf9"/><g font-family="'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', Arial, sans-serif">${body}</g></svg>\n`;
  await fs.writeFile(path.join(directory, 'memolink-overview.svg'), svg);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await buildOverview();
