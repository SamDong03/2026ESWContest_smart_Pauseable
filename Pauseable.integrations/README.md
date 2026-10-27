# Pauseable.integrations

<a id="모드와-실패-처리"></a>
<a id="처리-과정"></a>

**보호자 앱의 거주지역, 기상청 예보와 Home Assistant 태양 고도를 이용한 조명 연동입니다.**

[프로젝트](../README.md) · [앱·API](../Pauseable.apps/README.md) · [장치 배포](../Pauseable.deploy/README.md)

## 기능 개요

| 구성 | 담당 내용 |
| --- | --- |
| Guardian·API | 대상자의 거주지역·기상청 격자 저장·Device 조회 |
| 기상청 단기예보 | 하늘 상태 `SKY`, 강수 형태 `PTY`, 기온 `TMP` |
| HA `sun.sun` | 집 위치를 기준으로 태양 고도 제공 |
| Python | 밝기·색온도·전원 규칙 계산과 HA 명령 |
| Docker·systemd | 실행 환경과 약 1분 간격의 반복 호출 |

이 기능은 행동 AI의 MQTT 판단이나 Central의 Action Router와 별도 경로입니다.

## 폴더 구조

```text
Pauseable.integrations/
└── home-assistant/ — Home Assistant 외부 기능 연동
    └── weather-light-control/ — 지역·날씨·태양 고도 기반 조명 규칙
        └── deploy/ — 설치·서비스 설정
            └── systemd/ — 서비스·타이머 Unit
```

| 경로·파일 | 역할 |
| --- | --- |
| `home-assistant` | HA 기반 외부 기능 모음 |
| `weather-light-control` | 지역·예보·태양 고도·조명 처리 모듈 |
| `weather_api.py` | 설정·조회·계산·실제 HA 명령 |
| `weather_location.py` | 이전 Excel 방식의 수동 지역 선택 도구 |
| `config.example.json` | 기상청·HA·조명 엔티티 설정 예시 |
| `render-location.env.example` | 앱 지역 Device API 조회 설정 예시 |
| `test_weather_api.py` | 지역·인증·계산·실패 처리의 모의 검사 |
| `deploy/systemd` | Docker 실행 서비스와 반복 타이머 |

<a id="처리-흐름"></a>
<a id="지역-설정-처리"></a>

## 처리 방식

```text
지역 확인 → 해당 격자 예보 조회 → HA 태양 고도 조회
→ 밝기·색온도·전원 계산 → 설정한 light.* 엔티티 제어
```

### 지역 선택

| 모드 | 동작 |
| --- | --- |
| `WEATHER_LOCATION_SOURCE=render` | Device 인증으로 `/api/device/patients/{patient_id}/home-environment` 조회 |
| `legacy`·미설정 | 기존 `location_config.json` 사용. 없으면 HA 집 좌표를 기상청 격자로 변환 |

앱 연동에서는 `render`를 사용합니다. 지역 조회 실패·미설정이면 임의 지역으로 우회하지 않고 해당 회차의 제어를 중단합니다. 이전 Excel 도구의 `data/kma_grid.xlsx`는 저장소에 포함되지 않으며 render 방식에는 필요하지 않습니다.

앱 거주지역은 예보 조회에, HA의 집 위치는 태양 고도에 사용합니다. 두 설정이 같은 장소인지 확인해야 합니다. 앱 지역 변경이 HA 집 위치까지 자동으로 바꾸지는 않습니다.

### 날씨와 태양 고도

프로그램은 기상청 `getVilageFcst`의 사용 가능한 발표 시각을 선택하고 같은 예보 시각의 SKY·PTY·TMP를 읽습니다. TMP는 조회하지만 현재 조명 계산에는 사용하지 않습니다. 태양 고도는 `sun.sun`의 `attributes.elevation`입니다.

| 태양 고도 `e` | 기본 밝기 | 기본 색온도 |
| --- | --- | --- |
| `e >= 20°` | 10% | 4,500 K |
| `-6° < e < 20°` | `10 + (20-e) × 60 / 26`% | `2700 + (e+6) × 1800 / 26` K |
| `e <= -6°` | 70% | 2,700 K |

| 날씨 | 보정 |
| --- | --- |
| 구름 많음 `SKY=3` | 밝기 +10%p, 색온도 −150 K |
| 흐림 `SKY=4` | 밝기 +20%p, 색온도 −300 K |
| 강수 `PTY!=0` | 밝기 +20%p 추가, 색온도 최대 3,200 K |

최종 계산은 밝기 0~97%, 색온도 2,500~6,500 K로 제한합니다. 태양 고도 20° 미만·구름 많음/흐림·강수 중 하나면 켜고, 그 외의 밝은 조건에서는 끕니다. 색온도를 계산한 값과 조명 전원 결정은 구분합니다.

### HA 출력

켜기는 `light.turn_on`에 `entity_id`, `brightness_pct`, `color_temp_kelvin`을 전달하고 끄기는 `light.turn_off`를 호출합니다. 기본 엔티티는 `light.tapo_l530`이며 실제 장치 ID와 밝기·색온도 지원을 확인합니다.

`publish_helper_states=true`는 계산값을 HA Helper에 기록하는 선택 기능이며 기본값은 false입니다. 실제 조명 제어를 대신하지 않습니다.

<a id="준비할-설정"></a>

## 설정 준비

| 비공개 파일 | 값 |
| --- | --- |
| `config.json` | 기상청 Key·HA 주소·HA Token·조명 엔티티·Helper 옵션 |
| `render-location.env` | 위치 출처·API 주소·대상자 ID·Device Token |

[JSON 예시](home-assistant/weather-light-control/config.example.json)와 [환경 예시](home-assistant/weather-light-control/render-location.env.example)를 복사해 실제 값은 장치에서 설정합니다. 파일 권한은 `600`으로 제한합니다.

systemd 서비스는 지역 조회용 환경변수 4개를 Docker에 전달합니다. 기상청·HA 설정은 읽기 전용으로 마운트한 `config.json`에 둡니다. Python에서 지원하는 모든 환경변수가 이 서비스에도 자동 전달되지는 않습니다.

<a id="로컬-검사와-조회-시험"></a>

## 로컬 검사와 지역 조회

```sh
cd Pauseable.integrations/home-assistant/weather-light-control
python -m pip install -r requirements.txt
python -m unittest -v test_weather_api.py
```

`weather_api.py`는 Python 표준 라이브러리를 사용합니다. requirements의 pandas·openpyxl은 이전 Excel 도구용입니다. 모의 테스트는 외부 API나 조명을 호출하지 않습니다.

실제 환경 파일을 준비한 Linux 셸에서는 아래처럼 지역만 확인합니다.

```sh
chmod 600 config.json render-location.env
set -a
. ./render-location.env
set +a
python weather_api.py --check-location
```

`--check-location`은 예보·태양 고도 조회와 조명 명령을 실행하지 않습니다. 옵션 없는 실행은 실제 조명을 제어합니다.

<a id="장치-적용과-확인"></a>

## Pi 서비스와 확인

서비스는 `/var/lib/pauseable/weather-light-control`의 소스·설정을 사용하며 기존 `ha-ai-runner:review-20260908` 이미지와 `ha-docker-engine.service`가 필요합니다. 서비스의 `--pull=never`는 이미지를 자동으로 내려받지 않습니다. [서비스·타이머 원본](home-assistant/weather-light-control/deploy/systemd)을 적용하기 전에 실제 설치 경로와 기존 값을 확인합니다.

Unit 준비 후 서비스 한 회차를 시험하고 타이머를 활성화합니다. 아래 `start`부터 실제 제어가 가능합니다.

```sh
sudo systemctl daemon-reload
sudo systemctl start pauseable-weather-light.service
journalctl -u pauseable-weather-light.service -n 50 --no-pager
sudo systemctl enable --now pauseable-weather-light.timer
```

타이머는 부팅 후 2분을 시작 기준으로 이후 약 1분 간격으로 실행합니다. 중단은 다음과 같습니다.

```sh
sudo systemctl disable --now pauseable-weather-light.timer
sudo systemctl stop pauseable-weather-light.service
```

앱의 `auto_lighting_enabled`는 서버에 저장되지만 현재 Python 프로그램의 제어 허용과 연결되어 있지 않습니다. 타이머 중단이 이미 켜진 조명을 자동으로 끄지는 않습니다. 지역·예보·HA 인증·태양 고도 조회가 실패하면 해당 회차의 조명 명령에 도달하지 않고 다음 타이머에서 다시 확인합니다.
