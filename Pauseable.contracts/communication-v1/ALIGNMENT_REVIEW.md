# Pauseable 통신 계약 구현 대조 검토

검토일: 2026-09-16  
저장소 기준: `chimae-yebang/RACOS` `main` 커밋 `2252ec9d9661d29602e97be158b98c8d7f6fddd0`

## 결론

초안의 전체 통신 방향은 적절했지만 그대로 구현하면 현재 코드와 충돌하는 부분이 있었다. 이번 개정에서 AI 실제 출력, 기존 App Alert 필드, 최신 Device Token 코드, 현재 Backend와 Flutter의 동작을 반영했다.

## 반드시 수정한 항목

| 중요도 | 초안 문제 | 개정 내용 |
| --- | --- | --- |
| 높음 | AI에 없는 `confidence`를 필수로 요구 | 실제 출력인 `risk_score` 0~100을 사용 |
| 높음 | AI의 `normal/attention/risk`와 계약의 위험도 이름이 다름 | `normal/caution/danger` 변환표 명시 |
| 높음 | 현재 `related_event_id`와 새 `event_id`가 충돌 | `event_id`를 표준으로 하고 전환 기간 두 필드 동시 지원 |
| 높음 | Flutter WebSocket 인증 방법이 현재 코드에 없음 | 모바일 v1은 Bearer Header, Web은 별도 세션/Ticket 필요 명시 |
| 높음 | `PAUSEABLE_DEVICE_TOKEN`이 제안값인지 기존값인지 불명확 | 최신 저장소에 이미 보안 함수가 있음을 확인하고 그대로 사용 |
| 중간 | UTC 시간을 `Z`만 허용해 현재 `+00:00` 출력과 충돌 | 둘 다 수신하고 새 송신은 `Z` 권장 |
| 중간 | 보호자 `approved/rejected`의 의미가 불명확 | `confirmed_safe/needs_assistance/dismissed`로 변경 |
| 중간 | WebSocket 재연결 후 놓친 알림 처리의 Endpoint가 없음 | 알림 조회 Endpoint를 계약에 명시 |

## 현재 존재하지만 계약을 아직 만족하지 않는 코드

- Backend에는 `POST /api/events/ha`만 있고 `POST /api/events/decisions`는 없다.
- `/api/events/ha`와 `/ws/alerts`는 현재 Token 검증을 하지 않는다.
- Central `GatewayClient`는 `http://`만 지원하고 Authorization Header를 보내지 않는다.
- Central은 AI 판단 MQTT Topic을 Subscribe하지 않는다.
- Flutter `LiveAlertClient`는 생성·시작되지 않고 Token Header도 보내지 않는다.
- Flutter `AppAuthenticatedClient`는 존재하지만 `main.dart`에서 Token Provider가 주입되지 않는다.
- Render의 중복 제거, 알림 영속 저장, 보호자 응답, 명령 Polling, ACK는 구현되지 않았다.

## 유지해야 하는 기존 코드

- 기존 HA 연동 확인용 `POST /api/events/ha`는 새 Decision 흐름이 검증될 때까지 유지한다.
- 현재 Flutter가 읽는 `alert_id`, `occurred_at`, `risk_level`, `title`, `message`는 그대로 유지한다.
- 기존 `PAUSEABLE_APP_TOKEN`, `PAUSEABLE_DEVICE_TOKEN` 역할을 재사용한다.
- 음성 Worker와 R2 설정은 이번 비음성 계약에서 변경하지 않는다.

## 배포 전 확인

- 캡처에 노출된 실제 App/Worker/R2 자격 증명을 재발급한다.
- Render에 `PAUSEABLE_DEVICE_TOKEN`이 실제로 설정되어 있는지 확인한다.
- 중간 발표가 Android/iOS인지 Flutter Web인지 확정한다. Web이면 현재 모바일 Header 방식 대신 로그인/페어링 또는 단기 Ticket 계약이 먼저 필요하다.
