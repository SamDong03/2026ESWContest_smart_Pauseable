# 🔗 Memolink 공통 통신 규격

AI·Central·API·보호자 앱 사이의 메시지 형식을 정의합니다. JSON Schema에는 필수 필드, 자료형과 허용값을 명시했습니다. AI 추론, Central의 최종 결정과 앱 알림을 서로 다른 메시지로 구분하고, 각 서비스가 수신 시 형식과 처리 조건을 검사합니다.

**통신 규격은 서로 다른 프로그램이 같은 사건을 같은 의미로 읽기 위한 약속**입니다. JSON이 데이터의 표현 형식이라면, JSON Schema는 어떤 항목이 반드시 있고 어떤 값을 허용하는지 정한 검사 기준입니다. 규격 파일만으로 통신이 실행되는 것은 아니며, 각 프로그램의 수신 코드가 이를 검사합니다.

[전체 프로젝트](../README.md) · [AI](../Pauseable.ai/README.md) · [Central](../Pauseable.edge/README.md) · [API·앱](../Pauseable.apps/README.md)

[Schema 구성](#메시지-구성) · [수신 검증](#수신-메시지-검증) · [AI 입력](#ai--central-추론-전달) · [API 전달](#central--api-실행-결정-전달) · [검증 코드](#검증-구현)

## 메시지 구성

![AI Inference, Central Decision, App Alert가 역할에 따라 구분되는 메시지 지도](../Pauseable.docs/assets/readme/contract-map.svg)

AI는 관측 근거와 위험 상태를 전달합니다. Central은 이 결과에 실행 정책을 적용해 최종 Decision Event를 만들고, API는 보호자가 확인할 알림으로 제공합니다. AI의 `risk` 판정만으로 가전 동작이 실행되지는 않습니다.

| 단계 | 메시지가 답하는 질문 |
| --- | --- |
| 🧠 AI Inference | 어떤 행동을 관측했고 어떤 상태로 판단했는가? |
| 🧭 Central Decision | 메시지를 승인했으며 어떤 동작을 허용했는가? |
| 📱 App Alert | 보호자가 어떤 사건과 안내를 확인해야 하는가? |

<details>
<summary><strong>연결별 Schema 파일 전체 보기</strong></summary>

| 연결 | 기준 파일 | 메시지 의미 |
| --- | --- | --- |
| 반복행동·배회 AI → Central | [`communication-v1/schemas/behavior-inference.schema.json`](communication-v1/schemas/behavior-inference.schema.json) | AI 판단 상태·점수·관측 근거 |
| Central → API | [`communication-v1/schemas/decision-event.schema.json`](communication-v1/schemas/decision-event.schema.json) | 최종 Decision과 허용된 actions |
| API → 앱 | [`communication-v1/schemas/app-alert.schema.json`](communication-v1/schemas/app-alert.schema.json) | 보호자에게 보여줄 알림 |
| 보호자 응답 | [`guardian-response.schema.json`](communication-v1/schemas/guardian-response.schema.json) | 보호자 응답 형식 |
| 장치 명령·응답 | [`device-command.schema.json`](communication-v1/schemas/device-command.schema.json), [`command-ack.schema.json`](communication-v1/schemas/command-ack.schema.json) | 명령·ACK 형식 |
| 센서 → 수신기 | [`mmwave-target-event.schema.json`](mmwave-target-event.schema.json) | 센서 대상·위치·시각 등 입력 |
| HA → 연동 계층 | [`ha-entity-event.schema.json`](ha-entity-event.schema.json) | 엔티티 상태 이벤트 |
| 음성 요청·결과 | [`voice-request.schema.json`](voice-request.schema.json), [`voice-result.schema.json`](voice-result.schema.json) | 음성 관련 교환 형식 |

</details>

기본 AI·Central 통신은 `communication-v1`을 기준으로 합니다. 그 외 Schema의 적용 범위는 각 모듈의 구현과 배포 설정에 따릅니다.

## 수신 메시지 검증

![JSON 해석, 계약, 출처·시각, 사건 ID, 실행 정책의 단계별 검증](../Pauseable.docs/assets/readme/validation-gates.svg)

| 입력 사례 | 처리 원칙 |
| --- | --- |
| 반복행동 Topic에 배회 `source` | 출처 불일치로 거절 |
| 오래된 사건·허용 범위 밖의 미래 시각 | 로그를 남기고 실행에 전달하지 않음 |
| 동일 ID·동일 내용 | 중복으로 처리 |
| 동일 ID·다른 내용 | 충돌로 구분 |
| 관측 부족·센서/모델 오류 | `unknown`으로 구분, 정상이나 자동 가전 동작으로 바꾸지 않음 |

## AI → Central: 추론 전달

| MQTT Topic | `source` | 허용 행동 범위 |
| --- | --- | --- |
| `pauseable/ai/repetitive/decision` | `repetitive-ai` | `normal`, `repetitive`, `unknown` |
| `pauseable/ai/wandering/decision` | `wandering-ai` | `normal`, `wandering`, `unknown` |

<details>
<summary><strong>주요 필드와 식별 규칙</strong></summary>

| 필드 | 목적 |
| --- | --- |
| `contract_version` | 현재 v1 계약은 `1.0` |
| `event_id` | 사건 식별과 중복·내용 충돌 확인 |
| `occurred_at` | UTC 사건 시각, 타임존을 명시 |
| `patient_id`, `device_id` | 대상자·장치 일치 확인 |
| `source`, `behavior` | Topic·출처·행동의 의미 일치 |
| `risk_level`, `risk_score` | 위험 단계와 시스템 점수 |
| `inference_status` | 정상 추론·관측 부족·센서/모델 오류 구분 |
| `evidence` | 관측 개수·시간 범위·패턴·판단 근거 |

`inference_status=ok`이면 행동·위험도·정수 점수가 해당 계약을 따라야 합니다. 관측 부족이나 오류이면 행동과 위험도는 `unknown`, 점수는 `null`로 표현합니다. `risk_score`는 0~100의 시스템 점수이지 치매 확률이나 정확도가 아닙니다.

현재 v1은 시연 대상자·장치 ID를 고정해 검사합니다. 다른 가구나 다중 사용자에게 적용하려면 생산자·Central·Schema·API의 식별 규칙과 접근권한을 함께 변경해야 합니다.

</details>

## Central → API: 실행 결정 전달

Central은 AI 메시지를 그대로 전달하지 않고 내부 Decision과 실행 정책을 반영해 `POST /api/events/decisions`로 보냅니다.

- `source`는 `central-atlas-app`입니다.
- `decision`은 `normal`, `repetitive_behavior`, `wandering_suspected`, `unknown`을 구분합니다.
- v1 최종 Event의 `actions`에는 `notify_guardian`, `control_appliance`가 정의되어 있습니다.
- Device Token으로 인증하고 `event_id`를 기준으로 중복을 처리합니다.
- API의 `Idempotency-Key`와 본문의 `event_id`가 다르면 거절합니다.
- 동일 ID에 다른 내용이 들어오는 충돌과 동일 메시지 재전송을 구분합니다.

## 검증 구현

| 단계 | 구현 | 검증 범위 |
| --- | --- | --- |
| Central 입력 | [`BehaviorInference.cpp`](../Pauseable.edge/central/core/src/BehaviorInference.cpp) | JSON 필드·출처·Topic·시각·ID·중복 |
| Central 실행 | [`ActionRouter.cpp`](../Pauseable.edge/central/core/src/ActionRouter.cpp) | 행동별 활성화·위험도·cooldown·실행 허용 |
| API 수신 | [`main.py`](../Pauseable.apps/api/app/main.py) | 인증·요청 모델·UTC·actions·이벤트 충돌 |

형식이 올바른 JSON도 출처·시각·ID·실행 조건을 통과해야 처리합니다. JSON이 아닌 입력이나 잘못된 메시지는 거절 사유를 기록하며, 정상 메시지로 자동 변환하지 않습니다.

## 버전 관리

최상위의 [`decision-event.schema.json`](decision-event.schema.json)은 간략 형식이며 `communication-v1`과 필드·허용값이 다릅니다. 통신 규격을 변경할 때는 사용하는 버전과 배포 사본을 함께 갱신합니다.

1. 생산자·소비자·Topic·인증·버전을 먼저 정합니다.
2. 정상·unknown·누락 필드·범위 초과·동일 ID 충돌 사례를 함께 확인합니다.
3. JSON Schema와 C++/Python 검증기의 의미가 일치하는지 테스트합니다.
4. 배포 사본·환경 설정을 함께 맞추고 이전 메시지와의 호환 여부를 기록합니다.

예를 들어 아래 명령은 **JSON 문법만 확인**합니다. 의미 검증이나 E2E 시험을 대신하지 않습니다. 저장소 루트에서 실행합니다.

```sh
python -m json.tool Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json
```

규격의 초기 대조 내용은 [`ALIGNMENT_REVIEW.md`](communication-v1/ALIGNMENT_REVIEW.md)에 보관했습니다. 현재 동작은 위 검증 코드와 해당 버전의 테스트를 기준으로 확인합니다.
