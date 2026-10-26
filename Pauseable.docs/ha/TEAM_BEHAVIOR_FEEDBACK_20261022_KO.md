# 앱/백엔드 팀의 반복행동 검토 연결 계약

HA 수신·검증·학습 반영 코드는 구현했다. 이번에 Flutter 화면이나 백엔드 API를 변경한 것은 아니다.
따라서 현재 앱의 일반 확인 버튼을 누르면 새 학습 검토까지 자동으로 전달된다고 설명하면 안 된다.

## 기존 안전 응답은 유지

기존 guardian-response의 confirmed_safe/needs_assistance/dismissed는 안전 대응 결과다.
이를 normal/repetitive 학습 정답으로 변환하지 않는다. 기존 계약에 새 필드를 붙이는 것도 금지한다.
추가 입력은 '이 행동이 평소 정상 루틴인가'라는 명시적인 행동 검토로 구분한다.

## 새 입력

인증된 백엔드가 `pauseable/ai/repetitive/feedback`으로 QoS 1 / retain=false publish한다.
앱에 학습용 MQTT 관리자 비밀번호를 넣지 않는다.
실제 사용자 인증·환자별 권한 확인은 백엔드가 담당하며 reviewer_id는 그 결과에서 생성한다.

```json
{
  "contract_version": "1.0",
  "feedback_id": "review-unique-id",
  "event_id": "ACTUAL_HA_PUBLISHED_EVENT_ID",
  "source_type": "local",
  "household_id": "user_001",
  "patient_id": "byunwoojin",
  "device_id": "pi5-home-01",
  "review_kind": "behavior_label",
  "label": "normal",
  "reviewer_id": "authenticated-guardian-id",
  "reviewed_at": "2026-10-22T12:00:00Z",
  "reason": "usual meal preparation"
}
```

실제 이벤트 ID와 실제 UTC 검토 시각으로 채운다. 위 값은 문서 예시이며 HA가 등록하지 않은 ID는 거절한다.
이벤트별 검토가 아닌 경우 event_id 대신 period.start / period.end의 UTC 시각을 보낸다.
하루 이하의 실제 관측 기간만 허용한다.

| label | 의미 |
| --- | --- |
| normal | 보호자가 실제 맥락을 보고 정상 생활로 검토 |
| repetitive | 정상 학습에 넣지 않을 반복행동 후보로 검토 |
| uncertain | 모르겠음/보류. 정상 학습과 루틴 보정에 사용하지 않음 |

이는 의료 진단 라벨이 아니다. 확인하지 않은 사건을 자동 normal 처리하면 안 된다.
잘못된 검토를 고칠 때 같은 ID를 재활용하지 않고 새로운 feedback_id와 더 나중 reviewed_at을 보낸다.
재전송할 때는 원래 feedback_id와 전체 내용·시각을 그대로 유지한다.

## 완료 단계 구분

MQTT PUBACK = 브로커 수신.
queued_not_yet_applied = HA inbox 저장.
검토 원장 적용 = 정상/제외/보류 후보 갱신.
모델 학습 완료 = 별도 데이터 기간·주기·검증 gate를 통과한 상태.
이 네 단계를 모두 '학습 완료'로 표시하면 안 된다.

현재 HA 적용 결과는 models/feedback_inbox_audit.jsonl과 models/feedback.sqlite3에서 확인한다.
앱에 보여 줄 인증된 결과 조회 API나 push/receipt 연결은 백엔드와 별도 연동해야 한다.
이번 작업에서 존재하지 않는 백엔드 endpoint를 구현됐다고 가정하지 않았다.

전체 JSON Schema: deploy/contracts/repetitive-feedback.schema.json.
자세한 보호 규칙·학습 조건: PERSONALIZATION_WORKLOG_20261022_KO.md.
