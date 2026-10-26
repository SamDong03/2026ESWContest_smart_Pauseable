# 치매·생활센서 공개 데이터 연결

## 이번에 추가한 범위

TIHM, CASAS Cognitive Assessment, MIRATAR의 실제 공개 원본을 내려받고,
데이터별 특징 생성 -> IF/Autoencoder 학습 -> 별도 평가 -> 모델/점수/출처 저장 경로를 추가했다.
합성 환자 데이터로 대체하지 않았다. Pi의 기존 baseline, 개인화 모델, 30일 수집 조건은 변경하지 않았다.
이 기능은 연구용 비교 실험이며 치매 진단기나 의료적으로 검증된 경보 시스템이 아니다.

| 자료 | 실제로 사용하는 입력 | 평가 라벨 | 사용하지 않는 것 |
|---|---|---|---|
| TIHM | 방별 활동·냉장고/출입문 센서의 일별 기록 수, 야간 비율 등 | 기록된 건강 사건의 종류와 날짜 | 진단을 추측한 정상/비정상 라벨, 생리·수면·인구학 정보를 모델 입력으로 사용 |
| CASAS | 검사 세션의 모션·문·물건 센서 기록과 시간 간격 | 참가자 진단 코드: 치매와 MCI 각각 평가 | 관찰자 활동 점수, 진단 코드, 나이, 참가자 ID를 예측 특징으로 사용 |
| MIRATAR | 가구별 모션·문 CSV의 일별 기록 통계 | 공개 CSV에 진단/이상 정답 없음 | 외부 제공 .pkl/.h5 모델 실행, 0/1을 가전 사용 횟수로 해석 |

세 자료의 특징은 HA 가전 상태 이벤트와 동일하지 않다. 엑셀의 'loader만 교체' 설명을 그대로 적용하지 않았다.
예를 들어 TIHM Fridge Door는 타임스탬프 기록이지 열림/닫힘 상태 쌍이 아니므로 문을 열어 둔 시간을 계산하지 않는다.
CASAS 전력 센서도 있지만 이 경로에서는 단위·기기 매핑이 확인되지 않은 P/A 센서 수치를 가전별 전력으로 사용하지 않는다.

## 코드 흐름

1. `src/fetch_public_clinical.py`: Zenodo 고정 버전, 크기 제한, 공개 MD5 비교, SHA-256 및 이용 조건 저장.
2. `src/public_clinical_data.py`: ZIP 내부 데이터만 읽기, 센서별 변환, 품질 검사, 날짜/참가자 분할.
3. `src/public_clinical_models.py`: IF와 작은 dense AE 학습, calibration 95백분위 임계값, 점수 저장.
4. `src/run_public_clinical_benchmark.py`: 전체 실행과 데이터별 평가 보고서 생성.
5. `tests/test_public_clinical.py`: 데이터 누출, 누락, 출처 혼합, 공개 모델의 운영 진입 차단 회귀 검사.

모델은 기존 검증된 scikit-learn IsolationForest와 MLPRegressor 기반 AE, 기존 `dense_predict`를 사용한다.
IF 128개 트리, AE 은닉층 8-3-8, seed 42, 최대 400회 반복이다. 결과를 본 뒤 임계값/모델을 맞추지 않았다.
학습 구간에서만 log1p 후 표준화와 상수 특징 제거를 수행한다. calibration 구간에서만 95백분위 임계값을 정한다.
AE 비수렴 경고는 숨기지 않고 모델 manifest에 남긴다. 경고가 없다고 임상 성능이 검증되는 것도 아니다.

## 학습·평가 구분

### TIHM

- 한 사람의 관찰일을 시간순 60/20/20으로 나눈다. 첫날·마지막 날과 경계 하루를 제외한다.
- 학습·calibration에서는 기록된 건강 사건일 전후 1일을 제외한다. 이는 사후 라벨을 이용한 연구용 선별이며 실제 운영의 인과적 조기예측 실험이 아니다.
- '라벨 없음'은 `unknown`이다. 정상으로 임상 확인된 기록이라고 표현하지 않는다.
- 기록이 전혀 없는 날은 생성하지 않는다. 특정 방 기록 0은 설치/통신 상태가 확인된 비활동 0과 다르다.
- 일별 점수와 같은 날짜의 사건을 비교한다. 이미 그날 발생한 사건 이후의 센서 기록도 포함될 수 있으므로 조기예측률이 아니다.
- 명시적 정상 정답이 없으므로 precision, specificity, ROC-AUC를 계산하지 않는다.
- Agitation과 혈압/맥박 등 다른 종류를 한 가지 '치매 악화' 라벨로 합치지 않는다.

### CASAS

- 배포 ZIP에는 진단 항목이 400개다. 소개문/원논문의 179명 코호트를 재현했다고 주장하지 않는다.
- 한 참가자당 전체 검사 세션 한 행을 만든다. 학습과 평가에 같은 사람이 들어가지 않는다.
- 기준군은 진단 코드 4/5(60세 이상 정상 기준군)만 사용한다. 젊은 성인, 기타 질환, 위험군, 미상은 정상으로 합치지 않는다.
- 기준군을 진단 연령군별로 고정 해시 분할하여 train/calibration/holdout으로 나눈다.
- 치매(1)와 MCI(2)는 학습에 넣지 않고, 각각 heldout 기준군과 비교한다.
- 검사 없음/센서 없음/파싱 불가/시간 역행은 이유와 진단별 제외 내역을 남긴다.
- 검사 미완료, 도움말 제공, 표본 선택이 점수에 영향을 줄 수 있다. '집에서 장기간 쓰는 가전 이상'과는 다른 과제다.

### MIRATAR

- 50가구의 CSV 400개를 읽는다. 이 중 모션 200개와 문 50개로 특징을 만든다. 온도 150개는 원본 품질 목록만 작성한다.
- 타임스탬프가 없는 행은 시각을 만들어 채우지 않고 제외 건수를 남긴다.
- 분 단위 타임스탬프 중복은 순서를 재구성하지 않고 기록 수와 고유 분 수를 따로 계산한다.
- 다섯 센서 모두 기록이 있는 날만 모델 후보로 삼는다. 이것도 하루 종일 센서가 정상 작동했다는 증거는 아니다.
- 가구별 과거 routine 참고 모델이지 치매 정상/이상 분류 학습이 아니다. 경보 비율은 정확도가 아니다.

## 실행

기존 ML 의존성(numpy, pandas, scikit-learn 1.7.2, joblib 등)이 설치된 Python에서 프로젝트 루트를 기준으로 실행한다.
Pi에는 저장 공간을 차지하는 원본·연구 모델을 올리지 않는 것을 기본으로 한다.

```sh
python src/fetch_public_clinical.py --dataset all --output-dir data/public_clinical/downloads
python src/run_public_clinical_benchmark.py --dataset all --download-dir data/public_clinical/downloads --output-dir outputs/public_clinical_run_01
python -m unittest discover -s tests -p test_public_clinical.py -v
```

첫 명령만 인터넷이 필요하다. 출력 폴더는 새 이름을 사용한다. 기존 실험은 덮어쓰지 않는다.
`--dataset tihm`, `--dataset casas`, `--dataset miratar`로 각각 실행할 수도 있다.
다운로드는 ZIP 안의 예제 코드, pickle, 모델을 실행하지 않는다.

각 결과에는 `features.csv`, `scores.csv`, `report.json`, `models/*/manifest.json`과
실제 학습에 사용한 train/calibration/test CSV가 생긴다. TIHM은 사건 라벨 CSV도 별도로 저장한다.
자체 학습한 IF는 joblib, AE는 manifest의 weight/bias 배열로 저장한다. 외부 모델 pickle은 불러오지 않는다.
공개 모델 형식은 `public_clinical_research_v1`으로 HA 운영 모델 형식과 다르며,
`source_type=public`, `production_eligible=false`로 표시한다. 자동 승격/서비스 재시작은 하지 않는다.

## 다른 엑셀 후보의 채택 여부

| 후보 | 결정과 이유 |
|---|---|
| #31 Personalized IADL | 직접적인 치매·실가전 연구지만 원자료가 저자 요청 방식. 이번에 환자 가전 원자료를 확보했다고 주장하지 않음 |
| UK-DALE / REFIT | 기존 전력 분석 경로 유지. 가전 신호·세션 추출 시험에는 유용하지만 치매 정답 데이터가 아님 |
| KFall | 낙상 IMU 과제. 현재 HA 가전/생활센서 입력과 달라 이번 경로에는 미추가 |
| AI Hub 시니어 이상행동 / ETRI-Activity3D | 영상·별도 접근 조건의 다른 입력 과제. 데이터/가중치 미추가 |
| 통영 IoT 상담 통계 | 개인별 시계열이 아닌 집계 통계라 개인 AE 학습/임계값에 사용하지 않음 |
| Howz 분석 논문 | 개인 routine 비교 방법론 참고. 독립 원자료를 확보한 것으로 표시하지 않음 |
| MAISON-LLF | 최신 공개판은 골절 회복 고령자 18명 자료. 치매 가전 정답이 아니며 제공 특징은 사전 보간되어 미래 정보 혼입 여부를 통제하기 어려워 미추가 |
| DPUK / Minder | 별도 심사·접근 절차 대상. 우회하거나 승인받은 것으로 간주하지 않음 |

직접 환자 가전 자료를 확보하려면 #31 저자에게 비식별 센서/가전 기록, 가전-센서 매핑,
라벨 정의, 참가자별 분할 정보, 동의·이용허가 범위를 문의해야 한다. 이번 작업에서는 연락하지 않았다.
본인의 실제 가전 모델 학습은 별도 수집·품질 검사·개인화 절차를 계속 사용한다.

## 출처와 이용 조건

- TIHM: https://zenodo.org/records/7622128, DOI 10.5281/zenodo.7622128.
  메타데이터 CC-BY-4.0과 본문의 비상업 연구용 제한 문구가 상충한다. 이번 사용은 연구용으로 제한하며 상업 이용은 저자 확인이 필요하다.
  Surrey and Borders Partnership NHS Foundation Trust 및 Howz에 사사한다.
- CASAS: https://zenodo.org/records/15713579 (고정 v1), CC-BY-4.0.
  Dawadi, Cook, Schmitter-Edgecombe (2013), DOI 10.1109/TSMC.2013.2252338.
- MIRATAR: https://zenodo.org/records/15553764, CC-BY-4.0.
  Llumiguano 등, University of Castilla-La Mancha, MIRATAR TED2021-132149B-C41.
- #31: https://www.mdpi.com/1660-4601/18/24/13235, DOI 10.3390/ijerph182413235.
- MAISON-LLF 최신 공개판 확인: https://zenodo.org/records/17943110.
- 엑셀 근거: `AIoT_AI_Model_Data_Design.xlsx`의 `공공오픈데이터_맵` 5~20행과 DS 상세 시트,
  `Dementia_AIoT_Tech_AI.xlsx`의 `#31_Personalized IADL`, `#33_CASAS Cognitive` 등.

외부 파일은 해당 조건으로만 이용한다. 다른 공개 데이터와 섞거나 가구를 재식별하지 않는다.
