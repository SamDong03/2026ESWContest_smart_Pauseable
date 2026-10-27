# 거주지역·날씨를 이용한 조명 제어

이 모듈은 **보호자 앱에서 저장한 지역의 날씨와 Home Assistant의 태양 고도를 이용해 조명의 전원·밝기·색온도를 정합니다.** 반복행동·배회 판단이나 Central의 Action Router와는 별도로 실행합니다.

[전체 시스템](../README.md) · [앱·API](../Pauseable.apps/README.md) · [장치 배포](../Pauseable.deploy/README.md)

## 1. 무엇을 연결하는가

| 구성 요소 | 이 모듈에서 맡는 역할 |
| --- | --- |
| Flutter Guardian | 보호자가 환자의 거주지역 선택 |
| FastAPI | 지역 코드·행정구역·기상청 격자를 저장하고 Device API로 제공 |
| 기상청 단기예보 API | 해당 격자의 하늘 상태·강수 형태·기온 제공 |
| Home Assistant | `sun.sun`의 태양 고도 제공, 조명 명령 실행 |
| Pi의 Python 프로그램 | 지역·예보·태양 고도를 조회하고 조명 설정 계산 |
| Docker·systemd | 프로그램을 한 번씩 실행하고 타이머로 반복 호출 |

처리 순서는 **지역 확인 → 예보 조회 → 태양 고도 조회 → 조명 설정 계산 → HA 명령**입니다. MQTT 판단 메시지나 AI 모델을 거치는 경로는 아닙니다.

<a id="처리-과정"></a>
<a id="모드와-실패-처리"></a>

## 2. 조명 설정에 사용할 정보를 모은다

### 2.1 사용할 지역을 확인한다

[weather_api.py](home-assistant/weather-light-control/weather_api.py)의 `load_location()`이 위치 출처를 선택합니다.

| 설정 | 조회 순서 |
| --- | --- |
| `WEATHER_LOCATION_SOURCE=render` | Device Token으로 `GET /api/device/patients/{patient_id}/home-environment`를 호출하고 앱에 저장한 지역 사용 |
| `legacy` 또는 미설정 | 프로그램 옆 `location_config.json`을 먼저 사용. 없으면 HA `zone.home`의 위도·경도를 기상청 격자로 변환 |

앱 연동에는 `render`를 명시합니다. 응답의 대상자 ID, 지역 형식과 격자 `nx/ny`를 검사하며, 조회 실패나 지역 미설정 시에는 **기존 지역으로 우회하지 않고 조명 변경을 중단**합니다.

`weather_location.py`는 앱 연동 프로그램이 아니라 **이전 방식의 수동 지역 선택 도구**입니다. 별도로 준비한 `data/kma_grid.xlsx`를 읽어 `location_config.json`을 만듭니다. 이 Excel 파일은 저장소에 포함하지 않으며, 앱 지역을 사용하는 `render` 모드에는 필요하지 않습니다.

### 2.2 해당 지역의 예보를 가져온다

`get_weather()`는 기상청의 `getVilageFcst`를 호출합니다. 한국 시각에서 20분을 뺀 뒤, 그 시각을 넘지 않는 02·05·08·11·14·17·20·23시 중 가장 늦은 기준 시각을 선택합니다.

| 값 | 의미 | 조명 계산에서의 사용 |
| --- | --- | --- |
| `SKY` | 하늘 상태 | 1: 맑음, 3: 구름 많음, 4: 흐림에 따라 보정 |
| `PTY` | 강수 형태 | 0이 아니면 강수 보정 |
| `TMP` | 예보 기온 | 함께 조회·기록하지만 현재 조명 계산에는 미사용 |

세 항목이 모두 있는 예보 중 현재 시각에 가장 가까운 시간의 값을 선택합니다. 실내 조도 센서의 측정값이나 실시간 강수 감지값을 사용하는 것은 아닙니다.

### 2.3 HA에서 태양 고도를 읽는다

`get_sun_elevation()`은 `sun.sun`의 `attributes.elevation`을 읽습니다. 태양 고도는 지평선을 기준으로 한 태양의 각도이며, HA에 설정한 집 위치로 계산됩니다.

앱의 거주지역은 날씨 조회에, HA의 집 위치는 태양 고도에 쓰입니다. **두 위치를 같은 거주지에 맞춰야 합니다.** 앱 지역을 저장했다고 HA의 집 위치까지 자동 변경되지는 않습니다.

## 3. 전원·밝기·색온도를 계산한다

### 3.1 먼저 밝기와 색온도의 기본값을 정한다

`calculate_light()`의 태양 고도별 계산입니다. `e`는 태양 고도입니다.

| 태양 고도 | 기본 밝기 | 기본 색온도 |
| --- | --- | --- |
| `e >= 20°` | 10% | 4,500 K |
| `-6° < e < 20°` | `10 + (20 - e) × 60 / 26`% | `2700 + (e + 6) × 1800 / 26` K |
| `e <= -6°` | 70% | 2,700 K |

### 3.2 날씨에 따라 보정한다

| 날씨 조건 | 밝기 보정 | 색온도 보정 |
| --- | --- | --- |
| 구름 많음 · `SKY=3` | +10%p | -150 K |
| 흐림 · `SKY=4` | +20%p | -300 K |
| 강수 · `PTY != 0` | +20%p 추가 | 보정값을 최대 3,200 K로 제한 |

구름과 강수 보정은 함께 적용할 수 있습니다. 계산 후 정수로 반올림하고 밝기는 0~97%, 색온도는 2,500~6,500 K의 코드 제한 범위로 맞춥니다.

### 3.3 조명을 켤지 결정한다

`should_turn_on()`은 **태양 고도 20° 미만, 구름 많음·흐림, 강수 중 하나라도 해당하면 켜고**, 그 외의 맑은 낮에는 끕니다.

밝기 계산과 전원 결정은 별도입니다. 예를 들어 맑은 낮에 10%·4,500 K를 계산해도 전원 조건이 끄기이면 `light.turn_off`만 보냅니다.

## 4. 계산 결과를 HA 조명에 전달한다

`set_ha_light()`가 설정한 조명 엔티티에 다음 명령을 보냅니다.

| 전원 결정 | HA 서비스 | 전달값 |
| --- | --- | --- |
| 켜기 | `light.turn_on` | `entity_id`, `brightness_pct`, `color_temp_kelvin` |
| 끄기 | `light.turn_off` | `entity_id`만 전달 |

기본 대상은 `light.tapo_l530`이며 `HA_LIGHT_ENTITY_ID` 또는 `config.json`으로 바꿀 수 있습니다. 대상 조명은 HA에서 연결돼 있고 밝기·색온도 명령을 지원해야 합니다.

`publish_helper_states=true`이면 계산값을 아래 HA Helper에도 기록합니다. 실제 조명 명령을 대신하는 경로는 아니며, 기본값은 `false`입니다. 활성화하려면 해당 Helper를 HA에 먼저 만들어야 합니다.

- 전원: `input_boolean.pauseable_virtual_light_power`
- 밝기·색온도: `input_number.pauseable_virtual_light_brightness`, `input_number.pauseable_virtual_light_kelvin`
- 날씨: `input_number.pauseable_weather_sky`, `input_number.pauseable_weather_pty`

<a id="준비할-설정"></a>

## 5. 비공개 설정을 준비한다

설정 예시는 [config.example.json](home-assistant/weather-light-control/config.example.json)과 [render-location.env.example](home-assistant/weather-light-control/render-location.env.example)에 있습니다.

| 파일 | 준비할 값 |
| --- | --- |
| `config.json` | `kma_service_key`, `ha_url`, `ha_token`, `ha_light_entity_id`, `publish_helper_states` |
| `render-location.env` | `WEATHER_LOCATION_SOURCE=render`, `PAUSEABLE_API_BASE_URL`, `PATIENT_ID`, `PAUSEABLE_DEVICE_TOKEN` |

`PAUSEABLE_API_BASE_URL`에는 경로·인증정보가 없는 HTTPS 서버 주소를 넣고, `PATIENT_ID`는 앱의 대상자와 맞춥니다. 앱용 Token이 아니라 Device Token을 사용합니다.

**현재 systemd 서비스는 지역 조회용 환경변수 4개만 Docker에 전달합니다.** 서비스로 운용할 때 기상청 Key·HA 주소·HA Token·조명 엔티티는 마운트한 `config.json`에 저장합니다. Python 직접 실행에서 지원하는 환경변수가 모두 이 서비스에 자동 전달되는 것은 아닙니다.

실제 설정은 Git에 넣지 않고 파일 권한을 `600`으로 제한합니다. 예시 파일을 복사한 뒤 실제 값으로 바꿉니다.

<a id="로컬-검사와-조회-시험"></a>

## 6. 조명을 바꾸기 전에 검사한다

### 6.1 로컬 테스트

Python 3.12 별도 가상환경에서 저장소 루트 기준으로 시작합니다.

```sh
cd Pauseable.integrations/home-assistant/weather-light-control
python -m pip install -r requirements.txt
python -m unittest -v test_weather_api.py
```

`weather_api.py` 자체는 Python 표준 라이브러리를 사용합니다. `requirements.txt`의 pandas·openpyxl은 이전 Excel 지역 선택 도구에 필요합니다. 모의 테스트는 실제 API나 조명을 호출하지 않습니다.

### 6.2 지역 조회만 확인

같은 폴더에서 `config.json`과 `render-location.env`를 준비한 뒤 Linux 셸에서 실행합니다.

```sh
chmod 600 config.json render-location.env
set -a
. ./render-location.env
set +a
python weather_api.py --check-location
```

`--check-location`은 지역만 확인하고 날씨 조회·태양 고도 조회·조명 명령은 실행하지 않습니다. Render 모드의 이 검사는 기상청 Key와 HA Token 없이도 할 수 있습니다. **옵션 없는 실행은 실제 조명을 제어합니다.**

<a id="장치-적용과-확인"></a>

## 7. Pi에서 반복 실행한다

### 7.1 파일·실행 환경을 준비한다

| 장치 경로·조건 | 준비할 내용 |
| --- | --- |
| `/var/lib/pauseable/weather-light-control/` | `weather_api.py`, 실제 `config.json`, `render-location.env` |
| Docker 이미지 | `ha-ai-runner:review-20260908`가 장치에 있어야 함. 서비스는 `--pull=never` 사용 |
| Docker 서비스 | `ha-docker-engine.service` 의존성 확인 |
| systemd Unit | [service](home-assistant/weather-light-control/deploy/systemd/pauseable-weather-light.service), [timer](home-assistant/weather-light-control/deploy/systemd/pauseable-weather-light.timer) 등록 |

서비스는 위 폴더를 컨테이너 `/app`에 읽기 전용으로 마운트합니다. 실행 중인 서비스가 있으면 `systemctl cat pauseable-weather-light.service`로 설치 경로와 기존 설정을 먼저 확인합니다. Atlas의 읽기 전용 시스템 경로를 임의로 해제하거나 기존 Token·설정을 덮어쓰지 않습니다.

### 7.2 한 회차를 확인하고 타이머를 켠다

Unit과 설정 준비 후 아래 명령을 사용합니다. `start`부터는 실제 조명 명령이 전송됩니다.

```sh
sudo systemctl daemon-reload
sudo systemctl start pauseable-weather-light.service
journalctl -u pauseable-weather-light.service -n 50 --no-pager
sudo systemctl enable --now pauseable-weather-light.timer
systemctl list-timers pauseable-weather-light.timer
```

타이머는 부팅 후 2분을 시작 기준으로 삼고 이후 약 1분 간격으로 실행합니다. 매 회차 지역·예보·태양 고도를 다시 조회합니다. 로그의 대상 지역·격자·선택한 예보 시각·계산값과 실제 조명 상태를 대조합니다.

### 7.3 자동 제어를 중단한다

```sh
sudo systemctl disable --now pauseable-weather-light.timer
sudo systemctl stop pauseable-weather-light.service
```

타이머 중단만으로 이미 켜진 조명이 꺼지는 것은 아닙니다. 진행 중이거나 이미 전송한 HA 요청이 취소됐다고 보지 말고 실제 상태를 확인합니다.

## 8. 현재 연결 범위와 문제 확인

앱의 `auto_lighting_enabled` 값은 서버에 저장되지만, **현재 Python 프로그램은 이 값을 읽어 제어 허용 여부를 결정하지 않습니다.** 앱 토글과 Pi 타이머의 시작·중지는 아직 연결되어 있지 않습니다. 앱에 표시하는 연결 상태도 장치의 실제 출력 확인을 대신하지 않습니다.

| 증상 | 확인할 내용 |
| --- | --- |
| 지역 조회 401·403·404 | API 주소, Device Token, 대상자 ID, 서버 배포 경로 |
| 지역 미설정 | 앱에서 거주지역 저장. 조명 명령 없이 종료 코드 2 반환 |
| 앱 지역을 바꿔도 다른 날씨 사용 | `WEATHER_LOCATION_SOURCE=render`의 컨테이너 전달 여부 |
| 날씨 오류 | 기상청 Key·API 응답·해당 격자의 예보 |
| 태양 고도 오류 | HA 인증·`sun.sun`·HA 집 위치 |
| 조명 명령 오류 | `light.*` 엔티티·HA 연결·밝기/색온도 지원 |
| 서비스 실행 실패 | 장치 폴더·비공개 설정·기존 Docker 이미지·의존 서비스 |

지역·예보·태양 고도 조회가 실패하면 실제 조명 명령에 도달하지 않습니다. 지역 조회 장애 시 임의 지역으로 바꾸거나 조명을 강제로 끄는 복구 동작은 없습니다. 다음 타이머 회차에서 다시 조회합니다.

| 코드 | 담당 처리 |
| --- | --- |
| [weather_api.py](home-assistant/weather-light-control/weather_api.py) | 설정, 지역·예보·HA 조회, 계산과 명령 |
| [weather_location.py](home-assistant/weather-light-control/weather_location.py) | 이전 Excel 방식의 수동 지역 선택 |
| [test_weather_api.py](home-assistant/weather-light-control/test_weather_api.py) | 지역·인증·실패 처리·계산·HA 명령 회귀 검사 |
| [systemd 설정](home-assistant/weather-light-control/deploy/systemd) | Docker 실행과 반복 주기 |
