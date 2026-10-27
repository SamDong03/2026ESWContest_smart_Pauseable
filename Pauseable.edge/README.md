# 장치 실행과 Central

이 폴더는 Pi에서 실행하는 Central, 센서 중계, 카메라, 음성 모델 교체와 음악 출력을 관리합니다. **행동 AI가 상황을 판단하면 Central이 실행 조건을 검사하고, 출력 프로그램이 실제 장치를 동작시킵니다.**

[전체 시스템](../README.md) · [AI 분석](../Pauseable.ai/README.md) · [메시지 규격](../Pauseable.contracts/README.md) · [장치 배포](../Pauseable.deploy/README.md)

| 범주 | 위치 | 실행 장소 |
| --- | --- | --- |
| Central | `central/` | Pi 5 / Atlas |
| mmWave 중계 | `mmwave-relay/` | Pi 3 |
| 출입 사진 | `camera/` | Pi 4 |
| 음성 모델 교체 | `voice-model/` | Pi 5 |
| 선호 음악 | `actions/favorite-music/` | Pi 5 |

<a id="central-app"></a>
<a id="central-구현과-설치-상세"></a>

## 1. Central: 판단 메시지를 받아 실행을 결정한다

Central은 C++17 앱입니다. 진입점은 [main.cpp](central/src/main.cpp), 앱 메타데이터는 [appinfo.json](central/files/appinfo.json)입니다. 반복행동과 배회는 서로 다른 MQTT Topic에서 받지만 내부에서는 공통 Decision 형식으로 처리합니다.

### 1.1 MQTT에서 판단을 받는다

[MqttDecisionSubscriber.cpp](central/integration/src/MqttDecisionSubscriber.cpp)가 반복행동과 배회 Topic을 구독합니다. 현재 경로는 QoS 1·retained=false를 요구합니다.

- `pauseable/ai/repetitive/decision`: `source=repetitive-ai`
- `pauseable/ai/wandering/decision`: `source=wandering-ai`

MQTT Broker는 두 AI의 결과를 전달하는 중간 서버입니다. 원시 센서 좌표와 가전 상태를 이 판단 Topic에 그대로 보내지는 않습니다.

<a id="수신검증중복-처리"></a>

### 1.2 형식·출처·시각·사건 ID를 검사한다

1. [BehaviorInference.cpp](central/core/src/BehaviorInference.cpp)가 JSON 필드·자료형·위험 단계·ID를 검사합니다.
2. Topic과 source, 대상자·장치와 UTC 시각을 확인합니다. 기본 시각 범위는 과거 300초·미래 30초입니다.
3. EventLedger가 사건 ID와 내용을 비교합니다. 같은 내용의 재전송은 무시하고, 같은 ID의 다른 내용은 충돌로 차단합니다.
4. 통과한 입력을 내부 Decision으로 바꿉니다. 관측 부족·오류인 Unknown은 Normal과 구분합니다.

EventLedger는 이미 처리한 입력을 기억하는 기록입니다. 다음 단계의 Action Router 상태와 API 전송 대기함은 각각 따로 저장합니다.

<a id="action-router"></a>

### 1.3 Action Router가 실행 조건을 확인한다

[ActionRouter.cpp](central/core/src/ActionRouter.cpp)는 반복행동·배회별 활성화 설정, 현재 위험 단계와 이전 상태를 확인합니다.

| 상황 | 처리 |
| --- | --- |
| 해당 행동의 실행 비활성 | 차단 |
| Unknown | 기록만 남김 |
| Normal | 위험 활성 상태 해제. 설정에 따라 회복 알림 |
| 첫 주의·위험 또는 위험 단계 상승 | 실행 허용 |
| 같은 단계가 이어지는 새 사건 | cooldown 경과 여부로 실행·억제 결정 |

`cooldown`은 같은 계열 출력을 다시 허용하기까지의 간격입니다. 기본값은 반복행동 900초, 배회 300초입니다. 상태를 파일에 저장해 재시작 후에도 이전 위험 단계와 마지막 알림 시각을 복원합니다.

입력 재전송은 앞 단계에서 제거합니다. 처리 도중 실패해 같은 사건을 다시 다룰 때는 Router가 알림 전송 재시도와 로컬 음성 중복 억제를 구분합니다.

<a id="출력과-영속-전송"></a>

### 1.4 로컬 출력과 API 전송을 나누어 처리한다

| 경로 | 다음 프로그램 | 역할 |
| --- | --- | --- |
| 로컬 TTS | [PiperTtsEngine.cpp](central/integration/src/PiperTtsEngine.cpp) | 승인된 문장의 합성·재생 |
| 가전·행동별 안내 | [반복행동 watcher](../Pauseable.ai/ha/deploy/repetitive-central-output-watch.sh), [배회 watcher](central/deploy/wandering-voice/watch.sh) | Central 승인 로그를 확인한 뒤 출력 서비스 실행 |
| 보호자 사건 | [DecisionOutbox.cpp](central/integration/src/DecisionOutbox.cpp) | 최종 사건의 보관·복구·전송 재시도 |
| API 통신 | [DecisionGatewayClient.cpp](central/integration/src/DecisionGatewayClient.cpp) | Device Token으로 최종 사건 POST |

Outbox는 **API에 보낼 사건을 디스크에 보관하는 대기함**입니다. 전송 실패를 재시도하지만 TTS·가전을 모두 다시 실행하는 큐는 아닙니다. API 접수와 실제 스피커·가전·휴대폰 출력도 각각 확인합니다.

가전 연동은 별도 watcher와 bridge를 사용하는 구성이 포함되어 있습니다. 현재 기본 C++ Router는 `controlAppliance`를 활성화하지 않으므로, 통신 규격에 `control_appliance`가 정의되어 있다는 사실만으로 C++에서 직접 가전 명령까지 실행한다고 설명하지 않습니다.

### 1.5 활성화 설정을 맞춘다

[main.cpp](central/src/main.cpp)의 기본값은 다음과 같습니다. 실제 설치 환경 파일이 값을 바꿀 수 있습니다.

| 설정 | 코드 기본값 | 의미 |
| --- | --- | --- |
| `MQTT_DECISIONS_ENABLED` | `true` | 판단 메시지 수신 |
| `REPETITIVE_ACTIONS_ENABLED` | `false` | 반복행동 실행 허용 |
| `WANDERING_ACTIONS_ENABLED` | `false` | 배회 실행 허용 |
| `AI_LOCAL_TTS_ENABLED` | `false` | C++ 로컬 TTS |
| `DECISION_GATEWAY_ENABLED` | `false` | Outbox·API 전달 |
| `MMWAVE_ENABLED` | `0` | 별도 원시 UDP 관측 |

환경 파일, Token, 출력 watcher 설치와 SDK 앱 설정을 함께 확인합니다. 앱 실행만으로 모든 출력이 켜지는 구성은 아닙니다.

<a id="빌드와-검사"></a>

### 1.6 빌드·설치·검사 순서

1. [CMakeLists.txt](central/CMakeLists.txt)의 C++17·CMake·sdbus-c++·OpenSSL과 Atlas SDK 전용 의존성을 준비합니다.
2. 대상 SDK에서 Central을 빌드하고 `.ipk`를 설치합니다.
3. MQTT·대상자·Token·상태 경로·출력 설정을 적용합니다.
4. [tests](central/tests)의 검증기·Router·Outbox 검사를 확인합니다.
5. 시험 환경에서 [MQTT 입력 검사](central/scripts/test_mqtt_intake.sh) 후 실제 TTS·가전·API를 대조합니다.

`PAUSEABLE_BUILD_TESTS`를 켜도 정식 앱의 SDK 의존성이 사라지지는 않습니다. 아래는 Central 전체가 아닌 **독립 mmWave 수신기**의 host 검사입니다. 저장소 루트에서 실행합니다.

```sh
cmake -S Pauseable.edge/central/mmwave-tools -B build/mmwave-tools -DBUILD_TESTING=ON
cmake --build build/mmwave-tools --config Release
ctest --test-dir build/mmwave-tools -C Release --output-on-failure
```

<a id="센서-릴레이와-카메라"></a>

## 2. 센서 중계: Pi 3의 입력을 Pi 5로 전달한다

1. [relay_supervisor.py](mmwave-relay/relay_supervisor.py)가 Serial 릴레이와 연결을 관리합니다.
2. [validate_event.py](mmwave-relay/validate_event.py)가 센서 메시지 형식을 검사합니다.
3. SSH로 Pi 5의 `/run/pauseable-wandering-input.fifo`에 전달합니다.
4. Pi 5의 Python 배회 분석기가 FIFO를 읽습니다.

Serial/dialout 권한, SSH 계정·키와 Pi 5 FIFO reader를 준비해야 합니다. 선택적 UDP 복사는 Central 관측·Archive용입니다. 기본 port는 5005이며, 이 원시 관측은 MQTT AI 판단이나 Action Router 입력과 다릅니다.

<a id="카메라-트리거와-사진"></a>

## 3. 출입 사진: 트리거 주변의 대표 사진을 보낸다

1. [HA 트리거 설정](camera/home-assistant/pauseable_door_camera.yaml)이 도어락 상태 변경을 HTTP POST로 Pi 4에 알립니다.
2. [camera_buffer.py](camera/camera_buffer.py)가 카메라 버퍼에서 출입 시점의 대표 사진을 선택합니다.
3. Device 인증으로 API에 사진을 업로드합니다.
4. 앱이 App 인증으로 비공개 이미지를 조회합니다.

예시 트리거는 가상 도어락이므로 실제 엔티티에 맞춰 바꿉니다. [camera.env.example](camera/camera.env.example)과 [Dockerfile](camera/Dockerfile)에서 카메라 권한·인증·시간·주소를 준비합니다. 촬영, 업로드, 앱 조회를 같은 출입 사건으로 대조합니다.

## 4. 행동별 출력: Central 승인 후 가전과 안내를 실행한다

watcher는 `CENTRAL_DECISION_ACCEPTED`와 `CENTRAL_ACTION_ROUTED` 로그를 연결해, 해당 행동의 주의·위험이고 `execute`·`speak=true`인 사건만 처리합니다. 사건 ID별 claim 디렉터리로 같은 출력의 반복 실행을 막습니다.

| 행동 | 현재 시간대 선택 규칙 | 구현 |
| --- | --- | --- |
| 반복행동 | 08~17시 `tv`, 나머지 `air_purifier` | [시간 Router](../Pauseable.ai/ha/deploy/repetitive-central-time-router.sh), [출력 서비스](../Pauseable.ai/ha/deploy) |
| 배회 | 08~13시 `water_purifier`, 14~17시 `tiiun`, 나머지 `styler` | [시간 Router](central/deploy/wandering-voice/time-router.sh), [watcher·bridge](central/deploy/wandering-voice) |

표의 시간은 각 Router가 사용하는 로컬 시각의 시(hour) 기준입니다. 실제 가전 엔티티·백엔드·명령과 활성화 여부는 설치 설정으로 정합니다. 기본 비활성 bridge는 건너뛴 상태를 기록합니다. 행동별 watcher와 C++ 직접 TTS 설정은 실제 배포 구성에 맞춰 중복 안내가 없는지 확인합니다.

<a id="음성-모델-교체"></a>

## 5. 음성 모델 교체: 검사 후 활성 모델을 바꾼다

[voice_model_updater.py](voice-model/voice_model_updater.py)의 처리 순서입니다.

1. API에서 대상자의 후보 모델 정보를 조회합니다.
2. 모델과 Piper 설정을 내려받고 크기·SHA-256을 대조합니다.
3. 설정 형식과 로컬 합성을 검사합니다.
4. 통과한 모델을 활성화하고 설치 상태를 보고합니다.
5. 실패하면 기존 모델을 유지합니다.

[voice-model.env.example](voice-model/voice-model.env.example)에서 Device 인증·대상자·Piper 경로를 설정합니다. 모델을 만드는 [GPU 학습](../Pauseable.ai/README.md#voice-학습과-운영-상세)과 Pi의 모델 교체는 별도 프로그램입니다.

<a id="선호-음악-설치와-시험"></a>

## 6. 선호 음악: 안내 후 현재 등록 목록에서 재생한다

### 6.1 재생 요청 순서

1. 보호자가 앱에서 YouTube 링크를 등록하거나 삭제합니다.
2. Central이 허용한 반복행동·배회 안내를 처리합니다.
3. 출력 watcher가 별도 favorite-music 작업을 요청합니다.
4. Device API가 현재 등록 목록에서 곡을 무작위 선택합니다.
5. 기본 `atlas` 모드에서는 검증한 `video_id`를 Pi FIFO로 보내 기존 ATLAS Chromium 화면·스피커에 재생을 요청합니다. `PAUSEABLE_MUSIC_BACKEND=lg_tv`이면 같은 ID를 HA/webOS TV 실행기에 전달합니다.

LG TV 경로의 설치·환경변수·검증 범위는 [LG_TV_SETUP_KO.md](actions/favorite-music/LG_TV_SETUP_KO.md)를 참고합니다. 설치기는 기존 TV 실행기를 함께 배치하며, 실제 TV 재생은 별도 실기 확인이 필요합니다.

모듈은 [actions/favorite-music](actions/favorite-music)에 있습니다. 기본 재요청 간격은 300초이며 동시에 들어온 요청도 합칩니다. 빈 목록·인증·네트워크·플레이어 오류이면 음악만 건너뜁니다. 보호자 알림·사진 경로와 다른 작업입니다.

### 6.2 장치에 설치한다

1. 기존 설정·서비스를 백업하고 시연 중인 장치 조작을 멈춥니다.
2. `/var/lib/pauseable/ha.env`의 Device Token, 기존 Docker 이미지와 YouTube 화면·오디오 환경을 준비합니다. 설치기는 이미지를 자동 빌드하거나 내려받지 않습니다.
3. 저장소 루트에서 설치합니다.

```sh
sudo sh Pauseable.edge/actions/favorite-music/install.sh
```

4. `/data/pauseable/favorite-music/player.env`의 API 주소·`PATIENT_ID`를 앱과 맞춥니다.
5. 앱에서 선호곡을 등록하고 아래 명령으로 실제 재생을 시험합니다.

```sh
sudo sh /data/pauseable/favorite-music/request.sh
journalctl -u pauseable-favorite-music.service -u pauseable-youtube-control.service -n 50 --no-pager
```

ATLAS의 읽기 전용 루트는 설치기가 임의로 해제하지 않습니다. 서비스는 실제 화면·스피커를 동작시키므로 시험 장치에서 실행합니다. `REQUESTED` 로그는 컨트롤러에 요청한 상태이며 광고·로그인·네트워크·영상 삭제·자동 재생 정책에 따른 실제 재생은 화면과 소리로 확인합니다.

### 6.3 중단하거나 복구한다

`player.env`의 `PAUSEABLE_FAVORITE_MUSIC_ENABLED=0`은 이후 음악 요청만 중단합니다. `PAUSEABLE_MUSIC_COOLDOWN_SECONDS` 기본값은 300이며, 시험 중 0으로 바꿨다면 복구합니다.

이미 요청한 재생도 멈추려면 해당 작업과 브라우저 서비스를 중지합니다.

```sh
sudo systemctl stop pauseable-favorite-music.service
sudo systemctl stop pauseable-youtube-browser.service
```

설치 전 파일은 설치기가 출력한 `/data/pauseable/backups/favorite-music-...`에 보관됩니다. 해당 파일만 복원하고 `systemctl daemon-reload` 후 출력 watcher·YouTube controller를 재시작합니다. Central·Gateway·API·카메라 전체를 다시 설치할 필요는 없습니다.

<a id="실기-점검과-복구-원칙"></a>

## 7. 설치 후 확인하는 순서

1. 기존 모델·DB·설정의 백업과 설치 버전을 확인합니다.
2. HA·센서 입력, AI 결과, MQTT 수신과 Central 승인·억제 사유를 확인합니다.
3. 같은 사건 ID로 로컬 출력과 Outbox·API 저장을 대조합니다.
4. TTS·가전·음악·휴대폰 알림·출입 사진을 실제 장치에서 각각 확인합니다.
5. 중복 메시지, 재시작, 연결 끊김과 모델 검증 실패 시의 복구를 시험합니다.

[전체 배포 인계](../Pauseable.deploy/README.md#배포-순서) · [HA 시연 절차](../Pauseable.apps/guardian/docs/REAL_DEVICE_ALERT_VERIFICATION.md)
