# Pauseable.contracts

<a id="pauseablecontracts"></a>

**센서·AI·Central·API·보호자 앱이 주고받는 JSON의 형식과 의미를 정의합니다.**

[프로젝트](../README.md) · [AI](../Pauseable.ai/README.md) · [Central](../Pauseable.edge/README.md) · [API·앱](../Pauseable.apps/README.md)

[주요 구성](#주요-구성) · [폴더 구조](#폴더-구조) · [데이터가 전달되는 단계](#데이터가-전달되는-단계) · [AI 판단 메시지](#ai-판단-메시지) · [수신 검증](#수신-검증)

<a id="주요-구성"></a>

## 주요 구성

| 구분 | 내용 |
| --- | --- |
| JSON Schema | 필수 필드·자료형·허용값·범위를 정의 |
| 메시지 예시 | 정상 판단·명령·응답과 센서 오류 상황의 JSON |
| 규격 버전 | AI→Central→API 연결에는 `communication-v1` 사용 |

각 생산자·소비자가 같은 JSON 계약을 적용하도록 필드 정의와 검사 기준을 제공합니다.

<a id="폴더-구조"></a>

## 폴더 구조

```text
Pauseable.contracts/
├── communication-v1/                        # AI→Central→API→앱 연결 규격
│   ├── examples/
│   └── schemas/                             # 추론·최종 사건·알림·명령·응답 Schema
│       ├── app-alert.schema.json            # API → 보호자 앱 알림 규격
│       ├── behavior-inference.schema.json   # AI → Central 행동 추론 규격
│       ├── command-ack.schema.json          # 장치 명령 처리 결과 규격
│       ├── decision-event.schema.json       # Central → API 최종 사건 규격
│       ├── device-command.schema.json       # 장치 실행 명령 규격
│       └── guardian-response.schema.json    # 보호자 후속 응답 규격
├── examples/
│   └── mmwave/                              # 감지·미감지·오류·잘림·재생 센서 예시
├── ha-entity-event.schema.json              # HA 엔티티 관측 규격
├── mmwave-target-event.schema.json          # mmWave 원시 대상·좌표·품질 규격
├── voice-request.schema.json                # 음성 합성 요청 규격
└── voice-result.schema.json                 # 음성 합성 결과 규격
```

| 경로 | 설명 |
| --- | --- |
| `communication-v1/schemas` | 행동 추론·최종 사건·앱 알림·장치 명령·ACK·보호자 응답 |
| `communication-v1/examples` | 각 v1 메시지의 구체적인 작성 예시 |
| `examples/mmwave` | 감지·미감지·센서 오류·잘린 대상 목록·재생 입력 |
| 최상위 `*.schema.json` | 센서 원시 관측, HA 엔티티, 음성 요청·결과 등 보조 규격 |

<a id="메시지-구성"></a>

<a id="데이터가-전달되는-단계"></a>

## 데이터가 전달되는 단계

| 단계 | 생산자 → 소비자 | 기준 파일 |
| --- | --- | --- |
| 행동 추론 | HA·mmWave AI → Central | [behavior-inference](communication-v1/schemas/behavior-inference.schema.json) |
| 최종 사건 | Central → API | [decision-event](communication-v1/schemas/decision-event.schema.json) |
| 보호자 알림 | API → 앱 | [app-alert](communication-v1/schemas/app-alert.schema.json) |
| 후속 응답 | 앱·장치 → 처리 모듈 | [guardian-response](communication-v1/schemas/guardian-response.schema.json), [command-ack](communication-v1/schemas/command-ack.schema.json) |

추론 메시지는 분석 근거를 담고, 최종 사건은 Central이 허용한 actions를 담습니다. API의 앱 알림은 보호자가 확인할 형태로 변환된 자료입니다.

<a id="ai--central-추론-전달"></a>

<a id="ai-판단-메시지"></a>

## AI 판단 메시지

| Topic | `source` | `behavior` |
| --- | --- | --- |
| `pauseable/ai/repetitive/decision` | `repetitive-ai` | `normal`, `repetitive`, `unknown` |
| `pauseable/ai/wandering/decision` | `wandering-ai` | `normal`, `wandering`, `unknown` |

| 주요 필드 | 의미 |
| --- | --- |
| `contract_version` | 사용한 규격 버전. 현재 v1은 `1.0` |
| `event_id` | 중복·재전송·내용 충돌을 구별할 사건 ID |
| `occurred_at` | 타임존이 명시된 UTC 사건 시각 |
| `patient_id`, `device_id` | 대상자와 발생 장치 |
| `risk_level`, `risk_score` | 위험 단계와 0~100의 정수 점수 |
| `inference_status` | 정상 추론·관측 부족·센서 오류·모델 오류 구분 |
| `evidence` | 관측 개수·구간·패턴 등 선택적 근거 |

관측 부족·오류는 행동과 위험도를 `unknown`, 점수를 `null`로 전달합니다. [반복행동 예시](communication-v1/examples/repetitive-inference.json)

<a id="수신-메시지-검증"></a>

<a id="수신-검증"></a>

## 수신 검증

1. JSON 문법, 필수 필드, 자료형과 허용값을 검사합니다.
2. MQTT Topic과 `source`·행동의 조합을 확인합니다.
3. 대상자·장치와 사건 시각을 확인합니다. Central 기본 시간 범위는 과거 300초·미래 30초입니다.
4. 같은 ID·같은 내용은 중복으로, 같은 ID·다른 내용은 충돌로 처리합니다.
5. 통과한 추론을 내부 Decision으로 바꾸고 Action Router에서 실행 여부를 별도로 확인합니다.

현재 Schema의 시연 대상자·장치 ID를 바꿀 때는 Publisher·Central·API 설정도 함께 맞춥니다. QoS 1의 재전송 가능성 때문에 소비자의 중복 검사가 필요하며 retained 메시지를 실제 새 판단처럼 사용하지 않습니다.

<a id="central--api-실행-결정-전달"></a>

<a id="최종-사건과-보조-규격"></a>

## 최종 사건과 보조 규격

Central은 Device 인증으로 `POST /api/events/decisions`에 전송합니다. `source`는 `central-atlas-app`이며 v1의 actions에는 `notify_guardian`, `control_appliance`가 있습니다. `Idempotency-Key` 헤더를 사용하면 본문의 사건 ID와 일치해야 합니다. [최종 사건 예시](communication-v1/examples/central-decision.json)

| 보조 입력 | 규격 |
| --- | --- |
| mmWave 대상·좌표·품질 | [mmwave-target-event.schema.json](mmwave-target-event.schema.json) |
| HA 엔티티 상태 | [ha-entity-event.schema.json](ha-entity-event.schema.json) |
| 음성 합성 요청·결과 | [voice-request](voice-request.schema.json), [voice-result](voice-result.schema.json) |
| 장치 명령 | [device-command](communication-v1/schemas/device-command.schema.json) |

최상위 [decision-event.schema.json](decision-event.schema.json)은 간략 형식입니다.

<a id="검증-구현"></a>
<a id="버전-관리"></a>

<a id="규격-변경과-검사"></a>

## 규격 변경과 검사

변경 시 Schema·예시·생산자·소비자와 장치에 설치한 사본을 함께 확인합니다. 정상·unknown·필드 누락·시각 오류·같은 ID의 내용 충돌을 검사합니다.

```sh
python -m json.tool Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json
```

JSON 문법을 확인한 뒤 메시지의 필드·조합·시간·중복 처리는 [Central 테스트](../Pauseable.edge/central/tests), [API 테스트](../Pauseable.apps/api/tests), [센서 계약 검사](../Pauseable.edge/mmwave-relay/test_contract.py)에서 확인합니다.
