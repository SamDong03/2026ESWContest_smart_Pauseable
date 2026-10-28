# Pauseable.integrations

<a id="pauseableintegrations"></a>

**보호자 앱의 거주지역, 기상청 예보와 Home Assistant 태양 고도로 실내 조명을 조절합니다.**

[프로젝트](../README.md) · [앱·API](../Pauseable.apps/README.md) · [장치 배포](../Pauseable.deploy/README.md)

[기능 개요](#기능-개요) · [폴더 구조](#폴더-구조) · [처리 방식](#처리-방식) · [설정](#설정-준비) · [Pi 서비스](#pi-서비스와-확인)

<a id="기능-개요"></a>

## 기능 개요

| 구성 | 사용하는 정보 | 역할 |
| --- | --- | --- |
| Guardian·API | 대상자 거주지역, 기상청 격자 `nx`·`ny` | 앱에서 지역 저장, 장치에 Device API로 제공 |
| 기상청 단기예보 | 하늘 상태 `SKY`, 강수 형태 `PTY`, 기온 `TMP` | 해당 격자·예보 시각의 날씨 조회 |
| HA `sun.sun` | `attributes.elevation` | 집 위치의 태양 고도 조회 |
| `weather_api.py` | 지역·날씨·태양 고도 | 조명 전원·밝기·색온도 계산과 HA 호출 |
| Docker·systemd | 실행 환경·서비스·타이머 | 부팅 후 시작과 1분 간격 실행 |

조명 제어는 Python 프로그램이 지역 조회부터 HA 서비스 호출까지 한 회차로 처리하고, systemd 타이머가 주기적으로 실행합니다.

<a id="폴더-구조"></a>

## 폴더 구조

```text
Pauseable.integrations/
└── home-assistant/                                   # Home Assistant 기반 환경 제어
    └── weather-light-control/                        # 거주지역·날씨·태양 고도에 따른 조명 제어
        ├── deploy/
        │   └── systemd/
        │       ├── pauseable-weather-light.service   # Docker로 조명 제어 한 회차 실행
        │       └── pauseable-weather-light.timer     # 부팅 후 2분·이후 1분 간격 실행
        ├── config.example.json                       # 기상청·HA·조명 엔티티 설정
        ├── render-location.env.example               # 앱 거주지역 조회 설정
        ├── requirements.txt                          # 지역 선택 도구의 Python 의존성
        ├── weather_api.py                            # 지역·예보 조회와 밝기·색온도·전원 계산
        └── weather_location.py                       # Excel 지역 목록을 이용한 격자 선택
```

<a id="처리-과정"></a>
<a id="처리-흐름"></a>
<a id="지역-설정-처리"></a>
<a id="처리-방식"></a>

## 처리 방식

```text
앱 거주지역 저장 → Device API에서 격자 조회 → 기상청 예보 조회
→ HA 태양 고도 조회 → 밝기·색온도·전원 계산 → HA light 엔티티 제어
```

<a id="지역-선택"></a>

### ① 거주지역과 기상청 격자

`load_location()`은 `WEATHER_LOCATION_SOURCE`에 따라 지역을 읽습니다.

| 모드 | 지역 조회 과정 |
| --- | --- |
| `render` | Device 인증으로 `/api/device/patients/{patient_id}/home-environment` 조회 |
| `legacy`·기본값 | `location_config.json`을 읽고, 파일이 없으면 HA `zone.home`의 위도·경도를 격자로 변환 |

앱 연동에서는 `render`를 사용합니다. API 응답의 시·도, 시·군·구, 읍·면·동과 정수 격자 좌표를 검증한 뒤 예보 조회에 사용합니다. 지역 미설정 응답은 종료 코드 `2`로 처리하고, 다음 실행에서 다시 조회합니다.

기상청 격자는 앱에 저장한 거주지역을 기준으로 하고, 태양 고도는 HA의 집 위치를 기준으로 합니다. 설치 시 두 위치를 같은 거주지로 설정합니다. 수동 지역 선택 도구 [weather_location.py](home-assistant/weather-light-control/weather_location.py)를 사용하려면 기상청 격자 Excel을 `data/kma_grid.xlsx`에 별도로 준비해야 합니다. 도구가 선택 결과를 `location_config.json`으로 저장하며, 앱 지역을 조회하는 `render` 모드에는 이 Excel이 필요하지 않습니다.

<a id="날씨와-태양-고도"></a>

### ② 예보 시각과 날씨 정보

`get_base_date_time()`은 한국 시간 기준으로 사용할 발표 시각을 정하고, `get_weather()`가 기상청 `getVilageFcst` 응답에서 같은 예보 시각의 항목을 선택합니다.

| 항목 | 값·용도 |
| --- | --- |
| `SKY` | `1` 맑음, `3` 구름 많음, `4` 흐림. 밝기·색온도 보정 |
| `PTY` | `0` 무강수, 그 외 강수 형태. 강수 보정과 조명 켜기 판단 |
| `TMP` | 기온 조회·실행 로그 |
| `sun.sun`의 `elevation` | 낮·일몰 전후·밤의 기본 조명 값 계산 |

### ③ 밝기·색온도 계산

`calculate_light()`는 태양 고도 `e`로 기본 값을 정한 뒤 날씨 보정을 적용합니다.

| 태양 고도 | 기본 밝기 | 기본 색온도 |
| --- | --- | --- |
| `e >= 20°` | 10% | 4,500 K |
| `-6° < e < 20°` | `10 + (20-e) × 60 / 26`% | `2700 + (e+6) × 1800 / 26` K |
| `e <= -6°` | 70% | 2,700 K |

| 날씨 조건 | 밝기 보정 | 색온도 보정 |
| --- | --- | --- |
| 구름 많음 `SKY=3` | +10%p | −150 K |
| 흐림 `SKY=4` | +20%p | −300 K |
| 강수 `PTY!=0` | +20%p 추가 | 최대 3,200 K |

최종 밝기는 0–97%, 색온도는 2,500–6,500 K 범위에서 정수로 반올림합니다. 예를 들어 태양 고도 7°·맑음·강수 없음에서는 밝기 40%, 색온도 3,600 K를 계산합니다. 같은 고도에서 흐림과 강수가 함께 있으면 밝기 80%, 색온도 3,200 K를 계산합니다.

<a id="ha-출력"></a>

### ④ 전원 판단과 HA 출력

`should_turn_on()`은 태양 고도 20° 미만, 구름 많음·흐림, 강수 중 하나 이상에 해당하면 조명을 켭니다. 태양 고도 20° 이상·맑음·강수 없음 조건에서는 조명을 끕니다.

| 출력 | HA 호출과 전달값 |
| --- | --- |
| 켜기 | `light.turn_on`: `entity_id`, `brightness_pct`, `color_temp_kelvin` |
| 끄기 | `light.turn_off`: `entity_id` |
| 상태 기록 옵션 | `publish_helper_states=true`에서 전원·밝기·색온도·SKY·PTY Helper 갱신 |

기본 제어 대상은 `light.tapo_l530`입니다. 실제 조명은 밝기·색온도 제어를 지원하는 HA 엔티티 ID로 설정합니다. Helper 기록 기본값은 `false`입니다.

<a id="준비할-설정"></a>
<a id="설정-준비"></a>

## 설정 준비

### ① 설정 파일

| 파일 | 주요 항목 |
| --- | --- |
| `config.json` | `kma_service_key`, `ha_url`, `ha_token`, `ha_light_entity_id`, `publish_helper_states` |
| `render-location.env` | `WEATHER_LOCATION_SOURCE`, `PAUSEABLE_API_BASE_URL`, `PATIENT_ID`, `PAUSEABLE_DEVICE_TOKEN` |

[config.example.json](home-assistant/weather-light-control/config.example.json)과 [render-location.env.example](home-assistant/weather-light-control/render-location.env.example)을 복사해 장치의 실제 값을 입력합니다. 지역 출처는 `render`로 지정하고, 파일 접근 권한은 `600`으로 설정합니다.

### ② Python과 Docker 설정

`weather_api.py`는 Python 표준 라이브러리로 실행합니다. [requirements.txt](home-assistant/weather-light-control/requirements.txt)의 pandas·openpyxl은 Excel 지역 선택 도구에 사용합니다.

systemd 서비스는 지역 조회용 환경변수 4개를 Docker에 전달하고, `/var/lib/pauseable/weather-light-control`을 읽기 전용 `/app`으로 마운트합니다. 기상청·HA 연결값은 이 경로의 `config.json`에서 읽습니다.

<a id="로컬-검사와-조회-시험"></a>
<a id="로컬-검사와-지역-조회"></a>

## 로컬 검사와 지역 조회

### ① 모듈 검사

```sh
cd Pauseable.integrations/home-assistant/weather-light-control
python -m pip install -r requirements.txt
python -m unittest -v test_weather_api.py
```

[test_weather_api.py](home-assistant/weather-light-control/test_weather_api.py)는 지역 API 응답·인증·격자 변환·예보 선택·계산식·HA 요청을 모의 응답으로 검사합니다.

### ② 장치의 지역 설정 확인

Linux 셸에서 준비한 환경 파일을 로드하고 `--check-location`으로 지역 조회 결과를 확인합니다.

```sh
chmod 600 config.json render-location.env
set -a
. ./render-location.env
set +a
python weather_api.py --check-location
```

기본 실행 `python weather_api.py`는 지역·예보·태양 고도 조회 후 실제 조명 명령을 전송합니다.

<a id="장치-적용과-확인"></a>
<a id="pi-서비스와-확인"></a>

## Pi 서비스와 확인

### ① 실행 환경과 주기

[서비스·타이머](home-assistant/weather-light-control/deploy/systemd)는 기존 `ha-docker-engine.service`와 로컬 Docker 이미지 `ha-ai-runner:review-20260908`을 사용합니다. 설치 경로에 소스·설정 파일을 준비하고 두 Unit 파일을 systemd에 등록합니다.

| 항목 | 설정 |
| --- | --- |
| 소스·설정 경로 | `/var/lib/pauseable/weather-light-control` |
| 서비스 유형 | `oneshot`, 한 회차 제한 90초 |
| 첫 실행 기준 | 부팅 후 2분 |
| 반복 주기 | 이전 활성화 기준 1분, 허용 오차 10초 |
| 실행 로그 | systemd Journal |

### ② 시작과 로그 확인

```sh
sudo systemctl daemon-reload
sudo systemctl start pauseable-weather-light.service
journalctl -u pauseable-weather-light.service -n 50 --no-pager
sudo systemctl enable --now pauseable-weather-light.timer
```

로그에서 지역·격자·발표 시각·선택한 예보 시각·태양 고도·계산 밝기·색온도와 HA 제어 결과를 확인합니다. 지역·예보·HA 조회 오류는 해당 실행의 결과로 기록하며 다음 타이머 실행에서 다시 조회합니다.

<a id="모드와-실패-처리"></a>
