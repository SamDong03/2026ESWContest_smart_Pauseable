# Pauseable.edge

<a id="pauseableedge"></a>

**Raspberry Pi의 센서 입력, Central 판단, 출입 카메라와 현장 음성·영상 출력을 담당합니다.**

[프로젝트](../README.md) · [AI](../Pauseable.ai/README.md) · [통신 규격](../Pauseable.contracts/README.md) · [장치 배포](../Pauseable.deploy/README.md)

[주요 기능](#주요-기능) · [폴더 구조](#폴더-구조) · [Central](#central-처리-과정) · [카메라](#출입-카메라) · [음성 모델](#음성-모델-교체)

<a id="주요-기능"></a>

## 주요 기능

| 구성 | 입력 | 처리·출력 |
| --- | --- | --- |
| `central/` | 반복행동·배회 AI의 MQTT 메시지 | 추론 검증, 실행 계획, 로컬 TTS와 보호자 사건 전송 |
| `mmwave-relay/` | ESP32의 Serial 센서 이벤트 | JSON 계약 검사, SSH 연결, Pi 5 FIFO 전달 |
| `camera/` | 가상 도어락 해제와 카메라 프레임 | 출입 전후 움직임 분석, 대표 사진 선택·업로드 |
| `voice-model/` | API에 게시된 개인화 음성 모델 | 파일 검증, 시험 합성, 모델 경로 교체 |
| `actions/` | 대상자별 선호 YouTube 목록 | 등록곡 선택, Pi 화면 또는 HA LG TV 재생 요청 |

<a id="폴더-구조"></a>

## 폴더 구조

전체 하위 폴더와 주요 실행·설정 파일을 표시했습니다.

```text
Pauseable.edge/
├── actions/                        # 안내 이후 선호 음악·화면 재생
│   ├── favorite-music/             # 대상자별 등록곡 조회와 재생 요청
│   │   ├── tests/
│   │   ├── LG_TV_SETUP_KO.md       # Home Assistant와 LG TV 연결 안내
│   │   ├── player.env.example      # API·대상자·재생 장치 설정
│   │   └── player.py               # 등록곡 선택·재생 방식 분기·재요청 간격 관리
│   └── youtube/                    # Atlas 화면 앱과 Chromium 제어
│       ├── files/
│       ├── include/
│       └── src/
├── camera/                         # 출입 전후 영상 버퍼와 대표 사진 업로드
│   ├── home-assistant/             # 가상 도어락 촬영 자동화
│   ├── camera.env.example          # 촬영 인증·API·장치 설정
│   ├── camera_buffer.py            # 움직임 분석·출입 구분·대표 사진 선택
│   └── Dockerfile                  # GStreamer 카메라 실행 환경
├── central/                        # Pi 5의 C++ 중앙 판단·실행 앱
│   ├── atlas/                      # Property Manager D-Bus 연결
│   │   ├── include/
│   │   └── src/
│   ├── config/                     # 엔티티 매핑과 실행 환경 예시
│   ├── core/                       # 추론 검증·Decision·Action Router
│   │   ├── include/
│   │   └── src/
│   ├── deploy/
│   │   ├── systemd/
│   │   └── wandering-voice/        # 배회 음성·시간대별 출력·가전 Bridge
│   │       ├── tests/
│   │       ├── comfort_bridge.py   # 가상 기기 상태와 TTS 연결
│   │       ├── styler_bridge.py    # 스타일러 상태와 출력 연결
│   │       ├── time-router.sh      # 시간대에 따른 출력 요청 분기
│   │       └── watch.sh            # Central 출력 로그 감시
│   ├── files/
│   ├── integration/                # MQTT·HTTP·Outbox·Piper·센서 연결
│   │   ├── include/
│   │   └── src/
│   ├── mmwave/                     # 원시 센서 관측 라이브러리 빌드
│   ├── mmwave-tools/               # 센서 계약·UDP·Archive 확인 도구
│   ├── scripts/
│   ├── src/
│   │   └── main.cpp                # 환경 로드와 수신·판단·출력 모듈 연결
│   ├── tests/
│   └── CMakeLists.txt              # C++ 앱·라이브러리·검사 빌드
├── mmwave-relay/                   # Serial 센서 이벤트의 SSH·FIFO 중계
│   ├── relay_serial.py             # 센서 줄 단위 입력과 이벤트 처리
│   └── relay_supervisor.py         # 계약 검사·연결 준비·재연결 관리
└── voice-model/                    # 개인화 ONNX 모델 검증과 활성화
    ├── voice-model.env.example     # API·대상자·Piper 경로 설정
    └── voice_model_updater.py      # 모델 조회·다운로드·시험 합성·교체
```

<a id="central-하위-구조"></a>

### ① Central 모듈 구성

| 경로 | 담당 내용 |
| --- | --- |
| `central/core` | 공통 추론 자료형, 메시지 검증, Decision 생성, Action Router |
| `central/integration` | MQTT 수신, HTTPS 전송, Outbox, Piper, 원시 센서 연결 |
| `central/atlas` | Atlas Property Manager와 D-Bus 통신 |
| `central/config` | HA 엔티티 매핑, 환경 예시, 빌드에 포함할 설정 |
| `central/deploy/systemd` | Central 실행·감시 서비스 |
| `central/deploy/wandering-voice` | 로그 감시, 배회 음성, 시간대별 출력, 가전 Bridge |
| `central/mmwave`, `central/mmwave-tools` | UDP 관측·Archive 라이브러리와 독립 실행 도구 |

<a id="central-구현과-설치-상세"></a>
<a id="central-app"></a>
<a id="central-수신과-설치-상세"></a>
<a id="central-처리-과정"></a>

## Central 처리 과정

```text
행동 AI → MQTT 수신 → 메시지 검증 → Decision → Action Router
                                           ├── 로컬 TTS·출력 Watcher
                                           └── 최종 사건 → Outbox → HTTPS API → 보호자 앱
```

<a id="수신검증중복-처리"></a>

### ① 메시지 수신과 검증

[MqttDecisionSubscriber.cpp](central/integration/src/MqttDecisionSubscriber.cpp)가 메시지를 받고, [BehaviorInference.cpp](central/core/src/BehaviorInference.cpp)가 JSON 필드와 Topic·출처·대상자·시각·사건 ID를 검사합니다. 반복행동은 `repetitive-ai`, 배회는 `wandering-ai` 출처로 처리합니다.

수신부는 사건 ID와 내용을 대조해 신규 입력, 중복 수신과 ID 충돌을 구분합니다. 처리 결과는 `MQTT_DECISION_REJECTED`, `MQTT_DECISION_DUPLICATE`, `MQTT_DECISION_CONFLICT` 등의 로그로 남습니다. 관측 부족이나 모델 오류로 전달된 `unknown`은 Router에서 `audit_only`로 기록합니다.

<a id="action-router"></a>

### ② 실행 계획과 재알림 간격

[ActionRouter.cpp](central/core/src/ActionRouter.cpp)는 출처별 활성 상태, 마지막 위험 단계, 마지막 알림 시각과 사건 ID를 저장합니다. 행동별 실행 정책이 활성화되어 있으면 첫 위험 발생, 위험 단계 상승과 재알림 간격 경과를 기준으로 실행 계획을 만듭니다. 실제 음성 출력과 API 전송은 아래의 TTS·Gateway 설정도 각각 활성화해야 합니다.

| 상황 | Router 처리 |
| --- | --- |
| 첫 `caution`·`danger` 판단 | 보호자 알림과 로컬 음성 실행 계획 생성 |
| 위험 단계 상승 | 상승한 위험도를 반영해 실행 계획 갱신 |
| 재알림 간격 경과 | 지속 중인 위험에 대한 새 안내·알림 허용 |
| 동일 사건 재시도 | 보호자 전송 계획을 유지하고 로컬 음성 중복을 억제 |
| 재알림 대기 중 | `suppressed`와 `cooldown_active` 기록 |
| 정상 회복 | 활성 상태 해제, 설정에 따른 회복 알림 처리 |

기본 재알림 간격은 반복행동 900초, 배회 300초입니다. 상태는 `PAUSEABLE_ACTION_STATE_PATH`에 보관해 재시작 후 복원합니다.

<a id="출력과-영속-전송"></a>
<a id="출력과-서버-전송"></a>

### ③ 최종 사건과 Outbox

[DecisionEvent.cpp](central/core/src/DecisionEvent.cpp)가 보호자에게 전달할 사건을 만들고, [DecisionOutbox.cpp](central/integration/src/DecisionOutbox.cpp)가 전송 대기 내용을 파일로 보관합니다. [DecisionGatewayClient.cpp](central/integration/src/DecisionGatewayClient.cpp)는 Device 인증으로 API에 전송합니다.

Outbox는 전송 성공, 재시도 예약, 영구 실패와 횟수 초과를 구분합니다. 재시도에는 서버의 `Retry-After` 또는 상한이 있는 지수형 대기 시간을 적용하고, 같은 사건 ID에 다른 내용이 들어오면 충돌로 처리합니다. 기본 대기 한도는 10,000건, 최대 전송 시도는 3회입니다.

### ④ 로컬 TTS와 실행 설정

[PiperTtsEngine.cpp](central/integration/src/PiperTtsEngine.cpp)는 Piper로 안내 WAV를 생성하고 출력 음량을 보정해 로컬 재생에 사용합니다. [watch.sh](central/deploy/wandering-voice/watch.sh)와 [time-router.sh](central/deploy/wandering-voice/time-router.sh)는 Central 로그를 확인하고 시간대별 음성·가전 출력 경로로 연결합니다.

| 환경변수 | 설정 내용 |
| --- | --- |
| `MQTT_HOST`, `MQTT_PORT` | Broker 주소·포트, 기본 `127.0.0.1:1883` |
| `PAUSEABLE_PATIENT_ID` | 메시지 검증과 API 전송에 사용할 대상자 ID |
| `REPETITIVE_ACTIONS_ENABLED=1` | 반복행동 실행 정책 활성화 |
| `WANDERING_ACTIONS_ENABLED=1` | 배회 실행 정책 활성화 |
| `AI_LOCAL_TTS_ENABLED=1` | AI 판단 이후 로컬 음성 출력 활성화 |
| `DECISION_GATEWAY_ENABLED=1` | 최종 사건의 API 전송 활성화 |
| `PAUSEABLE_DEVICE_TOKEN` | 장치의 API 인증값 |
| `PIPER_ROOT`, `TTS_OUTPUT_PATH` | Piper 설치 위치와 합성 WAV 경로 |
| `TTS_GAIN` | WAV 음량 보정 배율, 기본 `2.0` |

출력 대상과 문장은 [wandering-voice](central/deploy/wandering-voice)의 설정·메시지 파일에서 관리하고, Atlas 엔티티 연결은 [central/config](central/config)에서 설정합니다.

<a id="센서-릴레이와-카메라"></a>
<a id="mmwave-입력"></a>

## mmWave 입력

### ① Serial·SSH·FIFO 전달

[relay_serial.py](mmwave-relay/relay_serial.py)가 센서 이벤트를 줄 단위로 읽고, [relay_supervisor.py](mmwave-relay/relay_supervisor.py)가 형식 검사와 연결 상태를 관리합니다. Supervisor는 SSH로 Pi 5의 `/run/pauseable-wandering-input.fifo`를 열고 준비 응답 `PAUSEABLE_FIFO_READY`를 확인한 뒤 입력을 전달합니다.

기본 Serial 장치는 `/dev/ttyUSB0`, 속도는 230400 baud입니다. `--device`, `--baud`, `--host`로 실제 연결을 지정하며, Pi 5의 FIFO 입력은 [mmWave AI](../Pauseable.ai/mmwave)에서 구간별 배회 분석에 사용합니다. `simulate.py`는 센서 이벤트 재생과 전달 과정 확인에 사용합니다.

### ② Pi 5 UDP 관측

Central은 `MMWAVE_ENABLED=1`에서 UDP 5005 입력을 수신합니다. `MMWAVE_BIND`, `MMWAVE_PORT`, `MMWAVE_ALLOW_PEER`로 수신 주소·포트·허용 송신자를 설정하며, `MMWAVE_STALE_MS`와 `MMWAVE_SUMMARY_MS`로 입력 만료·요약 주기를 관리합니다. Archive 옵션은 관측 자료의 저장 주기·보관 용량·일수를 지정합니다.

센서 연결은 전송 방식에 맞춰 구성합니다. Serial 구성은 ESP32 → 중계 Pi → SSH/FIFO → Pi 5 분석기로 연결합니다. Wi-Fi 구성은 ESP32의 목적지와 Pi 5 UDP 수신·분석기 입력을 함께 설정하며, 전원 공급용 Pi는 ESP32의 USB 전원을 담당합니다.

<a id="카메라-트리거와-사진"></a>
<a id="카메라-트리거와-업로드"></a>
<a id="출입-카메라"></a>

## 출입 카메라

### ① 도어락에서 촬영까지

[HA 자동화](camera/home-assistant/pauseable_door_camera.yaml)는 가상 도어락이 `locked`에서 `unlocked`로 바뀌면 카메라 서버의 `POST /trigger`를 호출합니다. [camera_buffer.py](camera/camera_buffer.py)는 GStreamer로 카메라를 읽고 촬영 요청 시점 전후의 움직임과 사진을 수집합니다.

| 항목 | 현재 설정 |
| --- | --- |
| 카메라 입력 | 1280×720, 10 FPS |
| 움직임 분석 | 160×120, 5 FPS |
| 요청 전 버퍼 | 움직임·사진 각각 최근 20초 |
| 사진 이력 | 초당 2장 |
| 요청 후 수집 | 10초, 시작 후 0.5초부터 움직임 판단 |
| 움직임 기준 | 픽셀 차이 25 이상인 비율 2%, 3프레임 연속 |

### ② 출입 구분과 대표 사진

| 요청 전 움직임 | 요청 후 움직임 | 결과 | 사진 선택 기준 |
| --- | --- | --- | --- |
| 있음 | 없음 | `EXIT` | 요청 수신 0.75초 전과 가장 가까운 사진 |
| 없음 | 있음 | `RETURN` | 요청 수신 2.5초 후와 가장 가까운 사진 |
| 있음 | 있음 | `UNKNOWN_ACTIVE_BOTH` | 움직임 점수가 가장 높은 시점 주변 사진 |
| 없음 | 없음 | `NO_PASSAGE` | 전체 수집 구간의 움직임 점수 기준 사진 |

카메라는 `representative.jpg`와 판단·촬영 시각·선택 정책을 저장하고, Device 인증으로 API에 업로드합니다. API는 출입 사진을 보호자 앱의 기록 화면에 제공합니다.

### ③ 연결 설정

[camera.env.example](camera/camera.env.example)에 API 주소, Device Token, 장치·대상자 ID와 Trigger Token을 설정합니다. HA는 [secrets 예시](camera/home-assistant/secrets.yaml.example)의 촬영 URL·Authorization 값으로 카메라에 접근합니다. `GET /health`는 입력 버퍼와 최근 처리 상태를 확인하는 경로입니다.

<a id="음성-모델-교체"></a>

## 음성 모델 교체

[voice_model_updater.py](voice-model/voice_model_updater.py)는 API의 최신 모델 Manifest를 조회하고 아래 순서로 개인화 음성을 적용합니다.

1. 대상자·장치에 게시된 ONNX와 설정 파일 정보를 조회합니다.
2. 준비 디렉터리에 내려받으면서 SHA-256을 검사합니다.
3. Piper로 시험 문장을 합성하고 생성된 WAV를 검사합니다.
4. 모델 디렉터리를 확정하고 `models` 심볼릭 링크를 원자적으로 교체합니다.
5. 활성화 후 검사를 수행하고 적용 상태를 기록합니다. 오류 시 이전 모델 경로로 복원합니다.

| 구성 | 경로·설정 |
| --- | --- |
| Piper 런타임 | `PIPER_ROOT/bin/piper`, `lib`, `share/espeak-ng-data` |
| 모델 접근 | API 주소, Device Token, `PATIENT_ID`, `DEVICE_ID` |
| 활성 버전 기록 | 모델 릴리스 경로의 `current.json` |
| 정기 갱신 | `pauseable-voice-model-update.service`·`.timer` |

설정은 [voice-model.env.example](voice-model/voice-model.env.example), 호출 주기는 [서비스·타이머](voice-model)를 기준으로 준비합니다.

<a id="선호-음악-설치와-시험"></a>
<a id="선호-음악과-현장-출력"></a>

## 선호 음악과 화면 출력

### ① 등록곡 선택과 재생 요청

[player.py](actions/favorite-music/player.py)는 Device API에서 대상자의 현재 등록곡 중 선택된 YouTube 영상 ID를 받아 재생 장치로 전달합니다. 반복행동·배회 음성 안내 이후 비동기 작업으로 실행하며, `last-request.json`에 성공한 요청의 대상자·재생 방식·시각을 기록합니다.

`PAUSEABLE_MUSIC_COOLDOWN_SECONDS`의 기본값은 300초입니다. 대상자와 재생 방식이 같은 요청에 이 간격을 적용하고, 장치 전환 시 새 방식으로 요청할 수 있습니다.

### ② 재생 장치 선택

| 방식 | 설정 | 전달 과정 |
| --- | --- | --- |
| Pi 화면 | `PAUSEABLE_MUSIC_BACKEND=atlas` | 영상 ID → 요청 FIFO → Atlas Chromium |
| LG TV | `PAUSEABLE_MUSIC_BACKEND=lg_tv` | 영상 ID → HA `webostv.command` → TV YouTube 앱 |

Pi 방식은 [youtube-control.sh](actions/favorite-music/youtube-control.sh)와 Atlas 화면 앱을 연결합니다. LG TV 방식은 `HA_URL`, `HA_TOKEN`, `TV_ENTITY`와 TV 전원 켜기에 사용할 Wake-on-LAN 값을 준비합니다. 설치는 [install.sh](actions/favorite-music/install.sh), [환경 예시](actions/favorite-music/player.env.example), [LG TV 안내](actions/favorite-music/LG_TV_SETUP_KO.md)를 기준으로 진행합니다.

<a id="빌드와-검사"></a>

## 빌드와 검사

### ① Central 빌드 환경

Central은 C++17과 Atlas SDK를 사용합니다. [CMakeLists.txt](central/CMakeLists.txt)는 `sdbus-c++`, OpenSSL, Threads, Property Manager, systemd, amclient, alog, fmt를 연결합니다. `PAUSEABLE_BUILD_TESTS=ON`으로 공통 추론·Action Router·Outbox 검사 실행 파일을 함께 구성합니다.

### ② Python 모듈 검사

저장소 루트에서 실행합니다.

```sh
python -m unittest discover -s Pauseable.edge/mmwave-relay -p 'test_*.py' -v
python -m unittest discover -s Pauseable.edge/voice-model -p 'test_*.py' -v
python -m unittest discover -s Pauseable.edge/actions/favorite-music/tests -v
python -m unittest discover -s Pauseable.edge/camera -p 'test_*.py' -v
```

각 검사는 센서 계약·중계 상태, 모델 검증·복원, 등록곡·재생 요청, 대표 사진 선택을 확인합니다.

<a id="실기-점검과-복구-원칙"></a>
<a id="실기-점검과-보존-규칙"></a>
<a id="실기-확인"></a>

## 장치 연결 확인

| 연결 | 확인 항목 |
| --- | --- |
| 센서 → Pi 5 | Serial·UDP 입력, FIFO 전달, AI 구간 생성 |
| AI → Central | MQTT 사건 ID, 추론 검증, Router 승인 로그 |
| Central → 음성·가전 | TTS WAV·스피커 출력, 연결한 Watcher·Bridge의 엔티티 상태 |
| 도어락 → 카메라 → 앱 | 촬영 요청, 출입 구분, 대표 사진, 기록 화면 |
| Central → API → 앱 | Outbox 상태, API 저장, 동일 사건의 보호자 알림 |
| 선호 음악 | 대상자 목록 조회, 영상 ID, 선택한 화면·TV의 재생 |

설치 순서와 장치별 서비스는 [Deploy](../Pauseable.deploy/README.md)에서 확인합니다.
