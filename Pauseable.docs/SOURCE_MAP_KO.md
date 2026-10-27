# Memolink 기능별 코드 위치

[전체 프로젝트](../README.md) · [개발환경](DEVELOPMENT_ENVIRONMENT_KO.md) · [통신 규격](../Pauseable.contracts/README.md) · [장치 배포](../Pauseable.deploy/README.md)

입력 수집부터 분석, Central 실행과 앱 표시까지 담당 파일을 연결했습니다. 각 파일의 설정·실행 명령은 해당 파트의 README에서 확인합니다.

## HA 가전 반복행동

| 단계 | 주요 코드 | 담당 처리 |
| --- | --- | --- |
| 이벤트 수집 | [collect_ha_events_ws.py](../Pauseable.ai/ha/src/collect_ha_events_ws.py) | HA WebSocket 구독, 상태 변경·초기 상태·관측 정보 |
| 상태 정규화 | [entity_mapper.py](../Pauseable.ai/ha/src/entity_mapper.py) | 엔티티 상태를 가전·행동 규격으로 변환 |
| 특징 생성 | [make_ha_features.py](../Pauseable.ai/ha/src/make_ha_features.py) | 시간 구간별 횟수·전환·재시작·시간·요일 |
| 참조 기준 생성 | [build_baseline.py](../Pauseable.ai/ha/src/build_baseline.py) | 정상 참조 특징의 분위수·IQR 통계 |
| 규칙 점수 | [infer_ha_baseline.py](../Pauseable.ai/ha/src/infer_ha_baseline.py) | 최소 횟수·통계 상한·패턴·야간 점수 |
| IF·AE 학습 | [train_ha_anomaly_models.py](../Pauseable.ai/ha/src/train_ha_anomaly_models.py) | 시간순 분할·모델 학습·임계값 보정 |
| 모델 운용 | [ha_model_lifecycle.py](../Pauseable.ai/ha/src/ha_model_lifecycle.py) | 학습 후보·활성화·fallback·갱신 |
| Routine 보정 | [ha_personal_routine.py](../Pauseable.ai/ha/src/ha_personal_routine.py) | 확인된 정상 생활패턴과 현재 근거 비교 |
| 서비스 관리 | [run_ha_full_service.py](../Pauseable.ai/ha/src/run_ha_full_service.py) | 지속 수집·분석 회차·판정 이력 관리 |
| 현재 결정 전송 | [ha_decision_delivery.py](../Pauseable.ai/ha/src/ha_decision_delivery.py) | 현재 결정 검사와 MQTT 전달 |

[HA 모듈 안내](../Pauseable.ai/ha/README.md) · [평가 원본](evaluation/ha)

## mmWave 이동 분석

| 단계 | 주요 코드 | 담당 처리 |
| --- | --- | --- |
| 센서 릴레이 | [relay_supervisor.py](../Pauseable.edge/mmwave-relay/relay_supervisor.py), [validate_event.py](../Pauseable.edge/mmwave-relay/validate_event.py) | 센서 입력 검증과 Pi 5 중계 |
| 실시간 실행 | [wandering_live.py](../Pauseable.ai/mmwave/src/wandering_live.py), [wandering_runtime.py](../Pauseable.ai/mmwave/src/wandering_runtime.py) | 스트림 입력·구간 생성·상태 저장 |
| 형태 모델 | [shape_v2](../Pauseable.ai/mmwave/src/shape_v2) | 경로 형태 특징·Random Forest·평가 |
| 개인 이력 | [personal_baseline.py](../Pauseable.ai/mmwave/src/personal_baseline.py) | 과거 관측 분포와 변화 비교 |
| 판단 전달 | [wandering_publisher.py](../Pauseable.ai/mmwave/src/wandering_publisher.py) | 계약에 맞는 MQTT 메시지 |

[mmWave 모듈 안내](../Pauseable.ai/mmwave/README.md) · [Runtime 정책](mmwave/RUNTIME.md)

## Central 수신과 실행

| 단계 | 주요 코드 | 담당 처리 |
| --- | --- | --- |
| 시작·설정 | [main.cpp](../Pauseable.edge/central/src/main.cpp) | 구성요소 연결과 실행 |
| MQTT Subscribe | [MqttDecisionSubscriber.cpp](../Pauseable.edge/central/integration/src/MqttDecisionSubscriber.cpp) | 반복행동·배회 Topic 구독 |
| 입력 검증 | [BehaviorInference.cpp](../Pauseable.edge/central/core/src/BehaviorInference.cpp) | 출처·필드·시각·식별자와 중복 검사 |
| 내부 Event | [DecisionEvent.cpp](../Pauseable.edge/central/core/src/DecisionEvent.cpp) | Decision과 API Event 형식 |
| Action Router | [ActionRouter.cpp](../Pauseable.edge/central/core/src/ActionRouter.cpp) | 활성화·위험 단계·cooldown에 따른 실행 허용 |
| 영속 전송 대기 | [DecisionOutbox.cpp](../Pauseable.edge/central/integration/src/DecisionOutbox.cpp) | API 전송 대기·재시도 상태 |
| Gateway | [DecisionGatewayClient.cpp](../Pauseable.edge/central/integration/src/DecisionGatewayClient.cpp) | 최종 Event의 API 전달 |
| 로컬 TTS | [PiperTtsEngine.cpp](../Pauseable.edge/central/integration/src/PiperTtsEngine.cpp) | Piper 음성 합성 연결 |

[Central 안내](../Pauseable.edge/central/README.md) · [입력 시험 스크립트](../Pauseable.edge/central/scripts/test_mqtt_intake.sh)

## 앱과 출력

| 기능 | 주요 경로 | 담당 처리 |
| --- | --- | --- |
| API 요청·인증 | [main.py](../Pauseable.apps/api/app/main.py), [security.py](../Pauseable.apps/api/app/security.py) | 장치·앱·Worker 요청 처리 |
| 보호자 앱 | [guardian/lib](../Pauseable.apps/guardian/lib) | 알림·사진·설정·녹음·모델 상태 |
| 출입 사진 | [camera_buffer.py](../Pauseable.edge/camera/camera_buffer.py) | 카메라 버퍼·대표 사진·업로드 |
| 지역·조명 | [weather_api.py](../Pauseable.integrations/home-assistant/weather-light-control/weather_api.py), [weather_location.py](../Pauseable.integrations/home-assistant/weather-light-control/weather_location.py) | 앱 지역·기상청·HA 조명 연결 |
| 선호 음악 | [favorite-music](../Pauseable.edge/actions/favorite-music/README.md), [youtube](../Pauseable.edge/actions/youtube) | 현재 등록 곡 조회·Pi Player 요청 |

[API 안내](../Pauseable.apps/api/README.md) · [보호자 앱 상세](../Pauseable.apps/guardian/README.md)

## 개인화 음성

| 단계 | 주요 경로 | 담당 처리 |
| --- | --- | --- |
| 학습 작업 수신 | [r2_worker.py](../Pauseable.ai/voice/pipeline/r2_worker.py) | API Job 임대·다운로드·검사·학습·게시 |
| 학습 실행 | [train_voice_model.sh](../Pauseable.ai/voice/train_voice_model.sh) | Docker Piper 학습 파이프라인 |
| WAV 전처리 | [preprocess.py](../Pauseable.ai/voice/scripts/preprocess.py) | mono·22,050 Hz·PCM16 변환 |
| Pi 모델 교체 | [voice_model_updater.py](../Pauseable.edge/voice-model/voice_model_updater.py) | 다운로드·해시·설정·합성 검사 후 적용 |

[Voice 모듈 안내](../Pauseable.ai/voice/README.md) · [데이터 정책](voice/DATA_AND_ARTIFACTS_KO.md)

## 설치와 검증

[개발환경](DEVELOPMENT_ENVIRONMENT_KO.md)에서 필요한 도구를 준비하고, [파트별 검사](../.github/CI_README.md)와 [배포 절차](../Pauseable.deploy/README.md)를 구분해 진행합니다. 실행 결과를 확인할 때는 입력의 `event_id`, Central 판단, API 접수와 실제 장치 출력을 연결해 대조합니다.
