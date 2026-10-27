# ⚙️ Memolink 장치 실행과 Central

Raspberry Pi에서 실행하는 Central, 센서 중계, 카메라와 출력 모듈입니다. Central은 AI 메시지를 검증하고 실행 정책을 적용합니다. 각 장치 모듈은 승인된 음성·가전·음악 출력과 출입 사진 처리를 담당합니다.

**AI가 '어떤 상황인가'를 판단한다면, Central은 '지금 무엇을 실행해도 되는가'를 결정**합니다. 센서 릴레이·카메라·음성 모델 교체기는 각 장치의 역할을 담당하며, 아래 표에서 실행 위치와 담당 코드를 구분했습니다.

[전체 프로젝트](../README.md) · [AI 판단](../Pauseable.ai/README.md) · [배포 안내](../Pauseable.deploy/README.md)

[Central 상세](#central-구현과-설치-상세) · [기능별 코드](../Pauseable.docs/SOURCE_MAP_KO.md#central-수신과-실행) · [개발환경](../Pauseable.docs/DEVELOPMENT_ENVIRONMENT_KO.md)

## 구성

| 경로 | 장치 | 역할 |
| --- | --- | --- |
| 🧭 [Central App](#central-구현과-설치-상세) | Pi 5 / Atlas | MQTT 수신, 계약 검증, Action Router, API Gateway |
| 📡 [`mmwave-relay`](mmwave-relay) | Pi 3 | serial 입력 검증·중계·프로세스 관리 |
| 📷 [`camera`](camera) | Pi 4 | 카메라 버퍼·출입 이벤트 대표 사진·업로드 |
| 🔊 [`voice-model`](voice-model) | Pi 5 | ONNX 다운로드·검증·교체 |
| 📺 [`actions/youtube`](actions/youtube) | Pi 5 | Chromium·화면·오디오 재생 브리지 |
| 🎵 [`actions/favorite-music`](actions/favorite-music) | Pi 5 | 앱의 선호 음악 조회·검증·재생 요청 |

## Central App

![MQTT 입력의 검증·중복 제거·Action Router와 로컬 출력·Outbox 분기](../Pauseable.docs/assets/readme/central-routing.svg)

| 단계 | 담당 역할 | 이후 단계로 넘기지 않는 사례 |
| --- | --- | --- |
| Subscriber / Validator | JSON·Topic/source·시각·ID 확인 | 출처 불일치·오래된 사건·잘못된 필드 |
| Decision / Dedup | 내부 결정으로 변환, 중복·동일 ID 충돌 구분 | 이미 처리한 사건·같은 ID의 다른 내용 |
| Action Router | 행동별 활성화·위험도·cooldown 확인 | 실행 비활성·억제 중인 동작 |
| Local / Gateway | 허용한 출력 실행, API 전송·재시도 | 관측 부족을 가전 명령으로 바꾸지 않음 |

<details>
<summary><strong>Central 기능별 코드 진입점</strong></summary>

| 기능 | 파일 |
| --- | --- |
| 앱 시작·설정·구성 요소 연결 | [`src/main.cpp`](central/src/main.cpp) |
| MQTT 연결·구독 | [`MqttDecisionSubscriber.cpp`](central/integration/src/MqttDecisionSubscriber.cpp) |
| 입력·시각·출처 검증 | [`BehaviorInference.cpp`](central/core/src/BehaviorInference.cpp) |
| 내부 Decision과 API Event | [`DecisionEvent.cpp`](central/core/src/DecisionEvent.cpp) |
| 실행·억제 정책 | [`ActionRouter.cpp`](central/core/src/ActionRouter.cpp) |
| 재전송 대기 상태 | [`DecisionOutbox.cpp`](central/integration/src/DecisionOutbox.cpp) |
| API 전송 | [`DecisionGatewayClient.cpp`](central/integration/src/DecisionGatewayClient.cpp) |
| 로컬 음성 합성 | [`PiperTtsEngine.cpp`](central/integration/src/PiperTtsEngine.cpp) |

</details>

### 실행 정책과 재전송

`cooldown`은 같은 동작을 다시 허용하기까지 기다리는 시간입니다. `Outbox`는 API로 보내야 할 사건의 전송 대기함으로, 프로세스가 다시 시작돼도 대기 상태를 이어갈 수 있도록 저장합니다. 같은 메시지를 다시 받는 것과 실제 동작을 다시 실행하는 것은 구분합니다.

- 반복행동과 배회를 서로 다른 MQTT Topic에서 받고 `source` 일치 여부를 확인합니다.
- 기본적으로 300초보다 오래된 이벤트, 30초를 초과한 미래 이벤트는 거부합니다.
- `unknown`·잘못된 계약·실행 비활성 입력을 그대로 가전 제어에 연결하지 않습니다.
- 반복행동·배회의 활성화와 cooldown은 각각 설정합니다.
- Outbox는 API 전송 대기·재시도용 영속 상태입니다. 실제 TTS·가전 동작까지 보장하는 큐는 아닙니다.
- 최종 API 메시지와 중복 처리 계약은 [Contracts](../Pauseable.contracts/README.md)를 따릅니다.

<details>
<summary><strong>Central 빌드 환경과 독립 수신기 host 테스트</strong></summary>

정식 Central은 C++17·CMake와 Atlas/webOS SDK, `sdbus-c++`, 플랫폼 전용 라이브러리가 필요합니다. [`CMakeLists.txt`](central/CMakeLists.txt)에 의존성이 정의되어 있습니다. 일반 PC의 CMake만으로 정식 앱이나 `.ipk`까지 만들어지지는 않습니다.

독립 mmWave 수신기와 해당 host 테스트는 별도 C++ 도구입니다. C++17 toolchain과 CMake를 준비하고 **저장소 루트에서** 실행합니다.

```sh
cmake -S Pauseable.edge/central/mmwave-tools -B build/mmwave-tools -DBUILD_TESTING=ON
cmake --build build/mmwave-tools --config Release
ctest --test-dir build/mmwave-tools -C Release --output-on-failure
```

이는 Central 전체의 TTS·D-Bus·가전 E2E 시험이 아닙니다. Central host 테스트 소스는 [`central/tests`](central/tests)에 있습니다.

</details>

## 센서 릴레이와 카메라

| 파트 | 주요 파일 | 확인할 조건 |
| --- | --- | --- |
| mmWave 릴레이 | [`relay_supervisor.py`](mmwave-relay/relay_supervisor.py), [`validate_event.py`](mmwave-relay/validate_event.py) | serial 권한·센서 계약·Pi 5 주소·연결 복구 |
| Camera | [`camera_buffer.py`](camera/camera_buffer.py), [`Dockerfile`](camera/Dockerfile) | 카메라 권한·트리거 인증·대표 사진·업로드 인증 |

실제 주소와 토큰은 장치의 비공개 환경 파일에 둡니다. 카메라 설정은 [`camera.env.example`](camera/camera.env.example), HA 트리거는 [`camera/home-assistant`](camera/home-assistant)에 있습니다. 사진 업로드 성공과 앱에서 인증된 사진 조회 성공을 따로 확인합니다.

## 음성 모델 교체

![모델 다운로드·크기와 SHA-256 확인·설정과 로컬 합성 검사 후 교체, 실패 시 기존 모델 유지](../Pauseable.docs/assets/readme/model-release.svg)

[`voice_model_updater.py`](voice-model/voice_model_updater.py)는 API/R2에서 모델을 받아 크기·SHA-256·설정·로컬 합성 결과를 확인한 뒤 활성 모델을 교체합니다. 새 모델이 검증되지 않으면 기존 모델을 유지합니다.

환경 예시: [`voice-model.env.example`](voice-model/voice-model.env.example). 학습 원본과 보관·삭제 정책은 [Voice 데이터 정책](../Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md)을 따릅니다.

## 선호 음악과 출력 경로

![Central 승인 이후 선호 음악 작업·Device API 조회·Pi Player 실행으로 이어지는 경로](../Pauseable.docs/assets/readme/favorite-music.svg)

Central이 안내를 승인하면 기존 TTS·가전 처리 후 선호 음악 작업을 별도로 요청합니다. API가 현재 등록 목록에서 선택한 영상을 Pi 화면·스피커로 재생합니다. 빈 목록·인증·네트워크·Player 오류가 발생하면 음악만 건너뛰며, 기본 재요청 제한 시간은 300초입니다. 행동 알림의 cooldown과는 별도 설정입니다.

| 상태 | 의미 |
| --- | --- |
| Central 승인 | 해당 안내·동작을 실행 정책상 허용 |
| API 전달 완료 | 서버가 사건을 접수함. TTS·가전 전체 성공과는 다름 |
| Player 요청 | 재생 요청 단계. 실제 화면·소리는 별도 확인 |
| 음악 조회·재생 실패 | 음악만 건너뛰고 기존 안내 경로와 분리해 기록 |

설치·수동 시험·로그·복구 절차는 [선호 음악 안내](#선호-음악-설치와-시험)에 정리했습니다. Player 요청 후 실제 영상·음성 출력까지 확인합니다.

## 실기 점검 순서

1. 배포 전 기존 설정·모델·DB·서비스를 백업합니다.
2. 센서 입력과 AI 메시지를 확인합니다.
3. Central의 검증·허용·억제 사유를 확인합니다.
4. TTS·가전·음악 출력을 각각 실제 장치에서 확인합니다.
5. 같은 `event_id`로 Outbox·API 이력·휴대폰 표시를 대조합니다.

장치 환경과 서비스별 실행 순서는 [배포 인계](../Pauseable.docs/DEPLOYMENT_HANDOFF.txt), 시험 입력과 확인 항목은 [HA 시연 절차](../Pauseable.docs/ha/DEMO_RUNBOOK_KO.md)에 정리했습니다.

## Central 구현과 설치 상세

<details>
<summary><strong>수신부터 출력까지의 코드·SDK 빌드·호스트 검사·장치 적용</strong></summary>

소스 위치: `Pauseable.edge/central`

AI가 전송한 반복행동·배회 메시지를 받아 실행 여부를 결정하는 C++ 앱입니다. AI의 `risk` 값을 바로 가전 명령으로 사용하지 않고, 입력과 실행 조건을 검사합니다.

**Central은 모델을 학습하는 곳이 아니라 판단과 실행 사이를 관리하는 곳**입니다. 같은 사건이 다시 와도 중복 출력하지 않도록 확인하고, Action Router가 지금 허용할 동작을 결정합니다. 이후 로컬 안내·출력과 보호자 서버 전송으로 나뉩니다.

![Central 수신 검증·실행 정책·로컬 출력과 API 전송](../Pauseable.docs/assets/readme/central-routing.svg)

### 입력부터 출력까지

| 단계 | 구현 | 처리 |
| --- | --- | --- |
| MQTT 구독 | [MqttDecisionSubscriber.cpp](central/integration/src/MqttDecisionSubscriber.cpp) | 반복행동·배회 Topic 수신 |
| 입력 검증 | [BehaviorInference.cpp](central/core/src/BehaviorInference.cpp) | 필드·출처·시각·식별자·중복 확인 |
| 내부 결정 | [DecisionEvent.cpp](central/core/src/DecisionEvent.cpp) | 최종 Decision Event 형식 |
| Action Router | [ActionRouter.cpp](central/core/src/ActionRouter.cpp) | 행동별 활성화·위험 단계·cooldown |
| 로컬 출력 | [PiperTtsEngine.cpp](central/integration/src/PiperTtsEngine.cpp), [deploy](central/deploy) | 허용한 음성·가전 출력 연결 |
| API 전송 | [DecisionOutbox.cpp](central/integration/src/DecisionOutbox.cpp), [DecisionGatewayClient.cpp](central/integration/src/DecisionGatewayClient.cpp) | 영속 전송 대기와 재시도 |

기본 사건 시각 허용 범위는 과거 300초, 미래 30초입니다. Topic과 `source`가 다르거나 유효하지 않은 입력은 실행으로 전달하지 않습니다. Outbox는 API 전달을 재시도하는 상태이며, 실제 음성·가전 동작 완료를 보장하는 작업 큐와는 다릅니다.

| 용어 | 역할 |
| --- | --- |
| 📥 Subscriber | 두 AI Topic을 구독해 메시지 수신 |
| 🛂 Validator | 메시지의 필드·출처·시각·중복 확인 |
| 🧭 Action Router | 활성화·위험도·cooldown에 따라 출력 허용 또는 억제 |
| 📤 Outbox / Gateway | API 사건을 보관·전송·재시도 |

형식 검사 통과는 입력을 해석할 수 있다는 뜻이고, 실행 승인은 해당 출력이 정책상 허용됐다는 뜻입니다. 실제 장치 동작 성공은 그다음 확인 단계입니다.

### 빌드와 검사

정식 앱은 [CMakeLists.txt](central/CMakeLists.txt)의 C++17·sdbus-c++·OpenSSL·Atlas 라이브러리와 SDK 환경이 필요합니다. `PAUSEABLE_BUILD_TESTS`를 켜는 것만으로 일반 PC에서 Atlas 의존성이 제거되지는 않습니다.

독립 mmWave 수신기 도구의 host 검사만 수행하는 명령입니다. 저장소 루트에서 실행합니다.

```sh
cmake -S Pauseable.edge/central/mmwave-tools -B build/mmwave-tools -DBUILD_TESTING=ON
cmake --build build/mmwave-tools --config Release
ctest --test-dir build/mmwave-tools -C Release --output-on-failure
```

[tests](central/tests)의 Central 회귀 소스, [MQTT 입력 시험 스크립트](central/scripts/test_mqtt_intake.sh), [앱 메타데이터](central/files/appinfo.json)를 구분해 확인합니다. 실제 MQTT 입력 시험과 서비스 시작은 연결된 출력에 영향을 줄 수 있으므로 시험 장치와 설정에서 수행합니다.

### 장치 적용

소스 업데이트, SDK 빌드, `.ipk` 설치, 환경 파일과 서비스 적용, 실기 확인은 각각의 단계입니다. [배포 안내](../Pauseable.deploy/README.md)와 [배포 인계](../Pauseable.docs/DEPLOYMENT_HANDOFF.txt)를 따릅니다. 서버 접수 이후에는 TTS·가전·사진·휴대폰 표시를 같은 사건 ID로 대조합니다.

</details>

## 선호 음악 설치와 시험

<details>
<summary><strong>실행 조건·설치 명령·로그·음악 중단과 복구</strong></summary>

소스 위치: `Pauseable.edge/actions/favorite-music`

보호자 앱에 등록한 YouTube 동영상을 행동 안내 후 Pi 화면·스피커로 재생하는 모듈입니다. Central이 승인한 안내를 기준으로 별도 작업을 요청하고, API에서 현재 목록의 곡을 무작위로 선택합니다.

### 흐름과 범위

![Central 승인 후 현재 선호곡 조회와 Pi 재생 요청](../Pauseable.docs/assets/readme/favorite-music.svg)

<details>
<summary>실행 조건과 API·Player 연결</summary>

```text
앱에서 노래 추가/삭제 → Render의 대상자별 목록 저장
감지 → Central 승인(주의/위험, execute, speak=true)
  → 기존 반복행동/배회 가전·TTS 안내
  → 별도 favorite-music oneshot 작업 (비동기)
  → Device Bearer로 GET /api/device/patients/{patient_id}/favorite-songs/random
  → 검증한 video_id만 Pi의 FIFO로 전달
  → 기존 ATLAS Chromium 화면·스피커에서 YouTube 재생 요청
```

</details>

- 확정/승인되지 않은 센서 원시 이벤트나 억제된 중복 이벤트로는 재생하지 않습니다.
- 반복행동은 시간대에 관계없이 기존 가전/TTS 처리 **이후**에, 배회는 기존 출력 처리 이후에 요청합니다.
- 반복행동과 배회 안내 모두 Pi의 화면·스피커 재생 경로를 사용합니다.
- 매 재생 요청마다 Render가 현재 등록 목록에서 무작위 선택합니다. 앱에서 삭제한 곡을 오래된 로컬 목록으로 다시 선택하지 않습니다.
- 기본 300초 동안 새 감지로 노래를 계속 다시 시작하지 않습니다. 설정으로 조정할 수 있습니다. 동시에 들어오는 요청도 한 작업으로 합쳐집니다.
- 빈 목록(404), 인증 오류, 응답 오류, 네트워크/플레이어 오류는 음악만 건너뜁니다. 다른 곡으로 임의 대체하지 않습니다.
- 음악 요청은 REST 알림·WebSocket·Push·사진 처리와 별도 경로로 동작합니다.
- 음악은 가전·TTS 뒤에 별도로 요청합니다. 기존 안내가 실패해도 승인 이력은 유지하며, 음악 요청의 결과는 따로 기록합니다.

### 장치 설치

1. Pi에 적용할 코드 버전을 준비하고 기존 설정·서비스를 백업합니다. `/data`, `/var/lib` 전체가 아닌 필요한 파일만 설치합니다.
2. `/var/lib/pauseable/ha.env`에 장치용 `PAUSEABLE_DEVICE_TOKEN`을 설정합니다. App·Worker Token과 분리하고 비공개 파일로 관리합니다.
3. 기존 `ha-ai-runner:review-20260908`, `pauseable-youtube:1` 이미지와 YouTube 화면·오디오 설정이 있어야 합니다. 설치 스크립트가 이미지를 내려받거나 빌드하지 않습니다.
4. **장비 조작/감지 시연을 잠시 멈춘 상태**에서 저장소 루트에서 다음을 실행합니다. 백업 경로가 출력됩니다.

```sh
sudo sh Pauseable.edge/actions/favorite-music/install.sh
```

ATLAS의 `/`가 읽기 전용이면 설치기는 변경 전에 중단합니다. 장치 관리 절차에 따라 쓰기 권한을 준비하고 설치 후 원래 상태로 복구합니다. 설치기는 루트 파일시스템의 보안·마운트 설정을 변경하지 않습니다.

5. `/data/pauseable/favorite-music/player.env`의 `PATIENT_ID`와 `PAUSEABLE_API_BASE_URL`을 앱의 대상자·API 설정과 맞춥니다. 설정 파일은 root만 읽을 수 있도록 관리합니다.
6. 앱의 `설정 → 환자가 좋아하는 노래`에서 동영상 링크를 한 개 이상 등록합니다. API에 선호곡 저장·장치 조회 기능이 배포되어 있어야 합니다.
7. 다음 명령으로 음악 경로를 시험합니다. 연속 시험에서 재생 간격을 해제하려면 `PAUSEABLE_MUSIC_COOLDOWN_SECONDS=0`을 사용하고 종료 후 300으로 복구합니다. 기본값에서는 수동 요청 뒤 5분간 음악 재요청이 생략됩니다. 이 시험은 실제 화면·스피커를 동작시키며 알림 이벤트나 사진은 생성하지 않습니다.

```sh
sudo sh /data/pauseable/favorite-music/request.sh
journalctl -u pauseable-favorite-music.service -u pauseable-youtube-control.service -n 50 --no-pager
```

8. 이어서 실제 반복행동/배회를 발생시키고 기존 알림·사진 수신과 노래를 각각 확인합니다.

```sh
journalctl -u pauseable-repetitive-central-output.service -u pauseable-wandering-tts.service \
  -u pauseable-favorite-music.service -u pauseable-youtube-control.service -f
```

확인할 로그: `REPETITIVE_FAVORITE_MUSIC_REQUEST` 또는 `WANDERING_FAVORITE_MUSIC_REQUEST` → `FAVORITE_MUSIC_REQUESTED ... video_id=...` → `YOUTUBE_OPEN_REQUEST_SENT ...`.

`REQUESTED`는 Pi 컨트롤러에 재생 요청이 전달된 상태입니다. 실제 재생은 YouTube 광고, 네트워크, 로그인·연령 제한, 영상 삭제와 브라우저 자동 재생 정책의 영향을 받습니다. API는 영상의 재생 가능 여부까지 검사하지 않으므로 화면과 음성을 함께 확인합니다.

### 설정과 복구

- `player.env`의 `PAUSEABLE_FAVORITE_MUSIC_ENABLED=0`으로 음악만 중단할 수 있습니다. 설정은 다음 요청 때 읽습니다. 감지·알림·사진·TTS에는 영향이 없습니다.
- `PAUSEABLE_MUSIC_COOLDOWN_SECONDS=300`은 성공적으로 Pi 컨트롤러에 전달한 요청 기준입니다. 시험 중 0으로 바꿀 수 있으나 연속 재생 재시작에 주의하세요.
- 이미 요청된 재생까지 멈추려면 작업을 먼저 중지한 뒤 기존 브라우저 서비스를 중지합니다.

```sh
sudo systemctl stop pauseable-favorite-music.service
sudo systemctl stop pauseable-youtube-browser.service
```

- 설치 전 파일은 출력된 `/data/pauseable/backups/favorite-music-...` 아래에 원래 절대 경로 구조로 보관됩니다. 되돌릴 때는 음악을 중단하고 해당 파일만 원래 위치에 복원한 뒤 `systemctl daemon-reload` 및 출력 watcher/YouTube controller만 재시작합니다. Central·Gateway·API·카메라는 재시작할 필요가 없습니다.
- 플레이어는 표준 라이브러리 Python만 사용합니다. 자동 테스트는 임시 디렉터리/모의 API/모의 플레이어만 사용하며 실제 장비를 켜지 않습니다.

</details>
