# Render 선호 영상 → Home Assistant → LG webOS TV

기존 ATLAS Chromium 출력은 기본값으로 유지합니다. `player.env`에서
`PAUSEABLE_MUSIC_BACKEND=lg_tv`를 선택하면 Render에서 조회·검증한 영상 ID를
기존 `Pauseable.ai/ha/src/play_lg_tv_youtube.py`의 `--video-id`로 전달합니다.
이 실행기는 HA `webostv.command` 서비스로 해당 TV의 YouTube 앱을 실행합니다.

## 설치와 설정

Pi에서 기존 `install.sh`를 실행하면 TV 실행기도 `/data/pauseable/favorite-music/`에
함께 설치됩니다. 설치기는 기존 YouTube controller를 재시작하므로 운영 중에는
적절한 작업 시간에 실행합니다. 이 변경 작업에서는 설치기를 실행하지 않았습니다.

`/data/pauseable/favorite-music/player.env`:

```dotenv
PAUSEABLE_MUSIC_BACKEND=lg_tv
TV_ENTITY=media_player.your_lg_tv
TV_BROADCAST_ADDRESS=255.255.255.255
```

기존 `/var/lib/pauseable/ha.env`에 실제 `HA_URL`, `HA_TOKEN`,
`PAUSEABLE_DEVICE_TOKEN`이 있어야 합니다. TV가 꺼져 있을 때 깨우려면 실제 `TV_MAC`도
설정합니다. 인증 정보와 실제 장비 주소는 저장소에 커밋하지 않습니다.
HA의 LG webOS 통합, TV 엔티티와 Wake-on-LAN 지원 여부를 먼저 확인합니다.

## 동작

승인된 안내 처리 → favorite-music 작업 → Render의 현재 목록에서 무작위 영상 조회
→ 영상 ID 검증 → HA/webOS 실행 요청. TV 경로는 ATLAS FIFO 없이도 동작합니다.
빈 목록·통신·TV 실행 오류 시 다른 곡이나 ATLAS로 임의 대체하지 않습니다.
기존 오류 처리에 따라 음악 작업만 종료하며, 실패한 실행은 재요청 대기시간을 소비하지 않습니다.

`FAVORITE_MUSIC_REQUESTED backend=lg_tv`는 실행기 완료를 의미하며 실제 화면의
재생을 보장하지 않습니다. 로그인·광고·자동재생 제한은 실제 TV에서 확인해야 합니다.
설정 후 `request.sh`를 수동 실행하면 실제 TV를 작동시킵니다.

## 검증 범위

`tests/test_lg_tv.py`는 가짜 Render 응답이 `--video-id`를 거쳐
HA `webostv.command`의 `contentId`까지 전달되는지 확인합니다.
네트워크·가전 호출은 모킹하며 실제 Pi/Render/TV 실증과 구분합니다.
