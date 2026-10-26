#!/usr/bin/env python3


from __future__ import annotations

import argparse
import json
import os
import time
from urllib.error import HTTPError
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


def entity_state(entity_id: str) -> str:
    result = request_json(f"/api/states/{entity_id}")
    return str(result.get("state", "unknown"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--entity-id",
        default="switch.gonggiceongjeonggi_power",
    )
    parser.add_argument("--desired-state", choices=("on", "off"), default="on")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()

    if entity_state(args.entity_id) == args.desired_state:
        print(
            f"AIR_PURIFIER_ALREADY_{args.desired_state.upper()} entity={args.entity_id}",
            flush=True,
        )
        return

    service = f"turn_{args.desired_state}"
    try:
        request_json(
            f"/api/services/switch/{service}",
            {"entity_id": args.entity_id},
        )
        print(
            f"AIR_PURIFIER_TURN_{args.desired_state.upper()}_REQUESTED "
            f"entity={args.entity_id}",
            flush=True,
        )
    except HTTPError as error:

        body = error.read().decode("utf-8", errors="replace")
        print(
            f"AIR_PURIFIER_TURN_{args.desired_state.upper()}_HTTP_ERROR "
            f"status={error.code} body={body[:300]}",
            flush=True,
        )

    deadline = time.monotonic() + args.timeout_seconds
    while time.monotonic() < deadline:
        if entity_state(args.entity_id) == args.desired_state:
            print(
                f"AIR_PURIFIER_{args.desired_state.upper()} entity={args.entity_id}",
                flush=True,
            )
            return
        time.sleep(args.poll_seconds)

    raise RuntimeError(
        f"Air purifier did not reach {args.desired_state} state within "
        f"{args.timeout_seconds:g} seconds"
    )


if __name__ == "__main__":
    main()
