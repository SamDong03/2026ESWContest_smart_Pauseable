# PAUSEABLE

**스마트 가전과 실내 이동 정보를 활용하는 개인화 생활 안전 보조 시스템**

PAUSEABLE은 Home Assistant의 가전 사용 이력과 mmWave 센서의 실내 이동 정보를 분석해 반복행동과 배회 의심 상황을 살펴보는 임베디드 SW 프로젝트입니다. Raspberry Pi 5의 Central App이 판단 결과를 검증하고, 설정된 정책에 따라 음성 안내·가전 제어·보호자 알림을 연결합니다.

이 저장소는 AI, 보호자 앱, API, 엣지 장치, 통신 계약, 배포 도구를 **기능과 실행환경별로 분리한 모노레포**입니다. 임상적 치매 진단이나 환자 안전을 보장하는 의료 시스템을 의미하지 않습니다.

[시스템 구조](#시스템-구조) · [저장소 구성](#저장소-구성) · [핵심 처리 과정](#핵심-처리-과정) · [개발 시작하기](#개발-시작하기) · [검증 범위](#검증-범위) · [배포 안내](#배포-안내)

## 시스템 구조

```text
스마트 가전 -> Home Assistant -> HA AI ---------+
                                               | MQTT / JSON
ESP32 / mmWave -> Pi 3 Relay -> mmWave AI ------+
                                               v
                                      Pi 5 / Central App
                                  입력 검증 -> Action Router
                                               |
                        +----------------------+----------------------+
                        v                      v                      v
                  Piper / ONNX           Home Assistant          FastAPI / Render
                    음성 안내              가전 제어             알림 이력·Push
                                                                     |
Pi 4 Camera ---------------- 출입 사진 업로드 -----------------------> |
                                                                     v
                                                             Flutter 보호자 앱

음성 모델: 보호자 녹음 -> API / R2 -> GPU Worker -> ONNX Export
           -> API / R2 -> Pi 5 Model Updater -> 검증 후 TTS 모델 교체
```

| 실행 위치 | 역할 | 주요 구성 요소 |
| --- | --- | --- |
| Raspberry Pi 3 | 센서 입력 중계 | mmWave serial 수신, 메시지 검증, Pi 5 전달 |
| Raspberry Pi 4 | 출입 상황 기록 | 카메라 버퍼, 이벤트 전후 대표 사진, API 업로드 |
| Raspberry Pi 5 / Atlas | 로컬 판단과 실행 | HA AI, mmWave AI, C++ Central, TTS, 가전 연동 |
| API 서버 / Render | 앱·장치·학습 작업 연결 | 인증, 알림 저장, WebSocket, FCM/Web Push, 모델 배포 API |
| GPU Worker / R2 | 개인화 음성 모델 처리 | 녹음·대본 검증, Piper 학습, ONNX Export, 비공개 객체 저장 |
| 보호자 휴대폰 / 웹 | 상태 확인과 설정 | Flutter 앱, 알림 확인, 출입 사진, 음성 녹음, 지역·선호 설정 |

반복행동과 배회 모델은 **각각 판단을 발행하고 Central에서 실행 정책을 적용**합니다. 두 센서 입력을 하나의 신경망으로 함께 학습하는 통합 모델 구조는 아닙니다. 위 흐름은 소프트웨어 연결 구조이며 모든 경로의 최신 실기 검증 완료를 뜻하지 않습니다.

## 저장소 구성

```text
Pauseable/
├── Pauseable.ai/             # HA·mmWave 분석과 음성 학습
├── Pauseable.apps/           # FastAPI 서버와 Flutter 보호자 앱
├── Pauseable.edge/           # Central·센서 릴레이·카메라·모델 교체
├── Pauseable.contracts/      # 공통 JSON Schema와 통신 계약
├── Pauseable.deploy/         # 장치별 배포·systemd·이전 설정 대응표
├── Pauseable.integrations/   # Home Assistant 날씨·조명 연동
├── Pauseable.docs/           # 운영·인수인계·평가·발표 자료
├── Pauseable.third_party/    # 외부 소스와 저작권 고지
└── .github/workflows/        # 파트별 검사와 Android APK 빌드
```

| 파트 | 소스 | 먼저 볼 자료 |
| --- | --- | --- |
| HA 반복행동 | [`Pauseable.ai/ha`](Pauseable.ai/ha) | [실시간 수집](Pauseable.docs/ha/ha_realtime_collection_guide.md), [시연 절차](Pauseable.docs/ha/DEMO_RUNBOOK_KO.md) |
| mmWave 배회 의심 | [`Pauseable.ai/mmwave`](Pauseable.ai/mmwave) | [Runtime과 판단 범위](Pauseable.docs/mmwave/RUNTIME.md), [모델 평가](Pauseable.ai/mmwave/src/shape_v2/artifacts/REPORT.md) |
| Central App | [`Pauseable.edge/central`](Pauseable.edge/central) | [MQTT 수신](Pauseable.edge/central/integration/src/MqttDecisionSubscriber.cpp), [입력 검증](Pauseable.edge/central/core/src/BehaviorInference.cpp), [Action Router](Pauseable.edge/central/core/src/ActionRouter.cpp) |
| API 서버 | [`Pauseable.apps/api`](Pauseable.apps/api) | [API 라우트](Pauseable.apps/api/app/main.py), [인증](Pauseable.apps/api/app/security.py), [테스트](Pauseable.apps/api/tests) |
| 보호자 앱 | [`Pauseable.apps/guardian`](Pauseable.apps/guardian) | [Android Push 설정](Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md), [실기 알림 확인](Pauseable.apps/guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md) |
| 개인화 음성 | [`Pauseable.ai/voice`](Pauseable.ai/voice), [`Pauseable.edge/voice-model`](Pauseable.edge/voice-model) | [Worker 운영](Pauseable.docs/voice/OPERATIONS_KO.md), [데이터·산출물 정책](Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md) |
| 센서·카메라 | [`mmwave-relay`](Pauseable.edge/mmwave-relay), [`camera`](Pauseable.edge/camera) | [장치별 배포 인계](Pauseable.docs/DEPLOYMENT_HANDOFF.txt) |
| 날씨·조명 | [`weather-light-control`](Pauseable.integrations/home-assistant/weather-light-control) | [지역 설정 연동](Pauseable.docs/integrations/home-assistant/RENDER_REGION_SETUP_KO.md) |

## 핵심 처리 과정

### 1. HA 반복행동 판단

```text
HA state_changed 이벤트 / Recorder 이력
  -> 엔티티 상태 정규화와 관측 품질 확인
  -> 1분 단위 특징 생성: 최근 10분·30분·1시간·2시간
  -> Baseline + Isolation Forest + Autoencoder
  -> 반복 증거·개인 Routine 정책·Episode 처리
  -> MQTT 판단 발행
```

- **수집:** WebSocket으로 상태 변경을 구독합니다. 1분 단위 특징을 만든다는 것은 HA를 1분에 한 번만 조회한다는 뜻이 아닙니다. 다만 제조사·클라우드·HA에서 누락된 이벤트까지 복구한다는 의미는 아닙니다.
- **초기 판단:** 학습 모델이 없을 때는 Baseline을 사용합니다. 변화 횟수·사용 간격·지속시간 등 관측된 반복 증거를 확인합니다.
- **개인화 학습:** 관측 범위와 출처가 확인된 정상 후보 이력을 모아 IF/AE를 학습합니다. 기본 조건은 하루 12개 이상 서로 다른 시간대의 유효 관찰이 있는 날 30일 이상이며, 단순한 달력상 30일과 다릅니다. Baseline 자동 선별과 사람의 정상 검토는 구분해 기록합니다.
- **모델 적용:** 시간순 학습·보정·검증을 거쳐 적용합니다. `shadow`는 점수 비교만 하고, `hybrid`는 반복 증거가 있는 구간에서 모델 판단을 결합합니다. 모델 오류나 호환성 문제는 Baseline fallback으로 처리하고, 관측 부족은 별도로 표시합니다.
- **갱신:** 재학습은 `retrain_days` 설정과 새 유효 이력 조건을 따릅니다. 기본값 `0`은 주기적 재학습 비활성화이므로, 최초 학습 기능과 상시 재학습 활성화 여부를 구분해야 합니다.

핵심 구현: [특징 생성](Pauseable.ai/ha/src/make_ha_features.py), [모델 학습](Pauseable.ai/ha/src/train_ha_anomaly_models.py), [모델 Lifecycle·Hybrid](Pauseable.ai/ha/src/ha_model_lifecycle.py), [수집·분석 서비스](Pauseable.ai/ha/src/run_ha_full_service.py).

### 2. mmWave 배회 의심 판단

센서 입력을 대상별로 관리하고 이동 경로의 반복 형태, 개인 이력 대비 변화, 관측 품질과 지속성을 함께 살펴봅니다. 최신 연구용 `shape_v2`는 경로 형태를 Random Forest로 평가합니다. 일시적인 점수 상승만으로 배회를 확정하지 않으며 관측이 부족하면 판단을 보류합니다.

현재 `shape_v2` 평가 기록은 `simulated_only`이고 `real_ld6004_validated=false`, `automatic_alerts_enabled=false`입니다. 연구 모델의 경로 분류 결과를 실제 치매 환자의 배회 탐지 정확도로 해석하지 않습니다. [Runtime 안내](Pauseable.docs/mmwave/RUNTIME.md)와 [평가 원본](Pauseable.ai/mmwave/src/shape_v2/artifacts/metrics.json)을 함께 확인합니다.

### 3. Central 검증과 실행

```text
MQTT Subscriber
  -> JSON 구조·Topic/source·시각·식별자 검증
  -> event_id 중복·동일 ID 내용 충돌 확인
  -> 내부 Decision 변환
  -> Action Router: 실행 허용·위험도·cooldown 판단
  -> 로컬 TTS / 설정된 가전 출력
  -> 영속 Outbox / Decision Gateway -> API -> 보호자 앱
```

Central은 AI 모델의 정확도를 다시 판단하는 모델이 아니라 **입력을 검증하고 실행을 통제하는 계층**입니다. 잘못된 입력, 오래된 이벤트, `unknown` 판단을 그대로 가전 실행으로 연결하지 않습니다. 출력은 기능별 활성화 설정과 장치 연결 상태에 따라 달라집니다.

### 4. 개인화 음성

보호자 동의와 녹음 → API/R2 저장 → GPU Worker의 입력 검증과 Piper fine-tuning → ONNX Export·산출물 검증 → Pi 5의 다운로드·SHA-256·로컬 합성 검사 → 활성 모델 교체 순서입니다. 새 모델 검증에 실패하면 기존 모델을 유지합니다. 이 음성 학습 경로는 HA의 IF/AE 학습과 별개입니다.

## 통신 계약

| 구간 | 방식 | 기준 |
| --- | --- | --- |
| 반복행동 AI → Central | MQTT `pauseable/ai/repetitive/decision` | `source=repetitive-ai` |
| 배회 AI → Central | MQTT `pauseable/ai/wandering/decision` | `source=wandering-ai` |
| Central → API | HTTPS `POST /api/events/decisions` | Device Token, `event_id` 기반 중복 처리 |
| API → 보호자 앱 | REST / WebSocket / FCM·Web Push | App Token, 구독·알림 권한·서버 설정 |
| 음성 학습·배포 | API / R2 presigned URL | Worker·Device 인증, 산출물 무결성 확인 |

행동 판단 연동은 [`communication-v1/schemas`](Pauseable.contracts/communication-v1/schemas)의 [Behavior Inference](Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json)와 [Central Decision Event](Pauseable.contracts/communication-v1/schemas/decision-event.schema.json)를 기준으로 확인합니다. 최상위의 간략 스키마와 필드가 같다고 가정하지 않습니다.

- `risk_score`는 0~100 범위의 시스템 점수이며 치매 확률이나 모델 정확도가 아닙니다.
- 기본 시각 정책은 300초보다 오래된 이벤트와 30초를 초과한 미래 이벤트를 거부합니다. 장치 간 시각 동기화가 필요합니다.
- MQTT PUBACK은 브로커 수신 확인입니다. Central 처리, TTS 재생, 가전 실행, 휴대폰 표시 성공은 각각 확인해야 합니다.
- 현재 계약의 대상자·장치 ID 제약과 실행 설정을 함께 맞춰야 합니다. README의 예시만 바꾼다고 다중 사용자 지원이 완성되지는 않습니다.

## 개발 시작하기

아래는 **로컬 개발·검사 명령**이며 실제 장치 설치 명령이 아닙니다. Python은 파트별 가상환경으로 분리하고 각 `requirements`를 사용합니다. HA/API 검사는 Python 3.12, Voice CI는 Python 3.11, Flutter CI는 Flutter 3.47.6을 기준으로 구성되어 있습니다.

### API 서버

저장소 루트에서 시작합니다. 가상환경 활성화는 운영체제에 맞는 한 가지 명령만 실행합니다.

```sh
cd Pauseable.apps/api
python -m venv .venv
```

```sh
# Linux / macOS
. .venv/bin/activate
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t . -p "test_*.py"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

로컬 API 문서: `http://127.0.0.1:8000/docs`. 기본 local storage는 실행 PC에 기록합니다. 외부 운영에는 `PAUSEABLE_ENV=production`, 용도별 `PAUSEABLE_APP_TOKEN`·`PAUSEABLE_DEVICE_TOKEN`·`PAUSEABLE_WORKER_TOKEN`, 영속 저장소 설정이 필요합니다. 토큰 없는 development 모드를 외부에 공개하지 않습니다.

### Flutter 보호자 앱

새 터미널에서 저장소 루트를 기준으로 실행합니다.

```sh
cd Pauseable.apps/guardian
flutter pub get
flutter analyze
flutter test
flutter run -d chrome --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

마지막 명령은 같은 PC의 로컬 API를 사용하는 개발 미리보기입니다. 실제 서버 연결·휴대폰 Push는 별도 설정이 필요합니다. 서버용 Device/Worker Token이나 R2 키를 Flutter에 넣지 않습니다. 현재 공유 App Token을 포함한 시험 APK는 공개 배포용 사용자 인증 체계를 대신하지 않습니다. [안전한 Render 웹 미리보기](Pauseable.apps/guardian/docs/RENDER_WEB_PREVIEW_KO.md)와 [Android 설정](Pauseable.apps/guardian/docs/ANDROID_PUSH_SETUP_KO.md)을 따릅니다.

### HA 분석과 보고서 검사

별도 Python 3.12 가상환경에서 저장소 루트를 기준으로 실행합니다.

```sh
python -m pip install -r Pauseable.ai/ha/requirements.txt
python -m unittest discover -s Pauseable.ai/ha/tests -v
python -m unittest discover -s Pauseable.docs/evaluation/ha/checks -v
python -O -m unittest discover -s Pauseable.docs/evaluation/ha/checks -v
```

Docker 연구 환경의 정의는 [`Dockerfile.research`](Pauseable.ai/ha/Dockerfile.research)와 [`compose.research.yaml`](Pauseable.ai/ha/compose.research.yaml)에 있습니다. 연구·검증 출력 경로와 실제 가구의 이력·모델 저장소를 분리합니다.

### Central / Voice

Central은 C++17과 CMake를 사용하며 **Atlas/webOS SDK 및 전용 라이브러리**가 필요합니다. 일반 PC에서 CMake만 실행하면 정식 앱이나 `.ipk`까지 만들어지는 구성은 아닙니다. [빌드 정의](Pauseable.edge/central/CMakeLists.txt)와 [배포 인계](Pauseable.docs/DEPLOYMENT_HANDOFF.txt)를 먼저 확인합니다.

Voice는 [GPU Worker 운영 가이드](Pauseable.docs/voice/OPERATIONS_KO.md)의 가상환경·Docker·NVIDIA GPU 점검 순서를 따릅니다. 개인 녹음 없이 먼저 dry-run으로 입력 계약을 확인할 수 있습니다.

## 검증 범위

**코드 구현, 저장된 시험 기록, 현재 기기의 동작 확인은 서로 다릅니다.** 아래는 저장소에 포함된 기록의 범위이며 이번 README 정리에서 전체 시스템을 다시 실행했다는 의미가 아닙니다.

| 항목 | 저장소에서 확인할 수 있는 내용 | 해석상 주의 |
| --- | --- | --- |
| HA 회귀·Lifecycle | 2026-10-23 기록: unit test 184개, report test 16개, 월간 학습·검증·갱신 시나리오 | x86_64·합성 데이터 시험이며 최신 Pi 배포 검증 아님 |
| HA 비교 평가 | 96개 시나리오와 Baseline/IF/AE 비교 결과 | 정상 맥락 48개 중 30개에서도 경보가 발생한 미해결 한계 포함 |
| Central | 입력 검증·Action Router·Outbox 테스트 소스와 host 시험 기록 | 실제 MQTT→TTS→가전→앱 완료는 별도 E2E 확인 필요 |
| mmWave `shape_v2` | 경로 형태 모델과 재현 가능한 평가 산출물 | 실측 LD6004·임상 배회 성능 검증 아님 |
| 앱/API/Voice | 파트별 테스트와 CI 정의, 실기 점검 절차 | 코드·설정 존재만으로 현재 서버/휴대폰/GPU의 성공을 단정하지 않음 |

평가 원본: [HA verification summary](Pauseable.docs/evaluation/ha/verification_summary.json), [HA 평가 폴더](Pauseable.docs/evaluation/ha), [mmWave metrics](Pauseable.ai/mmwave/src/shape_v2/artifacts/metrics.json). 자동 검사 정의: [HA report](.github/workflows/ha-report-checks.yml), [앱/API](.github/workflows/native-alert-checks.yml), [Voice](.github/workflows/voice-checks.yml), [Android APK](.github/workflows/native-push-apk.yml).

## 배포 안내

먼저 [전체 배포 인계](Pauseable.docs/DEPLOYMENT_HANDOFF.txt)를 읽습니다. 저장소 루트에서 장치별 **소스·설정 묶음**을 생성할 수 있습니다.

```sh
python Pauseable.deploy/mmwave-autostart/package_devices.py --verify-source-manifest
python Pauseable.deploy/mmwave-autostart/package_devices.py --output deployment-bundles
```

생성 파일은 `pauseable-pi3.tar.gz`, `pauseable-pi4.tar.gz`, `pauseable-pi5.tar.gz`입니다. 각 묶음은 `BUNDLE.sha256`을 포함합니다. 압축을 푼 최상위 폴더에서 `sha256sum -c BUNDLE.sha256`으로 확인합니다.

이 묶음은 설치 완료된 바이너리나 `.ipk`가 아닙니다. Central 앱 빌드·설치, Flutter 빌드, 모델·Piper 런타임 준비, 비밀 환경 설정, systemd 등록과 실기 확인은 따로 필요합니다.

기존 RACOS 이름을 사용하는 장치에서 전환할 때는 [이전→현재 대응표](Pauseable.deploy/migration/legacy-to-pauseable.json)를 확인합니다. 모델·DB·환경 파일·서비스 정의를 백업하고 MQTT Topic, 환경변수, 앱 ID, 경로를 함께 맞춥니다. **GitHub의 폴더 정리가 기존 Pi나 Render 설정을 자동으로 변경하지 않습니다.**

`Pauseable.docs`의 날짜가 있는 인수인계·시연 문서는 당시의 구현과 장비 상태를 기록한 자료입니다. 과거의 미구현 항목이나 장치 IP를 현재 상태로 그대로 적용하지 말고, 현재 소스·스키마·배포 설정과 대조합니다.

## 데이터와 보안

- 실제 대상자의 가전 이력·출입 사진·음성·개인화 모델, 토큰, presigned URL은 저장소나 공개 로그에 올리지 않습니다.
- 합성 데이터·공개 데이터·실제 가구 데이터는 출처와 저장 경로를 분리합니다. 공개 전력 데이터나 합성 시나리오는 치매 환자의 가전 반복행동 정답 데이터가 아닙니다.
- 인터넷이 필요한 제조사 가전 통합, API, Push, R2와 Pi 내부 판단·TTS를 구분합니다. Pi 단독 실행이 전체 기능의 오프라인 동작을 뜻하지 않습니다.
- 실제 가전 제어와 알림은 대상 엔티티·장치, 인증, 동작 허용, cooldown을 확인한 뒤 활성화합니다. 미확인 입력을 정상이나 안전으로 단정하지 않습니다.
- 음성의 동의·보관·삭제·모델 교체 절차는 [데이터·산출물 정책](Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md)을 확인합니다.

## 외부 소스와 라이선스

Piper와 nlohmann/json 등 외부 소스는 [`Pauseable.third_party`](Pauseable.third_party)에 분리되어 있습니다. [저작권 고지](Pauseable.third_party/NOTICE.txt), [nlohmann/json 라이선스](Pauseable.third_party/nlohmann/LICENSE.MIT), [Piper 원본 버전 정보](Pauseable.ai/voice/provenance)를 함께 확인합니다.

저장소 전체에 적용되는 자체 `LICENSE`는 아직 없습니다. 이 README가 별도의 사용 허락을 부여하지 않으며, 외부 코드·데이터·음성 모델의 이용 및 재배포 조건은 각각 확인해야 합니다.
