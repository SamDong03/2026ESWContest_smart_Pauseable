# 프로그램 사이의 메시지 규격

이 폴더는 **AI·Central·API·앱이 같은 데이터를 같은 의미로 읽도록 정한 약속**을 보관합니다. JSON은 데이터를 표현하는 형식이고, JSON Schema는 필수 항목·자료형·허용값을 정의한 검사 기준입니다. 실제 송수신은 각 프로그램이 수행합니다.

[전체 시스템](../README.md) · [AI](../Pauseable.ai/README.md) · [Central](../Pauseable.edge/README.md) · [API·앱](../Pauseable.apps/README.md)

<a id="메시지-구성"></a>

## 1. 세 종류의 메시지를 구분한다

| 순서 | 보내는 곳과 받는 곳 | 메시지에 담는 내용 | 기준 파일 |
| --- | --- | --- | --- |
| 1 | 행동 AI에서 Central로 | 관측한 행동·위험 단계·점수·근거 | [behavior-inference.schema.json](communication-v1/schemas/behavior-inference.schema.json) |
| 2 | Central에서 API로 | 최종 판단과 허용한 actions | [decision-event.schema.json](communication-v1/schemas/decision-event.schema.json) |
| 3 | API에서 보호자 앱으로 | 보호자가 확인할 사건·안내·읽음 정보 | [app-alert.schema.json](communication-v1/schemas/app-alert.schema.json) |

Central은 AI JSON을 그대로 API에 전달하지 않습니다. 수신 검증과 Action Router를 거친 결과로 두 번째 메시지를 만듭니다.

첫 번째는 **관측에 대한 판단**, 두 번째는 **Central이 허용한 처리**, 세 번째는 **보호자 화면에 표시할 알림**입니다. 같은 사건을 다루지만 메시지의 역할과 필드는 서로 다릅니다.

<a id="ai--central-추론-전달"></a>

## 2. AI 판단을 MQTT로 전달한다

MQTT의 **Topic**은 메시지를 구분하는 주소입니다. 반복행동과 배회는 다른 Topic을 사용하며, 본문의 `source`도 그 Topic과 일치해야 합니다.

| Topic | `source` | 허용 `behavior` |
| --- | --- | --- |
| `pauseable/ai/repetitive/decision` | `repetitive-ai` | `normal`, `repetitive`, `unknown` |
| `pauseable/ai/wandering/decision` | `wandering-ai` | `normal`, `wandering`, `unknown` |

### 2.1 메시지의 항목을 읽는 순서

| 필드 | 의미 |
| --- | --- |
| `contract_version` | 사용한 규격 버전. 현재 v1은 `1.0` |
| `event_id` | 사건 식별자. 재전송과 중복·충돌을 구별할 때 사용 |
| `occurred_at` | 타임존을 명시한 UTC 사건 시각 |
| `patient_id`, `device_id` | 대상자와 발생 장치 |
| `source`, `behavior` | 판단을 만든 프로그램과 관측 행동 |
| `risk_level`, `risk_score` | 시스템 위험 단계와 0~100의 정수 점수 |
| `model_version` | 판단에 사용한 모델·정책의 버전 |
| `inference_status` | 정상 추론, 관측 부족, 센서 오류, 모델 오류 구분 |
| `evidence` | 선택적인 관측 개수·구간 길이·패턴·판정 근거 |

`inference_status=ok`이면 행동·위험도·정수 점수를 보냅니다. 관측 부족이나 오류이면 행동과 위험도는 `unknown`, 점수는 `null`입니다. HA 내부의 `attention/risk`는 Publisher에서 `caution/danger`로 바꿉니다. 점수는 질병 확률이나 모델 정확도가 아닙니다.

필드가 채워진 예시는 [repetitive-inference.json](communication-v1/examples/repetitive-inference.json)에 있습니다. 예시를 실제 발행할 때는 새 사건 ID와 현재 UTC 시각을 사용해야 합니다.

`event_id`는 전송할 판단 메시지를 식별합니다. 네트워크 재시도에는 같은 ID·같은 내용을 사용하고, 새로운 판단에는 새 ID를 사용합니다. HA에서 여러 판정 시점을 묶은 Episode와 전송 메시지 ID는 구분합니다.

### 2.2 전달 방식

Central의 현재 수신 경로는 **QoS 1, retained=false** 메시지를 처리합니다. QoS 1은 재전송으로 같은 메시지가 두 번 도착할 수 있으므로, 소비자도 사건 ID와 내용을 검사해야 합니다.

현재 v1 Schema의 대상자·장치는 시연 ID로 고정되어 있습니다. 다른 가구를 연결할 때는 Publisher·Central 설정·Schema·API의 ID를 함께 맞춥니다.

<a id="수신-메시지-검증"></a>

## 3. Central이 메시지를 검사한다

1. JSON을 해석하고 필수 필드·자료형·허용값을 확인합니다.
2. Topic과 `source`, 행동 종류의 조합을 검사합니다.
3. 대상자·장치와 사건 시각을 검사합니다. 기본 허용 범위는 과거 300초·미래 30초입니다.
4. 같은 사건 ID의 이전 내용을 확인합니다. 같은 내용은 중복으로 무시하고 다른 내용은 충돌로 차단합니다.
5. 통과한 메시지를 C++ 내부 Decision으로 바꿉니다.
6. Action Router가 실행 정책을 별도로 검사합니다.

JSON이 아닌 입력이나 잘못된 필드는 거절 사유를 기록합니다. 정상 데이터로 자동 변환하지 않습니다. `unknown` 역시 `normal`과 다른 상태로 유지합니다.

<a id="central--api-실행-결정-전달"></a>

## 4. Central의 최종 사건을 API에 보낸다

보호자 전달이 허용된 사건은 Outbox에 보관한 뒤 Device Token으로 `POST /api/events/decisions`에 전송합니다.

| 항목 | 최종 사건의 값 |
| --- | --- |
| `source` | `central-atlas-app` |
| `decision` | `normal`, `repetitive_behavior`, `wandering_suspected`, `unknown` |
| `actions` | v1에서 정의한 `notify_guardian`, `control_appliance` |
| `event_id` | API 저장과 재전송 중복 처리의 기준 |
| `Idempotency-Key` | 헤더가 있으면 본문의 `event_id`와 일치해야 함 |

API도 같은 ID·같은 내용의 재전송과 같은 ID·다른 내용의 충돌을 구별합니다. 실제 예시는 [central-decision.json](communication-v1/examples/central-decision.json), 변환 코드는 [DecisionEvent.cpp](../Pauseable.edge/central/core/src/DecisionEvent.cpp)에 있습니다.

`actions`는 허용한 동작을 나타내는 필드이며 실제 장치의 완료 확인은 아닙니다. 현재 기본 C++ Router는 `control_appliance`를 활성화하지 않습니다. 가전은 Central 승인 로그를 확인하는 [별도 출력 프로그램](../Pauseable.edge/README.md#4-행동별-출력-central-승인-후-가전과-안내를-실행한다)에서 실행합니다.

## 5. 그 밖의 입력과 응답

| 용도 | 파일 |
| --- | --- |
| mmWave 대상·좌표·시각 | [mmwave-target-event.schema.json](mmwave-target-event.schema.json) |
| HA 엔티티 상태 | [ha-entity-event.schema.json](ha-entity-event.schema.json) |
| 보호자 응답 | [guardian-response.schema.json](communication-v1/schemas/guardian-response.schema.json) |
| 장치 명령·ACK | [device-command.schema.json](communication-v1/schemas/device-command.schema.json), [command-ack.schema.json](communication-v1/schemas/command-ack.schema.json) |
| 음성 요청·결과 | [voice-request.schema.json](voice-request.schema.json), [voice-result.schema.json](voice-result.schema.json) |

보조 규격의 적용 범위는 모듈마다 다릅니다. 해당 Schema와 실제 수신 코드·배포 설정을 함께 확인합니다.

<a id="검증-구현"></a>
<a id="버전-관리"></a>

## 6. 규격을 변경하고 확인하는 순서

1. 변경할 생산자·소비자와 사용하는 규격 버전을 정합니다.
2. Schema와 예시를 바꾼 뒤 정상·unknown·누락·범위 초과 사례를 준비합니다.
3. [Central 검증기](../Pauseable.edge/central/core/src/BehaviorInference.cpp), [Action Router](../Pauseable.edge/central/core/src/ActionRouter.cpp), [API 수신기](../Pauseable.apps/api/app/main.py)의 해석을 함께 맞춥니다.
4. 중복·시각 오류·같은 ID의 내용 충돌을 검사합니다.
5. 장치에 설치한 버전과 설정도 갱신하고 실제 메시지를 대조합니다.

최상위 [decision-event.schema.json](decision-event.schema.json)은 간략 형식이며 `communication-v1`과 다릅니다. 현재 AI·Central·API 연결은 `communication-v1`을 기준으로 확인합니다.

아래 명령은 저장소 루트에서 **JSON 문법만** 확인합니다. 전체 의미 검증은 각 생산자·소비자의 테스트에서 수행합니다.

```sh
python -m json.tool Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json
```

[Central 테스트](../Pauseable.edge/central/tests) · [API 테스트](../Pauseable.apps/api/tests)
