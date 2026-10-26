#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import os
import socket
import time
from urllib.request import Request, urlopen


def request_json(path: str, payload: dict | None = None):
    base = os.environ["HA_URL"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['HA_TOKEN']}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = Request(base + path, data=data, headers=headers)
    with urlopen(request, timeout=30) as response:
        body = response.read()
    return json.loads(body) if body else None


def state(entity_id: str) -> str:
    return str(request_json(f"/api/states/{entity_id}").get("state", "unknown"))


def call_service(domain: str, service: str, payload: dict) -> None:
    request_json(f"/api/services/{domain}/{service}", payload)


def launch_youtube(tv_entity: str, video_id: str) -> None:
    call_service(
        "webostv",
        "command",
        {
            "entity_id": tv_entity,
            "command": "system.launcher/launch",
            "payload": {
                "id": "youtube.leanback.v4",
                "contentId": f"v={video_id}",
            },
        },
    )


def send_wake_on_lan(mac_address: str, broadcast_address: str) -> None:
    mac = bytes.fromhex(mac_address.replace(":", "").replace("-", ""))
    if len(mac) != 6:
        raise ValueError("Wake-on-LAN MAC address must contain six bytes")
    packet = b"\xff" * 6 + mac * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(5):
            sock.sendto(packet, (broadcast_address, 9))
            time.sleep(0.2)
    print(f"TV_WOL_SENT mac={mac_address} broadcast={broadcast_address}", flush=True)


def ensure_tv_on(
    tv_entity: str,
    mac_address: str | None,
    broadcast_address: str,
    timeout: float,
) -> None:
    if state(tv_entity) == "on":
        return

    if not mac_address:
        raise ValueError("TV_MAC is required when the TV must be woken")
    send_wake_on_lan(mac_address, broadcast_address)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if state(tv_entity) == "on":
                print("TV_READY", flush=True)
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"TV did not become ready within {timeout:g} seconds")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tv-entity",
        default=os.getenv("TV_ENTITY", "media_player.lg_webos_tv"),
    )
    parser.add_argument("--tv-mac", default=os.getenv("TV_MAC"))
    parser.add_argument(
        "--broadcast-address",
        default=os.getenv("TV_BROADCAST_ADDRESS", "255.255.255.255"),
    )
    parser.add_argument(
        "--video-id",
        default=os.getenv("TV_YOUTUBE_VIDEO_ID", "-ra8Hpyylpw"),
    )
    parser.add_argument("--wake-timeout", type=float, default=45.0)
    parser.add_argument("--account-picker-delay", type=float, default=12.0)
    args = parser.parse_args()

    ensure_tv_on(args.tv_entity, args.tv_mac, args.broadcast_address, args.wake_timeout)
    launch_youtube(args.tv_entity, args.video_id)
    print(
        f"TV_YOUTUBE_INITIAL_REQUEST entity={args.tv_entity} video_id={args.video_id}",
        flush=True,
    )


    time.sleep(args.account_picker_delay)
    call_service(
        "webostv",
        "button",
        {
            "entity_id": args.tv_entity,
            "button": "ENTER",
        },
    )
    print("TV_YOUTUBE_PROFILE_CONFIRMED button=ENTER", flush=True)
    print(f"TV_YOUTUBE_REQUESTED entity={args.tv_entity} video_id={args.video_id}", flush=True)


if __name__ == "__main__":
    main()
