import argparse
import json
import math
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
from zoneinfo import ZoneInfo

API_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
LOCATION_CONFIG_FILE = BASE_DIR / "location_config.json"
KST = ZoneInfo("Asia/Seoul")

ENTITY_LIGHT_POWER = "input_boolean.pauseable_virtual_light_power"
ENTITY_LIGHT_BRIGHTNESS = "input_number.pauseable_virtual_light_brightness"
ENTITY_LIGHT_KELVIN = "input_number.pauseable_virtual_light_kelvin"
ENTITY_WEATHER_SKY = "input_number.pauseable_weather_sky"
ENTITY_WEATHER_PTY = "input_number.pauseable_weather_pty"
DEFAULT_LIGHT_ENTITY_ID = "light.tapo_l530"
DAYLIGHT_OFF_ELEVATION = 20
MIN_COLOR_TEMP_KELVIN = 2500
MAX_COLOR_TEMP_KELVIN = 6500


def load_config(*, require_lighting=True):
    config = {}

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

    service_key = os.getenv("KMA_SERVICE_KEY", config.get("kma_service_key", ""))
    ha_url = os.getenv("HA_URL", config.get("ha_url", "http://localhost:8123"))
    ha_token = os.getenv("HA_TOKEN", config.get("ha_token", ""))
    light_entity_id = os.getenv(
        "HA_LIGHT_ENTITY_ID",
        config.get("ha_light_entity_id", DEFAULT_LIGHT_ENTITY_ID),
    )
    publish_helper_states = config.get("publish_helper_states", False)

    if require_lighting and not service_key:
        raise ValueError("KMA_SERVICE_KEY 또는 config.json의 kma_service_key가 필요합니다.")

    if require_lighting and not ha_token:
        raise ValueError("HA_TOKEN 또는 config.json의 ha_token이 필요합니다.")

    if not light_entity_id.startswith("light."):
        raise ValueError("ha_light_entity_id는 light.로 시작해야 합니다.")

    return {
        "kma_service_key": unquote(service_key),
        "ha_url": ha_url.rstrip("/"),
        "ha_token": ha_token,
        "ha_light_entity_id": light_entity_id,
        "publish_helper_states": bool(publish_helper_states),


        "location_source": os.getenv(
            "WEATHER_LOCATION_SOURCE", config.get("location_source", "legacy")
        ).strip().lower(),
        "pauseable_api_base_url": os.getenv(
            "PAUSEABLE_API_BASE_URL",
            config.get("pauseable_api_base_url", "https://pauseable-api.onrender.com"),
        ).strip(),
        "patient_id": os.getenv("PATIENT_ID", config.get("patient_id", "")).strip(),
        "pauseable_device_token": os.getenv("PAUSEABLE_DEVICE_TOKEN", "").strip(),
    }


def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):

        return None


def request_json(
    method, url, headers=None, params=None, payload=None, timeout=10,
    follow_redirects=True,
):
    if params:
        url = f"{url}?{urlencode(params)}"

    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = Request(
        url,
        data=body,
        headers=headers or {},
        method=method,
    )

    try:
        open_request = urlopen if follow_redirects else build_opener(_NoRedirect()).open
        with open_request(request, timeout=timeout) as response:
            status_code = response.status
            response_text = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        status_code = error.code
        response_text = error.read().decode("utf-8", errors="replace")
    except URLError as error:
        raise RuntimeError(f"HTTP 연결 실패: {error.reason}") from None

    try:
        response_data = json.loads(response_text)
    except json.JSONDecodeError:
        response_data = None

    return status_code, response_data, response_text


def get_base_date_time(now=None):
    now = (now or datetime.now(KST)).astimezone(KST) - timedelta(minutes=20)

    base_times = ["0200", "0500", "0800", "1100", "1400", "1700", "2000", "2300"]
    current_time = now.strftime("%H%M")

    selected_time = None

    for base_time in base_times:
        if current_time >= base_time:
            selected_time = base_time

    if selected_time is None:
        yesterday = now - timedelta(days=1)
        return yesterday.strftime("%Y%m%d"), "2300"

    return now.strftime("%Y%m%d"), selected_time


def get_ha_state(config, entity_id):
    url = f"{config['ha_url']}/api/states/{entity_id}"

    headers = {
        "Authorization": f"Bearer {config['ha_token']}",
        "Content-Type": "application/json",
    }

    status_code, data, _ = request_json("GET", url, headers=headers)
    if status_code != 200:
        raise RuntimeError(
            f"HA 상태 조회 실패 ({entity_id}): HTTP {status_code}"
        )
    if data is None:
        raise RuntimeError(f"HA 상태 조회 응답이 JSON이 아닙니다: {entity_id}")

    return data


def get_sun_elevation(config):
    sun_state = get_ha_state(config, "sun.sun")
    elevation = sun_state.get("attributes", {}).get("elevation")
    if elevation is None:
        raise RuntimeError("sun.sun 엔티티에 elevation 속성이 없습니다.")
    return float(elevation)


def lat_lon_to_kma_grid(latitude, longitude):
    earth_radius_km = 6371.00877
    grid_spacing_km = 5.0
    standard_latitude_1 = 30.0
    standard_latitude_2 = 60.0
    origin_longitude = 126.0
    origin_latitude = 38.0
    origin_x = 43.0
    origin_y = 136.0

    degrees_to_radians = math.pi / 180.0
    scaled_radius = earth_radius_km / grid_spacing_km
    slat1 = standard_latitude_1 * degrees_to_radians
    slat2 = standard_latitude_2 * degrees_to_radians
    olon = origin_longitude * degrees_to_radians
    olat = origin_latitude * degrees_to_radians

    cone = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(
        math.pi * 0.25 + slat1 * 0.5
    )
    cone = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(cone)
    scale_factor = math.tan(math.pi * 0.25 + slat1 * 0.5)
    scale_factor = (
        math.pow(scale_factor, cone) * math.cos(slat1) / cone
    )
    origin_radius = math.tan(math.pi * 0.25 + olat * 0.5)
    origin_radius = scaled_radius * scale_factor / math.pow(origin_radius, cone)

    point_radius = math.tan(
        math.pi * 0.25 + latitude * degrees_to_radians * 0.5
    )
    point_radius = scaled_radius * scale_factor / math.pow(point_radius, cone)
    theta = longitude * degrees_to_radians - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= cone

    nx = math.floor(point_radius * math.sin(theta) + origin_x + 0.5)
    ny = math.floor(origin_radius - point_radius * math.cos(theta) + origin_y + 0.5)
    return nx, ny


class LocationNotConfigured(RuntimeError):
    pass


def load_render_location(config):
    base_url = config.get("pauseable_api_base_url", "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.path or parsed.query or parsed.fragment
    ):
        raise ValueError("PAUSEABLE_API_BASE_URL은 인증정보 없는 HTTPS 서버 주소여야 합니다.")
    patient_id = config.get("patient_id", "")
    token = config.get("pauseable_device_token", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", patient_id):
        raise ValueError("PATIENT_ID를 앱과 동일한 대상자 ID로 설정해 주세요.")
    if not token or re.search(r"\s", token):
        raise ValueError("PAUSEABLE_DEVICE_TOKEN을 장비의 비공개 환경파일에 설정해 주세요.")
    url = f"{base_url}/api/device/patients/{patient_id}/home-environment"
    try:
        status, data, _ = request_json(
            "GET", url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10, follow_redirects=False,
        )
    except (OSError, RuntimeError):

        raise RuntimeError("Render 지역 조회 연결에 실패했습니다. 이번 조명 변경을 중단합니다.") from None
    if status != 200:
        raise RuntimeError(f"Render 지역 조회 실패: HTTP {status}. 인증·배포·대상자 ID를 확인해 주세요.")
    if not isinstance(data, dict) or data.get("patient_id") != patient_id:
        raise RuntimeError("Render 지역 응답의 대상자 ID가 일치하지 않습니다.")
    if "region" not in data:
        raise RuntimeError("Render 지역 응답 형식이 올바르지 않습니다.")
    region = data["region"]
    if region is None:
        raise LocationNotConfigured("앱에서 환자 거주 지역을 먼저 저장해 주세요.")
    if not isinstance(region, dict) or not re.fullmatch(r"\d{10}", str(region.get("code", ""))):
        raise RuntimeError("Render 지역 응답 형식이 올바르지 않습니다.")
    if any(type(region.get(key)) is not int or not 1 <= region[key] <= 1000 for key in ("nx", "ny")):
        raise RuntimeError("Render의 기상청 격자 좌표가 올바르지 않습니다.")
    if any(not isinstance(region.get(key), str) for key in ("province", "city", "district")):
        raise RuntimeError("Render 지역 응답 형식이 올바르지 않습니다.")
    return {
        "sido": region["province"], "sigungu": region["city"], "dong": region["district"],
        "nx": region["nx"], "ny": region["ny"], "source": "render",
    }


def load_location(config):
    source = config.get("location_source", "legacy")
    if source == "render":


        return load_render_location(config)
    if source != "legacy":
        raise ValueError("WEATHER_LOCATION_SOURCE는 legacy 또는 render여야 합니다.")
    if LOCATION_CONFIG_FILE.exists():
        with open(LOCATION_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    home_state = get_ha_state(config, "zone.home")
    attributes = home_state.get("attributes", {})
    latitude = attributes.get("latitude")
    longitude = attributes.get("longitude")

    if latitude is None or longitude is None:
        raise RuntimeError(
            "location_config.json이 없고 zone.home에도 위도/경도가 없습니다."
        )

    nx, ny = lat_lon_to_kma_grid(float(latitude), float(longitude))
    return {
        "sido": "Home Assistant",
        "sigungu": "zone.home",
        "dong": "",
        "nx": nx,
        "ny": ny,
    }


def call_ha_service(config, domain, service, data):
    url = f"{config['ha_url']}/api/services/{domain}/{service}"

    headers = {
        "Authorization": f"Bearer {config['ha_token']}",
        "Content-Type": "application/json",
    }

    status_code, response_data, response_text = request_json(
        "POST",
        url,
        headers=headers,
        payload=data,
    )
    if not 200 <= status_code < 300:
        raise RuntimeError(
            f"HA 서비스 호출 실패 ({domain}.{service}): HTTP {status_code}"
        )

    return response_data if response_data is not None else response_text


def set_ha_number(config, entity_id, value):
    call_ha_service(
        config,
        "input_number",
        "set_value",
        {
            "entity_id": entity_id,
            "value": value,
        },
    )


def set_ha_boolean(config, entity_id, state):
    service = "turn_on" if state else "turn_off"

    call_ha_service(
        config,
        "input_boolean",
        service,
        {
            "entity_id": entity_id,
        },
    )


def set_ha_light(config, entity_id, is_on, brightness, kelvin):
    if not is_on:
        call_ha_service(
            config,
            "light",
            "turn_off",
            {"entity_id": entity_id},
        )
        return

    call_ha_service(
        config,
        "light",
        "turn_on",
        {
            "entity_id": entity_id,
            "brightness_pct": brightness,
            "color_temp_kelvin": kelvin,
        },
    )


def get_weather(config, nx, ny, base_date, base_time, target_time=None):
    params = {
        "serviceKey": config["kma_service_key"],
        "pageNo": 1,
        "numOfRows": 1000,
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }

    status_code, data, _ = request_json("GET", API_URL, params=params)
    if not 200 <= status_code < 300:
        error_data = data if isinstance(data, dict) else {}
        error_header = error_data.get("OpenAPI_ServiceResponse", {}).get(
            "cmmMsgHeader", {}
        )
        message = error_header.get("returnAuthMsg") or error_header.get("errMsg")
        detail = f": {message}" if message else ""
        raise RuntimeError(
            f"기상청 API 호출 실패: HTTP {status_code}{detail}"
        )

    if data is None:
        raise RuntimeError("기상청 API가 JSON이 아닌 응답을 반환했습니다.")

    if "response" not in data:
        raise RuntimeError("기상청 API 응답 오류")

    api_response = data["response"]
    header = api_response.get("header", {})
    if header.get("resultCode") != "00":
        message = header.get("resultMsg", "알 수 없는 오류")
        raise RuntimeError(f"기상청 API 응답 오류: {message}")

    items = api_response.get("body", {}).get("items", {}).get("item", [])
    if not items:
        raise RuntimeError("기상청 API 예보 데이터가 없습니다.")

    forecasts = {}

    for item in items:
        category = item["category"]

        if category in ["SKY", "PTY", "TMP"]:
            forecast_key = (item["fcstDate"], item["fcstTime"])
            forecasts.setdefault(forecast_key, {})[category] = item["fcstValue"]

    complete_forecasts = {
        key: values
        for key, values in forecasts.items()
        if {"SKY", "PTY", "TMP"}.issubset(values)
    }
    if not complete_forecasts:
        raise RuntimeError("기상청 API 응답에 완전한 SKY/PTY/TMP 예보가 없습니다.")

    target_time = (target_time or datetime.now(KST)).astimezone(KST)

    def forecast_datetime(key):
        date, time = key
        return datetime.strptime(date + time, "%Y%m%d%H%M").replace(tzinfo=KST)

    selected_key = min(
        complete_forecasts,
        key=lambda key: abs((forecast_datetime(key) - target_time).total_seconds()),
    )

    return complete_forecasts[selected_key], forecast_datetime(selected_key)


def calculate_light(weather, sun_elevation):
    sky = int(weather.get("SKY", 1))
    pty = int(weather.get("PTY", 0))

    if sun_elevation >= 20:
        brightness = 10
    elif sun_elevation <= -6:
        brightness = 70
    else:
        brightness = 10 + (20 - sun_elevation) * (60 / 26)

    if sky == 3:
        brightness += 10
    elif sky == 4:
        brightness += 20

    if pty != 0:
        brightness += 20

    brightness = round(clamp(brightness, 0, 97))

    if sun_elevation >= 20:
        kelvin = 4500
    elif sun_elevation <= -6:
        kelvin = 2700
    else:
        kelvin = 2700 + (sun_elevation + 6) * (1800 / 26)

    if sky == 3:
        kelvin -= 150
    elif sky == 4:
        kelvin -= 300

    if pty != 0:
        kelvin = min(kelvin, 3200)

    kelvin = round(clamp(kelvin, MIN_COLOR_TEMP_KELVIN, MAX_COLOR_TEMP_KELVIN))

    return brightness, kelvin


def should_turn_on(weather, sun_elevation):
    sky = int(weather.get("SKY", 1))
    pty = int(weather.get("PTY", 0))
    return sun_elevation < DAYLIGHT_OFF_ELEVATION or sky in (3, 4) or pty != 0


def publish_helper_states(config, is_on, brightness, kelvin, weather):
    set_ha_boolean(config, ENTITY_LIGHT_POWER, is_on)
    set_ha_number(config, ENTITY_LIGHT_BRIGHTNESS, brightness)
    set_ha_number(config, ENTITY_LIGHT_KELVIN, kelvin)
    set_ha_number(config, ENTITY_WEATHER_SKY, int(weather.get("SKY", 1)))
    set_ha_number(config, ENTITY_WEATHER_PTY, int(weather.get("PTY", 0)))


def main(*, check_location=False):
    config = load_config(require_lighting=not check_location)
    try:
        location = load_location(config)
    except LocationNotConfigured:
        print("거주 지역 미설정: 앱에서 지역을 저장해 주세요. 조명 명령은 전송하지 않았습니다.")
        return 2

    if check_location:
        source = "Render" if location.get("source") == "render" else "장비의 기존 위치 설정"
        print(f"지역 조회 확인 완료: {source} · 기상청 격자 확인됨")
        print("조명 명령은 전송하지 않았습니다.")
        return

    nx = location["nx"]
    ny = location["ny"]

    base_date, base_time = get_base_date_time()
    weather, forecast_time = get_weather(config, nx, ny, base_date, base_time)

    sun_elevation = get_sun_elevation(config)
    brightness, kelvin = calculate_light(weather, sun_elevation)
    is_on = should_turn_on(weather, sun_elevation)

    print(
        "지역:",
        location.get("sido", ""),
        location.get("sigungu", ""),
        location.get("dong", ""),
    )
    print("nx:", nx)
    print("ny:", ny)
    print("base_date:", base_date)
    print("base_time:", base_time)
    print("선택한 예보 시각:", forecast_time.strftime("%Y-%m-%d %H:%M KST"))
    print("날씨 데이터:", weather)
    print("태양 고도:", sun_elevation)
    print("조명 전원:", "켜기" if is_on else "끄기")
    print("조명 밝기:", brightness)
    print("조명 색온도:", kelvin)

    set_ha_light(
        config,
        config["ha_light_entity_id"],
        is_on,
        brightness,
        kelvin,
    )

    if config["publish_helper_states"]:
        publish_helper_states(config, is_on, brightness, kelvin, weather)

    print(f"Home Assistant 실제 조명 제어 완료: {config['ha_light_entity_id']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pauseable 날씨·조명 제어")
    parser.add_argument("--check-location", action="store_true", help="지역 조회만 확인하며 조명을 제어하지 않음")
    raise SystemExit(main(check_location=parser.parse_args().check_location))
