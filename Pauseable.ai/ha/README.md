# Memolink HA 반복행동 분석

[AI 구성·평가](../README.md) · [개발환경](../../Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md) · [기능별 코드](../../Pauseable.docs/SOURCE_MAP_KO.md#ha-가전-반복행동) · [통신 규격](../../Pauseable.contracts/README.md)

Home Assistant가 전달하는 가전 상태 변경을 기록하고, 시간 구간별 사용 특징으로 반복행동을 판단합니다. Baseline, IF·AE와 개인 Routine 정책을 적용한 결과를 MQTT로 Central에 전달합니다.

## 입력과 출력

| 구분 | 내용 |
| --- | --- |
| 입력 | HA 주소·Token, 선택한 Entity, 상태 변경과 관측 정보 |
| 참조 기준 | 정상 참조 특징으로 만든 Baseline JSON |
| 분석 파일 | 원시·정규화 CSV, Feature, 판정·Episode 요약 |
| 운영 상태 | 판정 SQLite, 관측 품질·학습 상태, 개인 모델 버전 |
| 전달 | `communication-v1`의 반복행동 판단 JSON |

엔티티 선택과 상태 매핑을 실제 가전에 맞춥니다. 도어 `on/off`를 `open/close`로 바꾸는 것은 해당 엔티티 매핑의 예시이며, 모든 HA 상태에 같은 변환을 적용하지 않습니다.

## 수집·특징·실행 주기

| 구분 | 동작 |
| --- | --- |
| 수집 | WebSocket의 `state_changed`를 받아 즉시 기록 |
| Feature 기준 시각 | 1분 간격의 시점별로 최근 10분·30분·1시간·2시간 이력 요약 |
| 서비스 분석 회차 | `run_ha_full_service.py`는 이전 분석 종료 후 `cycle_seconds`만큼 대기. 기본값 600초 |
| 초기 상태 | Snapshot으로 구분하며 실제 반복 횟수에 포함하지 않음 |

Feature를 1분 간격으로 계산하는 것과 서비스를 정확히 매분 실행하는 것은 다릅니다. Collector는 분석 사이에도 수집을 계속합니다. 2초 개폐도 HA가 두 상태 변경을 전달하면 각각 기록합니다.

## Baseline과 개인화 모델

| 구성 | 역할 | 구현 |
| --- | --- | --- |
| Baseline 생성 | 정상 참조 특징의 분위수·IQR 상한 계산 | [build_baseline.py](src/build_baseline.py) |
| Baseline 판정 | 특징별 최소 횟수·상한, 반복 패턴과 야간 점수 적용 | [infer_ha_baseline.py](src/infer_ha_baseline.py) |
| IF·AE 학습 | 정상 후보를 시간순으로 나누어 학습·보정·검증 | [train_ha_anomaly_models.py](src/train_ha_anomaly_models.py) |
| 모델 운용 | 학습 조건·모델 호환·활성화·갱신·fallback | [ha_model_lifecycle.py](src/ha_model_lifecycle.py) |
| Routine | 확인된 정상 생활패턴에 맞는 경보 보정 | [ha_personal_routine.py](src/ha_personal_routine.py) |

`MinCount`는 특징별 점수 계산에 필요한 최소 반복 횟수입니다. 기준 미만이면 해당 항목을 0점으로 처리합니다. 통계 상한을 넘는 정도에 따라 5·9·14점을 부여하고 패턴·Context 점수를 반영합니다. 기본 점수 경계는 Attention 35, Risk 70입니다.

AE는 scikit-learn MLP의 입력 복원 학습입니다. 정상 학습 특징으로 fit한 StandardScaler를 적용하고 Reconstruction Error를 구합니다. IF·AE의 모델 점수에는 반복 증거와 관측 품질 조건을 함께 적용합니다.

Baseline 생성기는 시간대별 통계도 저장하지만, 현재 기본 점수 계산은 전체 참조 통계와 명시적인 야간 점수를 사용합니다. 시간·요일 Feature와 Routine 비교를 '지난주 같은 요일의 사건을 하나씩 직접 대조하는 기능'으로 해석하지 않습니다.

최초 학습은 같은 가구·출처·특징 규격에서 하루 12개 이상 서로 다른 시간대의 유효 정상 후보가 있는 날 30일 이상을 기본 조건으로 합니다. `reviewed_normal`과 Baseline으로 선별한 후보는 구분합니다. `shadow`는 점수 관찰, `hybrid`는 모델 신호 결합이며, 주기 재학습은 `retrain_days=0`에서 꺼져 있습니다.

## 로컬 검사

[Python 3.12 가상환경](../../Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md#로컬-개발-준비)을 활성화한 뒤 저장소 루트에서 실행합니다.

```sh
python -m pip install -r Pauseable.ai/ha/requirements.txt
python -m unittest discover -s Pauseable.ai/ha/tests -v
python -m unittest discover -s Pauseable.docs/evaluation/ha/checks -v
```

이 명령은 코드·보고서 회귀 검사입니다. HA 연결이나 실기 출력 확인은 [실시간 수집](../../Pauseable.docs/ha/ha_realtime_collection_guide.md)과 [시연 절차](../../Pauseable.docs/ha/DEMO_RUNBOOK_KO.md)를 따릅니다.

## 배포와 평가 자료

- 장치 실행: [Dockerfile.pi](Dockerfile.pi), [systemd 설정](deploy/systemd), [전체 배포 안내](../../Pauseable.deploy/README.md)
- 연구 환경: [Dockerfile.research](Dockerfile.research), [compose.research.yaml](compose.research.yaml)
- 기존 평가: [AI 결과 설명](../README.md#ha-평가-결과), [평가 원본](../../Pauseable.docs/evaluation/ha)
- 데이터 출처: [공개 데이터 검토](../../Pauseable.docs/ha/public_power_data_guide.md), [문헌 기반 시나리오](../../Pauseable.docs/ha/EVIDENCE_RESEARCH_20261005_KO.md)

공개 연구·합성 자료와 개인 가구의 이력·모델을 별도 경로로 관리합니다. 실제 HA Token, 개인 이력과 학습 모델은 저장소에 넣지 않습니다.
