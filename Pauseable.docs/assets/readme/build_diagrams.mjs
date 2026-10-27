import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildArchitectures } from './build_architectures.mjs';

const out = path.dirname(fileURLToPath(import.meta.url));
const C = { ink: '#203b30', muted: '#65786e', line: '#b4c8bd', green: '#245c45', teal: '#147f82', blue: '#315f92', amber: '#a46a1e', red: '#a54545', paper: '#f5f8f6' };
const esc = value => String(value).replace(/[&<>\"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const text = (x, y, value, size = 15, color = C.ink, weight = 400) => `<text x="${x}" y="${y}" fill="${color}" font-size="${size}" font-weight="${weight}">${esc(value)}</text>`;
function node(x, y, w, title, lines = [], tone = 'green', h = 94, dark = false) {
  const color = C[tone];
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="6" fill="${dark ? color : '#fff'}" stroke="${dark ? color : '#d6e2db'}"/>` +
    `<rect x="${x}" y="${y}" width="4" height="${h}" rx="2" fill="${color}"/>` +
    text(x + 18, y + 30, title, 18, dark ? '#fff' : C.ink, 700) +
    lines.map((line, i) => text(x + 18, y + 54 + i * 19, line, 13.5, dark ? '#e4eee8' : C.muted)).join('');
}
const edge = (points, color = C.line, dashed = false) => `<path d="${points}" fill="none" stroke="${color}" stroke-width="1.8" ${dashed ? 'stroke-dasharray="5 4"' : ''} marker-end="url(#arrow)"/>`;
const rule = y => `<path d="M32 ${y}H1088" stroke="#d9e4dd"/>`;
const band = (x, y, w, label, detail, tone = 'green') => `<rect x="${x}" y="${y}" width="${w}" height="62" rx="5" fill="#fff" stroke="#d6e2db"/>` + text(x + 16, y + 25, label, 14, C[tone], 700) + text(x + 16, y + 46, detail, 13, C.muted);
const diagrams = [];
async function save(file, title, subtitle, height, content, note = '') {
  const body = `<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="${height}" viewBox="0 0 1120 ${height}" role="img" aria-labelledby="title desc"><title id="title">${esc(title)}</title><desc id="desc">${esc(subtitle)}</desc><defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7 3.5L0 7Z" fill="${C.line}"/></marker></defs><rect width="1120" height="${height}" rx="8" fill="${C.paper}"/><g font-family="'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', Arial, sans-serif">${text(32, 38, title, 25, C.ink, 700)}${text(32, 65, subtitle, 14, C.muted)}${rule(88)}${content}${note ? text(32, height - 20, note, 12, C.muted) : ''}</g></svg>\n`;
  await fs.writeFile(path.join(out, file), body);
  diagrams.push({ file, title, kind: 'architecture', liveStatus: false });
}

await buildArchitectures();
diagrams.push({ file: 'ai-pipelines.svg', title: 'Memolink AI 분석과 음성 학습 구조 · 개발팀 PAUSEABLE', kind: 'architecture', liveStatus: false });
let b = '';

function chain(labels, y = 144, tone = 'green') {
  const gap = 18;
  const w = (1056 - gap * (labels.length - 1)) / labels.length;
  let result = '';
  labels.forEach((label, i) => {
    const x = 32 + i * (w + gap);
    result += node(x, y, w, label[0], label.slice(1), tone, 100);
    if (i < labels.length - 1) result += edge(`M${x + w} ${y + 50}H${x + w + gap}`);
  });
  return result;
}
b = chain([['이력 수집', '데이터 출처 · 가구', '관측 범위 기록'], ['학습 조건', '유효 관측 30일', '정상 학습 후보'], ['IF · AE 학습', '시간순 데이터 분할', '학습 · 보정 · 평가'], ['모델 검증', '학습·검증 기준', '특징·모델 호환'], ['모델 적용', '버전별 모델 저장', '활성 버전 전환']], 140);
b += edge('M775 240V282H536V316', C.red, true) + band(344, 316, 384, '검증 실패 · 모델 사용 불가', '기존 호환 모델을 유지하거나 Baseline으로 판단합니다.', 'red');
b += band(32, 410, 510, 'SHADOW', '모델 점수를 기록하고 기존 규칙 판정은 유지합니다.', 'blue') + band(560, 410, 528, 'HYBRID', '반복 증거·실행 정책과 검증된 모델 점수를 함께 적용합니다.');
await save('learning-lifecycle.svg', '이력 수집부터 모델 적용까지', '달력상 경과일이 아니라 유효 이력과 학습·검증 조건으로 모델 적용을 결정합니다.', 520, b);

b = node(32, 136, 256, 'Pi 5 / Central', ['최종 Decision Event', 'Device Token'], 'green') + node(32, 284, 256, 'Pi 4 / Camera', ['출입 이벤트 사진', 'Device Token'], 'blue');
b += node(430, 208, 264, 'FastAPI / Render', ['인증 · 사건 이력 저장', '개인 설정 · 음성 학습 작업'], 'green', 112, true);
b += node(820, 136, 268, 'Flutter 보호자 앱', ['REST / WebSocket / Push', '상황 확인 · 설정 · 녹음'], 'teal') + node(820, 356, 268, 'GPU Worker', ['학습 작업 임대 · 처리', 'Worker Token'], 'blue');
b += node(430, 392, 264, 'R2 / 비공개 저장소', ['사진 · WAV · 음성 모델'], 'teal', 86);
b += edge('M288 183H358V242H430') + edge('M288 331H358V286H430') + edge('M694 242H752V183H820') + edge('M820 211H778V282H694') + edge('M562 320V392');
b += edge('M694 300H748V386H820') + edge('M694 418H820') + edge('M820 440H694');
b += text(756, 343, '학습 작업', 13, C.blue) + text(722, 124, 'App Token', 13, C.teal) + text(32, 443, 'App · Device · Worker 인증을 분리합니다.', 14, C.muted);
await save('apps-connections.svg', '장치 · API · 보호자 앱 연결', 'API는 사건과 설정을 저장하고, 앱 알림과 음성 학습 작업을 연결합니다.', 530, b);

const actors = [['Central', 130], ['API', 410], ['Push 서비스', 690], ['보호자 앱', 970]];
b = actors.map(([label, x]) => node(x - 96, 116, 192, label, [], 'green', 52) + `<path d="M${x} 168V500" stroke="#c9d7cf" stroke-dasharray="4 5"/>`).join('');
const messages = [[130, 410, 211, '1. Decision Event · Device Token'], [410, 970, 286, '3. 열린 앱에 WebSocket 전달'], [410, 690, 352, '4. FCM / Web Push 요청'], [690, 970, 411, '5. OS / 브라우저 알림'], [970, 410, 478, '6. 읽음 상태 갱신 · App Token']];
messages.forEach(([from, to, y, label]) => { b += edge(`M${from} ${y}H${to}`, C.blue) + text(Math.min(from, to) + 10, y - 12, label, 13, C.ink); });
b += text(424, 249, '2. 검증 · 중복 처리 · 저장', 13, C.green, 700);
await save('notification-sequence.svg', '상황 판단에서 보호자 알림까지', '사건 접수, 저장, 전송과 휴대폰 표시를 단계별로 확인합니다.', 550, b, 'Push 전달에는 기기 등록, 인증 설정과 OS·브라우저 권한이 필요합니다.');

b = node(32, 126, 328, 'AI 판단 메시지', ['source: repetitive-ai / wandering-ai', 'behavior / risk_level / risk_score', 'inference_status / evidence'], 'green', 136);
b += node(396, 126, 328, 'Central 최종 결정', ['source: central-atlas-app', 'decision / risk_level / actions', 'event_id / occurred_at'], 'blue', 136);
b += node(760, 126, 328, '보호자 알림', ['보호자에게 보여줄 사건 정보', '알림 이력 · 읽음 상태', '전송 접수와 실제 표시 구분'], 'teal', 136);
b += edge('M360 194H396') + edge('M724 194H760');
b += band(32, 306, 510, '식별자와 사건 시각', 'contract_version / event_id / patient_id / device_id / UTC') + band(560, 306, 528, '관측 부족 · 추론 오류', '행동과 위험도는 unknown, 점수는 null로 전달합니다.', 'amber');
await save('contract-map.svg', 'AI 추론 · 실행 결정 · 앱 알림의 통신 규격', '각 메시지는 판단 근거, 실행 정책과 보호자 표시라는 서로 다른 역할을 담당합니다.', 424, b);

b = chain([['JSON', '문법 · 자료형'], ['Schema', '필수 필드', '허용값 · 범위'], ['출처 · 시각', 'Topic/source 일치', 'UTC · 유효 시간'], ['Event ID', '중복 · 내용 충돌'], ['실행 정책', '활성화 · 위험 단계', 'Cooldown']], 142);
[130, 340, 550, 760].forEach(x => { b += `<path d="M${x} 242V286" fill="none" stroke="${C.red}" stroke-dasharray="4 4"/>`; });
b += `<path d="M130 286H760" stroke="${C.red}"/>` + edge('M550 286V322', C.red, true);
b += band(320, 322, 500, '유효하지 않은 입력은 실행에서 제외', '거절 사유를 기록하며 정상 사건으로 자동 변환하지 않습니다.', 'red');
await save('validation-gates.svg', 'Central 입력 검증과 실행 조건', '메시지 형식에 이어 출처·시각·사건 ID와 실행 정책을 검사합니다.', 444, b);

b = node(32, 232, 228, '저장소 소스', ['배포 Manifest 검사', '장치 인증값 제외'], 'green', 108, true);
const devices = [['Pi 3 소스 묶음', ['센서 중계 · 통신 규격'], 126, 'blue'], ['Pi 4 소스 묶음', ['카메라 · 업로드 설정'], 266, 'teal'], ['Pi 5 소스 묶음', ['Central · AI · 출력 설정'], 406, 'green']];
devices.forEach(([label, lines, y, tone]) => {
  b += node(390, y, 310, label, lines, tone, 86) + edge(`M260 286H322V${y + 43}H390`);
  b += node(804, y, 284, '장치 환경 준비', [y === 406 ? 'SDK · Docker · 모델 · 서비스' : y === 266 ? '카메라 · Docker · 권한' : 'Serial · 사용자 · SSH · FIFO'], tone, 86) + edge(`M700 ${y + 43}H804`);
});
await save('device-bundles.svg', '장치별 배포 소스 구성', 'Manifest에 선언한 소스를 장치별로 묶고, 빌드·설치에 필요한 환경을 준비합니다.', 556, b);

b = chain([['백업', '모델 · DB · 설정'], ['검증', '소스 Manifest'], ['빌드', 'SDK / Docker / APK'], ['설정', 'ID · 인증 · 권한'], ['설치', '파일 · 서비스'], ['실기 시험', '입력부터 출력까지']], 144);
b += band(32, 304, 510, '소스 압축 파일', 'Manifest의 소스·설정과 BUNDLE.sha256을 포함합니다.', 'blue') + band(560, 304, 528, '실행 산출물', 'Central 바이너리 · .ipk · APK · ONNX는 별도로 준비합니다.', 'amber');
await save('deployment-stages.svg', '빌드 · 설치 · 실기 확인 절차', '소스 무결성을 확인한 뒤 장치에 설치하고 실제 입력과 출력으로 동작을 점검합니다.', 416, b);

b = '';
const evidence = [['구현 코드', ['알고리즘 · 통신 · 실행 제어', '해당 버전의 구현 범위'], 'green'], ['자동 검사', ['Unit / 회귀 검사 / 빌드', '모의 입력과 코드 검사'], 'blue'], ['평가 기록', ['데이터 출처 · 수치 · 보고서', '저장된 실험의 평가 범위'], 'teal'], ['장치 실기 시험', ['센서 · 음성 · 가전 · 앱', '설치한 장치의 실제 입출력'], 'amber']];
evidence.forEach(([label, lines, tone], i) => {
  b += node(32 + i * 270, 138, 246, label, lines, tone, 128);
  if (i < 3) b += edge(`M${278 + i * 270} 202H${302 + i * 270}`);
});
b += band(32, 318, 1056, '검증 기록', '코드·모델 버전, 데이터 출처, 실행 명령, 결과 파일과 미실행 항목을 함께 기록합니다.');
await save('evidence-map.svg', '구현과 검증 자료의 구성', '자동 검사·저장된 평가·실제 장치 시험은 각각의 입력과 조건에 따라 해석합니다.', 428, b);

b = chain([['MQTT 수신', '반복행동 · 배회 Topic'], ['입력 검증', '계약 · 식별자', '사건 시각'], ['중복 처리', 'event_id · 내용 충돌'], ['Action Router', '위험 단계 · 활성화', 'Cooldown']], 132);
b += node(32, 310, 314, '거절 · 억제 기록', ['Unknown · 계약 오류 · 실행 제한', '가전 동작에서 제외'], 'amber', 106);
b += node(394, 310, 314, '로컬 안내 · 출력', ['Piper TTS · 허용된 가전 동작', '안내 이후 선호 음악 요청'], 'green', 106);
b += node(756, 310, 332, 'Outbox / API', ['영속 전송 대기 · 재시도', '보호자 이력 · 알림'], 'blue', 106);
b += edge('M910 232V266H550V310') + edge('M964 232V266H922V310') + edge('M420 232V266H190V310', C.amber, true);
await save('central-routing.svg', 'Central의 메시지 수신과 출력 제어', 'AI 판단에 입력 검증과 실행 정책을 적용해 로컬 출력과 API 전송을 처리합니다.', 472, b);

b = chain([['다운로드', 'ONNX + JSON'], ['무결성 검사', '크기 · SHA-256'], ['형식 검증', '설정 · 산출물'], ['합성 시험', '로컬 음성 생성'], ['모델 교체', '활성 모델 변경']], 146);
b += edge('M552 246V304', C.red, true) + band(312, 318, 500, '검증 실패 시 기존 모델 유지', '다운로드·형식·합성 검사를 통과한 모델만 활성화합니다.', 'red');
await save('model-release.svg', 'Pi 음성 모델 검증과 교체', 'Model Updater가 게시된 모델을 검사한 뒤 Piper의 활성 모델을 변경합니다.', 436, b);

b = chain([['Central 승인', 'Action Router'], ['기존 안내', 'TTS · 가전'], ['음악 요청', '별도 비동기 작업'], ['API 곡 선택', 'Device Token', '현재 선호 목록'], ['Pi Player', '검증한 video_id']], 142);
b += band(32, 306, 510, '음악 경로의 오류 처리', '빈 목록·인증·네트워크·재생 오류는 음악만 건너뜁니다.', 'amber') + band(560, 306, 528, '재요청 제한 시간', '기본 300초이며 행동 알림의 cooldown과 별도입니다.', 'blue');
await save('favorite-music.svg', '행동 안내 후 선호 음악 재생', '앱에 등록된 현재 목록에서 곡을 선택해 Pi 화면·스피커로 재생을 요청합니다.', 418, b);

b = chain([['보호자 앱', '거주지역 저장'], ['Device API', 'Device Token', '기상청 nx / ny'], ['환경 정보', '기상청 날씨', 'HA sun.sun'], ['조명 규칙', '밝기 계산', '색온도 계산'], ['HA 조명', '설정한 Entity']], 140);
b += band(32, 306, 510, 'Render 지역 조회 실패', '해당 회차 변경을 중단하고 기존 조명 상태를 유지합니다.', 'red') + band(560, 306, 528, '조회 시험', '--check-location은 조명 제어 없이 지역만 확인합니다.', 'blue');
await save('weather-light.svg', '거주지역 · 날씨 · 태양 고도 기반 조명', '앱의 지역 설정과 HA 조명 엔티티를 장치 설정에 연결합니다.', 420, b);

b = text(48, 126, 'WORKFLOW', 12, C.muted, 700) + text(410, 126, '검사 항목', 12, C.muted, 700) + text(830, 126, '실행 조건 / 산출물', 12, C.muted, 700);
const workflows = [
  ['HA 보고서', '평가 데이터 / 회귀 검사 / python -O', 'PR / main / 수동'],
  ['앱 + API', 'API 검사 / Flutter 분석·테스트·빌드', 'PR / main / 수동'],
  ['Voice', 'Worker / 학습 처리 / 모델 교체 / 설정', '관련 push / PR'],
  ['선호 음악', '모의 Player / 라우팅 / Shell 문법', 'PR / main / 수동'],
  ['Android 시험 APK', '비공개 설정 / Flutter / APK + SHA-256', '수동 빌드 산출물'],
];
workflows.forEach((row, i) => {
  const y = 146 + i * 66;
  b += `<rect x="32" y="${y}" width="1056" height="54" rx="4" fill="${i % 2 ? '#edf3f0' : '#fff'}"/>` + text(48, y + 32, row[0], 17, C.ink, 700) + text(410, y + 32, row[1], 14, C.muted) + text(830, y + 32, row[2], 14, C.green);
});
await save('ci-map.svg', '파트별 자동 검사와 앱 빌드', '변경 경로에 따라 Workflow를 실행하며 결과는 해당 commit의 Actions 기록에 남깁니다.', 530, b);

b = chain([['수동 실행', 'workflow_dispatch'], ['비공개 설정', 'Firebase 앱 설정', 'App Token'], ['코드 검사', 'Analyze / test'], ['APK 빌드', '팀 시험용 서명'], ['산출물', 'APK + SHA-256', '보관 기간 3일']], 144);
b += band(32, 306, 1056, '휴대폰 설치 후 확인', '알림 권한을 설정하고 foreground / background / 잠금 상태에서 수신·표시·앱 이동을 시험합니다.', 'blue');
await save('apk-build.svg', 'Android 시험 APK 생성과 실기 확인', '서버 비밀 키와 Device·Worker Token은 앱 빌드에서 제외합니다.', 420, b);

await fs.writeFile(path.join(out, 'diagram_manifest.json'), JSON.stringify({ generatedBy: 'build_diagrams.mjs', diagrams }, null, 2) + '\n');
console.log(JSON.stringify({ generated: diagrams.length, directory: out }));
