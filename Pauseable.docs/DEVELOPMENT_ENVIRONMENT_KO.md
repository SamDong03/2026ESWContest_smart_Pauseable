# Memolink 개발환경

[전체 프로젝트](../README.md) · [기능별 코드 위치](SOURCE_MAP_KO.md) · [장치 배포](../Pauseable.deploy/README.md)

장치, Runtime, 라이브러리와 빌드 도구를 정리한 문서입니다. 아래 버전은 저장소의 Dockerfile·의존성 파일·CI에 선언된 기준입니다. 설치된 Pi·서버·앱의 버전은 배포 기록에서 별도로 관리합니다.

## 실행 환경

| 영역 | 장치·환경 | Runtime·도구 | 기준 파일 |
| --- | --- | --- | --- |
| HA 수집·분석 | Pi 5, Docker | Python 3.12 slim | [Dockerfile.pi](../Pauseable.ai/ha/Dockerfile.pi) |
| mmWave 분석 | Pi 5의 Python Runtime | NumPy·scikit-learn, JSON RF | [requirements.txt](../Pauseable.ai/mmwave/requirements.txt), [실행 구성](../Pauseable.deploy/mmwave-autostart/pi5) |
| Central | Pi 5 / Atlas | C++17, CMake 3.14 이상, sdbus-c++ 2.0, OpenSSL, Atlas 라이브러리 | [CMakeLists.txt](../Pauseable.edge/central/CMakeLists.txt) |
| 센서 릴레이 | Pi 3 | Python, serial, SSH | [릴레이 코드](../Pauseable.edge/mmwave-relay), [설치 설정](../Pauseable.deploy/mmwave-autostart/pi3) |
| 출입 사진 | Pi 4, Docker | 카메라 버퍼·인증 업로드 | [Dockerfile](../Pauseable.edge/camera/Dockerfile), [설정 예시](../Pauseable.edge/camera/camera.env.example) |
| API | 로컬 Python 또는 Render | Python 3.12 기준 CI, FastAPI·Uvicorn | [requirements.txt](../Pauseable.apps/api/requirements.txt), [CI](../.github/workflows/native-alert-checks.yml) |
| 보호자 앱 | Flutter Web·Android | Flutter 3.47.6, Android 빌드 JDK 17 | [pubspec.yaml](../Pauseable.apps/guardian/pubspec.yaml), [CI](../.github/workflows/native-alert-checks.yml) |
| Voice 학습 | NVIDIA GPU PC, Docker GPU | Python 3.11, Piper, PyTorch | [Dockerfile.train](../Pauseable.ai/voice/docker/Dockerfile.train), [Compose](../Pauseable.ai/voice/compose.yaml) |
| Voice 모델 적용 | Pi 5 | Piper 로컬 합성, ONNX·설정·해시 검사 | [Model Updater](../Pauseable.edge/voice-model/voice_model_updater.py) |

Central의 정식 빌드는 Atlas SDK 환경이 필요합니다. 독립 mmWave 수신기 도구의 host 빌드와 Central 전체 앱·`.ipk` 빌드를 구분합니다.

## HA 분석 라이브러리

| 라이브러리 | 선언 버전 | 용도 |
| --- | --- | --- |
| NumPy | 2.3.5 | 수치 배열 |
| pandas | 3.0.1 | 이벤트·시간 구간별 특징 처리 |
| scikit-learn | 1.7.2 | Isolation Forest, StandardScaler, MLP Autoencoder |
| SciPy | 1.16.3 | 수치 연산 의존성 |
| joblib | 1.5.2 | 학습 산출물 처리 |
| paho-mqtt | 2.1.0 | MQTT 전송 |
| jsonschema | 4.26.0 | 공통 메시지 검사 |

기준은 [HA requirements](../Pauseable.ai/ha/requirements.txt)입니다. HA Autoencoder는 scikit-learn의 MLP가 입력 특징을 복원하도록 학습하는 구현입니다. GPU에서 실행하는 Piper 음성 학습과는 환경·데이터·모델이 다릅니다.

## 통신과 저장

| 연결·저장 | 사용 방식 |
| --- | --- |
| HA → 분석기 | WebSocket `state_changed` 구독 |
| AI → Central | MQTT Broker와 `communication-v1` JSON |
| Central·장치 → API | HTTPS, 역할별 Device Token |
| API → 앱 | REST, WebSocket, FCM/Web Push |
| Pi 로컬 데이터 | CSV 이벤트·특징, SQLite 판정 이력, 모델·설정 파일 |
| 서버 파일 | 선택한 Storage Backend의 사진·녹음·모델·설정 |
| 운영 | Docker, systemd, 비공개 환경 파일과 영속 저장 경로 |

알림·사진·모델의 API 계약은 [통신 규격](../Pauseable.contracts/README.md), 서버 저장·인증 설정은 [앱/API 안내](../Pauseable.apps/README.md)에 있습니다.

## 로컬 개발 준비

Python 의존성은 HA·API·Voice별 가상환경으로 분리합니다. 서로 다른 `requirements`를 하나의 환경에 합쳐 설치하지 않습니다.

저장소 루트에서 HA 환경을 만드는 예시입니다.

```sh
python -m venv .venv-ha
```

Linux / macOS:

```sh
. .venv-ha/bin/activate
python -m pip install -r Pauseable.ai/ha/requirements.txt
```

Windows PowerShell:

```powershell
.\.venv-ha\Scripts\Activate.ps1
python -m pip install -r Pauseable.ai/ha/requirements.txt
```

이후 [HA 로컬 검사](../Pauseable.ai/README.md#로컬-검사)를 실행합니다. API·Flutter는 [로컬 앱 실행](../Pauseable.apps/README.md), Voice는 [Worker 설치](voice/OPERATIONS_KO.md), Central은 [빌드 구분](../Pauseable.edge/README.md#빌드와-검사)을 따릅니다.

## 개인 설정 관리

실제 Token·HA 주소·대상자 설정·원본 녹음·개인 모델은 버전 관리에서 제외합니다. App·Device·Worker Token을 구분하고, 개발용 예시 Token을 운영 환경에 적용하지 않습니다. 모델·이력·Outbox·사진 저장 경로는 장치와 서버의 영속 저장 설정에 연결합니다.
