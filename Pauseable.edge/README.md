# 장치 실행과 Central

Pi의 센서 입력·실행 판단·로컬 출력·모델 교체를 담당합니다. **AI는 상황을 분석하고, Central은 메시지를 검사해 허용할 동작을 결정**합니다. API 전달은 로컬 출력과 별도 경로입니다.

[전체 프로젝트](../README.md) · [AI 분석](../Pauseable.ai/README.md) · [통신 계약](../Pauseable.contracts/README.md) · [배포](../Pauseable.deploy/README.md)

| 범주 | 실행 위치 | 소스·책임 |
| --- | --- | --- |
| [Central](#central-app) | Pi 5 / Atlas | `central/` · MQTT 검증, Action Router, API Outbox |
| [센서 중계](#센서-릴레이와-카메라) | Pi 3 | `mmwave-relay/` · Serial 검증·SSH/FIFO 중계 |
| [출입 사진](#카메라-트리거와-사진) | Pi 4 | `camera/` · 버퍼·대표 사진·업로드 |
| [음성 모델](#음성-모델-교체) | Pi 5 | `voice-model/` · 다운로드·검증·교체 |
| [선호 음악](#선호-음악-설치와-시험) | Pi 5 | `actions/` · API 곡 선택·FIFO·Chromium |

## Central App

### Central 구현과 설치 상세

![Central의 수신 검증과 실행 정책, 로컬 출력·영속 API 전송의 분리](../Pauseable.docs/assets/readme/central-routing.svg)

Central은 C++17 앱입니다. 반복행동·배회를 별도 MQTT Topic에서 받아 공통 내부 Decision으로 해석합니다. 잘못된 형식을 정상 JSON으로 변환하거나 AI 위험 점수를 바로 가전 명령으로 실행하지 않습니다.

### 수신·검증·중복 처리

| 순서 | 검사 | 실패·재전송 처리 | 구현 |
| --- | --- | --- | --- |
| MQTT 수신 | 두 Topic 구독 | 연결·수신 상태 기록 | [MqttDecisionSubscriber.cpp](central/integration/src/MqttDecisionSubscriber.cpp) |
| 입력 검증 | 필드·자료형·위험 단계·ID | 계약 위반 거절 | [BehaviorInference.cpp](central/core/src/BehaviorInference.cpp) |
| 출처·시각 | Topic/source, UTC | 기본 과거 300초·미래 30초 초과 거절 | 같은 검증기 |
| 사건 ID | ID와 내용 비교 | 동일 내용 중복 / 다른 내용 충돌 구분 | 같은 검증기 |
| 내부 결정 | 행동·위험·근거 해석 | Unknown은 Normal과 구분 | [DecisionEvent.cpp](central/core/src/DecisionEvent.cpp) |

Topic은 `pauseable/ai/repetitive/decision`, `pauseable/ai/wandering/decision`입니다. [메시지 계약](../Pauseable.contracts/README.md)에 출처·허용 상태·식별 규칙이 정의돼 있습니다.

### Action Router

[ActionRouter.cpp](central/core/src/ActionRouter.cpp)는 메시지 형식과 별개로 **실행 활성화·행동 종류·위험 단계·이전 상태·cooldown**을 검사합니다.

| 상황 | 정책 |
| --- | --- |
| 해당 행동의 실행 비활성 | 출력 차단 |
| Unknown | 감사 기록, 가전 동작으로 연결하지 않음 |
| Normal | 위험 활성 상태를 해제. 설정에 따라 회복 알림 |
| 첫 주의/위험·위험도 상승 | 실행 조건을 확인해 승인 |
| 같은 사건·짧은 시간의 반복 | 재실행 억제 또는 cooldown 적용 |

반복행동·배회 상태를 나눠 관리하고 설정한 파일 경로에 저장합니다. `cooldown`은 동일 계열 출력을 다시 허용하기까지의 시간입니다. 중복 검사, 실행 정책과 저장·복구는 서로 다른 책임입니다.

### 출력과 영속 전송

| 경로 | 처리 | 성공의 의미 |
| --- | --- | --- |
| 로컬 음성 | [PiperTtsEngine.cpp](central/integration/src/PiperTtsEngine.cpp) | 합성·재생 결과를 실제 스피커와 대조 |
| 가전·안내 연동 | [출력 서비스·설정](central/deploy) | 허용된 장치 요청과 실제 동작을 확인 |
| API Outbox | [DecisionOutbox.cpp](central/integration/src/DecisionOutbox.cpp) | 전송 대기 사건을 저장·복구·재시도 |
| API Gateway | [DecisionGatewayClient.cpp](central/integration/src/DecisionGatewayClient.cpp) | Device 인증으로 최종 사건 전송 |
| 선호 음악 | 별도 oneshot 작업 | 재생 요청과 실제 영상·소리를 구분 |

Outbox는 **API 사건의 영속 전송 대기함**입니다. API 접수는 스피커·가전·휴대폰 성공과 같지 않으며, Outbox가 모든 물리 동작의 정확히 한 번 실행을 보장하는 것은 아닙니다. 앱의 반복행동 알림 중지 역시 로컬 출력 중지와 다릅니다.

### 빌드와 검사

정식 앱은 [CMakeLists.txt](central/CMakeLists.txt)의 C++17·CMake·sdbus-c++·OpenSSL·Atlas 전용 라이브러리와 SDK가 필요합니다. `PAUSEABLE_BUILD_TESTS`를 켜도 SDK 의존성이 제거되지 않습니다. 앱 시작·구성은 [main.cpp](central/src/main.cpp), 메타데이터는 [appinfo.json](central/files/appinfo.json)에 있습니다.

**독립 mmWave 수신기 host 검사**는 아래와 같습니다. 저장소 루트에서 실행하며 Central 전체 TTS·D-Bus·가전 E2E와 다릅니다.

```sh
cmake -S Pauseable.edge/central/mmwave-tools -B build/mmwave-tools -DBUILD_TESTING=ON
cmake --build build/mmwave-tools --config Release
ctest --test-dir build/mmwave-tools -C Release --output-on-failure
```

[Central 회귀 소스](central/tests) · [MQTT 입력 시험](central/scripts/test_mqtt_intake.sh) · [배포 안내](../Pauseable.deploy/README.md)

MQTT 시험·서비스 시작은 실제 출력을 발생시킬 수 있으므로 시험 장치·설정에서 수행합니다. 소스 업데이트 → SDK 빌드 → `.ipk` 설치 → 환경·서비스 적용 → 실기 확인을 구분합니다.

## 센서 릴레이와 카메라

### mmWave 중계와 관측

[relay_supervisor.py](mmwave-relay/relay_supervisor.py)가 Serial 릴레이와 연결을 관리하고 [validate_event.py](mmwave-relay/validate_event.py)가 센서 계약을 확인합니다. 분석 입력은 **Pi 3 → SSH → Pi 5의 `/run/pauseable-wandering-input.fifo`**입니다. Serial/dialout 권한·SSH·FIFO reader 준비를 확인합니다.

선택적 UDP 복사는 Central의 관측·Archive에 사용합니다. Central의 `MMWAVE_ENABLED` 기본값은 `0`, 관측 port 기본값은 `5005`입니다. **UDP 관측 수신과 MQTT AI 판단 수신은 다르며**, 원시 관측은 Action Router에 직접 연결하지 않습니다.

### 카메라 트리거와 사진

[HA 트리거 설정](camera/home-assistant/pauseable_door_camera.yaml)이 HTTP POST로 Pi 4에 출입 시점을 알립니다. 현재 예시는 가상 도어락이므로 실제 엔티티에 맞춰 설정합니다. [camera_buffer.py](camera/camera_buffer.py)는 버퍼에서 대표 사진을 선택해 API에 업로드합니다.

| 단계 | 확인할 것 |
| --- | --- |
| 트리거 | HA 엔티티·상태·요청 인증 |
| 촬영 | 카메라 권한·버퍼·시간 |
| 업로드 | Device 인증·API·비공개 저장 |
| 앱 조회 | 같은 출입 사건의 App 인증 이미지 응답 |

[카메라 환경 예시](camera/camera.env.example) · [Dockerfile](camera/Dockerfile). 업로드 성공과 앱의 사진 조회 성공을 구분하며 원본·인증값은 공개하지 않습니다.

## 음성 모델 교체

![새 음성 모델의 무결성·설정·합성 검사와 활성화/실패 분기](../Pauseable.docs/assets/readme/model-release.svg)

[voice_model_updater.py](voice-model/voice_model_updater.py)가 API/R2의 모델을 내려받아 크기·SHA-256·Piper 설정·로컬 합성을 검사합니다. 통과한 모델만 활성화하고 실패 시 기존 모델을 유지합니다. 학습과 교체는 다른 프로그램입니다.

[환경 예시](voice-model/voice-model.env.example) · [GPU 학습](../Pauseable.ai/README.md#voice-학습과-운영-상세) · [보관·삭제 정책](../Pauseable.docs/voice/DATA_AND_ARTIFACTS_KO.md)

## 선호 음악 설치와 시험

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


## 실기 점검과 복구 원칙

1. 기존 모델·DB·서비스·환경 파일을 필요한 범위만 백업합니다.
2. 센서/HA 입력 → AI 결과 → MQTT → Central의 승인·억제 사유를 확인합니다.
3. TTS·가전·음악을 실제 장치에서 각각 확인합니다.
4. 같은 `event_id`로 Outbox·API 이력·휴대폰 표시를 대조합니다.
5. 중복·재시작·끊김·모델 검증 실패와 복구를 시험합니다.

[전체 배포 인계](../Pauseable.docs/DEPLOYMENT_HANDOFF.txt) · [HA 시연 절차](../Pauseable.docs/ha/DEMO_RUNBOOK_KO.md) · [기능별 코드 위치](../Pauseable.docs/SOURCE_MAP_KO.md#central-수신과-실행)
