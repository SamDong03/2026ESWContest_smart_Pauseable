# 앱에 등록한 노래 → Pi 화면·스피커 랜덤 재생

## 흐름과 범위

```text
앱에서 노래 추가/삭제 → Render의 대상자별 목록 저장
감지 → Central 승인(주의/위험, execute, speak=true)
  → 기존 반복행동/배회 가전·TTS 안내
  → 별도 favorite-music oneshot 작업 (비동기)
  → Device Bearer로 GET /api/device/patients/{patient_id}/favorite-songs/random
  → 검증한 video_id만 Pi의 FIFO로 전달
  → 기존 ATLAS Chromium 화면·스피커에서 YouTube 재생 요청
```

- 확정/승인되지 않은 센서 원시 이벤트나 억제된 중복 이벤트로는 재생하지 않습니다.
- 반복행동은 시간대에 관계없이 기존 가전/TTS 처리 **이후**에, 배회는 기존 출력 처리 이후에 요청합니다.
- 기존 낮 시간 반복행동의 고정 LG TV 영상 호출은 제거하고 Pi 재생으로 통일했습니다.
- 매 재생 요청마다 Render가 현재 등록 목록에서 무작위 선택합니다. 앱에서 삭제한 곡을 오래된 로컬 목록으로 다시 선택하지 않습니다.
- 기본 300초 동안 새 감지로 노래를 계속 다시 시작하지 않습니다. 설정으로 조정할 수 있습니다. 동시에 들어오는 요청도 한 작업으로 합쳐집니다.
- 빈 목록(404), 인증 오류, 응답 오류, 네트워크/플레이어 오류는 음악만 건너뜁니다. 다른 곡으로 임의 대체하지 않습니다.
- REST 알림, WebSocket, Web Push/FCM, 사진 업로드·인증·조회 코드는 변경하지 않았습니다.
- 이 작업은 가전/TTS 뒤의 추가 작업입니다. 안내 자체가 실패한 경우에도 감지 승인 이력은 기존대로 남고 음악 요청은 별도로 시도합니다.

## 장비 적용 (노트북에서 GitHub에 올리는 것만으로 Pi 파일은 바뀌지 않음)

1. Pi에 최신 브랜치/병합된 코드를 받습니다. 기존 장비의 `/data`, `/var/lib` 전체를 덮어쓰지 마세요.
2. 기존 `/var/lib/pauseable/ha.env`에 **장비용** `PAUSEABLE_DEVICE_TOKEN`이 설정되어 있어야 합니다. 앱/Worker 토큰을 사용하거나 토큰을 GitHub에 올리지 마세요.
3. 기존 `ha-ai-runner:review-20260908`, `pauseable-youtube:1` 이미지와 YouTube 화면·오디오 설정이 있어야 합니다. 설치 스크립트가 이미지를 내려받거나 빌드하지 않습니다.
4. **장비 조작/감지 시연을 잠시 멈춘 상태**에서 저장소 루트에서 다음을 실행합니다. 백업 경로가 출력됩니다.

```sh
sudo sh Pauseable.edge/actions/favorite-music/install.sh
```

ATLAS의 `/`가 읽기 전용이면 설치기는 변경 전에 중단합니다. 장비 관리자가 기존 설치 절차에 따라 잠시 쓰기 가능하게 만든 뒤 설치하고 원래 읽기 전용으로 돌려놓으세요. 스크립트는 루트 파일시스템 보안/마운트 설정을 바꾸지 않습니다.

5. `/data/pauseable/favorite-music/player.env`의 `PATIENT_ID`를 앱과 동일하게 설정합니다(현재 `byunwoojin`). `PAUSEABLE_API_BASE_URL`도 앱과 같은 Render여야 합니다. 예제는 실제 자격증명을 포함하지 않습니다. 파일은 root만 읽도록 유지합니다.
6. 앱에서 `설정 → 환자가 좋아하는 노래`에 **동영상 링크**를 한 개 이상 추가합니다. 보호자 앱 UI를 업데이트하는 것과 Pi 런타임 설치는 별개입니다. API 경로/요청 형식은 기존과 같으므로 서버 재배포는 필요 없습니다.
7. 실제 감지 전에 수동으로 음악 경로만 시험할 수 있습니다. 이 명령은 알림 이벤트를 만들거나 사진을 촬영하지 않습니다. **아래 명령을 실행하면 실제 장비 화면·스피커가 동작합니다.**

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

`REQUESTED`는 재생 명령 전송 확인이지 영상·소리가 실제 나왔다는 증거는 아닙니다. YouTube 광고, 네트워크, 로그인/연령 제한, 삭제된 영상, 브라우저 자동 재생 정책은 실제 화면·스피커에서 확인해야 합니다. 영상이 재생 가능하다고 API가 검증하는 기능은 아닙니다.

## 설정 / 중단 / 되돌리기

- `player.env`의 `PAUSEABLE_FAVORITE_MUSIC_ENABLED=0`으로 음악만 중단할 수 있습니다. 설정은 다음 요청 때 읽습니다. 감지·알림·사진·TTS에는 영향이 없습니다.
- `PAUSEABLE_MUSIC_COOLDOWN_SECONDS=300`은 성공적으로 Pi 컨트롤러에 전달한 요청 기준입니다. 시험 중 0으로 바꿀 수 있으나 연속 재생 재시작에 주의하세요.
- 이미 요청된 재생까지 멈추려면 작업을 먼저 중지한 뒤 기존 브라우저 서비스를 중지합니다.

```sh
sudo systemctl stop pauseable-favorite-music.service
sudo systemctl stop pauseable-youtube-browser.service
```

- 설치 전 파일은 출력된 `/data/pauseable/backups/favorite-music-...` 아래에 원래 절대 경로 구조로 보관됩니다. 되돌릴 때는 음악을 중단하고 해당 파일만 원래 위치에 복원한 뒤 `systemctl daemon-reload` 및 출력 watcher/YouTube controller만 재시작합니다. Central·Gateway·API·카메라는 재시작할 필요가 없습니다.
- 플레이어는 표준 라이브러리 Python만 사용합니다. 자동 테스트는 임시 디렉터리/모의 API/모의 플레이어만 사용하며 실제 장비를 켜지 않습니다.
