# 앱 거주 지역을 날씨 조명 모듈에 적용하기

보호자 앱에 저장한 환자 거주 지역을 기존 날씨·조명 프로그램이 사용하도록 설정합니다. 서버 코드의 main 반영과 Render 배포가 먼저 완료되어야 하며, Pi 또는 실행 컴퓨터에도 새 `weather_api.py`와 아래 환경 설정을 적용해야 합니다. GitHub 업데이트만으로 이미 실행 중인 장비 파일이 바뀌지는 않습니다.

## 연결 방식

1. 앱은 App Token으로 `PUT /api/patients/{patient_id}/home-environment`에 지역 코드를 저장합니다.
2. Render는 기존 R2 저장소를 사용하고 표준 기상청 격자를 반환합니다.
3. 날씨·조명 모듈은 Device Token으로 `GET /api/device/patients/{patient_id}/home-environment`를 읽습니다.
4. 모듈은 응답의 `nx`, `ny`로 기상청을 조회하고 기존 HA 밝기·색온도 규칙을 적용합니다.

새 조회 경로는 읽기 전용이며 기존 App/Worker 토큰으로는 접근할 수 없습니다. KMA와 HA 키는 기존 장비에 그대로 두며 Render나 Flutter에 추가하지 않습니다. 기존 알림·사진·음성 API 및 인증값은 바꾸지 않습니다.

## 장비 환경 설정

`render-location.env.example`을 참고해 장비에 비공개 `render-location.env`를 만듭니다. 이미 같은 파일이 있으면 덮어쓰지 말고 필요한 항목만 편집합니다.

```dotenv
WEATHER_LOCATION_SOURCE=render
PAUSEABLE_API_BASE_URL=https://pauseable-api.onrender.com
PATIENT_ID=byunwoojin
PAUSEABLE_DEVICE_TOKEN=
```

빈 토큰 칸에는 **Render의 기존 `PAUSEABLE_DEVICE_TOKEN`과 동일한 값**을 장비의 파일 편집기로 입력합니다. App Token이나 Worker Token을 넣으면 안 됩니다. 키를 채팅·GitHub·셸 명령행에 붙여 넣지 않고 파일 권한은 소유자만 읽도록 `600`으로 제한합니다. `config.json`의 기존 KMA/HA 설정과 `location_config.json`은 삭제하지 않습니다.

기존 설정에 `WEATHER_LOCATION_SOURCE`가 없으면 `legacy` 모드로 동작하므로 잘 되던 장비의 위치 설정이 갑자기 바뀌지 않습니다. `render` 모드는 앱 지역을 우선하며, 지역 조회 실패·대상자 불일치·잘못된 격자·지역 미설정 시 그 회차의 조명 변경을 중단합니다. 이전 로컬 지역으로 몰래 대체하거나 조명 전원을 강제로 끄지는 않습니다. 통신이 복구되면 다음 실행 때 다시 읽습니다.

## ATLAS Pi5에 적용

저장소에 기록된 배포 경로 기준입니다. `systemctl cat pauseable-weather-light.service`로 현재 장비의 실행 파일·이미지·유닛 위치를 먼저 확인합니다. 아래와 다르면 조원의 현재 배포 경로에 맞게 적용하고 기존 실행 옵션은 보존합니다. root SSH 셸에서는 `sudo`를 생략합니다.

최신 저장소 루트에서 기존 파일을 백업한 뒤 새 프로그램과 유닛을 복사합니다. 백업은 `-n`으로 기존 백업을 덮어쓰지 않습니다.

```bash
sudo cp -n /var/lib/pauseable/weather-light-control/weather_api.py /var/lib/pauseable/weather-light-control/weather_api.py.before-render
sudo cp -n /data/share/usr/lib/systemd/system/pauseable-weather-light.service /data/share/usr/lib/systemd/system/pauseable-weather-light.service.before-render
sudo install -m 644 Pauseable.integrations/home-assistant/weather-light-control/weather_api.py /var/lib/pauseable/weather-light-control/weather_api.py
sudo install -m 644 Pauseable.integrations/home-assistant/weather-light-control/deploy/systemd/pauseable-weather-light.service /data/share/usr/lib/systemd/system/pauseable-weather-light.service
```

`/var/lib/pauseable/weather-light-control/render-location.env`를 위 내용으로 만들고 토큰을 입력한 뒤 권한을 제한합니다. 유닛은 이 환경파일을 읽어 Docker에 변수 이름으로 전달하므로 토큰 값을 실행 명령에 넣을 필요가 없습니다.

```bash
sudo chmod 600 /var/lib/pauseable/weather-light-control/render-location.env
sudo systemctl daemon-reload
```

먼저 **조명 명령을 보내지 않는 조회 시험**을 실행합니다. 기존 KMA/HA 키가 없어도 Render 연결만 확인할 수 있습니다.

```bash
sudo docker run --rm --name pauseable-weather-location-check --pull=never --network host \
  --env-file /var/lib/pauseable/weather-light-control/render-location.env \
  --mount type=bind,src=/var/lib/pauseable/weather-light-control,dst=/app,readonly \
  -w /app --entrypoint python3 ha-ai-runner:review-20260908 \
  /app/weather_api.py --check-location
```

성공하면 `지역 조회 확인 완료: Render · 기상청 격자 확인됨`과 `조명 명령은 전송하지 않았습니다.`가 출력됩니다. 지역 미설정은 종료 코드 2이며 앱에서 먼저 올바른 환자 거주 지역을 저장합니다. 오류가 있으면 아래 표를 확인한 뒤 진행합니다.

실제 제어를 시작하기 전에 앱의 지역이 환자 집과 일치하는지 확인합니다. 이 명령부터는 기존 프로그램의 판단에 따라 실제 조명이 바뀔 수 있습니다.

```bash
sudo systemctl start pauseable-weather-light.service
sudo systemctl enable --now pauseable-weather-light.timer
sudo systemctl status pauseable-weather-light.service --no-pager
sudo journalctl -u pauseable-weather-light.service -n 50 --no-pager
sudo systemctl list-timers pauseable-weather-light.timer
```

저장소의 타이머는 약 1분 간격으로 재실행합니다. 앱에서 지역을 저장하면 다음 실행부터 새 격자를 읽습니다. 기존 밝기·색온도 계산과 조명 엔티티는 바꾸지 않으며 태양 고도는 계속 HA `sun.sun`을 사용하므로 HA의 집 위치도 실제 환자 집이어야 합니다. 과거 앱의 `auto_lighting_enabled` 저장 필드는 이번 지역 연동으로 장비 타이머를 끄는 스위치가 되지 않습니다.

## 일반 Python 실행 장비에 적용

새 `weather_api.py`와 비공개 환경파일을 같은 폴더에 놓고 기존 가상환경에서 실행합니다. 환경파일은 위처럼 공백 없는 `이름=값` 형식으로 작성하며, 파일 내용을 화면에 출력하지 않습니다.

```bash
chmod 600 render-location.env
set -a
. ./render-location.env
set +a
python weather_api.py --check-location
```

조회 시험이 성공하고 실제 조명 제어를 진행할 준비가 되면 `python weather_api.py`를 실행합니다. 기존 cron/systemd도 같은 환경을 전달하도록 설정해야 합니다. 단순히 셸에서 한 번 설정한 변수는 기존 타이머에 자동으로 전달되지 않습니다.

## 오류 확인과 복귀

| 결과 | 확인할 내용 |
| --- | --- |
| HTTP 401 | Device Token이 빠졌는지 확인 |
| HTTP 403 | Render의 Device Token과 같은지 확인하고 App/Worker 토큰을 사용하지 않았는지 확인 |
| HTTP 404 | Render 새 경로 배포 완료 여부와 앱·장비의 동일한 `PATIENT_ID` 확인 |
| HTTP 503 또는 서버 오류 | Render 인증 환경변수·R2 상태 확인 |
| 거주 지역 미설정 | 앱에서 환자의 실제 거주 지역 저장 |
| 연결 실패 또는 리다이렉트 | HTTPS 기본 주소·인터넷 확인. 인증정보 보호를 위해 리다이렉트는 따르지 않음 |

기존 방식으로 돌아가려면 장비 환경파일의 `WEATHER_LOCATION_SOURCE`를 `legacy`로 바꾸고 서비스를 다시 실행합니다. 남겨 둔 `location_config.json` 또는 HA `zone.home`를 다시 사용하며 Render에 저장된 지역 데이터는 삭제하지 않습니다.

완료 확인은 조회 시험 성공, 다음 타이머 실행의 올바른 지역, 실제 조명 반응 순서로 진행합니다. GitHub 병합이나 조회 API 성공만으로 실장비까지 완료된 것으로 판단하지 않습니다.
