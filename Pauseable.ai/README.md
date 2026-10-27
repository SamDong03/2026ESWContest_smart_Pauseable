# PAUSEABLE / AI

가전 반복행동, 이동 경로, 개인화 음성 모델을 다루는 영역입니다. **상황 판단을 생성하는 코드**와 **음성 모델을 학습하는 코드**가 함께 있으며, 실제 출력 허용은 [Central](../Pauseable.edge/README.md)이 담당합니다.

[전체 프로젝트](../README.md) · [통신 계약](../Pauseable.contracts/README.md) · [검증 자료](../Pauseable.docs/README.md)

## 구성

| 경로 | 목적 | 입력 → 출력 | 실행 환경 |
| --- | --- | --- | --- |
| [`ha`](ha) | 가전 반복행동 판단 | HA 상태 이력 → 특징·판정·MQTT | Pi 5 / Python·Docker |
| [`mmwave`](mmwave) | 배회 의심 상황 분석 | 이동 경로 → 형태·개인 변화·판단 근거 | Pi 5 / Python, 연구·검증 도구 |
| [`voice`](voice) | 보호자 음성 모델 학습 | 동의한 녹음·대본 → Piper ONNX | GPU Worker / Docker |

## HA 반복행동

```text
HA state_changed / Recorder
  → 엔티티·상태 정규화
  → 1분 간격 특징: 최근 10분·30분·1시간·2시간
  → Baseline + IF + AE + 반복 증거·Routine 정책
  → 판정·Episode 기록
  → repetitive-ai MQTT 메시지
```

### 단계별 역할

| 단계 | 구현 | 핵심 내용 |
| --- | --- | --- |
| 수집 | [`collect_ha_events_ws.py`](ha/src/collect_ha_events_ws.py) | WebSocket 상태 변경 구독, 초기 상태와 관측 정보 수집 |
| 특징 | [`make_ha_features.py`](ha/src/make_ha_features.py) | 횟수·상태 전환·재시작·시간대·요일 등 수치 특징 |
| 학습 | [`train_ha_anomaly_models.py`](ha/src/train_ha_anomaly_models.py) | 정상 후보로 IF·AE 학습, 시간순 분할·보정·검증 |
| Lifecycle | [`ha_model_lifecycle.py`](ha/src/ha_model_lifecycle.py) | 이력 저장·학습 조건·모델 적용·fallback·갱신 |
| 서비스 | [`run_ha_full_service.py`](ha/src/run_ha_full_service.py) | 수집과 주기적 분석의 실행 관리 |

**1분은 특징 생성 간격입니다.** 상태 변화는 이벤트로 수집하므로 HA를 1분에 한 번만 조회하는 구조가 아닙니다. 단, 제조사 클라우드나 HA가 전달하지 않은 짧은 상태 변화까지 복구하는 기능은 아닙니다.

### Baseline과 개인화 모델

| 상태 | 처리 |
| --- | --- |
| 학습 이력 부족 | Baseline으로 판단, 관측 부족은 별도 상태로 표시 |
| 유효 정상 후보 확보 | 같은 가구·출처·특징 규격을 확인한 뒤 IF/AE 학습 |
| `shadow` | 모델 점수만 비교하고 최종 규칙 경보는 바꾸지 않음 |
| `hybrid` | 반복 증거가 있는 구간에서 검증된 모델 점수를 결합 |
| 모델 손상·호환성 불일치 | 학습 모델을 사용하지 않고 Baseline fallback |
| 주기적 재학습 | `retrain_days`와 새 유효 이력 조건을 충족할 때만 시도 |

- 기본 최초 학습 조건은 하루 12개 이상 서로 다른 시간대에서 유효한 정상 후보가 있는 날 **30일 이상**입니다. 단순히 달력상 한 달이 지났다고 학습하지 않습니다.
- Baseline이 선별한 `baseline_screened`와 사람이 확인한 `reviewed_normal`은 다릅니다. 자동 선별 이력을 사람의 정상 정답으로 표시하지 않습니다.
- AE는 입력 특징을 복원하도록 학습하며, 복원오차를 보정 기준과 비교합니다. IF도 정상 후보 분포를 학습하는 모델입니다.
- Baseline, IF, AE의 점수를 무조건 평균하지 않습니다. 반복 증거·관측 품질·Routine 정책이 함께 적용됩니다.
- `retrain_days=0`은 주기적 재학습 비활성입니다. 최초 자동 학습 구현과 현재 장치의 재학습 활성화 여부는 구분합니다.

### 로컬 검사

Python 3.12 가상환경을 활성화하고 **저장소 루트에서** 실행합니다.

```sh
python -m pip install -r Pauseable.ai/ha/requirements.txt
python -m unittest discover -s Pauseable.ai/ha/tests -v
python -m unittest discover -s Pauseable.docs/evaluation/ha/checks -v
```

Docker 연구 환경: [`Dockerfile.research`](ha/Dockerfile.research), [`compose.research.yaml`](ha/compose.research.yaml). 실제 가구의 이력·모델 경로와 연구 출력 경로는 분리합니다.

자세히 보기: [실시간 수집](../Pauseable.docs/ha/ha_realtime_collection_guide.md), [개인화·이상 탐지](../Pauseable.docs/ha/ha_anomaly_shadow_guide.md), [시연 절차](../Pauseable.docs/ha/DEMO_RUNBOOK_KO.md).

## mmWave 배회 의심 분석

```text
ESP32 / LD6004 → Pi 3 Relay → 이동 구간 생성
  → 형태 특징·개인 이력 비교·관측 품질
  → 지속성 확인 → 판단 상태·근거 → wandering-ai MQTT
```

| 구분 | 위치 | 역할 |
| --- | --- | --- |
| 실시간 연결 | [`wandering_runtime.py`](mmwave/src/wandering_runtime.py), [`wandering_live.py`](mmwave/src/wandering_live.py) | 입력과 구간·상태 처리 |
| 개인 이력 | [`personal_baseline.py`](mmwave/src/personal_baseline.py) | 개인 과거 기록과 비교 |
| 메시지 출력 | [`wandering_publisher.py`](mmwave/src/wandering_publisher.py) | 계약에 맞는 MQTT 메시지 |
| 형태 연구 모델 | [`shape_v2`](mmwave/src/shape_v2) | Random Forest 경로 형태 분석·재현 가능한 평가 |

형태 점수의 일시적 상승만으로 배회를 확정하지 않습니다. 구간 지속성, 관측 누락과 품질, 개인 비교 가능 여부를 구분합니다. `shape_v2` 기록은 `simulated_only`이고 실측 LD6004와 임상 배회 성능은 검증되지 않았으며 해당 연구 모델의 자동 알림은 비활성입니다.

시작 문서: [Runtime·결과 해석](../Pauseable.docs/mmwave/RUNTIME.md), [모델 프로토콜](mmwave/src/shape_v2/PROTOCOL.md), [평가 원본](mmwave/src/shape_v2/artifacts/metrics.json).

## Voice 학습

```text
Guardian 녹음·대본 → API / R2 → GPU Worker
  → WAV·metadata 검사 → Piper fine-tuning → ONNX Export
  → 산출물·샘플 음성 검증 → API / R2 게시
  → Pi 5 Model Updater → 검증 후 활성 모델 교체
```

| 항목 | 계약 |
| --- | --- |
| 입력 | 160~240개 WAV와 대응하는 `recording_script.csv` |
| WAV 형식 | mono, 22,050 Hz, PCM 16-bit |
| 파일명 | `S001.wav`부터 연속 번호 |
| 결과 | ONNX·Piper JSON·manifest·status·샘플 WAV·학습 로그 |
| 모델 적용 | Pi 5의 크기·SHA-256·로컬 합성 검증 후 교체, 실패 시 기존 모델 유지 |

Voice는 HA의 IF/AE 학습과 별도의 파이프라인입니다. 녹음 원본·checkpoint·개인화 ONNX는 Git에 넣지 않습니다.

[GPU Worker 운영](../Pauseable.docs/voice/OPERATIONS_KO.md) · [데이터·동의·보관 정책](../Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md) · [Pi 모델 교체 코드](../Pauseable.edge/voice-model)

## 검증을 읽는 기준

- 합성 시나리오 통과는 자동화 연결과 소프트웨어 동작의 근거입니다. 실제 환자 탐지 성능의 근거와 같지 않습니다.
- 공개 전력·활동 데이터는 출처와 목적을 구분합니다. 치매 환자의 가전 반복행동 정답으로 간주하지 않습니다.
- HA 저장 기록과 현재 Pi 설치 버전, mmWave 연구 모델과 실기 입력은 각각 확인합니다.

평가 파일과 한계는 [Docs README](../Pauseable.docs/README.md#평가-자료-읽기)에 모았습니다.
