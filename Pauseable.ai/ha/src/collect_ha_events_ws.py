import argparse
import base64
import csv
import hashlib
import json
import os
import socket
import ssl
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from collect_ha_states import (
    DEFAULT_ENTITY_KEYWORDS,
    FIELDNAMES,
    append_rows,
    entity_is_selected,
    normalize_ha_url,
    selected_states,
    state_to_row,
)


MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketError(RuntimeError):
    pass


def resolve_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[1] / path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def websocket_url(ha_url):
    base = normalize_ha_url(ha_url)
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https", "ws", "wss"}:
        raise ValueError(f"unsupported Home Assistant URL scheme: {parsed.scheme}")

    scheme = "wss" if parsed.scheme in {"https", "wss"} else "ws"
    path = parsed.path.rstrip("/")
    return f"{scheme}://{parsed.netloc}{path}/api/websocket"


def read_until(sock, marker):
    data = b""
    while marker not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise WebSocketError("socket closed while reading handshake")
        data += chunk
    return data


class SimpleWebSocket:
    def __init__(self, url, timeout):
        self.url = url
        self.timeout = timeout
        self.sock = None
        self.buffer = b""
        self.deadline = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def connect(self):
        parsed = urlparse(self.url)
        if parsed.scheme not in {"ws", "wss"}:
            raise ValueError(f"unsupported WebSocket URL scheme: {parsed.scheme}")

        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        raw_sock = socket.create_connection((host, port), timeout=self.timeout)
        raw_sock.settimeout(self.timeout)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            self.sock = context.wrap_socket(raw_sock, server_hostname=host)
        else:
            self.sock = raw_sock

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host_header = host if parsed.port is None else f"{host}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response_bytes = read_until(self.sock, b"\r\n\r\n")
        header_bytes, self.buffer = response_bytes.split(b"\r\n\r\n", 1)
        response = header_bytes.decode("iso-8859-1")
        header_lines = response.split("\r\n")
        if not header_lines or " 101 " not in header_lines[0]:
            raise WebSocketError(f"WebSocket handshake failed: {header_lines[0] if header_lines else response}")

        headers = {}
        for line in header_lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()

        accept = headers.get("sec-websocket-accept", "")
        expected = base64.b64encode(hashlib.sha1((key + MAGIC).encode("ascii")).digest()).decode("ascii")
        if accept != expected:
            raise WebSocketError("invalid Sec-WebSocket-Accept header")

    def close(self):
        if self.sock is None:
            return
        try:
            self.send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None

    def _read_exact(self, length):
        data = b""
        if self.buffer:
            take = min(length, len(self.buffer))
            data = self.buffer[:take]
            self.buffer = self.buffer[take:]
        while len(data) < length:
            if self.deadline is not None:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise socket.timeout("collection deadline reached")
                self.sock.settimeout(min(self.timeout, remaining))
            try:
                chunk = self.sock.recv(length - len(data))
            except socket.timeout:
                if data:
                    raise WebSocketError("timeout inside WebSocket frame; reconnecting")
                raise
            if not chunk:
                raise WebSocketError("socket closed")
            data += chunk
        return data

    def send_frame(self, opcode, payload):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        first = 0x80 | opcode
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, 0x80 | length)
        elif length < (1 << 16):
            header = struct.pack("!BBH", first, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", first, 0x80 | 127, length)

        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def recv_frame(self):
        first, second = struct.unpack("!BB", self._read_exact(2))
        try:
            return self._read_frame_body(first, second)
        except socket.timeout as error:
            raise WebSocketError("timeout inside WebSocket frame; reconnecting") from error

    def _read_frame_body(self, first, second):
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F

        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]

        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))

        return opcode, payload

    def send_json(self, data):
        self.send_frame(0x1, json.dumps(data, ensure_ascii=False))

    def recv_json(self):
        while True:
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise socket.timeout("collection deadline reached")
            opcode, payload = self.recv_frame()
            if opcode == 0x1:
                return json.loads(payload.decode("utf-8"))
            if opcode == 0x8:
                raise WebSocketError("server closed WebSocket")
            if opcode == 0x9:
                self.send_frame(0xA, payload)
            elif opcode == 0xA:
                continue


def authenticate(ws, token):
    message = ws.recv_json()
    if message.get("type") != "auth_required":
        raise WebSocketError(f"expected auth_required, got: {message}")

    ws.send_json({"type": "auth", "access_token": token})
    message = ws.recv_json()
    if message.get("type") == "auth_invalid":
        raise WebSocketError(f"Home Assistant auth failed: {message.get('message', '')}")
    if message.get("type") != "auth_ok":
        raise WebSocketError(f"expected auth_ok, got: {message}")
    return message


def wait_for_result(ws, command_id, event_handler=None):
    while True:
        message = ws.recv_json()
        if message.get("type") == "event":
            if event_handler:
                event_handler(message.get("event") or {})
            continue

        if message.get("type") == "result" and message.get("id") == command_id:
            if not message.get("success"):
                raise WebSocketError(f"command failed: {message}")
            return message.get("result")


def subscribe_state_changed(ws, command_id, event_handler=None):
    ws.send_json({
        "id": command_id,
        "type": "subscribe_events",
        "event_type": "state_changed",
    })
    wait_for_result(ws, command_id, event_handler)


def get_states(ws, command_id, event_handler=None):
    ws.send_json({"id": command_id, "type": "get_states"})
    return wait_for_result(ws, command_id, event_handler) or []


def event_to_row(event, include_attribute_only):
    data = event.get("data") or {}
    new_state = data.get("new_state") or {}
    old_state = data.get("old_state") or {}

    if new_state.get("entity_id", "").startswith("climate."):
        keys = ("temperature", "fan_mode")
        include_attribute_only = include_attribute_only or any(
            (old_state.get("attributes") or {}).get(key) !=
            (new_state.get("attributes") or {}).get(key) for key in keys)

    if not new_state:
        if not old_state:
            return None
        new_state = {**old_state, 'state': 'unavailable'}

    if (
        old_state
        and not include_attribute_only
        and old_state.get("state") == new_state.get("state")
    ):
        return None

    row = state_to_row(new_state, "state_changed_event", utc_now())
    row["event_time"] = event.get("time_fired") or row["event_time"]
    return row


def selected_entity(entity_id, keywords, behavior_only, entity_ids=(), excluded_ids=()):
    if entity_id in excluded_ids:
        return False
    return entity_id in entity_ids if entity_ids else entity_is_selected(entity_id, keywords, behavior_only)


def append_event_row(output_path, event, keywords, behavior_only, include_attribute_only,
                     entity_ids=(), excluded_ids=()):
    row = event_to_row(event, include_attribute_only)
    if not row:
        return 0

    if not selected_entity(row['entity_id'], keywords, behavior_only, entity_ids, excluded_ids):
        return 0

    append_rows(output_path, [row])
    return 1


def selected_keywords(args):
    if args.include_all:
        return []
    if args.entity_keyword:
        return args.entity_keyword
    return DEFAULT_ENTITY_KEYWORDS


def should_stop(deadline, max_events, written):
    if max_events > 0 and written >= max_events:
        return True
    if deadline is not None and time.monotonic() >= deadline:
        return True
    return False


def run_session(args, output_path, token, ha_url, keywords, deadline, written):
    ws_url = websocket_url(ha_url)
    with SimpleWebSocket(ws_url, args.timeout) as ws:
        ws.deadline = deadline
        auth = authenticate(ws, token)
        print(f"websocket connected: {ws_url} ({auth.get('ha_version', 'unknown')})")

        entity_ids = getattr(args, 'entity_id', [])
        excluded_ids = getattr(args, 'exclude_entity_id', [])
        snapshot_events = set()

        def handle(event):
            nonlocal written
            snapshot_events.add((event.get('data') or {}).get('entity_id'))
            written += append_event_row(output_path, event, keywords, args.behavior_only,
                                        args.include_attribute_only, entity_ids, excluded_ids)

        command_id = 1
        subscribe_state_changed(ws, command_id, handle)
        print("subscribed: state_changed")
        session_start = utc_now()
        coverage_path = output_path.with_suffix('.coverage.json')

        def confirm():
            data = json.loads(coverage_path.read_text()) if coverage_path.exists() else {'intervals': []}
            now = utc_now()
            intervals = data['intervals']
            if intervals and intervals[-1][0] == session_start:
                intervals[-1][1] = now
            else:
                intervals.append([session_start, now])
            cutoff = datetime.now(timezone.utc).timestamp() - 3 * 3600
            data['intervals'] = [item for item in intervals if datetime.fromisoformat(item[1]).timestamp() >= cutoff]
            data['confirmed_at'] = now
            temp = coverage_path.with_suffix('.tmp')
            temp.write_text(json.dumps(data), encoding='utf-8')
            temp.replace(coverage_path)

        if args.write_initial_snapshot:
            command_id += 1
            snapshot_events.clear()
            states = [item for item in get_states(ws, command_id, handle)
                      if selected_entity(item.get('entity_id'), keywords, args.behavior_only, entity_ids, excluded_ids)
                      and item.get('entity_id') not in snapshot_events]
            rows = [
                state_to_row(item, "state_snapshot", utc_now())
                for item in states
            ]
            append_rows(output_path, rows)
            written += len(rows)
            print(f"initial snapshot rows written: {len(rows)} total: {written}")
        confirm()

        last_status = time.monotonic()
        pending_ping = None
        while not should_stop(deadline, args.max_events, written):
            try:
                message = ws.recv_json()
            except socket.timeout:
                if should_stop(deadline, args.max_events, written):
                    break
                if pending_ping is not None:
                    raise WebSocketError('Home Assistant heartbeat timed out')
                command_id += 1
                pending_ping = command_id
                ws.send_json({'id': pending_ping, 'type': 'ping'})
                now = time.monotonic()
                if now - last_status >= args.status_every_seconds:
                    print(f"listening... total rows: {written}")
                    last_status = now
                continue
            except WebSocketError as exc:
                print(f"websocket session ended: {exc}")
                return written
            except OSError as exc:
                print(f"websocket session ended: {exc}")
                return written

            if message.get('type') == 'pong' and message.get('id') == pending_ping:
                pending_ping = None
                confirm()
            if message.get("type") != "event":
                continue
            confirm()

            event = message.get("event") or {}
            wrote = append_event_row(
                output_path,
                event,
                keywords,
                args.behavior_only,
                args.include_attribute_only,
                entity_ids, excluded_ids,
            )
            written += wrote
            if wrote:
                row_entity = (event.get("data") or {}).get("entity_id", "")
                print(f"event row written: {row_entity} total: {written}")

    return written


def collect_loop(args):
    from ha_runtime_health import validate_selection
    validate_selection(getattr(args, 'entity_id', []), getattr(args, 'exclude_entity_id', []))
    output_path = resolve_path(args.output)
    token = args.token or os.getenv("HA_TOKEN")
    ha_url = args.ha_url or os.getenv("HA_URL")
    if not token:
        raise ValueError("Home Assistant token is required. Use --token or HA_TOKEN.")
    if not ha_url:
        raise ValueError("Home Assistant URL is required. Use --ha-url or HA_URL.")

    keywords = selected_keywords(args)
    deadline = None
    if args.duration_seconds > 0:
        deadline = time.monotonic() + args.duration_seconds

    written = 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.truncate and output_path.exists():
        output_path.unlink()
    if args.truncate:
        output_path.with_suffix('.coverage.json').unlink(missing_ok=True)

    while not should_stop(deadline, args.max_events, written):
        try:
            written = run_session(
                args,
                output_path,
                token,
                ha_url,
                keywords,
                deadline,
                written,
            )
        except KeyboardInterrupt:
            raise
        except WebSocketError as exc:
            if "auth failed" in str(exc).lower():
                raise
            print(f"websocket session failed: {exc}")
        except OSError as exc:
            print(f"websocket connection failed: {exc}")

        if not should_stop(deadline, args.max_events, written):
            print(f"reconnecting in {args.reconnect_seconds:g}s...")
            time.sleep(args.reconnect_seconds)

    if not output_path.exists():
        with output_path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

    print(f"saved: {output_path}")
    print(f"total rows written: {written}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ha-url", help="Home Assistant base URL, or HA_URL env var")
    parser.add_argument("--token", help="Long-lived access token, or HA_TOKEN env var")
    parser.add_argument("--output", default="data/raw/ha_state_events_ws.csv")
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--reconnect-seconds", type=float, default=5.0)
    parser.add_argument("--status-every-seconds", type=float, default=60.0)
    parser.add_argument("--max-events", type=int, default=0)
    parser.add_argument("--entity-keyword", action="append")
    parser.add_argument("--include-all", action="store_true")
    parser.add_argument("--behavior-only", action="store_true", default=True)
    parser.add_argument("--include-telemetry", dest="behavior_only", action="store_false")
    parser.add_argument("--include-attribute-only", action="store_true")
    parser.add_argument('--entity-id', action='append', default=[])
    parser.add_argument('--exclude-entity-id', action='append', default=[])
    parser.add_argument("--write-initial-snapshot", action="store_true")
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    try:
        collect_loop(args)
    except KeyboardInterrupt:
        print("stopped by user")


if __name__ == "__main__":
    main()
