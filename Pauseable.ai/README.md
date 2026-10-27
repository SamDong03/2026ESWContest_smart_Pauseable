# AI 분석과 개인화 음성 학습

Memolink의 AI 영역은 **HA 가전 반복행동, mmWave 배회 의심 판단, 보호자 음성 학습**으로 나뉩니다. 앞의 두 모듈은 판단 메시지를 만들고, Voice는 Pi에서 안내에 사용할 음성 모델을 만듭니다. 실제 출력을 허용할지는 [Central](../Pauseable.edge/README.md#central-app)이 결정합니다.

[전체 프로젝트](../README.md) · [통신 계약](../Pauseable.contracts/README.md) · [개발환경](../Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md)

| 범주 | 입력 | 핵심 처리 | 출력·실행 위치 |
| --- | --- | --- | --- |
| [HA 반복행동](#ha-반복행동-판단) · `ha/` | 가전 상태 변경·관측 정보 | 특징, Baseline·IF·AE, Routine, Episode | 판단 JSON → MQTT / Pi 5 |
| [mmWave 배회](#mmwave-구현과-설치-상세) · `mmwave/` | 대상·좌표·시각·품질 | 경로 형태, 개인 이력, 지속성 | 판단 JSON → MQTT / Pi 5 |
| [Voice](#voice-학습과-운영-상세) · `voice/` | 동의한 WAV·대본 | 전처리, Piper fine-tuning, 검증 | ONNX → API/R2 / GPU Worker |

![HA·mmWave·Voice의 입력, 처리와 출력](../Pauseable.docs/assets/readme/ai-pipelines.svg)

## HA 반복행동 판단

### HA 데이터 수집과 특징 생성

HA 상태를 매분 조회하는 대신 **WebSocket `state_changed`를 구독**합니다. HA가 변경을 보내면 시각·엔티티·상태를 기록합니다. 열림과 닫힘이 모두 전달되면 2초 개폐도 두 기록으로 남습니다. 제조사나 HA가 전달하지 않은 변화까지 복구하는 기능은 아닙니다.

| 단계 | 처리 | 주요 코드 |
| --- | --- | --- |
| 수집 | 상태 변경·초기 Snapshot·연결 관측 기록 | [collect_ha_events_ws.py](ha/src/collect_ha_events_ws.py) |
| 정규화 | 엔티티별 상태를 가전 행동으로 매핑 | [entity_mapper.py](ha/src/entity_mapper.py) |
| 특징 생성 | 횟수·전환·시작/재시작·시간대·요일 수치화 | [make_ha_features.py](ha/src/make_ha_features.py) |
| 판단 | 통계 규칙과 사용 가능한 모델·Routine 적용 | [run_ha_pipeline.py](ha/src/run_ha_pipeline.py), [ha_model_lifecycle.py](ha/src/ha_model_lifecycle.py) |
| 기록·전송 | 판정·Episode·현재 판단 저장/전달 | [summarize_ha_result.py](ha/src/summarize_ha_result.py), [ha_decision_delivery.py](ha/src/ha_decision_delivery.py) |

공통 스키마는 냉장고·도어락·전자레인지·세탁기·건조기·식기세척기·공기청정기·에어컨의 8종을 지원합니다. 실제 분석 대상은 선택한 엔티티·매핑과 장치가 제공하는 상태에 따라 달라집니다. 전력 사용만으로 냉장고 문 개폐를 알 수는 없습니다.

#### 수집·특징·실행 주기

| 구분 | 기준 | 의미 |
| --- | --- | --- |
| Event 수집 | 상태 변경 수신 시 | 초기 Snapshot은 반복 횟수에서 제외 |
| Feature 기준 시각 | 1분 간격 | 각 시점의 최근 10분·30분·1시간·2시간을 요약 |
| 서비스 분석 회차 | 이전 분석 종료 후 기본 600초 대기 | 수집기는 분석 사이에도 계속 실행 |

`Sliding Window`는 기준 시각이 이동할 때 과거 일정 길이의 이력을 다시 요약하는 방식입니다. 12:00의 10분 특징은 최근 10분을, 12:01의 특징은 1분 이동한 구간을 봅니다. 54개 수치 특징에 서로 겹치는 이력이 들어가므로 **Feature 행 수는 독립 사건 수와 다릅니다.** 즉시 기록과 즉시 알림도 다릅니다.

![같은 48시간의 가전별 상태 변경과 표준화한 54개 특징](../Pauseable.docs/assets/readme/ha-event-features.png)

저장된 합성 평가 자료입니다. 위쪽 색은 **시간당 상태 변경 횟수**, 아래쪽 색은 **학습 구간 scaler로 표준화한 특징값**입니다. 사용 횟수와 상태 변경 횟수는 다를 수 있습니다. 아래 색만 −2~4로 제한하며 원래 값은 유지합니다. [원본](../Pauseable.docs/evaluation/ha/visual_data.json) · [그림 출처](../Pauseable.docs/assets/readme/evaluation_figure_manifest.json)

### Baseline과 개인화 모델

#### 1. Baseline: 이력이 적을 때의 초기 기준

[build_baseline.py](ha/src/build_baseline.py)가 정상 참조 특징의 분위수·IQR 상한을 저장하고, [infer_ha_baseline.py](ha/src/infer_ha_baseline.py)가 최소 횟수·통계 상한·반복 패턴·야간 조건을 적용합니다. 공통 참조로 만든 기준은 개인 기준과 구분합니다.

| 계산 | 현재 규칙 |
| --- | --- |
| 최소 반복 | 특징별 `MinCount` 미만이면 해당 특징은 0점 |
| 통계 상한 | `max(Q3 + 1.0×IQR, P90)`, `max(Q3 + 1.5×IQR, P95)`, `max(Q3 + 2.0×IQR, P99)` |
| 특징 점수 | 상한 초과 단계에 따라 5·9·14점 |
| 추가 근거 | 가전별 반복·재시작 패턴과 야간 Context |
| 기본 단계 | Attention 35 이상, Risk 70 이상 |

예를 들어 `fridge_door_open_count_30m`의 `MinCount`는 5입니다. **5회면 무조건 경보라는 뜻이 아니라** 그 특징을 점수 계산에 넣기 위한 하한입니다. 다른 시간 구간과 패턴 조건도 최종 점수에 반영됩니다. 생성기는 시간대 통계도 보관하지만 현재 기본 추론은 전체 참조 통계와 명시적인 야간 점수를 사용합니다.

#### 2. IF·AE: 정상 분포와 다른 입력 탐색

[train_ha_anomaly_models.py](ha/src/train_ha_anomaly_models.py)는 정상 후보를 시간순 Train·Calibration·Holdout으로 분리합니다. 겹치는 시간 구간의 정보가 분할 경계를 넘지 않도록 경계 구간을 제외합니다. scaler는 Train에서만 학습하고 임계값은 Calibration에서 정합니다.

| 모델 | 학습·점수 | 역할 |
| --- | --- | --- |
| Isolation Forest | 정상 특징 분포 학습, 분리되기 쉬운 입력의 이상 점수 | 여러 특징의 드문 조합 탐색 |
| Autoencoder | StandardScaler → MLP 입력 복원, `54–16–6–16–54` / ReLU·Adam | 정상 특징으로 설명하기 어려운 입력의 Reconstruction Error |
| 임계값 | 모델별 Calibration 점수의 P95·P99 | Attention·Risk 구분 |

치매 여부를 직접 분류하도록 학습하는 구조가 아닙니다. 정상 후보에 관측 오류나 반복 이상이 섞이면 개인 기준도 흐려질 수 있습니다.

#### 3. Lifecycle: 학습 시점·검증·모델 교체

![정상 후보 선별, 시간순 학습·검증, 모드 적용과 실패 처리](../Pauseable.docs/assets/readme/learning-lifecycle.svg)

| 조건·상태 | 코드의 기본 처리 |
| --- | --- |
| 자료 출처 | 같은 가구·출처·특징 규격의 완전한 관측 구간 |
| 정상 후보 | `reviewed_normal`과 규칙 선별인 `baseline_screened` 구분. Local은 기본 확인된 정상만 사용, 선별 후보 허용은 별도 설정 |
| 최초 학습 | 하루 12개 이상 서로 다른 시간대가 있는 유효일 30일 이상, 전체 유효 시간대 360개 이상 |
| 모델 승인 | 학습 경고·수렴, 정상 후보 Holdout 경보 비율, 호환성과 점수 계산 확인 |
| 운용 모드 | `shadow`: 점수 관찰 / `hybrid`: 반복 증거와 모델 신호 결합 |
| 갱신 | `retrain_days=0`이면 비활성. 활성화 시 경과 기간과 새 유효 시간대 24개 이상 등을 확인 |
| 실패 | 새 모델을 적용하지 않고 기존 호환 모델 또는 Baseline 유지 |

Lifecycle은 정상 후보 Holdout에서 IF 또는 AE가 경보인 비율이 0.15 이하인지도 검사합니다. 이는 정상 후보의 동작 검사이며 실제 이상행동 탐지율과 다릅니다. 모델은 버전별 저장 후 활성 포인터를 교체합니다.

#### 4. Hybrid: 모델 점수의 결합 규칙

두 점수를 단순 평균하지 않습니다. [combine()](ha/src/ha_model_lifecycle.py)은 먼저 실제 반복 증거가 있는지 확인합니다.

| 입력 상태 | 결합 규칙 |
| --- | --- |
| 반복 증거 없음 | 모델 단독 이상은 감사 기록에 남기고 반복행동 경보로 승격하지 않음 |
| 검증된 모델 + 반복 증거 + IF 또는 AE 경보 | 규칙이 Normal이면 Attention으로 승격 |
| 검증된 모델 + 반복 증거 + IF·AE 모두 Risk | Risk로 승격 가능 |
| `shadow` | 모델 점수를 기록하되 규칙 판정 유지 |

관측 불완전·모델 오류는 모델의 Normal과 구분합니다. 최종 통신에서는 추론 부족·오류를 `unknown`으로 표현합니다.

#### 5. Routine: 확인된 생활패턴으로 경보 보정

[ha_personal_routine.py](ha/src/ha_personal_routine.py)는 **요일 × 4시간 단위 시간대 × 반복 패턴**으로 프로필을 만듭니다. 하루는 00~04시, 04~08시 등 6개 구간으로 나눕니다. 확인된 정상 이력의 최근 45일을 사용하고, 프로필마다 최소 3일·30분 단위 표본 6개를 요구합니다. 지난주 같은 요일의 사건 하나를 직접 대조하는 방식은 아닙니다.

보정하려면 관측이 완전하고 최근 14일 안에 관측된 프로필 범위에 들어가며, 현재 횟수 조합을 지지하는 과거 날짜가 2개 이상 있어야 합니다. **IF·AE가 모두 Normal이어야** 경보를 낮춥니다. 반복/불확실로 확인된 평가와 보호 규칙(도어락·고밀도 반복 등)은 보정을 막습니다. 보호자의 안전 확인 응답을 자동으로 학습용 정상 라벨로 바꾸지 않습니다.

#### 6. Episode와 MQTT 전달

[summarize_ha_result.py](ha/src/summarize_ha_result.py)는 같은 주요 패턴의 연속 이상 판정을 시작·종료·최고 점수·근거로 요약합니다. 기본 연결 간격은 최대 2분입니다. 겹치는 Feature 행을 사건 단위로 읽기 위한 요약이며 현재 판단 전송과 구분합니다.

[ha_decision_delivery.py](ha/src/ha_decision_delivery.py)는 현재 판단을 공통 계약으로 만들고 전송 상태를 관리합니다. 서비스의 `--publish-mqtt`는 명시적으로 활성화합니다. MQTT 전달과 [Central의 실행 승인](../Pauseable.edge/README.md#central-app)은 별도 단계입니다.

### HA 평가 결과

![같은 조건의 Baseline·IF·AE·Hybrid 경보 비교](../Pauseable.docs/assets/readme/ha-component-comparison.png)

| 시험 | Baseline | Hybrid | 해석 |
| --- | --- | --- | --- |
| 반복 가설 24개 | 16/24 경보 | 24/24 경보 | 경보 범위 확대 |
| 정상 맥락 48개 | 22/48 경보 | 30/48 경보 | 정상 사용의 경보도 증가 |
| 별도 Routine 576시점 | 보정 전 Attention 6·Risk 6 | Attention 6개 Normal 보정, Risk 6개 유지 | 위 48개 시험과 별도 |

모델 비교는 같은 규칙·반복 증거·관측 마스크를 유지한 Ablation이며 **Routine은 미적용**입니다. 경보는 Attention 또는 Risk가 한 번 이상 나온 시나리오 수입니다. 환자 탐지 정확도와 같지 않으며, 별도 Routine 결과를 위 오탐이 모두 해결된 결과로 합치지 않습니다.

![정상 후보 Holdout 144개의 모델별 점수와 임계값](../Pauseable.docs/assets/readme/ha-model-scores.png)

저장된 기록은 Train 428 / Calibration 142 / Holdout 144, AE 337 iterations·최종 Loss 약 0.0382입니다. 위 그림은 **Holdout 점수**이며 Training Loss 곡선이 아닙니다. 선택한 평가 JSON에는 iteration별 Loss 시계열이 없습니다.

### HA 구현과 실행 상세

#### 로컬 검사

Python 3.12 별도 가상환경에서 **저장소 루트 기준**으로 실행합니다.

```sh
python -m pip install -r Pauseable.ai/ha/requirements.txt
python -m unittest discover -s Pauseable.ai/ha/tests -v
python -m unittest discover -s Pauseable.docs/evaluation/ha/checks -v
```

| 준비·운영 | 자료 |
| --- | --- |
| 실제 HA 연결 | [주소·Token·엔티티·수집 설정](../Pauseable.docs/ha/ha_realtime_collection_guide.md) |
| 지속 서비스 | [run_ha_full_service.py](ha/src/run_ha_full_service.py), [systemd](ha/deploy/systemd), [Dockerfile.pi](ha/Dockerfile.pi) |
| 연구 실행 | [Dockerfile.research](ha/Dockerfile.research), [compose.research.yaml](ha/compose.research.yaml) |
| 시연·배포 | [시연 절차](../Pauseable.docs/ha/DEMO_RUNBOOK_KO.md), [배포 안내](../Pauseable.deploy/README.md) |

연구 데이터·실제 가구 이력·모델 경로를 분리하고 HA Token·개인 데이터는 Git에 넣지 않습니다. 자동 검사와 실제 HA·Pi·가전 시험은 별도입니다.

## mmWave 구현과 설치 상세

### 입력과 처리 경로

센서의 대상·좌표·시각·품질을 받아 경로 형태와 개인 변화의 지속성을 확인합니다. 실제 연결은 **LD6004/ESP32 → Pi 3 Serial 릴레이 → SSH → Pi 5 FIFO → Python 분석**입니다. 원시 관측의 선택적 UDP 복사는 Central 관측용이며 AI 판단 Topic과 다릅니다.

| 처리 | 구현 | 역할 |
| --- | --- | --- |
| 입력·구간 | [wandering_live.py](mmwave/src/wandering_live.py), [wandering_runtime.py](mmwave/src/wandering_runtime.py) | 스트림별 이동 구간·상태 |
| 형태 | [shape_v2](mmwave/src/shape_v2) | 36개 특징의 Random Forest |
| 개인 변화 | [personal_baseline.py](mmwave/src/personal_baseline.py) | 별도 9개 특징 규격의 개인 이력 |
| 전송 | [wandering_publisher.py](mmwave/src/wandering_publisher.py) | 공통 계약의 MQTT 판단 |
| 중계 | [Pi 3 릴레이](../Pauseable.edge/mmwave-relay) | 센서 계약·Serial·연결 관리 |

### 판단 조건과 상태 관리

현재 시험 정책은 높은 증거가 **3개 연속 구간·총 90초 이상** 지속돼야 후보를 만듭니다. 저장 RF의 시작 기준은 0.66, 해제 기준은 시작보다 0.10 낮습니다. 개인 변화는 P95에서 시작해 P90 미만에서 해제합니다. 점수 경계에서 후보가 반복 전환되는 것을 줄이는 구성입니다.

형태·개인 증거는 따로 누적하고 센서·출처·대상별 상태를 나눕니다. 단절·저품질·시간 역전·모델 변경 시 증거를 초기화하거나 누적을 보류합니다. 개인 이력이 없으면 `unavailable`로 남기며, 개인에게 드물지 않은 경로라는 이유만으로 지속 형태 후보를 차단하지 않습니다. [상태·버전·시간 처리 전체](../Pauseable.docs/mmwave/RUNTIME.md)

### 연구 결과와 적용 범위

![합성 경로의 반복 이동 후 전환 사례와 Random Forest 결과](mmwave/src/shape_v2/artifacts/inspect_paths.png)

경로는 생성한 합성 데이터입니다. `label`은 생성 규칙의 정답, `pred`는 분류, `score`는 보정되지 않은 점수이며 좌표는 실제 미터가 아닙니다. 저장 평가는 `simulated_only`, 연구 모델 자동 알림은 비활성입니다. 시연 Publisher 설정과 실측 LD6004·임상 배회 검증을 구분합니다.

### 설치와 확인

1. [의존성](mmwave/requirements.txt)과 [Pi 5 실행 구성](../Pauseable.deploy/mmwave-autostart/pi5)을 준비합니다.
2. [센서 계약](../Pauseable.contracts/mmwave-target-event.schema.json), Serial·시계·품질과 FIFO 입력을 확인합니다.
3. 입력 → Runtime → MQTT → Central 승인 → 실제 출력을 대조합니다.
4. 다른 모델·정책으로 연구를 재실행할 때는 기존 개인 DB를 섞지 않습니다.

[실험 설계](mmwave/src/shape_v2/PROTOCOL.md) · [평가 원본](mmwave/src/shape_v2/artifacts/metrics.json)

## Voice 학습과 운영 상세

### 녹음에서 모델 게시까지

동의한 음성과 대본으로 Piper를 fine-tuning합니다. 녹음을 그대로 재생하는 기능이 아니라 **새 안내 문장을 보호자 음성으로 합성하는 모델**을 만듭니다. 학습은 GPU Worker, TTS는 Pi에서 실행합니다.

| 단계 | 처리·형식 | 구현 |
| --- | --- | --- |
| 앱 수집 | 160문장, 16 kHz·mono·PCM16 WAV, 동의 영수증 | [Guardian](../Pauseable.apps/README.md#음성-녹음과-동의) |
| 준비 | 160~240 WAV와 `recording_script.csv`, 번호·대본 검사 | [prepare_dataset.py](voice/pipeline/prepare_dataset.py) |
| 전처리 | 22,050 Hz·mono·PCM16, `S001.wav`부터 연속 번호 | [preprocess.py](voice/scripts/preprocess.py) |
| 학습 | Piper fine-tuning·ONNX Export | [train_voice_model.sh](voice/train_voice_model.sh), [Dockerfile](voice/docker/Dockerfile.train) |
| 작업 관리 | 임대·갱신·다운로드·학습·업로드 | [r2_worker.py](voice/pipeline/r2_worker.py) |
| 게시 | ONNX·Piper JSON·manifest·status·샘플 WAV·로그 | [publish_voice_model.py](voice/pipeline/publish_voice_model.py) |

### Pi 검증과 모델 교체

![후보 다운로드·검증·시험 합성·활성화와 기존 모델 유지](../Pauseable.docs/assets/readme/model-release.svg)

Pi의 [Model Updater](../Pauseable.edge/README.md#음성-모델-교체)는 크기·SHA-256·설정·로컬 합성 후 활성 모델을 교체합니다. 업로드, 학습 완료, 게시, Pi 적용과 실제 스피커 출력은 각각 확인합니다.

### Worker 검사와 운영

Python 3.11 별도 가상환경에서 시작합니다.

```sh
cd Pauseable.ai/voice
python -m pip install -r requirements.worker.txt
python -m unittest discover -s pipeline -p 'test_*.py' -v
```

실제 학습 전 [dry-run](../Pauseable.docs/voice/OPERATIONS_KO.md#3-설치와-사전-점검)으로 자료를 검사합니다. GPU·Driver·Docker·systemd·인증은 [운영 안내](../Pauseable.docs/voice/OPERATIONS_KO.md), 입력·보관·삭제는 [데이터 정책](../Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md), 환경 형식은 [worker.env.example](voice/worker.env.example)을 따릅니다.

## 데이터 출처와 검증 기준

| 자료 | 용도 | 구분할 점 |
| --- | --- | --- |
| 공개 전력·활동 데이터 | 일반 패턴 참고·파이프라인 시험 | 치매 반복행동 정답이 아님 |
| 문헌 기반 합성 시나리오 | 규칙·모델·전송·회귀 검사 | 시나리오 수와 환자 수는 다름 |
| 실제 가구 이력 | 출처·품질·정상 검토 후 개인화 | 확보·라벨·장기 성능 검증 필요 |
| 보호자 녹음 | 동의한 개인 음성 모델 학습 | 원본·checkpoint·모델·Token은 Git 제외 |

[공개 데이터](../Pauseable.docs/ha/public_power_data_guide.md) · [문헌 조사](../Pauseable.docs/ha/EVIDENCE_RESEARCH_20261005_KO.md) · [Baseline 검증](../Pauseable.docs/ha/ha_baseline_validation_protocol.md) · [평가 기록](../Pauseable.docs/README.md#평가-자료-읽기)

Piper의 [원본·버전](voice/provenance)과 [외부 고지](../Pauseable.third_party/NOTICE.txt)를 보존합니다. 코드 검사·장치 출력·환자 대상 성능 검증은 다른 확인 단계입니다.
