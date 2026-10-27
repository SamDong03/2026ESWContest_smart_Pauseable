# 설계·데이터·평가·운영 문서 안내

이 폴더는 **왜 이렇게 설계했는지, 어떤 자료로 시험했는지, 장치에 어떻게 적용하는지**를 설명하는 자료를 모았습니다. 프로그램의 현재 처리 순서는 각 상위 폴더 README에서 읽고, 수치와 시험 조건은 원본 기록에서 확인합니다.

[전체 시스템](../README.md) · [AI](../Pauseable.ai/README.md) · [Central·장치](../Pauseable.edge/README.md) · [앱·API](../Pauseable.apps/README.md) · [배포](../Pauseable.deploy/README.md)

<a id="주요-문서"></a>

## 1. 시스템 구성을 이해한다

| 읽는 순서 | 문서 | 알 수 있는 내용 |
| --- | --- | --- |
| 1 | [프로젝트 README](../README.md) | 목적, 장치별 역할, 수집부터 출력까지의 연결 |
| 2 | [개발환경](DEVELOPMENT_ENVIRONMENT_KO.md) | Pi·Python·SDK·Flutter·GPU와 의존성 |
| 3 | [기능별 코드 위치](SOURCE_MAP_KO.md) | Subscribe·Action Router 등 기능의 구현 파일 |
| 4 | [통신 규격](../Pauseable.contracts/README.md) | AI 판단·Central 사건·앱 알림의 차이 |

## 2. 파트별 메커니즘을 읽는다

| 파트 | 현재 설명 | 보충 자료 |
| --- | --- | --- |
| HA | [수집·특징·Baseline·학습·판정](../Pauseable.ai/README.md#ha-반복행동-판단) | [실시간 수집](ha/ha_realtime_collection_guide.md), [Baseline 검증 절차](ha/ha_baseline_validation_protocol.md) |
| mmWave | [위치 입력·형태·개인 변화·지속성](../Pauseable.ai/README.md#mmwave-구현과-설치-상세) | [Runtime](mmwave/RUNTIME.md), [경로 형태 실험 설계](../Pauseable.ai/mmwave/src/shape_v2/PROTOCOL.md) |
| Central | [수신 검증·실행·출력·Outbox](../Pauseable.edge/README.md#central-app) | [코드 위치](SOURCE_MAP_KO.md#central-수신과-실행) |
| 앱·API | [사건 저장·알림·설정·녹음](../Pauseable.apps/README.md) | [실기 알림 확인](../Pauseable.apps/guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md) |
| 음성 | [녹음부터 모델 게시까지](../Pauseable.ai/README.md#voice-학습과-운영-상세) | [Worker 운영](voice/OPERATIONS_KO.md), [데이터 정책](voice/DATA_AND_ARTIFACTS_KO.md) |
| 조명 | [지역·날씨·태양 고도 규칙](../Pauseable.integrations/README.md) | [지역 설정 연동](integrations/home-assistant/RENDER_REGION_SETUP_KO.md) |

<a id="평가-자료-읽기"></a>

## 3. 데이터 근거와 평가 조건을 확인한다

### 3.1 사용한 자료의 성격

| 자료 | 위치 | 사용하는 목적 |
| --- | --- | --- |
| 공개 전력 데이터 검토 | [public_power_data_guide.md](ha/public_power_data_guide.md) | 일반 가전 사용 패턴과 입력 변환 참고 |
| 문헌 조사 | [EVIDENCE_RESEARCH_20261005_KO.md](ha/EVIDENCE_RESEARCH_20261005_KO.md) | 반복행동에서 관측할 수 있는 가전 시나리오 구성 |
| 검증 설계 | [HA 검증 절차](ha/ha_baseline_validation_protocol.md), [mmWave 실험 설계](../Pauseable.ai/mmwave/src/shape_v2/PROTOCOL.md) | 정상·반복 입력, 분할·비교 조건 정의 |
| 개인 데이터 정책 | [DATA_AND_ARTIFACTS_KO.md](voice/DATA_AND_ARTIFACTS_KO.md) | 동의·보관·삭제·Git 제외 범위 |

공개 전력 데이터와 문헌 기반 합성 입력은 실제 치매 환자의 가전 반복행동 정답 데이터와 구분합니다.

### 3.2 결과의 원본

| 시험 | 원본 | 읽을 때 확인할 점 |
| --- | --- | --- |
| HA 자동 운용·학습·갱신·MQTT | [verification_summary.json](evaluation/ha/verification_summary.json) | 2026-10-23의 x86_64·합성 입력 기록. Unit 184개·Report 16개, 해당 기록에서 Pi·실가전 E2E 미실행 |
| HA 모델별 비교 | [baseline_comparison.json](evaluation/ha/baseline_comparison.json) | 반복 가설 24개·정상 맥락 48개. Routine 미적용 |
| HA Routine | 같은 검증 요약의 개인화 결과 | 별도 576시점에서 Attention 6개 Normal 보정·Risk 6개 유지 |
| HA 이벤트·특징·점수 | [visual_data.json](evaluation/ha/visual_data.json) | 그래프에 사용한 데이터와 점수 |
| mmWave 경로 형태 | [metrics.json](../Pauseable.ai/mmwave/src/shape_v2/artifacts/metrics.json) | 합성 경로, 실측 LD6004·임상 성능 미검증 |
| 앱·API | [검사·팀 시험 기록](../Pauseable.apps/README.md#자동-검사와-팀-실기-기록), [Actions 안내](../.github/CI_README.md) | 대상 commit과 자동 검사·실기 보고 구분 |

### 3.3 HA 비교 결과의 의미

모델별 비교의 반복 가설 경보는 Baseline 16/24·Hybrid 24/24였고, 정상 맥락 경보도 22/48에서 30/48로 늘었습니다. 이는 같은 합성 입력에서 모델 신호를 추가했을 때의 경보 변화입니다. 실제 환자 대상 정확도나 오탐 해결 결과로 사용하지 않습니다.

Routine의 576시점 시험은 위 48개 정상 맥락과 다른 시험입니다. 두 결과를 합쳐 ‘개인화로 모든 오탐을 해결했다’고 해석하지 않습니다. Sliding Window의 겹치는 행도 독립 사건이나 환자 수로 세지 않습니다.

<a id="보고서와-시각-자료"></a>

## 4. 보고서와 그림의 출처를 찾는다

| 자료 | 위치 |
| --- | --- |
| 저장된 HA 보고서 | [PowerPoint](presentation/ha/HA_Final_Report.pptx), [PDF](presentation/ha/HA_Final_Report.pdf) |
| 전체 구조도 | [pauseable-system.svg](assets/pauseable-system.svg) |
| 이벤트·Feature·모델 점수·비교 그래프 | [assets/readme](assets/readme) |
| 그림별 근거·수치·재생성 방법 | [ASSETS.md](assets/readme/ASSETS.md), [evaluation_figure_manifest.json](assets/readme/evaluation_figure_manifest.json) |

보고서는 해당 파일이 작성된 시점의 산출물입니다. 이후 기능 변경은 현재 코드와 README를 기준으로 확인합니다. IF·AE 점수 그래프와 Training Loss는 서로 다른 자료입니다.

그림을 다시 만들려면 문서용 환경에서 저장소 루트 기준으로 실행합니다.

```sh
node Pauseable.docs/assets/readme/build_diagrams.mjs
python Pauseable.docs/assets/readme/plot_evaluation.py
```

구조도 생성기는 Node.js 표준 모듈, 평가 그래프의 기준 환경은 Matplotlib 3.10.8·NumPy 2.3.5입니다. 그래프 생성은 저장된 JSON을 읽는 과정이며 모델을 새로 학습하지 않습니다.

<a id="실기-시험과-운영-기록"></a>

## 5. 장치에 적용하고 결과를 기록한다

1. [배포 README](../Pauseable.deploy/README.md)에서 장치별 산출물과 현재 소스 검사 상태를 확인합니다.
2. [DEPLOYMENT_HANDOFF.txt](DEPLOYMENT_HANDOFF.txt)의 설치·환경·서비스 절차를 따릅니다.
3. [HA 시연 절차](ha/DEMO_RUNBOOK_KO.md), [Android Push 설정](../Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md), [음악 설치](../Pauseable.edge/README.md#선호-음악-설치와-시험)에서 해당 기능을 시험합니다.
4. 소스·모델·설정 버전, 입력, 승인·거절 사유와 실제 출력을 같은 사건 ID로 대조해 기록합니다.

Token·원본 사진·녹음·개인 이력은 공유 작업 로그에서 제외합니다.

### 이전 기록을 읽을 때

[PI_FULL_AUTOMATION_KO.md](ha/PI_FULL_AUTOMATION_KO.md), [TEAM_HANDOFF_KO.md](ha/TEAM_HANDOFF_KO.md), [ha_anomaly_shadow_guide.md](ha/ha_anomaly_shadow_guide.md)는 당시 구성과 작업 과정을 보존한 자료입니다. 예전 IP·서비스 이름·Shadow 초기 설명은 현재 코드와 다를 수 있습니다. 현재 학습·Hybrid·재학습 설정은 [AI README](../Pauseable.ai/README.md#baseline과-개인화-모델)에서 확인합니다.

<a id="문서-폴더"></a>

## 6. 폴더별 자료 위치

| 폴더 | 내용 |
| --- | --- |
| [ha](ha) | 수집·Baseline·공개 데이터·학습·시연·운영 |
| [mmwave](mmwave) | 이동경로·개인 변화·지속성 |
| [voice](voice) | Worker 운영과 데이터 정책 |
| [integrations](integrations) | HA·지역·날씨 연결 |
| [evaluation/ha](evaluation/ha) | 평가 원본·보고서 회귀 검사 |
| [presentation/ha](presentation/ha) | 보고서 PPTX·PDF |
| [assets](assets) | 구조도·그래프·출처 |
