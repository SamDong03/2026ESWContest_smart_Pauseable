# PAUSEABLE / AI

**가전 사용의 반복 패턴, 이동 경로의 변화, 보호자의 목소리를 각각의 파이프라인으로 다룹니다.** HA와 mmWave는 상황 판단을 만들고, Voice는 안내용 음성 모델을 학습합니다. 판단 이후의 실행 허용은 [Central](../Pauseable.edge/README.md)이 담당합니다.

[전체 프로젝트](../README.md) · [통신 계약](../Pauseable.contracts/README.md) · [검증 자료](../Pauseable.docs/README.md)

![HA, mmWave, Voice의 입력·처리·출력과 담당 환경](../Pauseable.docs/assets/readme/ai-pipelines.svg)

| 파트 | 입력 → 출력 | 실행 환경 | 코드 |
| --- | --- | --- | --- |
| HA | 가전 상태 이력 → 특징·판정·MQTT | Pi 5 / Python·Docker | [`ha`](ha) |
| mmWave | 이동 경로 → 형태·개인 변화·판단 근거 | Pi 5 / Python, 연구 도구 | [`mmwave`](mmwave) |
| Voice | 동의한 녹음·대본 → Piper ONNX | GPU Worker / Docker | [`voice`](voice) |

## HA 이벤트에서 특징으로

HA의 `state_changed`를 WebSocket으로 구독하고, 상태가 바뀔 때 이벤트를 기록합니다. 이 이력을 바탕으로 **1분마다 최근 10분·30분·1시간·2시간의 특징**을 생성합니다. 1분은 특징 생성 간격이지 HA 조회 간격이 아닙니다.

아래 HA 그래프는 모두 저장소의 **합성 검증 자료**를 다시 그린 것입니다. 실제 환자 기록이나 임상 정확도를 나타내지 않습니다. [데이터 원본](../Pauseable.docs/evaluation/ha/visual_data.json) · [그림별 출처와 수치](../Pauseable.docs/assets/readme/evaluation_figure_manifest.json)

![48시간 가전 상태 변경 횟수와 같은 구간의 표준화한 54개 특징](../Pauseable.docs/assets/readme/ha-event-features.png)

| 그림 | 읽는 방법 | 처리 의미 |
| --- | --- | --- |
| 위: Raw Event | 가로 48시간, 세로 8개 가전, 색은 시간당 상태 변경 횟수 | 열림·닫힘 등 상태 전환 기록. 사용 횟수와 반드시 같지는 않음 |
| 아래: Feature | 같은 48개 시점에서 54개 수치 특징을 표시 | 가전별 횟수·지속·전환·시간대·요일을 모델 입력으로 구성 |
| Color scale | 위는 횟수, 아래는 표준화 값으로 단위가 다름 | 학습 구간의 scaler 적용. 아래 색만 −2~4로 제한하고 원래 값은 유지 |

HA가 전달한 2초 간격의 열림·닫힘은 이벤트로 남길 수 있습니다. 다만 제조사나 HA가 아예 전달하지 않은 변화는 복구하지 못합니다. 초기 상태 Snapshot과 실제 상태 변경도 구분합니다.

## Baseline에서 개인화 모델로

처음에는 Baseline을 사용하고, 유효한 정상 후보가 충분히 쌓이면 IF와 AE를 학습·검증합니다. **모델이 준비되었다는 이유만으로 기존 판단을 즉시 대체하지 않습니다.**

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

## 모델을 더했을 때 달라지는 점

![Baseline, +IF, +AE, Hybrid의 반복 가설 및 정상 맥락 시나리오 경보 비교](../Pauseable.docs/assets/readme/ha-component-comparison.png)

왼쪽은 반복 가설 24개 중 경보가 나온 수입니다. Baseline의 16개에서 Hybrid의 24개로 늘었습니다. 오른쪽은 정상 맥락 48개 중 경보가 나온 수로, 22개에서 30개로 함께 늘었습니다. **경보 증가만으로 성능이 좋아졌다고 결론 내릴 수 없습니다.** 정상 맥락의 불필요한 경보를 줄이는 정책과 실제 사용자 평가가 함께 필요합니다. [비교 원본](../Pauseable.docs/evaluation/ha/baseline_comparison.json)

같은 Baseline·반복 증거·관측 마스크를 유지하고 모델 신호만 분리한 Ablation입니다. 이 저장된 비교에는 **Routine correction을 적용하지 않았습니다.** 경보는 `attention` 또는 `risk`가 한 번 이상 나온 시나리오를 센 값이며, 임상 정답률이 아닙니다.

![시간순 Holdout 144개에서 IF Score와 AE Reconstruction Error 및 각각의 임계값](../Pauseable.docs/assets/readme/ha-model-scores.png)

두 그래프는 정상 후보 Holdout 144개에 대한 모델별 점수입니다. IF Score와 AE Reconstruction Error는 단위와 임계값이 다르므로 높이 자체를 서로 비교하지 않습니다. **Epoch별 Training Loss 그래프가 아닙니다.**

| 저장된 학습 기록 | 값 | 해석 |
| --- | --- | --- |
| 입력 | 54개 수치 특징 | timestamp 제외 |
| 시간순 분할 | Train 428 / Calibration 142 / Holdout 144 | 학습·임계값 보정·평가 역할 분리, 경계 구간 제외 |
| AE 학습 | 337 iterations, 최종 Loss 약 0.0382 | 저장된 학습 요약값. 환자 탐지 정확도가 아님 |

선택한 평가 JSON에는 iteration별 Loss 시계열이 없으므로 곡선을 임의로 만들지 않았습니다. 모든 수치의 적용 범위와 재현 절차는 [평가 자료 안내](../Pauseable.docs/README.md#평가-자료-읽기)에 모았습니다.

## mmWave 경로 분석

이동 구간의 형태 특징과 개인 이력, 관측 품질을 확인하고 지속성을 판단합니다. 형태 점수가 잠시 높아졌다는 이유만으로 배회를 확정하지 않습니다.

![합성 이동 경로의 경계 사례와 shape_v2 모델 점수](mmwave/src/shape_v2/artifacts/inspect_paths.png)

위 그림은 `shape_v2`의 **합성 경로 경계 사례**입니다. 좌표는 arbitrary units이며 실제 LD6004 측정 위치가 아닙니다. 저장된 평가는 `simulated_only`이고 실측 센서·임상 배회 성능은 검증되지 않았으며 해당 연구 모델의 자동 알림은 비활성입니다.

[Runtime·결과 해석](../Pauseable.docs/mmwave/RUNTIME.md) · [모델 프로토콜](mmwave/src/shape_v2/PROTOCOL.md) · [평가 원본](mmwave/src/shape_v2/artifacts/metrics.json)

## 개인화 Voice

Guardian 녹음과 대본을 API/R2에 등록하면 GPU Worker가 WAV·metadata 검사, Piper fine-tuning, ONNX Export와 산출물 검증을 수행합니다. Pi는 게시된 모델을 내려받아 검증한 뒤 교체합니다. HA의 IF/AE 학습과는 별도 경로입니다.

| 구분 | 계약 |
| --- | --- |
| 입력 | 160~240개 WAV와 대응하는 `recording_script.csv` |
| WAV | mono, 22,050 Hz, PCM 16-bit, `S001.wav`부터 연속 번호 |
| 산출물 | ONNX·Piper JSON·manifest·status·샘플 WAV·학습 로그 |
| 적용 | 크기·SHA-256·로컬 합성 검증 후 교체, 실패 시 기존 모델 유지 |

[GPU Worker 운영](../Pauseable.docs/voice/OPERATIONS_KO.md) · [데이터·동의·보관 정책](../Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md) · [Pi 모델 교체 흐름](../Pauseable.edge/README.md#음성-모델-교체)

## 개발과 코드 안내

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

[실시간 수집](../Pauseable.docs/ha/ha_realtime_collection_guide.md) · [개인화·이상 탐지](../Pauseable.docs/ha/ha_anomaly_shadow_guide.md) · [시연 절차](../Pauseable.docs/ha/DEMO_RUNBOOK_KO.md)

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

## 검증을 읽는 기준

합성 시나리오 통과는 소프트웨어 동작의 근거이지 실제 환자 탐지 성능의 근거는 아닙니다. 공개 전력·활동 데이터도 출처와 사용 목적을 구분합니다. 녹음·개인 이력·checkpoint·개인화 ONNX·인증값은 Git에 올리지 않습니다. 저장된 검증 기록과 현재 Pi의 설치·운용 상태는 별도로 확인합니다.
