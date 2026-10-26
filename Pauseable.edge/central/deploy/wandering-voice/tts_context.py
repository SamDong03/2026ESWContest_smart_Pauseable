#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PLACEHOLDER = "{{patient_call_name}}"
DEFAULT_API_BASE_URL = "https://pauseable-api.onrender.com"
DEFAULT_PATIENT_ID = "byunwoojin"
DEFAULT_CALL_NAME = "할머니"


def normalize_call_name(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    call_name = value.strip()
    if not call_name or len(call_name) > 40:
        return fallback
    if any(ord(character) < 32 or ord(character) == 127 for character in call_name):
        return fallback
    return call_name


def fetch_call_name(
    *,
    api_base_url: str,
    patient_id: str,
    device_token: str,
    fallback: str,
    timeout: float = 15,
) -> str:
    if not device_token:
        raise RuntimeError("PAUSEABLE_DEVICE_TOKEN is not configured")

    url = (
        f"{api_base_url.rstrip('/')}"
        f"/api/device/patients/{quote(patient_id, safe='')}/tts-context"
    )
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {device_token}",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)

    if payload.get("patient_id") != patient_id:
        raise RuntimeError("TTS context patient does not match the request")
    if not payload.get("is_configured"):
        return fallback
    return normalize_call_name(payload.get("patient_call_name"), fallback)


def render_template(template: str, call_name: str) -> str:
    return template.replace(PLACEHOLDER, call_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument(
        "--fallback",
        default=os.getenv("PATIENT_CALL_NAME_FALLBACK", DEFAULT_CALL_NAME),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    template = args.template.read_text(encoding="utf-8").strip()
    if PLACEHOLDER not in template:
        print(template)
        return 0

    fallback = normalize_call_name(args.fallback, DEFAULT_CALL_NAME)
    try:
        call_name = fetch_call_name(
            api_base_url=os.getenv("PAUSEABLE_API_BASE_URL", DEFAULT_API_BASE_URL),
            patient_id=os.getenv("PATIENT_ID", DEFAULT_PATIENT_ID),
            device_token=os.getenv("PAUSEABLE_DEVICE_TOKEN", ""),
            fallback=fallback,
        )
    except (HTTPError, URLError, OSError, ValueError, RuntimeError, json.JSONDecodeError):

        print("TTS_CONTEXT_FALLBACK reason=context_unavailable", file=sys.stderr)
        call_name = fallback

    print(render_template(template, call_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
