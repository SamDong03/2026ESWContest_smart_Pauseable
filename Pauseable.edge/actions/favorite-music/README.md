# 선호 음악 재생

보호자 앱에 등록한 YouTube 동영상을 행동 안내 후 Pi 화면·스피커로 재생하는 모듈입니다. Central이 승인한 안내를 기준으로 별도 작업을 요청하고, API에서 현재 목록의 곡을 무작위로 선택합니다.

## 흐름과 범위

![Central 승인 후 현재 선호곡 조회와 Pi 재생 요청](../../../Pauseable.docs/assets/readme/favorite-music.svg)

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

## 장치 설치

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

## 설정과 복구

- `player.env`의 `PAUSEABLE_FAVORITE_MUSIC_ENABLED=0`으로 음악만 중단할 수 있습니다. 설정은 다음 요청 때 읽습니다. 감지·알림·사진·TTS에는 영향이 없습니다.
- `PAUSEABLE_MUSIC_COOLDOWN_SECONDS=300`은 성공적으로 Pi 컨트롤러에 전달한 요청 기준입니다. 시험 중 0으로 바꿀 수 있으나 연속 재생 재시작에 주의하세요.
- 이미 요청된 재생까지 멈추려면 작업을 먼저 중지한 뒤 기존 브라우저 서비스를 중지합니다.

```sh
sudo systemctl stop pauseable-favorite-music.service
sudo systemctl stop pauseable-youtube-browser.service
```

- 설치 전 파일은 출력된 `/data/pauseable/backups/favorite-music-...` 아래에 원래 절대 경로 구조로 보관됩니다. 되돌릴 때는 음악을 중단하고 해당 파일만 원래 위치에 복원한 뒤 `systemctl daemon-reload` 및 출력 watcher/YouTube controller만 재시작합니다. Central·Gateway·API·카메라는 재시작할 필요가 없습니다.
- 플레이어는 표준 라이브러리 Python만 사용합니다. 자동 테스트는 임시 디렉터리/모의 API/모의 플레이어만 사용하며 실제 장비를 켜지 않습니다.
