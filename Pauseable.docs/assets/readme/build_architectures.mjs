import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { systemArchitecture } from './build_system_architecture.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const font = "'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', Arial, sans-serif";
const colors = {
  ink: '#21372d', muted: '#56685e', line: '#778b80',
  green: '#38734b', greenBg: '#eaf4e7', greenLine: '#a9cda2',
  blue: '#376a9d', blueBg: '#eaf1fc', blueLine: '#adc4e4',
  amber: '#93611e', amberBg: '#fff3db', amberLine: '#dfc999',
  violet: '#79578f', violetBg: '#f3edf8', violetLine: '#c8b3d8',
};
const escape = value => String(value).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const label = (x, y, value, size = 18, fill = colors.ink, weight = 400, anchor = 'start') =>
  `<text x="${x}" y="${y}" font-size="${size}" fill="${fill}" font-weight="${weight}" text-anchor="${anchor}">${escape(value)}</text>`;

function rect(x, y, w, h, fill, stroke = 'none', radius = 8) {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="1.3"/>`;
}

function group(x, y, w, h, title, detail, tone) {
  return rect(x, y, w, h, colors[`${tone}Bg`], colors[`${tone}Line`], 16) +
    label(x + 24, y + 40, title, 25, colors[tone], 700) +
    label(x + 24, y + 68, detail, 17, colors.muted) +
    `<path d="M${x + 24} ${y + 86}H${x + w - 24}" stroke="${colors[`${tone}Line`]}"/>`;
}

function box(x, y, w, h, title, lines = [], tone = 'green', options = {}) {
  const { titleSize = 22, bodySize = 17, bodyTop = 66, lineHeight = 25 } = options;
  return rect(x, y, w, h, '#fff', colors[`${tone}Line`]) +
    label(x + 18, y + 34, title, titleSize, colors.ink, 700) +
    lines.map((line, i) => label(x + 18, y + bodyTop + i * lineHeight, line, bodySize, colors.muted)).join('');
}

const arrow = (d, tone = 'green', dashed = false) =>
  `<path d="${d}" fill="none" stroke="${colors[tone]}" stroke-width="2.2" stroke-linejoin="round" ${dashed ? 'stroke-dasharray="7 5"' : ''} marker-end="url(#arrow-${tone})"/>`;

function svg(w, h, title, description, content) {
  const markers = ['green', 'blue', 'amber', 'violet'].map(tone =>
    `<marker id="arrow-${tone}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8Z" fill="${colors[tone]}"/></marker>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-labelledby="title desc"><title id="title">${escape(title)}</title><desc id="desc">${escape(description)}</desc><defs>${markers}</defs><rect width="${w}" height="${h}" fill="#fff"/><g font-family="${font}">${content}</g></svg>\n`;
}

export function aiArchitecture() {
  let body = label(32, 47, 'Memolink AI 분석 · 음성 학습 구조', 32, colors.ink, 700) +
    label(1408, 47, '개발팀 PAUSEABLE', 19, colors.muted, 700, 'end') +
    label(32, 79, '반복행동·배회 판단과 개인화 음성 학습을 서로 독립된 파이프라인으로 구성합니다.', 19, colors.muted);
  const pipelines = [
    { x: 32, tone: 'green', title: '가전 반복행동', detail: 'Home Assistant · Pi 5 / Python', steps: [
      ['가전 상태 수집', ['state_changed · WebSocket']],
      ['시간 구간별 특징 생성', ['최근 10분 · 30분 · 1시간 · 2시간']],
      ['반복행동 판단', ['Baseline + IF + AE', '반복 증거 · 관측 품질 · 개인 생활패턴']],
      ['판단 결과 전송', ['MQTT · repetitive-ai · 공통 JSON']],
    ] },
    { x: 500, tone: 'blue', title: '배회 의심 판단', detail: 'mmWave · Pi 5 / Python', steps: [
      ['위치 · 이동 정보 수신', ['ESP32 / LD6004 → Pi 3 중계']],
      ['이동 경로 특징 생성', ['경로 형태 · 재방문 · 개인 이력']],
      ['지속성 · 관측 품질 확인', ['일시적 형태 점수와 지속 상황 구분']],
      ['판단 결과 전송', ['MQTT · wandering-ai · 공통 JSON']],
    ] },
    { x: 968, tone: 'violet', title: '개인화 음성', detail: 'GPU Worker 학습 → Pi 5 적용', steps: [
      ['보호자 녹음 · 동의', ['WAV 형식 · 대본 · 녹음 정보 검사']],
      ['GPU 음성 학습', ['Piper fine-tuning']],
      ['모델 변환 · 검증', ['ONNX · JSON · 샘플 음성']],
      ['Pi 5 모델 배포', ['다운로드 · 검증 후 활성 모델 교체']],
    ] },
  ];
  for (const pipeline of pipelines) {
    body += group(pipeline.x, 112, 440, 620, pipeline.title, pipeline.detail, pipeline.tone);
    pipeline.steps.forEach(([title, lines], i) => {
      const y = 220 + i * 128;
      const h = 96;
      body += box(pipeline.x + 24, y, 392, h, title, lines, pipeline.tone,
        { bodyTop: lines.length > 1 ? 61 : 66, lineHeight: 23, titleSize: 23, bodySize: 17 });
      if (i < pipeline.steps.length - 1) body += arrow(`M${pipeline.x + 220} ${y + h}V${y + 128}`, pipeline.tone);
    });
  }
  body += `<path d="M252 700V764H486" fill="none" stroke="${colors.green}" stroke-width="2.2"/>` +
    `<path d="M720 700V764H486" fill="none" stroke="${colors.blue}" stroke-width="2.2"/>` + arrow('M486 764V796');
  body += label(486, 753, 'MQTT / JSON', 17, colors.muted, 400, 'middle');
  body += rect(32, 796, 908, 88, '#254e3c', '#254e3c', 10) +
    label(56, 831, 'Central · 검증 후 실행', 25, '#fff', 700) +
    label(56, 862, '계약 · 시각 · 중복 · 실행 정책 확인 → 음성 안내 · 가전 제어 · 보호자 알림', 18, '#e6f1e7');
  body += arrow('M1188 700V796', 'violet', true) +
    rect(968, 796, 440, 88, colors.violetBg, colors.violetLine, 10) +
    label(992, 831, 'Pi 5 · Piper TTS', 25, colors.violet, 700) +
    label(992, 862, '검증한 음성 모델로 로컬 합성', 18, colors.muted);
  return svg(1440, 916, 'Memolink AI 분석과 음성 학습 구조 · 개발팀 PAUSEABLE',
    '가전 반복행동과 배회 판단은 각 MQTT 메시지로 Central에 전달됩니다. 개인화 음성은 GPU에서 학습한 모델을 Pi 5에서 검증 후 사용합니다.', body);
}

export { systemArchitecture };

export async function buildArchitectures() {
  await fs.writeFile(path.join(here, 'ai-pipelines.svg'), aiArchitecture());
  await fs.writeFile(path.join(here, '..', 'pauseable-system.svg'), systemArchitecture());
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await buildArchitectures();
  console.log('Generated Korean AI and system architecture diagrams.');
}
