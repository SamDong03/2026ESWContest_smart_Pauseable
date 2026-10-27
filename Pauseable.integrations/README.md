# 거주지역·날씨를 이용한 조명 제어

이 모듈은 보호자 앱의 거주지역, 기상청 날씨와 Home Assistant의 태양 고도를 사용해 조명을 조절합니다. **반복행동·배회 AI와 별개로 실행하는 환경 조명 규칙**입니다.

[전체 시스템](../README.md) · [앱·API](../Pauseable.apps/README.md) · [장치 배포](../Pauseable.deploy/README.md)

<a id="처리-과정"></a>

## 1. 보호자 앱에서 거주지역을 저장한다

보호자가 Guardian에서 지역을 선택하면 API에 지역 코드와 기상청 격자가 저장됩니다. 이는 GPS 추적이나 상세 주소 수집이 아니라 날씨 조회에 사용할 지역 설정입니다.

<a id="모드와-실패-처리"></a>

## 2. 조명 장치가 지역과 환경 정보를 조회한다

[weather_location.py](home-assistant/weather-light-control/weather_location.py)와 [weather_api.py](home-assistant/weather-light-control/weather_api.py)가 위치 설정을 읽습니다.

| 모드 | 지역을 얻는 곳 |
| --- | --- |
| `WEATHER_LOCATION_SOURCE=render` | Device 인증으로 API의 대상자별 거주지역·기상청 `nx/ny` 조회 |
| `legacy` 또는 미설정 | 기존 장치의 위치 설정 |

지역을 확인한 뒤 기상청에서 `SKY`·`PTY`를 가져오고, HA의 `sun.sun`에서 태양 고도를 읽습니다. 태양 고도는 HA에 설정한 집 위치를 사용하므로 실제 거주지역과 맞춰야 합니다.

## 3. 밝기·색온도와 전원 상태를 계산한다

`calculate_light()`는 아래 규칙을 적용합니다.

| 계산 항목 | 현재 규칙 |
| --- | --- |
| 기본 밝기 | 태양 고도 20° 이상 10%, -6° 이하 70%, 중간은 선형 계산 |
| 날씨 밝기 보정 | 구름 많음 +10, 흐림 +20, 강수 +20. 최종 0~97% 제한 |
| 기본 색온도 | 고도에 따라 2,700~4,500 K, 날씨 보정 후 2,500~6,500 K 제한 |
| 켜는 조건 | 고도 20° 미만 또는 구름 많음·흐림·강수 |
| 끄는 조건 | 그 외의 맑은 낮 조건 |

기본 밝기 계산과 전원을 켜는 조건은 다릅니다. 밝기를 10%로 계산했더라도 맑은 낮에는 전원 조건에 따라 끕니다. 조도 센서의 실측 lux나 학습 모델을 사용하는 방식은 아닙니다.

## 4. HA 조명 엔티티에 전달한다

계산 결과를 설정한 `light.*` 엔티티의 `turn_on`·`turn_off`로 전달합니다. 켜는 요청에는 밝기와 색온도를 함께 넣습니다. [systemd 타이머](home-assistant/weather-light-control/deploy/systemd)는 부팅 후 2분에 시작하고 약 1분 간격으로 실행합니다.

Render 지역 조회가 실패하거나 지역·격자가 유효하지 않으면 그 회차의 조명 변경을 중단하고 다음 실행에서 재시도합니다. 이 경우 임의 지역으로 전환하거나 조명을 끄지 않고 기존 상태를 유지합니다.

<a id="준비할-설정"></a>

## 5. 연결 설정을 준비한다

| 설정 | 준비할 값 | 예시 파일 |
| --- | --- | --- |
| 기상청 | Service Key | [config.example.json](home-assistant/weather-light-control/config.example.json) |
| HA | 주소·장기 Token·조명 엔티티 ID | 같은 설정 파일 |
| API 지역 조회 | API 주소·대상자·Device Token·위치 출처 | [render-location.env.example](home-assistant/weather-light-control/render-location.env.example) |

실제 값은 장치의 비공개 `config.json`·`render-location.env`에 저장하고 읽기 권한을 제한합니다. App Token 대신 Device Token을 사용합니다.

<a id="로컬-검사와-조회-시험"></a>

## 6. 조명을 바꾸기 전에 조회부터 검사한다

별도 Python 가상환경을 활성화하고 **저장소 루트에서** 시작합니다.

```sh
cd Pauseable.integrations/home-assistant/weather-light-control
python -m pip install -r requirements.txt
python -m unittest -v test_weather_api.py
```

장치의 비공개 환경 파일을 준비한 뒤 Linux 셸에서 위치만 조회합니다.

```sh
chmod 600 render-location.env
set -a
. ./render-location.env
set +a
python weather_api.py --check-location
```

`--check-location`은 조명 명령을 보내지 않습니다. 옵션 없는 실행이나 서비스 시작은 실제 조명을 제어합니다.

<a id="장치-적용과-확인"></a>

## 7. 타이머를 적용하고 조명을 확인한다

1. API가 반환한 대상자·지역·격자를 확인합니다.
2. HA의 집 위치와 조명 엔티티를 확인합니다.
3. [설치 가이드](../Pauseable.docs/integrations/home-assistant/RENDER_REGION_SETUP_KO.md)에 따라 서비스·타이머를 적용합니다.
4. 다음 회차의 계산 결과와 실제 밝기·색온도를 대조합니다.
5. Render 지역 조회 실패 시 조명 변경을 중단하는지 확인합니다.

현재 앱의 `auto_lighting_enabled` 저장은 장치 타이머의 시작·중지와 직접 연결된 기능이 아닙니다. 앱 설정 저장과 장치에서의 실행 여부를 각각 확인합니다.
