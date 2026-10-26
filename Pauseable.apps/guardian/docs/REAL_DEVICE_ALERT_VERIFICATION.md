# Pi5 → Render → 보호자 웹앱 알림 확인 절차

이 문서는 구현 여부와 **실제 장비에서 받은 사실**을 구분하기 위한 점검표입니다. 환자 안전 기능으로 취급하기 전에 팀원과 함께 제한된 시험 환경에서 진행하세요.

2026-10-05 현재 Render에는 `/api/events/decisions`가 배포되어 있습니다. 반복행동·배회 의심 모두 서버 저장, 열린 앱의 WebSocket 알림, 설정된 구독으로 Web Push 발송 경로가 구현됐습니다. 냉장고 반복행동 데모는 팀원이 MQTT와 Central 수신까지 확인했지만, Pi의 Render 전송 스위치는 기본값이 꺼져 있고 실장비 → Render → 앱은 아직 검증하지 못했습니다. 배회 판단 Publisher와 실측 정확도도 별도 검증 대상입니다. 과거 팀 인수인계 문서의 "API 404" 기록은 이 배포 이전 상태입니다.

보호자 웹앱의 HTTPS 주소는 웹앱을 배포한 호스팅 서비스의 사이트 화면에서 확인합니다. `https://pauseable-api.onrender.com`은 API 서버 주소이고, `http://127.0.0.1:...`은 노트북 전용 미리보기입니다. 저장소에는 현재 웹앱 호스팅 설정이 없으므로, 배포하지 않았다면 아직 공개 HTTPS 주소가 없습니다. 휴대폰이 없다면 1~2단계와 서버의 계약·인증 테스트까지만 검증하고, 3단계 이후 실제 OS 수신은 보류합니다.

1. 변경된 FastAPI와 Flutter Web을 각각 배포하고 배포된 코드 버전을 기록합니다. Render에 `STORAGE_BACKEND=r2` 및 기존 R2 설정, 서로 다른 `PAUSEABLE_APP_TOKEN`과 `PAUSEABLE_DEVICE_TOKEN`을 넣습니다. Web Push용 `PAUSEABLE_WEB_PUSH_ENABLED=1`, 짝이 맞는 VAPID 공개/개인키, `PAUSEABLE_VAPID_SUBJECT`, `PAUSEABLE_WEB_ORIGINS=https://보호자-웹앱-도메인`도 설정합니다. 개인키·토큰은 Git, 채팅, Flutter 빌드에 넣지 않습니다.
2. 공개 웹앱의 고정 `APP_TOKEN` 빌드는 실서비스 인증으로 쓰면 안 됩니다. 구독 API가 보호 대상자의 알림 수신 권한을 주기 때문입니다. 공개 시험 전 로그인 기반 단기 세션이나 BFF를 연결해 사용자별 환자 접근권한을 검증합니다. 이 작업이 없으면 테스트 계정/폐기 가능한 토큰과 제한된 환경에서만 시험합니다.
3. HTTPS 웹앱을 실제 보호자 휴대폰에서 열고 `설정 → 웹 푸시 알림 → 켜기`를 누른 다음 브라우저 및 OS 알림 권한을 허용합니다. Android Chrome은 사이트 알림이 켜져 있어야 하고, iPhone은 홈 화면에 추가한 웹앱에서 버튼을 눌러야 합니다. 브라우저 개발자 도구나 서버 로그에서 구독 POST 201을 확인합니다.
4. Pi5가 최신 Central Atlas App 코드를 실행하는지, MQTT 판단 입력과 `patient_id=byunwoojin`, `device_id=pi5-home-01`이 계약과 일치하는지 확인합니다. 서버에 `/api/events/decisions`가 배포되어 있고 Device Bearer로 승인된 시험 요청이 HTTP 202인지 먼저 확인합니다. 이 단계에서는 임의의 환자 알림을 보내지 않도록 명확히 표기된 시험 사건만 사용합니다.
5. 승인된 반복행동 시험에서만 Pi5의 `REPETITIVE_ACTIONS_ENABLED=1`, `DECISION_GATEWAY_ENABLED=1`, `DECISION_GATEWAY_URL=https://.../api/events/decisions`, `PAUSEABLE_DEVICE_TOKEN`을 실행 환경에 적용합니다. `WANDERING_ACTIONS_ENABLED`와 `RAW_HA_ACTIONS_ENABLED`는 별도 검증 없이 켜지 않습니다. Pi 로그의 `ACTION_ROUTER_READY`, `DECISION_GATEWAY_READY`, `DECISION_OUTBOX_STATUS`를 확인합니다.
6. 센서의 반복 개폐를 안전하게 재현해 새 `event_id`가 만들어졌는지 확인합니다. Render 요청은 HTTP 202, 앱이 열려 있을 때 WebSocket `app_alert`, 앱 이력 조회에서 같은 `alert_id`가 하나인지 확인합니다. 앱/브라우저를 닫고 **다른 새 사건**을 발생시켜 휴대폰 OS 알림이 실제로 뜨는지 확인합니다. Render의 `Web Push alert=... attempted=... accepted=...` 로그는 푸시 서비스의 수락까지만 뜻하며, 휴대폰 표시 여부는 직접 확인해야 합니다.
7. 배회는 실측 검증을 마친 판단 Publisher가 MQTT 계약에 맞게 보내는 것이 확인된 뒤 **별도 승인된 시험에서만** `WANDERING_ACTIONS_ENABLED=1`을 적용하고 6단계를 반복합니다. 합성 경로 후보를 실제 배회 확정으로 표시하지 않습니다.
8. 동일 `event_id`를 재전송하면 HTTP 200, 앱 이력 한 건, 푸시 추가 발송 없음이 정상입니다. 401/403은 토큰·권한, 404는 배포 버전·경로, 422는 계약 필드/시간대, 409는 ID 충돌, 5xx는 서버·R2·푸시 설정을 점검합니다. 기기별 OS 절전/집중 모드도 확인합니다.

Web Push는 높은 긴급도(`Urgency: high`)로 요청하지만 네트워크·브라우저·OS 정책 때문에 지연되거나 표시되지 않을 수 있고, 알림 소리는 휴대폰 설정에 따릅니다. 현재 발송 작업은 영속 재시도 큐가 아닌 서버 백그라운드 작업입니다. 안전 대응의 유일한 경로로 사용하지 마세요. 실장비 검증 완료 기록에는 Pi 이벤트 ID, Render 시각/상태, WebSocket 수신, 앱 이력, 닫힌 앱의 휴대폰 알림 캡처를 함께 남깁니다.
