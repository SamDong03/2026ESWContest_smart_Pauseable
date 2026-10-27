import fs from 'node:fs/promises';
import { C, text, rect, group, box, arrow, note, table, frame } from './diagram_primitives.mjs';

export function aiArchitecture() {
  const cols = [
    { x: 32, tone: 'green', brand: 'homeassistant', title: 'HA 가전 반복행동', steps: [
      ['상태 변경 수집', ['WebSocket · state_changed', 'Snapshot / 실제 변경 구분']],
      ['54개 특징 생성', ['10m · 30m · 1h · 2h', '횟수 · 전환 · 시간대 · 요일']],
      ['판단 · 개인화', ['Baseline / 검증된 IF · AE', '반복 증거 · 품질 · Routine']],
      ['MQTT 판단 전송', ['repetitive-ai', '실행 여부는 Central에서 결정']],
    ] },
    { x: 500, tone: 'blue', brand: 'raspberrypi', title: 'mmWave 배회 의심', steps: [
      ['센서 입력 · 구간 구성', ['Pi 3 Serial → SSH → Pi 5 FIFO', '대상 · 좌표 · 시각 · 추적 품질']],
      ['형태 / 개인 변화 분리', ['RF 36개 특징 / 개인 이력 9개', '다른 특징 규격 · 별도 상태']],
      ['지속성 · 품질 확인', ['연속 구간 · 누적 시간', '끊김 · 저품질은 판단 보류']],
      ['MQTT 판단 전송', ['wandering-ai', '연구 모델과 운영 설정 구분']],
    ] },
    { x: 968, tone: 'teal', brand: 'python', title: '보호자 음성 학습', steps: [
      ['동의한 WAV · 대본', ['앱 160문장 · 16 kHz mono', 'API / R2에 작업 자료 저장']],
      ['전처리 · GPU 학습', ['22,050 Hz · 번호 / 대본 검사', 'Piper fine-tuning']],
      ['모델 검증 · 게시', ['ONNX + Piper JSON', 'manifest · 샘플 · status']],
      ['Pi 검증 · 모델 교체', ['크기 · SHA-256 · 로컬 합성', '실패 시 기존 모델 유지']],
    ] },
  ];
  let b = '';
  for (const p of cols) {
    b += group(p.x, 124, 440, 674, p.title, p.tone, p.brand);
    p.steps.forEach((s, i) => {
      const y = 204 + i * 146;
      b += box(p.x + 20, y, 400, 116, s[0], s[1], p.tone, i === 3);
      if (i < 3) b += arrow(`M${p.x + 220} ${y + 116}V${y + 146}`, p.tone);
    });
  }
  b += text(52, 829, 'Pi 5 / Python · 행동 판단', 19, C.green, 700, 400) + text(520, 829, 'Pi 5 / Python · 이동 분석', 19, C.blue, 700, 400) + text(988, 829, 'GPU 학습 → Pi 5 로컬 TTS', 19, C.teal, 700, 400);
  return frame('AI 분석과 음성 학습의 세 범주', '행동 모듈은 판단 메시지를, Voice는 배포할 음성 모델을 만듭니다.', 862, b);
}

export async function buildMechanisms() {
  const figures = [];
  const save = async (file, title, subtitle, height, content, sources) => {
    await fs.writeFile(new URL(file, import.meta.url), frame(title, subtitle, height, content));
    figures.push({ file, title, kind: 'architecture', liveStatus: false, sources });
  };
  await fs.writeFile(new URL('ai-pipelines.svg', import.meta.url), aiArchitecture());
  figures.push({ file: 'ai-pipelines.svg', title: 'AI 분석과 음성 학습의 세 범주', kind: 'architecture', liveStatus: false, sources: ['Pauseable.ai/README.md'] });

  let b = group(32, 126, 414, 372, '01  이력과 학습 자격', 'green', 'homeassistant') +
    box(52, 206, 374, 112, '정상 후보 선별', ['같은 가구 · 출처 · 특징 규격', 'reviewed / screened 구분']) +
    box(52, 348, 374, 112, '유효 관측 조건', ['30일 · 하루 12개 이상 시간대', '총 360시간 이상']);
  b += arrow('M239 318V348') + arrow('M426 404H466V262H506');
  b += group(486, 126, 426, 372, '02  학습과 독립 평가', 'blue', 'python') +
    box(506, 206, 386, 112, '시간순 분할 · 학습', ['Train / Calibration / Holdout', '경계 제외 · scaler는 Train만'], 'blue') +
    box(506, 348, 386, 112, '모델 승인 검사', ['경고 · 수렴 · 호환성 · 점수', '정상 후보 Holdout 경보 ≤ 0.15'], 'blue') + arrow('M699 318V348', 'blue');
  b += group(952, 126, 456, 372, '03  적용 모드 선택', 'teal') +
    box(972, 206, 416, 112, 'Shadow', ['모델 점수만 기록', '규칙 기반 최종 판단 유지'], 'teal') +
    box(972, 348, 416, 112, 'Hybrid', ['반복 증거 + 검증된 모델', 'IF / AE 조건 결합 · Routine'], 'teal');
  b += arrow('M892 404H932V262H972', 'blue') + arrow('M932 404H972', 'blue');
  b += arrow('M239 460V540', 'amber', true) + note(52, 540, 374, '조건 미충족', 'Baseline 유지 · 관측 계속', 'amber');
  b += arrow('M699 460V540', 'red', true) + note(486, 540, 426, '검증 실패 / 모델 사용 불가', '기존 호환 모델 또는 Baseline', 'red');
  b += arrow('M1180 498V540', 'teal', true) + note(952, 540, 456, '버전별 저장 · 활성 포인터', '주기 재학습은 retrain_days로 제어', 'teal');
  b += text(32, 665, 'Local은 기본 확인된 정상 이력만 사용합니다. screened 후보는 별도 허용하며 retrain_days=0이면 주기 갱신은 꺼집니다.', 18, C.muted, 400, 1376);
  await save('learning-lifecycle.svg', '개인 이력에서 IF·AE 적용까지', '관측일과 정상 후보를 확인하고, 새 모델의 검증 결과에 따라 활성화를 결정합니다.', 704, b, ['Pauseable.ai/ha/src/ha_model_lifecycle.py', 'Pauseable.ai/ha/src/train_ha_anomaly_models.py']);

  b = group(32, 126, 360, 438, '현장 장치', 'green', 'raspberrypi') +
    box(52, 210, 320, 120, 'Pi 5 / Central', ['최종 판단 사건 전송', '지역 · 곡 · 모델 조회']) +
    box(52, 384, 320, 120, 'Pi 4 / Camera', ['출입 대표 사진 업로드', 'Device Token']);
  b += group(492, 126, 456, 438, 'API / Render', 'blue', 'fastapi') +
    box(512, 210, 416, 122, '인증 · 계약 · 사건 이력', ['App / Device / Worker 분리', 'event_id 중복 / 내용 충돌'], 'blue', true) +
    box(512, 384, 416, 120, '설정 · 비공개 파일 · 작업', ['프로필 · 지역 · 곡 · 알림 중지', '사진 · WAV · 모델 · Job'], 'blue');
  b += group(1048, 126, 360, 438, '앱과 학습', 'teal', 'flutter') +
    box(1068, 210, 320, 120, 'Flutter Guardian', ['REST 설정 · 이력 · 사진', 'WebSocket / FCM / Web Push'], 'teal') +
    box(1068, 384, 320, 120, 'GPU Worker', ['음성 작업 임대 · 결과 게시', 'Worker Token'], 'teal');
  b += arrow('M372 268H512') + arrow('M372 444H512') + text(396, 253, 'Device', 17, C.green, 700, 110);
  b += arrow('M928 250H1068', 'blue') + arrow('M1068 292H928', 'teal') + text(958, 234, 'App', 17, C.teal, 700, 90);
  b += arrow('M928 426H1068', 'blue') + arrow('M1068 474H928', 'teal');
  b += arrow('M720 504V602', 'blue') + box(492, 602, 456, 112, 'R2 / 비공개 영속 저장', ['이력 · 설정 파일 · 사진 · WAV · 모델'], 'blue');
  b += note(32, 602, 400, '장치 출력은 Pi의 역할', 'API 접수와 물리 출력 성공은 별도', 'green') + note(1008, 602, 400, '모델 학습은 Worker의 역할', '앱은 녹음 · 작업 상태를 관리', 'teal');
  await save('apps-connections.svg', '장치·API·보호자 앱의 책임', '요청 주체별 인증을 나누고, 사건 전달과 개인 설정·음성 작업을 같은 API로 연결합니다.', 758, b, ['Pauseable.apps/api/app/main.py', 'Pauseable.apps/api/app/security.py', 'Pauseable.apps/guardian/lib/main.dart']);

  const actors = [['Central', 148], ['API / 이력', 506], ['전달 정책', 878], ['Guardian / OS', 1250]];
  b = actors.map(([t, x]) => box(x - 116, 126, 232, 58, t, [], 'blue') + `<path d="M${x} 184V652" stroke="${C.light}" stroke-dasharray="5 5"/>`).join('');
  b += arrow('M148 224H506', 'green') + text(165, 210, '1. Decision + Device 인증', 18, C.green, 700, 310);
  b += box(370, 250, 272, 112, '2. 검증 · 중복 · 저장', ['같은 ID / 다른 내용 충돌', '중지 중에도 이력은 보관'], 'blue');
  b += arrow('M506 390H878', 'blue') + text(525, 376, '3. 반복행동 중지 여부 확인', 18, C.blue, 700, 326);
  b += box(742, 412, 272, 112, '중지 활성', ['반복 알림 전달만 생략', '배회 · 사진은 유지'], 'amber');
  b += arrow('M878 564H1250', 'teal') + text(900, 548, '4. 허용 시 WebSocket / Push', 17, C.teal, 700, 340);
  b += arrow('M1250 628H506', 'blue') + text(690, 612, '5. 알림 선택 · 이력 조회 · 읽음 갱신', 18, C.blue, 700, 550);
  b += note(32, 704, 660, '만료 시각을 영속 저장 · 자동 / 수동 재개', '중지 기간의 과거 알림을 재개 시 다시 발송하지 않습니다.', 'amber');
  b += note(716, 704, 692, '중지와 무관하게 유지하는 현장 처리', 'Pi 감지 · TTS · 가전, 사건 이력은 계속 동작합니다.', 'green');
  await save('notification-sequence.svg', '사건 저장과 보호자 알림 전달', '저장 성공·전송 접수·실제 표시를 구분하고, 중지 설정은 반복행동 알림 경로에만 적용합니다.', 820, b, ['Pauseable.apps/api/app/main.py', 'Pauseable.apps/api/app/alert_pauses.py']);

  b = group(32, 126, 424, 370, 'AI → Central', 'green', 'mqtt') +
    box(52, 208, 384, 250, 'Behavior Inference', ['source / behavior', 'risk_level / risk_score', 'inference_status / evidence', '관측한 행동과 판단 근거'], 'green');
  b += group(508, 126, 424, 370, 'Central → API', 'blue', 'cplusplus') +
    box(528, 208, 384, 250, 'Decision Event', ['source: central-atlas-app', 'decision / risk_level / actions', '추론에 실행 정책을 반영', 'POST /api/events/decisions'], 'blue');
  b += group(984, 126, 424, 370, 'API → Guardian', 'teal', 'flutter') +
    box(1004, 208, 384, 250, 'App Alert', ['보호자에게 표시할 사건·안내', 'REST / WebSocket / Push', '알림 설정 · 읽음 상태', '저장과 전달을 분리'], 'teal');
  b += arrow('M456 310H508') + arrow('M932 310H984', 'blue');
  b += table(32, 538, [410, 966], ['공통 식별', '계약에서 맞추는 정보'], [
    ['contract_version / event_id', '규격 버전 · 사건 식별 · 동일 ID의 내용 비교'],
    ['occurred_at / patient / device', 'UTC 사건 시각 · 대상자 · 장치 일치'],
    ['unknown', '관측 부족·추론 오류는 unknown / score=null'],
  ]);
  await save('contract-map.svg', '세 메시지는 서로 다른 책임을 담습니다', 'AI 판단을 그대로 앱으로 복사하지 않고, Central 정책과 API 표시 형식으로 각각 구성합니다.', 790, b, ['Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json', 'Pauseable.contracts/communication-v1/schemas/decision-event.schema.json', 'Pauseable.contracts/communication-v1/schemas/app-alert.schema.json']);

  b = table(32, 132, [90, 304, 554, 428], ['단계', '검사', '통과 조건', '미통과 처리'], [
    ['01', 'JSON / 계약', '문법 · 필수 필드 · 자료형 · 허용값', '거절 사유 기록'],
    ['02', '출처 / 식별', 'Topic = source · 대상자 / 장치 일치', '잘못된 출처·ID 거절'],
    ['03', '사건 시각', 'UTC · 과거 300초 / 미래 30초 이내', 'stale / invalid_clock'],
    ['04', 'event_id / 내용', '새 사건 · 동일 ID 내용 일치 여부', '동일 내용 중복 / 내용 충돌'],
    ['05', 'Action Router', '활성화 · 위험 단계 · 상태 · cooldown', '감사 기록 / 실행 억제'],
  ], 'blue', 68);
  b += note(32, 554, 662, '입력 형식 검사와 실행 승인은 다릅니다', '계약이 맞아도 출력 정책에 따라 실행하지 않을 수 있습니다.', 'blue') +
    note(718, 554, 690, '잘못된 입력을 정상으로 변환하지 않습니다', 'Unknown은 Normal과 구분하며 가전 동작으로 연결하지 않습니다.', 'amber');
  await save('validation-gates.svg', 'Central 수신 검증의 다섯 단계', '어떤 조건을 검사하고 어디에서 거절·중복·억제를 기록하는지 구분합니다.', 680, b, ['Pauseable.edge/central/core/src/BehaviorInference.cpp', 'Pauseable.edge/central/core/src/ActionRouter.cpp']);

  b = group(32, 126, 1376, 236, '수신과 정책 / Pi 5 · C++', 'green', 'cplusplus');
  const intake = [['MQTT Subscriber', ['반복행동 / 배회 Topic']], ['Validator', ['계약 · 출처 · 시각 · ID']], ['중복 / 충돌', ['event_id + 내용 비교']], ['Action Router', ['활성화 · 위험 · cooldown']]];
  intake.forEach((s, i) => { const x = 52 + i * 340; b += box(x, 210, 316, 112, s[0], s[1]); if (i < 3) b += arrow(`M${x + 316} 266H${x + 340}`); });
  b += arrow('M548 322V410H238V446', 'amber', true) + arrow('M1230 322V398H720V446') + arrow('M1284 322V418H1180V446', 'blue');
  b += box(32, 446, 412, 160, '거절 · 감사 · 억제', ['형식 / 시각 / 출처 불일치', '중복 · Unknown · 실행 제한', '실행 경로로 넘기지 않음'], 'amber');
  b += box(492, 446, 412, 160, '허용한 로컬 출력', ['Piper TTS · 가전 연동', '기존 안내 이후 선호 음악', '실제 화면 · 소리는 별도 확인']);
  b += box(952, 446, 456, 160, '최종 사건 → API Outbox', ['영속 전송 대기 · 재시작 복구', 'Gateway 전송 · 실패 시 재시도', 'API 이력 → 보호자 알림'], 'blue');
  b += note(32, 654, 660, 'Action Router 상태', '행동별 위험 활성 · 최근 사건 · 실행 시각을 보관합니다.', 'green') + note(716, 654, 692, 'Outbox의 범위', 'API 전달용이며 TTS·가전의 물리 완료를 보장하지 않습니다.', 'blue');
  await save('central-routing.svg', '판단 메시지에서 실행과 전송으로', '입력 검증 뒤 실행 정책을 적용하고, 현장 출력과 서버 전달의 완료 상태를 나눕니다.', 778, b, ['Pauseable.edge/central/src/main.cpp', 'Pauseable.edge/central/core/src/ActionRouter.cpp', 'Pauseable.edge/central/integration/src/DecisionOutbox.cpp']);

  b = group(32, 126, 360, 398, '게시된 모델 후보', 'teal', 'cloudflare') +
    box(52, 214, 320, 130, 'API / R2', ['ONNX + Piper JSON', '크기 · SHA-256 · manifest'], 'teal') +
    text(52, 398, '다운로드 성공만으로', 20, C.teal, 700, 320) + text(52, 430, '활성 모델을 바꾸지 않습니다.', 20, C.teal, 700, 320);
  b += group(452, 126, 496, 398, 'Pi Model Updater', 'blue', 'raspberrypi') +
    box(472, 214, 456, 112, '무결성 · 형식', ['크기 · 해시 · 설정 · 산출물 검사'], 'blue') +
    arrow('M700 326V372', 'blue') + box(472, 372, 456, 112, '로컬 합성 시험', ['Piper로 문장을 WAV로 생성'], 'blue');
  b += arrow('M372 270H472', 'teal') + arrow('M928 428H1028', 'green') + box(1028, 372, 380, 112, '활성 모델 교체', ['검증된 버전만 TTS에 적용'], 'green', true);
  b += arrow('M700 484V574', 'red', true) + note(452, 574, 496, '다운로드 / 검사 / 합성 실패', '기존 모델을 유지하고 실패를 기록합니다.', 'red');
  b += note(992, 574, 416, '적용 후 출력 확인', '모델 적용과 스피커 출력은 별도', 'green');
  await save('model-release.svg', '새 음성 모델의 검증과 교체', 'GPU 학습·게시 이후, Pi가 후보 모델을 검사하고 기존 모델을 안전하게 유지합니다.', 704, b, ['Pauseable.edge/voice-model/voice_model_updater.py']);

  b = group(32, 126, 424, 392, '실행 승인', 'green', 'cplusplus') +
    box(52, 214, 384, 112, 'Central 승인 안내', ['주의 / 위험 · execute · speak', '반복행동 / 배회 출력 조건']) +
    arrow('M244 326V370') + box(52, 370, 384, 112, '기존 TTS · 가전 처리', ['음악은 별도 비동기 작업으로 요청']);
  b += group(508, 126, 424, 392, '현재 목록 조회', 'blue', 'fastapi') +
    box(528, 214, 384, 112, 'Favorite Music 작업', ['별도 cooldown · 기본 300초', '동시 요청 합침'], 'blue') +
    arrow('M720 326V370', 'blue') + box(528, 370, 384, 112, 'Device API 곡 선택', ['대상자의 현재 목록에서 무작위', '빈 목록 · 인증 실패는 건너뜀'], 'blue');
  b += group(984, 126, 424, 392, 'Pi 화면 · 스피커', 'teal', 'raspberrypi') +
    box(1004, 214, 384, 112, 'video_id 검증', ['검증한 ID만 FIFO로 전달'], 'teal') +
    arrow('M1196 326V370', 'teal') + box(1004, 370, 384, 112, 'Chromium / YouTube', ['영상 재생 요청', '실제 영상 · 음성은 직접 확인'], 'teal');
  b += arrow('M436 426H480V270H528') + arrow('M912 426H956V270H1004', 'blue');
  b += note(32, 566, 660, '실패는 음악 경로에서 분리', '빈 목록·네트워크·Player 오류로 다른 곡을 임의 대체하지 않습니다.', 'amber') + note(716, 566, 692, 'REQUESTED와 재생 완료는 다릅니다', '광고 · 로그인 · 네트워크 · 자동 재생 정책을 확인합니다.', 'teal');
  await save('favorite-music.svg', '행동 안내 이후 선호 음악 요청', '보호자 앱이 등록한 현재 목록을 조회하며 기존 안내와 음악 재생 상태를 분리합니다.', 690, b, ['Pauseable.edge/actions/favorite-music', 'Pauseable.edge/actions/youtube']);

  b = group(32, 126, 410, 390, '거주지역 설정', 'teal', 'flutter') +
    box(52, 210, 370, 112, 'Guardian → API', ['대상자 지역 · 기상청 격자 저장'], 'teal') +
    arrow('M237 322V368', 'teal') + box(52, 368, 370, 112, '장치의 지역 조회', ['render: Device 인증 API', 'legacy: 기존 위치 설정'], 'teal');
  b += group(496, 126, 422, 390, '환경 조회 · 규칙', 'blue', 'python') +
    box(516, 210, 382, 112, '기상청 + HA sun.sun', ['SKY · PTY / 태양 고도', '같은 거주지역 설정 확인'], 'blue') +
    arrow('M707 322V368', 'blue') + box(516, 368, 382, 112, '조명 규칙 계산', ['전원 · 밝기 · 색온도', '날씨 보정 · 수치 범위 제한'], 'blue');
  b += group(972, 126, 436, 390, 'HA 조명 실행', 'green', 'homeassistant') +
    box(992, 210, 396, 112, '설정한 light.* 엔티티', ['turn_on / turn_off', 'brightness_pct / color_temp_kelvin']) +
    box(992, 368, 396, 112, '별도 systemd timer', ['약 1분 간격', '행동 AI의 분석 회차와 무관']);
  b += arrow('M422 424H470V266H516', 'teal') + arrow('M898 424H944V266H992', 'blue');
  b += note(32, 564, 660, 'Render 지역 조회 실패', '회차 변경 중단 · 기존 조명 유지 · 다음 타이머에서 재시도', 'red') + note(716, 564, 692, '--check-location', '지역 조회만 시험하며 조명 제어 명령을 보내지 않습니다.', 'blue');
  b += text(32, 688, '앱의 auto_lighting_enabled 저장과 장치 타이머 시작·중지는 직접 연결돼 있지 않습니다.', 18, C.muted, 400, 1376);
  await save('weather-light.svg', '지역·날씨·태양 고도에 따른 조명', '앱의 위치 설정을 조회해 환경 규칙을 실행합니다. 행동 AI나 실측 조도 모델은 아닙니다.', 726, b, ['Pauseable.integrations/home-assistant/weather-light-control/weather_api.py', 'Pauseable.integrations/home-assistant/weather-light-control/weather_location.py']);

  b = group(32, 126, 340, 494, '검증된 배포 입력', 'green', 'docker') +
    box(52, 214, 300, 164, '소스 + Manifest', ['선언된 경로만 수집', 'FILES.sha256 대조', '불일치 시 승인 보류']) +
    text(52, 432, '개인 설정 · 토큰 · 원본 녹음', 18, C.muted, 400, 300) +
    text(52, 460, '실행 바이너리 / 개인화 모델은', 18, C.muted, 400, 300) + text(52, 488, '소스 묶음과 분리합니다.', 18, C.muted, 400, 300);
  b += table(476, 126, [214, 414, 304], ['소스 묶음', '담당 소스', '별도 준비'], [
    ['Pi 3', 'Serial 릴레이 · 센서 계약', '사용자 · SSH · Serial'],
    ['Pi 4', '카메라 · 트리거 · 업로드', '카메라 · Docker · 인증'],
    ['Pi 5', 'Central · AI · 출력 · 서비스', 'SDK · 이미지 · 모델'],
  ], 'blue', 104);
  b += arrow('M352 296H410V226H476', 'green') + arrow('M410 296V330H476', 'green') + arrow('M410 330V434H476', 'green');
  b += note(476, 554, 932, '각 tar.gz의 무결성: BUNDLE.sha256', '소스 압축 파일은 Central .ipk · Android .apk · Voice .onnx가 아닙니다.', 'blue');
  await save('device-bundles.svg', '장치별 소스와 실행 산출물의 구분', 'Manifest가 선언한 입력을 검증하고, 대상 장치에 필요한 소스 묶음만 생성합니다.', 680, b, ['Pauseable.deploy/mmwave-autostart/package_devices.py']);

  const phases = [
    { x: 32, tone: 'green', title: '01  준비와 검증', blocks: [['백업', ['모델 · DB · 환경 · 서비스']], ['소스 무결성', ['Manifest · 선언 파일 · 체크섬']]] },
    { x: 508, tone: 'blue', title: '02  대상 빌드와 설치', blocks: [['실행 산출물 준비', ['SDK / Docker / APK / ONNX']], ['장치 적용', ['ID · 인증 · 권한 · 서비스']]] },
    { x: 984, tone: 'teal', title: '03  실제 입출력 확인', blocks: [['서비스 + 입력', ['수집 · 판단 · 승인 로그']], ['출력과 전달', ['TTS · 가전 · API · 앱 표시']]] },
  ];
  b = '';
  for (const p of phases) {
    b += group(p.x, 126, 424, 364, p.title, p.tone);
    p.blocks.forEach((s, i) => { b += box(p.x + 20, 210 + 146 * i, 384, 98, s[0], s[1], p.tone); });
    b += arrow(`M${p.x + 212} 308V356`, p.tone);
  }
  b += arrow('M436 405H480V259H528') + arrow('M912 405H956V259H1004', 'blue');
  b += note(32, 540, 660, '검증 실패 시 진행 중단', '체크섬을 무조건 갱신하지 않고 원인과 포함 파일을 검토합니다.', 'red') + note(716, 540, 692, '설치 실패 시 필요한 파일만 복구', '개인 이력·DB를 덮어쓰지 않고 백업 버전과 설정을 복원합니다.', 'amber');
  b += text(32, 664, 'GitHub 반영 ≠ 장치 설치 ≠ 서비스 active ≠ 실제 출력 완료', 22, C.ink, 700, 1376);
  await save('deployment-stages.svg', '배포의 단계별 진행 조건', '소스 검증·설치·실기 시험을 구분하고, 실패한 단계에서 멈추거나 기존 상태로 복구합니다.', 704, b, ['Pauseable.deploy/README.md', 'Pauseable.docs/DEPLOYMENT_HANDOFF.txt']);

  b = group(32, 126, 660, 266, '구현 코드', 'green') +
    box(52, 210, 620, 144, '해당 버전이 무엇을 하는가', ['입력 · 알고리즘 · 통신 · 실행 정책', '기능별 코드 위치 / 현재 README', '코드 존재만으로 장치 적용을 증명하지 않음']);
  b += group(748, 126, 660, 266, '자동 검사', 'blue') +
    box(768, 210, 620, 144, '검사한 조건에서 코드가 통과했는가', ['Unit · 회귀 검사 · 빌드 / 대상 commit', 'Workflow · 실행 로그 · 테스트 범위', '모의 입력과 실제 입출력은 별개'], 'blue');
  b += group(32, 432, 660, 266, '저장된 평가', 'teal') +
    box(52, 516, 620, 144, '어떤 데이터에서 어떤 결과를 얻었는가', ['출처 · 분할 · 분모 · 시나리오 · 수치', 'JSON 원본 · 그래프 · 출처 해시', '합성 평가와 환자 성능은 별개'], 'teal');
  b += group(748, 432, 660, 266, '장치 실기 기록', 'amber') +
    box(768, 516, 620, 144, '설치한 버전이 실제로 동작했는가', ['장치 · 설정 · 모델 · 입력 · 출력', '같은 event_id로 API · 화면 · 소리 대조', '과거 팀 시연과 최신 버전 재시험 구분'], 'amber');
  b += text(32, 746, '네 범주의 근거를 함께 제시합니다. 자동 검사 하나를 전체 실기 성능으로 확대하지 않습니다.', 20, C.muted, 400, 1376);
  await save('evidence-map.svg', '설계·시험·평가·실기 기록의 읽는 법', '검증 자료를 네 범주로 나누고, 각 자료가 설명하는 범위를 구분합니다.', 790, b, ['Pauseable.docs/evaluation/ha/verification_summary.json', 'Pauseable.docs/README.md']);

  b = table(32, 132, [262, 638, 476], ['Workflow', '검사 범주', '실행 / 산출물'], [
    ['HA 보고서', '보고서 회귀 · 일반 / python -O', '관련 PR · main push · 수동'],
    ['앱 · API', 'API · catalog · Push · 날씨 / Flutter 분석·시험', '관련 PR · main push · 수동'],
    ['Voice', 'Worker · pipeline · 설정 · 모델 updater', '관련 push · PR / 검사 로그'],
    ['선호 음악', '모의 Player · 라우팅 · Shell 문법', '관련 PR · main push · 수동'],
    ['Android 시험 APK', '비공개 설정 · 분석·시험 · release 빌드', '수동 / APK + SHA-256'],
  ], 'blue', 72);
  b += note(32, 596, 660, '경로 필터와 대상 commit', '문서 수정만으로 모든 런타임 검사가 다시 실행되지는 않습니다.', 'blue') + note(716, 596, 692, '실기 E2E는 별도 시험', 'CI 통과는 GPU 학습·Pi 출력·휴대폰 표시 완료가 아닙니다.', 'amber');
  await save('ci-map.svg', '자동 검사의 다섯 범주', '각 Workflow의 책임을 분리하며, 실제 실행 여부와 결과는 Actions 기록에서 확인합니다.', 720, b, ['.github/workflows/ha-report-checks.yml', '.github/workflows/native-alert-checks.yml', '.github/workflows/voice-checks.yml', '.github/workflows/favorite-music-checks.yml', '.github/workflows/native-push-apk.yml']);

  b = group(32, 126, 660, 406, 'GitHub Actions / 수동 빌드', 'blue', 'flutter') +
    box(52, 210, 620, 112, 'workflow_dispatch + 팀 시험 설정', ['Firebase Android 클라이언트 설정 · App Token', 'Device / Worker / R2 / 서버 비밀 키 제외'], 'blue') +
    arrow('M362 322V376', 'blue') + box(52, 376, 620, 112, 'Analyze · Test · release APK', ['APK + SHA-256 / artifact 보관 3일', '현재 시험용 서명 · 공유 App Token'], 'blue');
  b += group(748, 126, 660, 406, 'Android / 실기 확인', 'teal', 'firebase') +
    box(768, 210, 620, 112, 'APK 설치 · 등록 · 권한', ['서버·대상자·Firebase 설정 일치', '알림 권한 · 절전 · 방해 금지 확인'], 'teal') +
    arrow('M1078 322V376', 'teal') + box(768, 376, 620, 112, '실제 알림과 앱 이동', ['Foreground / Background / 잠금 상태', '같은 event_id의 API 저장 · 실제 표시 대조'], 'teal');
  b += arrow('M672 430H768', 'blue');
  b += note(32, 584, 1376, '빌드 성공과 휴대폰 수신 성공을 따로 기록합니다', '현재 내부 시험 APK는 공개 배포용 사용자 인증·서명·릴리스 체계를 대신하지 않습니다.', 'amber');
  await save('apk-build.svg', 'Android 빌드와 실제 알림 시험', '자동으로 만들 수 있는 산출물과 휴대폰에서 확인해야 하는 수신 상태를 나눕니다.', 712, b, ['.github/workflows/native-push-apk.yml', 'Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md']);

  return figures;
}
