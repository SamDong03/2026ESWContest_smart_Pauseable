# Memolink AI 분석과 음성 학습

가전 사용과 이동 경로에서 주의할 상황을 찾고, 안내에 사용할 보호자 음성을 학습하는 영역입니다. **하나의 AI가 모든 일을 하는 것이 아니라 세 파이프라인이 서로 다른 입력을 처리**합니다. HA·mmWave는 판단 메시지를, Voice는 Pi에 설치할 음성 모델을 만듭니다. 판단에 따른 실행 여부는 [Central](../Pauseable.edge/README.md)이 결정합니다.

[전체 프로젝트](../README.md) · [통신 계약](../Pauseable.contracts/README.md) · [검증 자료](../Pauseable.docs/README.md)

[HA 구현](#ha-구현과-실행-상세) · [mmWave 구현](#mmwave-구현과-설치-상세) · [Voice 구현](#voice-학습과-운영-상세) · [개발환경](../Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md)

![HA, mmWave, Voice의 입력·처리·출력과 담당 환경](../Pauseable.docs/assets/readme/ai-pipelines.svg)

| 파트·소스 | 입력 → 출력 | 실행 환경 | 상세 안내 |
| --- | --- | --- | --- |
|  HA · `ha/` | 가전 상태 이력 → 특징·판정·MQTT | Pi 5 / Python·Docker | [HA 안내](#ha-구현과-실행-상세) |
|  mmWave · `mmwave/` | 이동 경로 → 형태·개인 변화·판단 근거 | Pi 5 / Python, 연구 도구 | [mmWave 안내](#mmwave-구현과-설치-상세) |
|  Voice · `voice/` | 동의한 녹음·대본 → Piper ONNX | GPU Worker / Docker | [Voice 안내](#voice-학습과-운영-상세) |

**읽는 순서:** 이벤트·특징 생성 → 초기 Baseline → IF·AE와 개인화 → 평가 결과 순으로 HA를 설명합니다. 이동 분석과 음성 학습은 뒤에서 별도로 다룹니다. `Feature`는 횟수·전환·시간대 등을 숫자로 정리한 모델 입력이고, `Calibration`은 학습과 분리한 구간으로 임계값을 정하는 과정입니다.

## HA 데이터 수집과 특징 생성

HA의 `state_changed` 이벤트를 WebSocket으로 구독해 상태 변경을 기록합니다. 분석할 때는 **1분 간격의 기준 시각별로 최근 10분·30분·1시간·2시간의 특징**을 생성합니다. 짧은 구간에서는 연속 조작을, 긴 구간에서는 일정 간격의 반복과 재시작을 확인합니다.

지속 수집 서비스의 분석 회차는 이 Feature 간격과 별개입니다. `run_ha_full_service.py`는 이전 분석 종료 후 기본 600초를 기다리며, 그동안 Collector는 계속 수집합니다. [세 가지 주기 구분](#수집특징실행-주기)

아래 HA 그래프는 동일한 합성 평가 자료를 사용했습니다. 실제 환자의 가전 사용 기록은 아닙니다. [평가 데이터](../Pauseable.docs/evaluation/ha/visual_data.json)와 [그림별 수치·출처](../Pauseable.docs/assets/readme/evaluation_figure_manifest.json)를 함께 제공합니다.

![48시간 가전 상태 변경 횟수와 같은 구간의 표준화한 54개 특징](../Pauseable.docs/assets/readme/ha-event-features.png)

| 그림 | 읽는 방법 | 처리 의미 |
| --- | --- | --- |
| 위: Raw Event | 가로 48시간, 세로 8개 가전, 색은 시간당 상태 변경 횟수 | 열림·닫힘 등 상태 전환 기록. 사용 횟수와 반드시 같지는 않음 |
| 아래: Feature | 같은 48개 시점에서 54개 수치 특징을 표시 | 가전별 횟수·지속·전환·시간대·요일을 모델 입력으로 구성 |
| Color scale | 위는 횟수, 아래는 표준화 값으로 단위가 다름 | 학습 구간의 scaler 적용. 아래 색만 −2~4로 제한하고 원래 값은 유지 |

수집은 1분 단위 조회가 아니라 이벤트 방식이므로, HA가 전달한 2초 간격의 열림·닫힘도 기록할 수 있습니다. 제조사나 HA가 전달하지 않은 변화는 수집할 수 없으며, 초기 상태 Snapshot은 실제 상태 변경과 구분합니다.

## 반복행동 판단과 개인화

### Baseline

[`build_baseline.py`](ha/src/build_baseline.py)는 정상 참조 특징에서 분위수와 IQR을 계산해 기준값을 생성합니다. [`infer_ha_baseline.py`](ha/src/infer_ha_baseline.py)는 이 기준값에 최소 조작 횟수, 가전별 반복 규칙과 야간 정보를 적용해 점수와 판단 근거를 산출합니다. 기준을 실제 사용자 이력으로 만들기 전에는 개인화된 기준으로 해석하지 않습니다.

`MinCount`는 해당 특징을 점수 계산에 포함할 최소 횟수입니다. 기준 미만이면 0점이며, 통계 상한을 넘는 정도에 따라 5·9·14점을 더합니다. 반복 패턴·야간 등 Context 점수를 함께 적용하며 기본 Baseline 경계는 Attention 35, Risk 70입니다. [점수 계산 구현](#baseline과-개인화-모델)

특징에는 냉장고 열림, 도어락 해제, 전자레인지 시작, 세탁기·건조기·식기세척기 재시작, 공기청정기·에어컨의 반복 조작 등이 포함됩니다. 분석 대상은 HA 엔티티 선택과 상태 매핑으로 설정합니다. 동일한 외형의 반복이라도 정상적인 사용 목적이 있을 수 있으므로, 관측 품질과 확인된 개인 생활패턴을 함께 반영합니다.

### IF·AE 학습과 적용

유효한 정상 이력이 쌓이면 Isolation Forest와 Autoencoder를 학습하고 검증합니다. Baseline을 유지한 상태에서 모델 점수를 관찰하는 `shadow`와, 반복 증거·개인 생활패턴을 함께 적용하는 `hybrid`를 구분했습니다.

![수집·유효 이력 확인·학습·검증·활성화와 실패 시 기존 판단 유지](../Pauseable.docs/assets/readme/learning-lifecycle.svg)

| 운용 단계 | 처리 |
| --- | --- |
| 이력 부족 | Baseline 사용. 관측 부족을 정상으로 간주하지 않음 |
| 학습 조건 충족 | 같은 가구·출처·특징 규격의 정상 후보로 IF/AE 학습 |
| `shadow` | 모델 점수만 비교하고 최종 규칙 경보는 유지 |
| `hybrid` | 반복 증거·관측 품질·Routine 정책을 확인하고 검증된 모델 점수 결합 |
| 모델 손상·호환성 불일치 | Baseline fallback. 검증되지 않은 모델은 사용하지 않음 |

- 기본 최초 학습 조건은 하루 12개 이상 서로 다른 시간대에 유효 정상 후보가 있는 날 **30일 이상**입니다. 단순히 달력상 한 달이 지났다는 뜻은 아닙니다.
- `baseline_screened`는 규칙으로 선별한 정상 후보, `reviewed_normal`은 사람이 확인한 정상 이력입니다. 둘을 같은 정답으로 취급하지 않습니다.
- Local 이력은 기본적으로 확인된 정상 이력을 사용하며, Baseline 선별 후보까지 학습에 쓰려면 별도 허용 설정이 필요합니다. 이력 수집만으로 모든 행이 학습 대상으로 승인되지는 않습니다.
- IF는 정상 후보 분포에서 벗어나는 정도를, AE는 입력 특징의 Reconstruction Error를 계산합니다. 두 점수를 단순 평균하지 않습니다.
- 재학습은 `retrain_days`와 새 유효 이력 조건으로 제어합니다. **`retrain_days=0`이면 주기적 재학습은 비활성**입니다. 코드 지원과 현재 Pi 설정은 별도로 확인합니다.

시간대·요일은 특징과 개인 생활패턴 판단에 사용합니다. 지난주 같은 요일의 사건 하나와 직접 대조하는 방식은 아닙니다. 연속된 이상 판정은 Episode로 묶어 기록합니다. 보호자의 안전 확인 응답과 학습용 정상 판정도 구분하며, 명시적으로 확인한 행동 평가만 학습·보정에 반영합니다.

## HA 평가 결과

![Baseline, +IF, +AE, Hybrid의 반복 가설 및 정상 맥락 시나리오 경보 비교](../Pauseable.docs/assets/readme/ha-component-comparison.png)

반복 가설 24개에서 경보가 발생한 시나리오는 Baseline 16개, Hybrid 24개였습니다. 정상 맥락 48개에서도 각각 22개, 30개에 경보가 발생했습니다. 모델 추가로 경보 범위가 넓어졌지만, 정상 사용을 경보로 판단한 사례가 남았습니다. [방법별 결과](../Pauseable.docs/evaluation/ha/baseline_comparison.json)

이 비교는 같은 Baseline·반복 증거·관측 마스크를 유지하고 모델 신호만 분리한 Ablation이며, **Routine 보정은 미적용**입니다. 경보 수는 `attention` 또는 `risk`가 한 번 이상 나온 시나리오 수입니다. 별도의 개인화 시험에서는 576개 시점 중 `attention` 6개가 정상으로 조정되고 `risk` 6개는 유지됐습니다. 두 시험은 평가 대상이 다르므로, 개인화 결과가 위 정상 맥락의 오탐 전체를 해결한 것으로 볼 수는 없습니다.

![시간순 Holdout 144개에서 IF Score와 AE Reconstruction Error 및 각각의 임계값](../Pauseable.docs/assets/readme/ha-model-scores.png)

위 그래프는 정상 후보 Holdout 144개의 IF Score와 AE Reconstruction Error입니다. 모델마다 단위와 임계값이 다르며, 학습 중 Loss의 변화가 아니라 평가 입력에 대한 점수 변화를 나타냅니다.

| 저장된 학습 기록 | 값 | 해석 |
| --- | --- | --- |
| 입력 | 54개 수치 특징 | timestamp 제외 |
| 시간순 분할 | Train 428 / Calibration 142 / Holdout 144 | 학습·임계값 보정·평가 역할 분리, 경계 구간 제외 |
| AE 학습 | 337 iterations, 최종 Loss 약 0.0382 | 저장된 학습 요약값. 환자 탐지 정확도가 아님 |

학습 Loss는 저장된 최종값을 표기했습니다. iteration별 학습 곡선은 해당 평가 JSON에 포함되어 있지 않습니다. 데이터 분할과 재현 절차는 [평가 자료](../Pauseable.docs/README.md#평가-자료-읽기)에 정리했습니다.

## mmWave 경로 분석

이동 구간의 형태 특징과 개인 이력, 관측 품질을 확인하고 지속성을 판단합니다. 형태 점수가 잠시 높아졌다는 이유만으로 배회를 확정하지 않습니다.

![합성 이동 경로의 경계 사례와 shape_v2 모델 점수](mmwave/src/shape_v2/artifacts/inspect_paths.png)

위 그림은 `shape_v2` Random Forest에 합성 이동 경로를 입력한 결과입니다. 반복 이동 후 다른 곳으로 이동하는 경계 사례를 표시했으며, 좌표는 실제 미터 단위가 아닙니다. `label`은 생성 규칙의 정답, `pred`는 모델 분류, `score`는 보정되지 않은 모델 점수입니다. 실제 센서나 환자의 배회 기록으로 얻은 결과는 아닙니다.

저장된 평가의 출처는 `simulated_only`입니다. 실측 LD6004와 임상 배회 성능은 검증되지 않았으며, 해당 연구 모델의 자동 알림은 비활성입니다.

[Runtime·결과 해석](../Pauseable.docs/mmwave/RUNTIME.md) · [모델 프로토콜](mmwave/src/shape_v2/PROTOCOL.md) · [평가 원본](mmwave/src/shape_v2/artifacts/metrics.json)

## 개인화 Voice

Guardian 녹음과 대본을 API/R2에 등록하면 GPU Worker가 WAV·metadata 검사, Piper fine-tuning, ONNX Export와 산출물 검증을 수행합니다. Pi는 게시된 모델을 내려받아 검증한 뒤 교체합니다. HA의 IF/AE 학습과는 별도 경로입니다.

| 구분 | 계약 |
| --- | --- |
| 입력 | 160~240개 WAV와 대응하는 `recording_script.csv` |
| 앱 녹음 | 16 kHz, mono, PCM 16-bit. 현재 앱 고정 대본은 160문장 |
| 학습 전처리 | mono·22,050 Hz·PCM 16-bit로 변환, `S001.wav`부터 연속 번호와 대본 대조 |
| 산출물 | ONNX·Piper JSON·manifest·status·샘플 WAV·학습 로그 |
| 적용 | 크기·SHA-256·로컬 합성 검증 후 교체, 실패 시 기존 모델 유지 |

[GPU Worker 운영](../Pauseable.docs/voice/OPERATIONS_KO.md) · [데이터·동의·보관 정책](../Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md) · [Pi 모델 교체 흐름](../Pauseable.edge/README.md#음성-모델-교체)

앱의 녹음 형식과 학습용 전처리 형식은 서로 다른 단계입니다. 변환은 [`preprocess.py`](voice/scripts/preprocess.py)가 수행하며 원본의 sample rate와 변환 결과를 기록합니다.

## 실행 준비와 주요 코드

실제 HA 연결에는 HA 주소·Token, MQTT 설정, 분석할 엔티티와 Baseline JSON이 필요합니다. 개인별 이력과 학습 모델은 별도 저장 경로에 준비합니다. 저장소의 연구용 데이터와 실제 가구의 이력·모델은 분리해 운용합니다.

환경 버전은 [개발환경](../Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md), 수집·Baseline·학습·Publisher의 파일 연결은 [기능별 코드 위치](../Pauseable.docs/SOURCE_MAP_KO.md)에서 확인합니다.

<details>
<summary><strong>HA 코드 진입점과 로컬 검사</strong></summary>

| 단계 | 구현 | 핵심 내용 |
| --- | --- | --- |
| 수집 | [`collect_ha_events_ws.py`](ha/src/collect_ha_events_ws.py) | WebSocket 상태 변경·초기 상태·관측 정보 |
| 특징 | [`make_ha_features.py`](ha/src/make_ha_features.py) | 횟수·상태 전환·재시작·시간대·요일 |
| 학습 | [`train_ha_anomaly_models.py`](ha/src/train_ha_anomaly_models.py) | 정상 후보 IF/AE, 시간순 분할·보정·검증 |
| Lifecycle | [`ha_model_lifecycle.py`](ha/src/ha_model_lifecycle.py) | 이력·학습 조건·모델 적용·fallback·갱신 |
| 서비스 | [`run_ha_full_service.py`](ha/src/run_ha_full_service.py) | 수집·주기적 분석 실행 관리 |

Python 3.12 별도 가상환경을 활성화한 뒤 **저장소 루트에서** 실행합니다.

```sh
python -m pip install -r Pauseable.ai/ha/requirements.txt
python -m unittest discover -s Pauseable.ai/ha/tests -v
python -m unittest discover -s Pauseable.docs/evaluation/ha/checks -v
```

Docker 연구 환경: [`Dockerfile.research`](ha/Dockerfile.research), [`compose.research.yaml`](ha/compose.research.yaml). 실제 가구 이력·모델 경로와 연구 출력을 분리합니다.

[실시간 수집](../Pauseable.docs/ha/ha_realtime_collection_guide.md) · [현재 모델 운용](#baseline과-개인화-모델) · [시연 절차](../Pauseable.docs/ha/DEMO_RUNBOOK_KO.md)

</details>

<details>
<summary><strong>mmWave 코드 진입점</strong></summary>

| 구분 | 위치 | 역할 |
| --- | --- | --- |
| 실시간 연결 | [`wandering_runtime.py`](mmwave/src/wandering_runtime.py), [`wandering_live.py`](mmwave/src/wandering_live.py) | 입력·구간·상태 |
| 개인 이력 | [`personal_baseline.py`](mmwave/src/personal_baseline.py) | 과거 기록과 비교 |
| 메시지 | [`wandering_publisher.py`](mmwave/src/wandering_publisher.py) | 계약에 맞는 MQTT 출력 |
| 형태 연구 | [`shape_v2`](mmwave/src/shape_v2) | Random Forest 경로 분석·재현 가능한 평가 |

</details>

## 데이터와 검증 범위

공개 전력·활동 데이터, 문헌을 참고한 합성 시나리오, 실제 사용자 이력은 출처와 용도를 구분합니다. 공개 전력 데이터를 치매 환자의 반복행동 정답으로 사용하지 않습니다. [공개 데이터 검토](../Pauseable.docs/ha/public_power_data_guide.md), [문헌 기반 시나리오](../Pauseable.docs/ha/EVIDENCE_RESEARCH_20261005_KO.md), [Baseline 검증 절차](../Pauseable.docs/ha/ha_baseline_validation_protocol.md)를 제공합니다.

현재 제시한 HA·경로 형태 평가는 소프트웨어 동작과 시나리오 분류를 확인한 결과이며, 실제 환자 탐지 성능은 추가 검증이 필요합니다. 원본 녹음·개인 이력·checkpoint·개인화 ONNX·인증값은 저장소에서 제외합니다.

## HA 구현과 실행 상세

<details>
<summary><strong>입출력·수집 주기·Baseline·학습 조건·로컬 검사</strong></summary>

소스 위치: `Pauseable.ai/ha`

Home Assistant가 전달하는 가전 상태 변경을 기록하고, 시간 구간별 사용 특징으로 반복행동을 판단합니다. Baseline, IF·AE와 개인 Routine 정책을 적용한 결과를 MQTT로 Central에 전달합니다.

**이 모듈의 입력은 가전 상태, 출력은 판단 메시지**입니다. 냉장고 문이 열렸다는 기록을 받아 사용 패턴을 분석할 뿐, 이 코드가 직접 보호자 알림이나 가전 명령을 실행하지는 않습니다.

| 처리 순서 | 냉장고 개폐를 예로 들면 |
| --- | --- |
|  기록 | HA가 보낸 열림·닫힘 이벤트와 시각 저장 |
|  특징 생성 | 최근 시간 구간의 열림 횟수·전환 등 숫자 특징 계산 |
|  판단 | Baseline과 사용 가능한 IF·AE, Routine 조건 적용 |
|  전달 | 상태·점수·근거를 공통 JSON으로 만들어 Central에 전달 |

### 입력과 출력

| 구분 | 내용 |
| --- | --- |
| 입력 | HA 주소·Token, 선택한 Entity, 상태 변경과 관측 정보 |
| 참조 기준 | 정상 참조 특징으로 만든 Baseline JSON |
| 분석 파일 | 원시·정규화 CSV, Feature, 판정·Episode 요약 |
| 운영 상태 | 판정 SQLite, 관측 품질·학습 상태, 개인 모델 버전 |
| 전달 | `communication-v1`의 반복행동 판단 JSON |

엔티티 선택과 상태 매핑을 실제 가전에 맞춥니다. 도어 `on/off`를 `open/close`로 바꾸는 것은 해당 엔티티 매핑의 예시이며, 모든 HA 상태에 같은 변환을 적용하지 않습니다.

### 수집·특징·실행 주기

| 구분 | 동작 |
| --- | --- |
| 수집 | WebSocket의 `state_changed`를 받아 즉시 기록 |
| Feature 기준 시각 | 1분 간격의 시점별로 최근 10분·30분·1시간·2시간 이력 요약 |
| 서비스 분석 회차 | `run_ha_full_service.py`는 이전 분석 종료 후 `cycle_seconds`만큼 대기. 기본값 600초 |
| 초기 상태 | Snapshot으로 구분하며 실제 반복 횟수에 포함하지 않음 |

Feature를 1분 간격으로 계산하는 것과 서비스를 정확히 매분 실행하는 것은 다릅니다. Collector는 분석 사이에도 수집을 계속합니다. 2초 개폐도 HA가 두 상태 변경을 전달하면 각각 기록합니다.

`Sliding Window`는 기준 시각이 이동하면서 과거 일정 길이의 기록을 다시 요약하는 방식입니다. 예를 들어 12시에는 11시 50분~12시의 10분 이력을, 다음 기준 시각에는 그만큼 이동한 이력을 봅니다. 서로 겹치는 요약값이므로 각 행을 독립된 사건 수로 세지는 않습니다.

### Baseline과 개인화 모델

| 구성 | 역할 | 구현 |
| --- | --- | --- |
| Baseline 생성 | 정상 참조 특징의 분위수·IQR 상한 계산 | [build_baseline.py](ha/src/build_baseline.py) |
| Baseline 판정 | 특징별 최소 횟수·상한, 반복 패턴과 야간 점수 적용 | [infer_ha_baseline.py](ha/src/infer_ha_baseline.py) |
| IF·AE 학습 | 정상 후보를 시간순으로 나누어 학습·보정·검증 | [train_ha_anomaly_models.py](ha/src/train_ha_anomaly_models.py) |
| 모델 운용 | 학습 조건·모델 호환·활성화·갱신·fallback | [ha_model_lifecycle.py](ha/src/ha_model_lifecycle.py) |
| Routine | 확인된 정상 생활패턴에 맞는 경보 보정 | [ha_personal_routine.py](ha/src/ha_personal_routine.py) |

`MinCount`는 특징별 점수 계산에 필요한 최소 반복 횟수입니다. 기준 미만이면 해당 항목을 0점으로 처리합니다. 통계 상한을 넘는 정도에 따라 5·9·14점을 부여하고 패턴·Context 점수를 반영합니다. 기본 점수 경계는 Attention 35, Risk 70입니다.

AE는 scikit-learn MLP의 입력 복원 학습입니다. 정상 학습 특징으로 fit한 StandardScaler를 적용하고 Reconstruction Error를 구합니다. IF·AE의 모델 점수에는 반복 증거와 관측 품질 조건을 함께 적용합니다.

Baseline 생성기는 시간대별 통계도 저장하지만, 현재 기본 점수 계산은 전체 참조 통계와 명시적인 야간 점수를 사용합니다. 시간·요일 Feature와 Routine 비교를 '지난주 같은 요일의 사건을 하나씩 직접 대조하는 기능'으로 해석하지 않습니다.

최초 학습은 같은 가구·출처·특징 규격에서 하루 12개 이상 서로 다른 시간대의 유효 정상 후보가 있는 날 30일 이상을 기본 조건으로 합니다. `reviewed_normal`과 Baseline으로 선별한 후보는 구분합니다. `shadow`는 점수 관찰, `hybrid`는 모델 신호 결합이며, 주기 재학습은 `retrain_days=0`에서 꺼져 있습니다.

<details>
<summary><strong>정상 데이터로 학습하는 이유와 공개 데이터의 역할</strong></summary>

IF·AE는 '치매 행동의 정답'을 직접 분류하도록 학습하는 구성이 아닙니다. 해당 사용자의 정상 후보 분포를 학습하고, 현재 입력이 그 분포와 얼마나 다른지 점수화합니다. 따라서 데이터가 충분히 있어도 정상 후보에 반복 이상이나 관측 오류가 섞이면 기준이 흐려질 수 있습니다.

공개 전력 데이터는 가전 사용의 일반적 패턴과 파이프라인 시험에 참고할 수 있지만, 전력 사용만으로 냉장고 문 개폐나 환자의 기억 상태를 알 수는 없습니다. 문헌 기반 합성 시나리오도 로직 시험에 사용하며 실제 환자의 정답 라벨로 취급하지 않습니다. 정상 후보 확보, 실제 사용 이력, 시나리오 검증의 역할을 분리합니다.

</details>

### 로컬 검사

[Python 3.12 가상환경](../Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md#로컬-개발-준비)을 활성화한 뒤 저장소 루트에서 실행합니다.

```sh
python -m pip install -r Pauseable.ai/ha/requirements.txt
python -m unittest discover -s Pauseable.ai/ha/tests -v
python -m unittest discover -s Pauseable.docs/evaluation/ha/checks -v
```

이 명령은 코드·보고서 회귀 검사입니다. HA 연결이나 실기 출력 확인은 [실시간 수집](../Pauseable.docs/ha/ha_realtime_collection_guide.md)과 [시연 절차](../Pauseable.docs/ha/DEMO_RUNBOOK_KO.md)를 따릅니다.

### 배포와 평가 자료

- 장치 실행: [Dockerfile.pi](ha/Dockerfile.pi), [systemd 설정](ha/deploy/systemd), [전체 배포 안내](../Pauseable.deploy/README.md)
- 연구 환경: [Dockerfile.research](ha/Dockerfile.research), [compose.research.yaml](ha/compose.research.yaml)
- 기존 평가: [AI 결과 설명](#ha-평가-결과), [평가 원본](../Pauseable.docs/evaluation/ha)
- 데이터 출처: [공개 데이터 검토](../Pauseable.docs/ha/public_power_data_guide.md), [문헌 기반 시나리오](../Pauseable.docs/ha/EVIDENCE_RESEARCH_20261005_KO.md)

공개 연구·합성 자료와 개인 가구의 이력·모델을 별도 경로로 관리합니다. 실제 HA Token, 개인 이력과 학습 모델은 저장소에 넣지 않습니다.

</details>

## mmWave 구현과 설치 상세

<details>
<summary><strong>주요 코드·판단 조건·센서 설치·연구 경로 그림</strong></summary>

소스 위치: `Pauseable.ai/mmwave`

센서의 대상·위치·추적 정보를 이동 구간으로 묶어 경로 형태, 개인 이력과 관측 품질을 확인합니다. 반복 형태가 지속되는 상황과 개인 분포의 변화를 분리해 판단 근거를 생성합니다.

**가전 상태가 아니라 사람이 이동한 경로를 다루는 모듈**입니다. 짧은 순간의 방향 전환과 계속 이어지는 반복 이동을 구분하기 위해 형태·지속 시간·개인 이력·추적 품질을 함께 확인합니다.

| 입력 | 분석 | 출력 |
| --- | --- | --- |
|  대상·좌표·시각·추적 정보 | 경로 형태, 개인 과거 분포, 연속성과 관측 품질 |  Central에 전달할 상태·근거·위험 정보 |

### 구성

| 경로·파일 | 담당 처리 |
| --- | --- |
| [wandering_live.py](mmwave/src/wandering_live.py) | 실시간 실행 진입점 |
| [wandering_runtime.py](mmwave/src/wandering_runtime.py) | 스트림별 구간·상태·결과 처리 |
| [personal_baseline.py](mmwave/src/personal_baseline.py) | 개인 과거 분포와 비교 |
| [wandering_publisher.py](mmwave/src/wandering_publisher.py) | 계약에 맞는 MQTT 판단 메시지 |
| [shape_v2](mmwave/src/shape_v2) | 경로 형태 Random Forest와 연구 평가 |
| [센서 릴레이](../Pauseable.edge/mmwave-relay) | Pi 3 입력 검증·Pi 5 중계 |

### 판단과 연구 모델

`shape_v2`의 36개 RF 특징과 기존 개인 이력의 9개 특징은 서로 다른 규격입니다. 모델·정책·특징 버전에 맞는 상태 DB를 사용하고, 센서·출처·대상별 스트림을 분리합니다.

형태 점수, 개인 희귀도, 연속 구간·누적 시간과 관측 품질을 함께 확인합니다. 연결 단절·저품질·시간 역전·모델 변경의 처리와 현재 후보 상태 이름은 [Runtime 정책](../Pauseable.docs/mmwave/RUNTIME.md)에 정리했습니다.

저장된 형태 평가는 합성 경로를 사용한 `simulated_only` 연구 결과입니다. 연구 모델의 자동 알림은 비활성이며, 실제 LD6004와 확인 라벨을 이용한 검증은 별도입니다. 시연·운영 Publisher의 설정과 연구 결과를 혼동하지 않습니다.

### 설치와 확인

1. [mmWave 의존성](mmwave/requirements.txt)과 [Pi 5 실행 구성](../Pauseable.deploy/mmwave-autostart/pi5)을 확인합니다.
2. [센서 계약](../Pauseable.contracts/mmwave-target-event.schema.json)에 맞는 입력과 serial·시계·추적 품질을 확인합니다.
3. 입력, Runtime 결과와 MQTT 메시지를 단계별로 대조합니다.
4. [Central](../Pauseable.edge/README.md#central-구현과-설치-상세)의 검증·실행 정책 이후 출력을 따로 확인합니다.

[실험 설계](mmwave/src/shape_v2/PROTOCOL.md) · [평가 원본](mmwave/src/shape_v2/artifacts/metrics.json) · [경로 그림](mmwave/src/shape_v2/artifacts/inspect_paths.png)

<details>
<summary><strong>합성 경로 연구 그림과 읽는 방법</strong></summary>

![합성 경로의 반복 이동 후 전환 사례와 Random Forest 분류 결과](mmwave/src/shape_v2/artifacts/inspect_paths.png)

`label`은 경로 생성 규칙의 정답, `pred`는 모델 분류, `score`는 보정되지 않은 모델 점수입니다. 곡선은 생성한 이동 경로이며 좌표는 실제 미터 단위가 아닙니다. HA 가전 데이터나 실제 환자의 이동 기록으로 만든 그림은 아닙니다.

</details>

</details>

## Voice 학습과 운영 상세

<details>
<summary><strong>녹음 형식·산출물·학습 코드·Worker 검사</strong></summary>

소스 위치: `Pauseable.ai/voice`

보호자가 동의하고 녹음한 WAV와 대본으로 Piper 음성 모델을 학습합니다. GPU Worker가 작업을 처리하고, Pi는 검증된 ONNX를 내려받아 로컬 TTS에 사용합니다. HA의 IF·AE 학습과는 별도 파이프라인입니다.

**녹음 파일을 그대로 재생하는 기능이 아니라, 안내 문장을 읽어 주는 음성 모델을 만드는 과정**입니다. 학습은 별도 GPU 환경에서 수행하고, 만들어진 모델로 문장을 음성으로 바꾸는 TTS는 Pi에서 실행합니다. Worker는 API가 배정한 학습 작업을 처리하는 프로그램입니다.

### 입력과 산출물

| 단계 | 자료·형식 |
| --- | --- |
| 앱 수집 | 현재 160문장, WAV 16 kHz·mono·PCM16 |
| Worker 입력 | 160~240개 WAV, 대응 `recording_script.csv`, 동의·작업 정보 |
| 학습 전처리 | mono·22,050 Hz·PCM16로 변환 |
| 학습·Export | Piper fine-tuning, ONNX·Piper JSON |
| 게시 | manifest·status·샘플 WAV·로그와 검증한 모델 |
| Pi 적용 | 크기·SHA-256·설정·로컬 합성 검사 후 교체 |

![게시된 음성 모델을 Pi가 다운로드·검사·합성 시험한 뒤 적용하는 과정](../Pauseable.docs/assets/readme/model-release.svg)

ONNX는 모델 파일, Piper JSON은 그 모델로 음성을 합성하는 데 필요한 설정입니다. WAV 업로드, 학습 완료, 모델 게시, Pi 적용과 실제 스피커 출력은 서로 다른 단계입니다.

### 주요 코드

| 파일 | 역할 |
| --- | --- |
| [pipeline/r2_worker.py](voice/pipeline/r2_worker.py) | 작업 임대·다운로드·검사·학습·업로드 |
| [pipeline/prepare_dataset.py](voice/pipeline/prepare_dataset.py) | 대본·WAV 검사와 데이터 준비 |
| [scripts/preprocess.py](voice/scripts/preprocess.py) | 학습용 음성 형식 변환 |
| [train_voice_model.sh](voice/train_voice_model.sh) | Docker 학습 실행 |
| [pipeline/publish_voice_model.py](voice/pipeline/publish_voice_model.py) | 기존 검증 ONNX 게시 |
| [docker/Dockerfile.train](voice/docker/Dockerfile.train) | Python 3.11·Piper·PyTorch 학습 환경 |
| [worker.env.example](voice/worker.env.example) | API·Worker 인증·작업 경로 예시 |

### 검사와 운영

별도 Python 3.11 가상환경에서 저장소 루트 기준으로 실행합니다.

```sh
cd Pauseable.ai/voice
python -m pip install -r requirements.worker.txt
python -m unittest discover -s pipeline -p 'test_*.py' -v
```

실제 학습 전에는 [Worker의 dry-run](../Pauseable.docs/voice/OPERATIONS_KO.md#3-설치와-사전-점검)으로 자료를 검사합니다. GPU·Driver·Docker 설정, 실제 Worker 실행과 systemd 등록은 같은 운영 문서를 따릅니다. 단위시험은 실제 GPU 학습·게시·Pi 음성 출력을 수행한 결과와 구분합니다.

원본 녹음·checkpoint·개인화 모델·Token을 Git에 넣지 않습니다. [Piper 출처와 버전](voice/provenance), [외부 저작권 고지](../Pauseable.third_party/NOTICE.txt)를 함께 확인합니다.

</details>
