# PAUSEABLE / Integrations

**보호자가 설정한 지역의 날씨와 태양 고도를 조명 제어에 반영합니다.** AI의 반복행동·배회 판단과는 별도 경로이며, 외부 정보·API·Home Assistant를 연결하는 모듈입니다.

[전체 프로젝트](../README.md) · [API·앱](../Pauseable.apps/README.md) · [배포 안내](../Pauseable.deploy/README.md)

![Guardian 지역 설정에서 기상청·HA sun 정보와 조명 제어로 이어지는 연결](../Pauseable.docs/assets/readme/weather-light.svg)

## 조명 한 회차의 처리

| 입력·단계 | 하는 일 |
| --- | --- |
| Guardian 지역 | 앱이 저장한 대상자별 거주 지역 확인 |
| 위치 조회 | Device 인증으로 API의 지역과 기상청 `nx/ny` 조회 |
| 환경 정보 | 기상청 날씨와 HA `sun.sun`의 태양 고도 사용 |
| 규칙 적용 | 밝기·색온도 규칙으로 HA 조명 엔티티에 명령 |
| 오류 처리 | Render 모드의 위치 조회 실패 시 해당 회차 변경 중단 |

약 1분 간격의 타이머 실행과 실제 조명 반응은 별도로 확인합니다. 이 주기는 HA AI의 WebSocket 수집 주기와 관계없습니다.

<details>
<summary><strong>구현 파일과 설정 위치</strong></summary>

| 파일 | 역할 |
| --- | --- |
| [`weather_api.py`](home-assistant/weather-light-control/weather_api.py) | 지역·날씨 조회와 HA 조명 밝기·색온도 처리 |
| [`weather_location.py`](home-assistant/weather-light-control/weather_location.py) | 위치 설정과 Render 지역 조회 |
| [`config.example.json`](home-assistant/weather-light-control/config.example.json) | 기상청·HA·조명 엔티티 설정 형식 |
| [`render-location.env.example`](home-assistant/weather-light-control/render-location.env.example) | Device 인증·지역 출처 설정 예시 |
| [`deploy/systemd`](home-assistant/weather-light-control/deploy/systemd) | 서비스와 타이머 |
| [`test_weather_api.py`](home-assistant/weather-light-control/test_weather_api.py) | API·위치 연동 회귀 검사 |

</details>

## 모드와 실패 처리

| 모드 | 동작 |
| --- | --- |
| `WEATHER_LOCATION_SOURCE=render` | 앱에 저장된 지역을 Device 인증 API로 조회 |
| `legacy` 또는 미설정 | 기존 장치의 위치 설정 사용 |
| Render 조회 실패·지역 미설정·격자 오류 | 해당 회차 조명 변경 중단, 다음 실행에서 재시도 |

Render 모드 오류를 숨기고 예전 로컬 지역으로 바꾸거나 조명을 강제로 끄지 않습니다. 태양 고도는 HA의 집 위치에 영향을 받으므로 `sun.sun`과 거주 지역이 실제 장치 위치에 맞아야 합니다.

## 준비할 설정

<details>
<summary><strong>비공개 설정 체크리스트</strong></summary>

| 항목 | 위치·주의 |
| --- | --- |
| 기상청 Service Key | 장치의 비공개 `config.json` |
| HA 주소·장기 Token·조명 Entity ID | 장치의 비공개 `config.json` |
| Render API·대상자·Device Token | 비공개 `render-location.env` |
| 실제 거주 지역 | Guardian에서 저장하고 API 영속 저장 여부 확인 |

예시 파일을 복사한 뒤 실제 값을 로컬 편집기로 입력합니다. 기존 설정을 덮어쓰지 않고, 토큰을 채팅·Git·명령행 인자로 공개하지 않습니다. App/Worker Token을 조명 장치의 Device Token 대신 사용하지 않습니다.

</details>

## 로컬 검사와 조회 시험

<details>
<summary><strong>회귀 검사와 조명을 바꾸지 않는 조회 명령</strong></summary>

별도 Python 가상환경을 활성화하고 **저장소 루트에서** 시작합니다.

```sh
cd Pauseable.integrations/home-assistant/weather-light-control
python -m pip install -r requirements.txt
python -m unittest -v test_weather_api.py
```

장치의 비공개 환경 파일을 준비한 뒤 Linux 셸에서 다음처럼 조회만 확인할 수 있습니다.

```sh
chmod 600 render-location.env
set -a
. ./render-location.env
set +a
python weather_api.py --check-location
```

`--check-location`은 **조명 명령을 보내지 않는 조회 시험**입니다. 옵션 없는 실행이나 systemd 시작은 실제 조명을 바꿀 수 있으므로 여기서는 자동으로 실행하지 않습니다.

</details>

## 장치 적용과 확인

장치 경로·서비스·타이머·Docker 실행과 복귀 절차는 [지역 설정 연동 가이드](../Pauseable.docs/integrations/home-assistant/RENDER_REGION_SETUP_KO.md)를 따릅니다. 저장소 타이머는 약 1분 간격으로 실행하도록 구성되어 있습니다.

1. API 지역 조회 성공을 확인합니다.
2. 반환 격자와 대상자 일치를 확인합니다.
3. 다음 타이머 실행과 실제 조명 반응을 확인합니다.
4. 통신 실패 시 조명 변경이 중단되는지 확인합니다.

앱의 지역 저장 성공은 조명 제어 완료를 의미하지 않습니다. `auto_lighting_enabled` 설정을 저장하는 것과 장치 타이머를 시작·중지하는 것도 동일한 기능이 아닙니다.
