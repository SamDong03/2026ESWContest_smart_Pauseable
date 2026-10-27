import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const brands = JSON.parse(fs.readFileSync(path.join(here, 'brand-icons.json'), 'utf8'));
const C = {
  ink: '#20392f', muted: '#566c60', rule: '#c4d5cb',
  green: '#39714e', greenBg: '#eef6eb', greenBorder: '#a5c69c',
  blue: '#35678d', blueBg: '#edf3fb', blueBorder: '#aec5df',
  amber: '#92651c', amberBg: '#fff7e6', amberBorder: '#dfc48b',
  teal: '#267b7b', tealBg: '#edf7f5', tealBorder: '#a9ceca',
  violet: '#795b94', violetBg: '#f5f0f9', violetBorder: '#c8b6d9',
};
const esc = value => String(value).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const rect = (x, y, w, h, fill, stroke, radius = 9, id = '') => `<rect ${id ? `id="${id}"` : ''} x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="1.4"/>`;
const text = (x, y, value, size = 20, color = C.ink, weight = 400, width = 1000, anchor = 'start') =>
  `<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-weight="${weight}" text-anchor="${anchor}" data-max-width="${width}">${esc(value)}</text>`;
function logo(slug, x, y, size = 28, fill) {
  const icon = brands.icons[slug];
  if (!icon) throw new Error('Unknown brand: ' + slug);
  return `<g data-brand="${slug}" transform="translate(${x} ${y}) scale(${size / 24})"><path fill="${fill || '#' + icon.hex}" d="${esc(icon.path)}"/></g>`;
}
function panel(x, y, w, h, title, detail, tone, brand) {
  return rect(x, y, w, h, C[tone + 'Bg'], C[tone + 'Border'], 23) +
    (brand ? logo(brand, x + 24, y + 23, 32) : '') +
    text(x + (brand ? 68 : 24), y + 46, title, 26, C.ink, 700, w - (brand ? 92 : 48)) +
    text(x + 24, y + 76, detail, 17, C.muted, 400, w - 48) +
    `<path d="M${x + 24} ${y + 89}H${x + w - 24}" stroke="${C[tone + 'Border']}"/>`;
}
function card(id, x, y, w, h, title, lines, tone, brand, size = 23, bodySize = 18) {
  return rect(x, y, w, h, '#fff', C[tone + 'Border'], 9, id) +
    (brand ? logo(brand, x + 18, y + 17, 28) : '') +
    text(x + (brand ? 58 : 18), y + 38, title, size, C.ink, 700, w - (brand ? 76 : 36)) +
    lines.map((line, i) => text(x + 18, y + 73 + i * 26, line, bodySize, C.muted, 400, w - 36)).join('');
}
const line = (d, tone = 'green', both = false, dashed = false) => `<path d="${d}" fill="none" stroke="${C[tone]}" stroke-width="2.2" stroke-linejoin="round" ${dashed ? 'stroke-dasharray="7 5"' : ''} ${both ? `marker-start="url(#arrow-${tone})"` : ''} marker-end="url(#arrow-${tone})"/>`;
function laneCard(id, x, y, w, title, detail, tone, brand) {
  return rect(x, y, w, 70, '#fff', C[tone + 'Border'], 8, id) +
    (brand ? logo(brand, x + 14, y + 12, 24) : '') +
    text(x + (brand ? 49 : 16), y + 30, title, 20, C.ink, 700, w - (brand ? 65 : 32)) +
    text(x + 16, y + 56, detail, 17, C.muted, 400, w - 32);
}

export function systemArchitecture() {
  let b = text(24, 55, 'Memolink', 34, C.ink, 700, 180) + '<path d="M216 27V63" stroke="#bdcfc3"/>';
  b += text(244, 55, '시스템 아키텍처', 29, C.ink, 700, 500);
  b += text(1576, 35, '개발팀', 15, C.muted, 400, 140, 'end') + text(1576, 61, 'PAUSEABLE', 23, C.ink, 700, 200, 'end');
  b += text(24, 89, '가전과 이동 정보를 Pi 5에서 분석하고, 검증한 판단을 음성·가전·보호자 앱으로 연결합니다.', 20, C.muted, 400, 1520);

  b += panel(24, 112, 292, 702, '가전 · 센서 입력', '스마트 가전 · 실내 이동', 'green');
  b += panel(364, 112, 766, 702, 'Raspberry Pi 5 · Atlas', 'Python / Docker · C++ Central · CSV / SQLite', 'blue', 'raspberrypi');
  b += logo('python', 1014, 140, 24) + logo('docker', 1052, 140, 24) + logo('cplusplus', 1090, 140, 24);
  b += panel(1178, 112, 398, 430, 'API · 학습 · 저장', 'Render · Cloudflare R2 · GPU Worker', 'amber');
  b += rect(1178, 586, 398, 228, C.tealBg, C.tealBorder, 23);
  b += logo('flutter', 1202, 606, 34) + text(1250, 635, 'Flutter 보호자 앱', 26, C.ink, 700, 304);

  // Inter-panel routes stay in the gutters; photos and voice models use separate lanes below.
  b += line('M292 277H388') + text(340, 259, '연동', 17, C.green, 400, 44, 'middle');
  b += line('M170 518V598') + text(188, 564, 'UART / USB', 17, C.green, 400, 112);
  b += line('M292 654H340V437H388', 'blue');
  b += line('M340 607H388', 'blue', false, true) + text(364, 590, 'UDP', 15, C.blue, 400, 38, 'middle');
  b += line('M656 277H720', 'blue');
  b += line('M913 332V382', 'blue') + text(930, 363, 'Publish', 16, C.blue, 400, 130);
  b += line('M656 437H720', 'blue') + text(688, 419, 'MQTT', 15, C.blue, 400, 52, 'middle');
  b += line('M913 492V542', 'blue') + text(930, 523, 'Subscribe', 16, C.blue, 400, 150);
  b += line('M913 672V712', 'blue');
  b += line('M1106 595H1154V285H1202', 'amber') + text(1154, 577, 'HTTPS', 16, C.amber, 400, 76, 'middle');
  b += line('M1285 348V390', 'amber', true) + text(1301, 376, '파일', 15, C.amber, 400, 48);
  b += line('M1469 348V390', 'amber', true) + text(1485, 376, 'Job', 15, C.amber, 400, 48);
  b += line('M1552 285H1564V692H1552', 'teal', true);
  b += text(1194, 569, 'REST · WebSocket · FCM / Web Push', 17, C.teal, 400, 362);

  b += card('appliances', 48, 222, 244, 142, '연동 가전', ['냉장고 · 세탁기 등', '가전 상태 · 서비스'], 'green');
  b += card('sensor', 48, 414, 244, 104, 'ESP32 · LD6004', ['대상 · 위치 · 추적 품질'], 'green', null, 21);
  b += card('pi3', 48, 598, 244, 112, 'Pi 3 Relay', ['센서 입력 검증 · 중계', 'SSH → Pi 5 FIFO'], 'green', 'raspberrypi', 21);
  b += text(48, 758, 'Serial 원시 입력과', 18, C.muted, 400, 244) + text(48, 785, '판단용 MQTT를 구분', 18, C.muted, 400, 244);

  b += card('ha', 388, 222, 268, 110, 'Home Assistant', ['WebSocket · state_changed', '가전 통합 · 상태 변경'], 'blue', 'homeassistant', 21, 17);
  b += card('repetitive', 720, 222, 386, 110, '반복행동 판단', ['Baseline + IF + AE', '54개 특징 · 반복 증거 · Routine'], 'blue');
  b += card('wandering', 388, 382, 268, 110, '배회 의심 판단', ['경로 형태 · 개인 이력', '지속성 · 관측 품질'], 'blue');
  b += card('sensor-observation', 388, 542, 268, 130, '원시 센서 관측', ['Central UDP · Archive', '선택 경로 · 실행과 분리'], 'blue');
  b += card('mqtt', 720, 382, 386, 110, 'MQTT Broker', ['Mosquitto · 공통 JSON', '반복행동 / 배회 Topic'], 'blue', 'mqtt');
  b += rect(720, 542, 386, 130, '#254e3c', '#254e3c', 10, 'central');
  b += logo('cplusplus', 740, 559, 29, '#fff') + text(784, 582, 'Central App', 27, '#fff', 700, 270);
  b += text(740, 618, '출처 · 시각 · 중복 검증', 21, '#fff', 400, 346) + text(740, 649, 'Action Router · 영속 Outbox', 19, '#e1eee5', 400, 346);
  b += rect(388, 712, 718, 80, '#fff', C.blueBorder, 9);
  for (const [index, title, detail] of [[0, 'Piper TTS', '스피커 음성 안내'], [1, 'HA 가전 제어', '허용된 가전 요청'], [2, '영상 · 선호 음악', 'Pi 화면 · 스피커']]) {
    const x = 408 + index * 239;
    if (index) b += `<path d="M${x - 16} 727V779" stroke="#c6d7e8"/>`;
    b += text(x, 745, title, 21, C.blue, 700, 207) + text(x, 775, detail, 17, C.muted, 400, 207);
  }

  b += card('api', 1202, 222, 350, 126, 'FastAPI', ['인증 · 사건 이력 · 설정', '학습 Job · 모델 API'], 'amber', 'fastapi', 26);
  b += logo('render', 1458, 243, 18) + text(1485, 259, 'Render', 16, C.muted, 400, 62);
  b += card('r2', 1202, 390, 166, 114, 'R2', ['사진·WAV·모델', '비공개 파일 저장'], 'amber', 'cloudflare', 24, 16);
  b += card('gpu', 1386, 390, 166, 114, 'GPU Worker', ['Piper 학습', 'ONNX Export'], 'amber', null, 20);
  b += rect(1202, 652, 350, 140, '#fff', C.tealBorder, 9, 'guardian');
  b += text(1222, 684, '알림 · 이력 · 출입 사진', 20, C.ink, 400, 310);
  b += text(1222, 714, '음성 녹음 · 호칭 · 거주지역', 20, C.ink, 400, 310);
  b += text(1222, 744, '선호 음악 · 개인 설정', 20, C.ink, 400, 310);
  b += logo('firebase', 1222, 762, 18) + text(1252, 779, 'FCM / Web Push', 17, C.muted, 400, 280);

  b += '<path d="M24 836H1576" stroke="#c4d5cb"/>';
  b += text(24, 887, '출입 사진', 21, C.blue, 700, 130);
  const camera = [
    ['door-trigger', 168, 262, 'HA 출입 이벤트', 'HTTP POST → Pi 4', 'homeassistant'],
    ['camera', 470, 262, 'Pi 4 · 카메라', '대표 사진 선택', 'raspberrypi'],
    ['photo-api', 772, 262, 'API / R2', '인증 업로드 · 저장', 'fastapi'],
    ['photo-app', 1074, 502, '보호자 앱', '출입 사진 조회', 'flutter'],
  ];
  camera.forEach(([id, x, w, title, detail, brand], i) => {
    b += laneCard(id, x, 852, w, title, detail, 'blue', brand);
    if (i < camera.length - 1) b += line(`M${x + w} 887H${camera[i + 1][1]}`, 'blue');
  });
  b += text(24, 985, '음성 모델', 21, C.violet, 700, 130);
  const voice = [
    ['recording', 168, 230, '앱 동의 · 녹음', 'WAV · 대본', 'flutter'],
    ['voice-api', 438, 230, 'API / R2', '등록 · 비공개 저장', 'cloudflare'],
    ['voice-training', 708, 230, 'GPU · Piper 학습', 'Fine-tuning · Export', null],
    ['model', 978, 230, 'ONNX + JSON', 'API / R2에 게시', null],
    ['model-updater', 1248, 328, 'Pi 5 모델 검증 · 교체', '로컬 Piper TTS에 적용', 'raspberrypi'],
  ];
  voice.forEach(([id, x, w, title, detail, brand], i) => {
    b += laneCard(id, x, 950, w, title, detail, 'violet', brand);
    if (i < voice.length - 1) b += line(`M${x + w} 985H${voice[i + 1][1]}`, 'violet');
  });
  b += text(24, 1065, '환경 조명', 21, C.teal, 700, 130);
  b += text(168, 1065, '앱 거주지역 → 기상청 날씨 · HA 태양 고도 → 별도 타이머 → HA 조명', 20, C.ink, 400, 1408);
  b += text(24, 1107, '상단: 행동 판단과 실행  /  하단: 출입 사진·음성 모델·환경 조명의 별도 연결', 16, C.muted, 400, 1540);

  const markers = ['green', 'blue', 'amber', 'teal', 'violet'].map(tone => `<marker id="arrow-${tone}" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto-start-reverse"><path d="M0 0L6 3L0 6Z" fill="${C[tone]}"/></marker>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1132" viewBox="0 0 1600 1132" role="img" aria-labelledby="title desc"><title id="title">Memolink 시스템 아키텍처 · 개발팀 PAUSEABLE</title><desc id="desc">가전과 ESP32/LD6004 입력, Pi 3의 SSH/FIFO 중계, Pi 5 안의 Home Assistant·독립 행동 분석·MQTT Broker·C++ Central·로컬 출력, API·R2·GPU와 Flutter 보호자 앱을 구분합니다. 카메라·음성 학습·환경 조명은 하단의 별도 경로로 표시합니다.</desc><defs>${markers}</defs><rect width="1600" height="1132" fill="#fff"/><g font-family="'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', Arial, sans-serif">${b}</g></svg>\n`;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  fs.writeFileSync(path.join(here, '..', 'pauseable-system.svg'), systemArchitecture());
}
