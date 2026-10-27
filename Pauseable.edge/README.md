# Pauseable.edge

<a id="central-구현과-설치-상세"></a>
<a id="실기-점검과-복구-원칙"></a>
<a id="출력과-영속-전송"></a>
<a id="카메라-트리거와-사진"></a>

**Pi에서 동작하는 Central, 센서 중계, 카메라와 음성·음악 출력 모듈입니다.**

[프로젝트](../README.md) · [AI](../Pauseable.ai/README.md) · [통신 규격](../Pauseable.contracts/README.md) · [장치 배포](../Pauseable.deploy/README.md)

## 주요 기능

| 구성 | 역할 |
| --- | --- |
| `central/` | AI 메시지 수신·검증·실행 정책·최종 사건 전송 |
| `mmwave-relay/` | Serial 원시 센서 계약 검사·SSH/FIFO 중계 |
| `camera/` | 출입 시점 전후의 카메라 버퍼·대표 사진 업로드 |
| `voice-model/` | 게시된 개인화 모델 다운로드·검증·활성화 |
| `actions/` | 안내 이후 선호 음악 조회·Pi 화면 재생 요청 |

## 폴더 구조

```text
Pauseable.edge/
├── actions/ — 안내 이후 실행하는 음악·화면 출력
│   ├── favorite-music/ — 앱 등록곡 조회·선택·비동기 재생 요청
│   │   └── tests/
│   └── youtube/ — Atlas 화면 앱·Chromium·YouTube 제어
│       ├── files/ — Atlas 앱 등록 정보
│       ├── include/ — 공개 헤더와 연결 인터페이스
│       └── src/ — 구현 소스
├── camera/ — 카메라 버퍼·대표 사진 선택·업로드
│   └── home-assistant/ — 가상 도어락과 촬영 HTTP 트리거
├── central/ — Atlas C++ 중앙 판단·실행 앱
│   ├── atlas/ — Atlas Property Manager D-Bus 연결
│   │   ├── include/ — 공개 헤더와 연결 인터페이스
│   │   └── src/ — 구현 소스
│   ├── config/ — 환경·엔티티·빌드 설정
│   ├── core/ — 추론 검증·판정·Action Router
│   │   ├── include/ — 공개 헤더와 연결 인터페이스
│   │   └── src/ — 구현 소스
│   ├── deploy/ — 설치·서비스 설정
│   │   ├── systemd/ — 서비스·타이머 Unit
│   │   └── wandering-voice/ — 배회 TTS·시간대 라우팅·가전 Bridge
│   │       └── tests/
│   ├── files/ — Atlas 앱 등록 정보
│   ├── integration/ — MQTT·API·Outbox·Piper·원시 센서 연결
│   │   ├── include/ — 공개 헤더와 연결 인터페이스
│   │   └── src/ — 구현 소스
│   ├── mmwave/ — 원시 센서 관측 라이브러리 빌드 구성
│   ├── mmwave-tools/ — 센서 계약·Archive 독립 실행 도구
│   ├── scripts/ — 전처리·실행·출력 보조 스크립트
│   ├── src/ — 구현 소스
│   └── tests/
├── mmwave-relay/ — Serial 계약 검사·SSH/FIFO 전달·시뮬레이션
└── voice-model/ — ONNX 모델 다운로드·검증·활성화
```

### Central 하위 구조

| 경로 | 담당 내용 |
| --- | --- |
| `central/core/include`, `core/src` | 공통 추론·판정·Action Router |
| `central/integration/include`, `integration/src` | MQTT·HTTP·Outbox·Piper·mmWave 연결 |
| `central/atlas/include`, `atlas/src` | Atlas Property Manager와 D-Bus |
| `central/src/main.cpp` | 구성 로드와 모듈 실행 연결 |
| `central/config` | 엔티티·환경 예시·빌드 시 포함 설정 |
| `central/files` | Atlas 앱 등록 정보 |
| `central/deploy/systemd` | Central 실행 확인·Watchdog |
| `central/deploy/wandering-voice` | 배회 음성·시간대 라우팅·가전 Bridge |
| `central/mmwave`, `mmwave-tools` | 원시 센서 관측과 독립 검사 도구 |
| `central/tests` | 계약·Router·Outbox·센서·TTS 회귀 검사 |

<a id="central-app"></a>
<a id="central-수신과-설치-상세"></a>
<a id="수신검증중복-처리"></a>
<a id="action-router"></a>
<a id="출력과-서버-전송"></a>

## Central 처리 과정

```text
행동 AI MQTT → JSON·Topic·출처·시각·ID 검사 → 내부 Decision
→ Action Router → 허용한 로컬 TTS·출력 Watcher
                └→ 최종 사건 → Outbox → HTTPS API
```

| 처리 | 주요 코드 |
| --- | --- |
| 추론 검증 | [BehaviorInference.cpp](central/core/src/BehaviorInference.cpp) |
| 실행 정책 | [ActionRouter.cpp](central/core/src/ActionRouter.cpp) |
| 최종 사건 생성 | [DecisionEvent.cpp](central/core/src/DecisionEvent.cpp) |
| MQTT 수신 | [MqttDecisionSubscriber.cpp](central/integration/src/MqttDecisionSubscriber.cpp) |
| API 전송·재시도 | [DecisionGatewayClient.cpp](central/integration/src/DecisionGatewayClient.cpp), [DecisionOutbox.cpp](central/integration/src/DecisionOutbox.cpp) |
| 로컬 음성 | [PiperTtsEngine.cpp](central/integration/src/PiperTtsEngine.cpp) |

Router는 기능 활성화, 위험 단계, 상태 전환과 재실행 간격을 확인합니다. `unknown`이나 잘못된 입력을 정상 판단으로 바꾸지 않습니다. Outbox는 보호자 API 사건을 재전송하는 대기함이며 물리 동작 전체의 재실행 큐가 아닙니다.

C++의 기본 `controlAppliance`는 비활성입니다. 현장 가전 출력은 별도 Watcher·Bridge의 설정과 실행 결과를 확인합니다. 반복행동·배회 실행, 로컬 TTS, Gateway는 기본적으로 꺼진 설정이 있으므로 앱 실행만으로 모두 활성화됐다고 보지 않습니다.

<a id="센서-릴레이와-카메라"></a>

## mmWave 입력

[relay_serial.py](mmwave-relay/relay_serial.py)가 줄 단위 센서 이벤트를 읽고, [relay_supervisor.py](mmwave-relay/relay_supervisor.py)가 검사·연결·전달을 관리합니다. 저장소의 Serial 경로는 Pi 5 FIFO와 배회 분석기에 연결됩니다. `simulate.py`와 관련 테스트는 장비 없이 계약·중계 조건을 확인하는 용도입니다.

Central의 UDP 5005 원시 관측은 `MMWAVE_ENABLED=1`로 켜며 코드 기본값은 `0`입니다. 원시 관측·Archive와 행동 AI의 MQTT 판단은 다른 입력입니다. ESP32를 Wi-Fi로 직접 연결할 때는 펌웨어와 AI로 이어지는 전달 경로를 함께 확인합니다. 전원만 공급하는 Pi에는 데이터 중계 역할이 없습니다.

<a id="카메라-트리거와-업로드"></a>

## 출입 카메라

1. [HA 설정](camera/home-assistant/pauseable_door_camera.yaml)이 가상 도어락의 잠금 해제를 관찰합니다.
2. 인증된 HTTP `POST /trigger`를 카메라 서버에 보냅니다.
3. [camera_buffer.py](camera/camera_buffer.py)가 버퍼에서 대표 사진을 선택합니다.
4. Device 인증으로 API에 업로드하고 보호자 앱에서 조회합니다.

카메라·트리거 주소·인증·출력 경로는 [camera.env.example](camera/camera.env.example)과 [HA secrets 예시](camera/home-assistant/secrets.yaml.example)를 기준으로 실제 장치에 설정합니다. 현재 커밋의 HA 예시는 URL 설정 방식이므로 다른 장치에서 적용한 자동 발견 구성이 저장소에도 들어 있다고 가정하지 않습니다.

HA→카메라의 Trigger Token과 카메라→API의 Device Token은 다른 인증값입니다. 각각 실제 설정과 맞춥니다.

<a id="음성-모델-교체"></a>

## 음성 모델 교체

[voice_model_updater.py](voice-model/voice_model_updater.py)는 모델 Manifest를 조회해 ONNX·설정 파일을 내려받고 크기·SHA-256·형식·로컬 시험 합성을 검사합니다. 통과한 후보만 활성화하고 실패하면 기존 모델을 유지합니다. [서비스·타이머](voice-model)는 갱신 주기를 담당합니다.

장치용 Piper 실행 파일과 기존 개인화 모델은 별도로 준비합니다. 모델을 다운로드했다는 사실과 실제 스피커로 안내가 출력된 결과는 각각 확인합니다.

<a id="선호-음악-설치와-시험"></a>

## 선호 음악과 현장 출력

`actions/favorite-music/player.py`는 대상자의 현재 YouTube 목록을 Device API로 조회해 임의의 등록곡을 선택하고 Pi 화면·플레이어에 전달합니다. 반복행동·배회 안내 이후 별도 비동기 작업으로 요청하며 기본 재요청 제한은 300초입니다. 빈 목록·인증·네트워크·플레이어 실패 시 음악 요청을 생략합니다.

| 재생 방식 | 설정 | 전달 경로 |
| --- | --- | --- |
| Pi 화면·기본값 | `PAUSEABLE_MUSIC_BACKEND=atlas` | 검증한 영상 ID → FIFO → ATLAS Chromium |
| LG TV | `PAUSEABLE_MUSIC_BACKEND=lg_tv` | 동일 영상 ID → HA `webostv.command` → TV YouTube 앱 |

LG TV 방식은 ATLAS FIFO 없이 동작하며 HA 주소·Token·TV 엔티티와 필요 시 Wake-on-LAN 설정을 사용합니다. [LG TV 연결 안내](actions/favorite-music/LG_TV_SETUP_KO.md)를 따르고 실제 TV를 시험합니다. 실패 시 다른 출력 방식이나 곡으로 임의 대체하지 않습니다.

[install.sh](actions/favorite-music/install.sh), [환경 예시](actions/favorite-music/player.env.example)와 [youtube-control.sh](actions/favorite-music/youtube-control.sh)를 함께 준비합니다. 재생 요청 성공과 실제 YouTube 화면·스피커 출력은 구분합니다. 광고·로그인·자동 재생 정책도 실기에서 확인합니다.

<a id="빌드와-검사"></a>

## 빌드와 검사

| 항목 | 준비·검사 |
| --- | --- |
| 정식 Central | C++17·Atlas SDK·sdbus-c++·OpenSSL·Property Manager 등 [CMake 의존성](central/CMakeLists.txt) |
| Central 회귀 | `central/tests`, CMake의 `PAUSEABLE_BUILD_TESTS` 옵션 |
| 센서 계약 | `python -m unittest discover -s Pauseable.edge/mmwave-relay -p 'test_*.py' -v` |
| 모델 교체 | `python -m unittest discover -s Pauseable.edge/voice-model -p 'test_*.py' -v` |
| 음악 처리 | `python -m unittest discover -s Pauseable.edge/actions/favorite-music/tests -v` |

Python 명령은 저장소 루트 기준입니다. 일반 PC CMake만으로 Atlas 전용 라이브러리까지 준비되지는 않습니다. 실제 설치는 [Deploy](../Pauseable.deploy/README.md), 환경은 [central/config](central/config)를 기준으로 합니다.

<a id="실기-점검과-보존-규칙"></a>

## 실기 확인

입력·계약 검증·Router 승인·출력 로그·API·앱을 같은 사건으로 대조합니다. 가전 Bridge가 있다는 이유만으로 디스플레이·공기청정기·정수기 등 실제 장치가 연결된 것은 아닙니다. 연결한 엔티티와 출력 경로별로 시험하고 기존 모델·DB·Token을 보존합니다.
