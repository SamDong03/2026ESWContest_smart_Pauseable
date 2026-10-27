# 설계·데이터·평가·운영 문서 안내

이 폴더는 **왜 이렇게 설계했는지, 어떤 자료로 시험했는지, 장치에 어떻게 적용하는지**를 설명하는 자료를 모았습니다. 프로그램의 현재 처리 순서는 각 상위 폴더 README에서 읽고, README 그림의 수치와 범위는 그림 폴더의 합성 원본과 출처 Manifest에서 확인합니다.

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
| HA | [수집·특징·Baseline·학습·판정](../Pauseable.ai/README.md#ha-반복행동-판단) | [실시간 수집](../Pauseable.ai/ha/src/collect_ha_events_ws.py), [Baseline 검증 절차](../Pauseable.ai/ha/tests/test_full_lifecycle.py) |
| mmWave | [위치 입력·형태·개인 변화·지속성](../Pauseable.ai/README.md#mmwave-구현과-설치-상세) | [Runtime](../Pauseable.ai/mmwave/src/wandering_runtime.py), [경로 형태 실험 설계](../Pauseable.ai/mmwave/src/shape_v2/PROTOCOL.md) |
| Central | [수신 검증·실행·출력·Outbox](../Pauseable.edge/README.md#central-app) | [코드 위치](SOURCE_MAP_KO.md#central-수신과-실행) |
| 앱·API | [사건 저장·알림·설정·녹음](../Pauseable.apps/README.md) | [실기 알림 확인](../Pauseable.apps/guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md) |
| 음성 | [녹음부터 모델 게시까지](../Pauseable.ai/README.md#voice-학습과-운영-상세) | [Worker 운영](../Pauseable.ai/voice/pipeline/r2_worker.py), [데이터 정책](../Pauseable.apps/README.md#음성-녹음과-동의) |
| 조명 | [지역·날씨·태양 고도 규칙](../Pauseable.integrations/README.md) | [지역 설정 연동](../Pauseable.integrations/home-assistant/weather-light-control/render-location.env.example) |

<a id="평가-자료-읽기"></a>

## 3. 데이터 근거와 평가 조건을 확인한다

### 3.1 사용한 자료의 성격

| 자료 | 위치 | 사용하는 목적 |
| --- | --- | --- |
| 공개 전력 데이터 검토 | [전력 데이터 변환 코드](../Pauseable.ai/ha/src/prepare_public_power.py) | 일반 가전 사용 패턴과 입력 변환 참고 |
| 문헌 조사 | [합성 시나리오 코드](../Pauseable.ai/ha/src/ha_evidence_scenarios.py) | 반복행동에서 관측할 수 있는 가전 시나리오 구성 |
| 검증 설계 | [HA 검증 절차](../Pauseable.ai/ha/tests/test_full_lifecycle.py), [mmWave 실험 설계](../Pauseable.ai/mmwave/src/shape_v2/PROTOCOL.md) | 정상·반복 입력, 분할·비교 조건 정의 |
| 개인 데이터 정책 | [음성 수집·동의](../Pauseable.apps/README.md#음성-녹음과-동의) | 동의·보관·삭제·Git 제외 범위 |

공개 전력 데이터와 문헌 기반 합성 입력은 실제 치매 환자의 가전 반복행동 정답 데이터와 구분합니다.

### 3.2 그림에 필요한 원본

README 그림에 필요한 합성 JSON 두 개만 `assets/readme/data/`에 보관합니다. 예전 보고서·PPT·PDF·날짜별 운영 기록은 최종 소스에서 정리했습니다.

| 시험 | 원본 | 읽을 때 확인할 점 |
| --- | --- | --- |
| HA 모델별 비교 | [baseline_comparison.json](assets/readme/data/baseline_comparison.json) | 반복 가설 24개·정상 맥락 48개. Routine 미적용 |
| HA 이벤트·특징·점수 | [visual_data.json](assets/readme/data/visual_data.json) | 그래프에 사용한 데이터와 점수 |
| mmWave 경로 형태 | [학습·평가 코드](../Pauseable.ai/mmwave/src/shape_v2/train.py) | 합성 경로, 실측 LD6004·임상 성능 미검증 |
| 앱·API | [검사·팀 시험 기록](../Pauseable.apps/README.md#자동-검사와-팀-실기-기록), [Actions 안내](../.github/CI_README.md) | 대상 commit과 자동 검사·실기 보고 구분 |

### 3.3 HA 비교 결과의 의미

모델별 비교의 반복 가설 경보는 Baseline 16/24·Hybrid 24/24였고, 정상 맥락 경보도 22/48에서 30/48로 늘었습니다. 이는 같은 합성 입력에서 모델 신호를 추가했을 때의 경보 변화입니다. 실제 환자 대상 정확도나 오탐 해결 결과로 사용하지 않습니다.

위 모델 비교에는 Routine 보정이 적용되지 않았습니다. Sliding Window의 겹치는 행도 독립 사건이나 환자 수로 세지 않습니다.

<a id="보고서와-시각-자료"></a>

## 4. 보고서와 그림의 출처를 찾는다

| 자료 | 위치 |
| --- | --- |
| 전체 구조도 | [pauseable-system.svg](assets/pauseable-system.svg) |
| 이벤트·Feature·모델 점수·비교 그래프 | [assets/readme](assets/readme) |
| 그림별 근거·수치·재생성 방법 | [ASSETS.md](assets/readme/ASSETS.md), [evaluation_figure_manifest.json](assets/readme/evaluation_figure_manifest.json) |

그림은 저장된 합성 원본을 사용합니다. 현재 기능은 코드와 README를 기준으로 확인하며, IF·AE 점수 그래프와 Training Loss는 구분합니다.

그림을 다시 만들려면 문서용 환경에서 저장소 루트 기준으로 실행합니다.

```sh
node Pauseable.docs/assets/readme/build_diagrams.mjs
python Pauseable.docs/assets/readme/plot_evaluation.py
```

구조도 생성기는 Node.js 표준 모듈, 평가 그래프의 기준 환경은 Matplotlib 3.10.8·NumPy 2.3.5입니다. 그래프 생성은 저장된 JSON을 읽는 과정이며 모델을 새로 학습하지 않습니다.

<a id="실기-시험과-운영-기록"></a>

## 5. 장치에 적용하고 결과를 기록한다

1. [배포 README](../Pauseable.deploy/README.md)에서 장치별 산출물과 현재 소스 검사 상태를 확인합니다.
2. [배포 순서](../Pauseable.deploy/README.md#배포-순서)의 설치·환경·서비스 절차를 따릅니다.
3. [HA 시연 절차](../Pauseable.apps/guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md), [Android Push 설정](../Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md), [음악 설치](../Pauseable.edge/README.md#선호-음악-설치와-시험)에서 해당 기능을 시험합니다.
4. 소스·모델·설정 버전, 입력, 승인·거절 사유와 실제 출력을 같은 사건 ID로 대조해 기록합니다.

Token·원본 사진·녹음·개인 이력은 공유 작업 로그에서 제외합니다.

<a id="문서-폴더"></a>

## 6. 폴더별 자료 위치

| 자료 | 내용 |
| --- | --- |
| [DEVELOPMENT_ENVIRONMENT_KO.md](DEVELOPMENT_ENVIRONMENT_KO.md) | 현재 개발환경과 도구 |
| [SOURCE_MAP_KO.md](SOURCE_MAP_KO.md) | 기능별 소스 위치 |
| [assets](assets) | README 구조도·그래프·출처와 재생성용 합성 원본 |
