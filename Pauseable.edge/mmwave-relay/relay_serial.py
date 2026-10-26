

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import select
import socket
import sys
import time

from validate_event import ContractError, MAX_PACKET_BYTES, parse_event


class SerialDecoder:
    def __init__(self, sensor_id="esp32-ld6004-living-room-01"):
        self.sensor_id = sensor_id
        self.buffer = bytearray()
        self.discarding = False
        self.counts = {
            "valid": 0, "invalid": 0, "diagnostics": 0, "oversized": 0,
            "wrong_source": 0, "boots": 0, "brownouts": 0,
        }
        self.last_status = None
        self.last_event = None

    def _line(self, raw):
        payload = raw[:-1] if raw.endswith(b"\r") else raw
        if len(payload) > MAX_PACKET_BYTES:
            self.counts["oversized"] += 1
            return None
        if not payload.startswith(b"{"):
            if payload.strip():
                self.counts["diagnostics"] += 1
                if payload.startswith(b"BOOT "):
                    self.counts["boots"] += 1
                if b"Brownout" in payload:
                    self.counts["brownouts"] += 1
                if payload.startswith(b"STATUS "):
                    self.last_status = {
                        key.decode("ascii"): int(value)
                        for key, value in re.findall(
                            rb"(uptime_ms|checksum_errors|malformed|target_frames)=([0-9]+)", payload
                        )
                    }
            return None
        try:
            event = parse_event(payload)
        except ContractError:
            self.counts["invalid"] += 1
            return None
        if (event["data_origin"] != "live"
                or event["source"] != "esp32-ld6004"
                or event["sensor_id"] != self.sensor_id):
            self.counts["wrong_source"] += 1
            return None
        self.counts["valid"] += 1
        self.last_event = event
        return payload, event

    def feed(self, data):
        if self.discarding:
            delimiter = data.find(b"\n")
            if delimiter < 0:
                return []
            data = data[delimiter + 1:]
            self.discarding = False
        self.buffer.extend(data)
        output = []
        while True:
            delimiter = self.buffer.find(b"\n")
            if delimiter < 0:
                break
            raw = bytes(self.buffer[:delimiter])
            del self.buffer[:delimiter + 1]
            result = self._line(raw)
            if result is not None:
                output.append(result)

        if len(self.buffer) > MAX_PACKET_BYTES + 1:
            self.counts["oversized"] += 1
            self.buffer.clear()
            self.discarding = True
        return output

    def finish_log(self):


        if self.discarding or not self.buffer:
            return []
        raw = bytes(self.buffer)
        self.buffer.clear()
        result = self._line(raw)
        return [] if result is None else [result]

    def summary(self):
        result = dict(self.counts)
        result["partial_bytes"] = len(self.buffer)
        result["sensor_status_counters"] = self.last_status
        if self.last_event is not None:
            result.update({
                key: self.last_event[key]
                for key in ("session_id", "seq", "uptime_ms", "target_count", "sensor_status")
            })
        return result


def announce(status, **values):
    print(json.dumps({"relay": status, **values}, allow_nan=False), file=sys.stderr, flush=True)


def open_serial(device, baud):

    import termios

    baud_code = getattr(termios, "B" + str(baud), None)
    if baud_code is None:
        raise ValueError("Unsupported Linux serial baud rate")
    fd = os.open(device, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = 0
        attrs[1] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[3] = 0
        attrs[4] = baud_code
        attrs[5] = baud_code
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)

        termios.tcflush(fd, termios.TCIFLUSH)
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_pipe(fd, payload, timeout=2.0):
    deadline = time.monotonic() + timeout
    remaining = memoryview(payload + b"\n")
    while remaining:
        wait = deadline - time.monotonic()
        if wait <= 0 or not select.select([], [fd], [], wait)[1]:
            raise TimeoutError("SSH output blocked; relay stopped instead of accumulating old frames")
        try:
            written = os.write(fd, remaining)
        except BlockingIOError:
            continue
        if written <= 0:
            raise BrokenPipeError("SSH output closed")
        remaining = remaining[written:]


def check_log(path, sensor_id):
    decoder = SerialDecoder(sensor_id)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4096), b""):
            decoder.feed(chunk)
    decoder.finish_log()
    announce("LOG_CHECK", **decoder.summary())
    return 0 if decoder.counts["valid"] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=230400)
    parser.add_argument("--sensor-id", default="esp32-ld6004-living-room-01")
    parser.add_argument("--udp-host", help="Optional IPv4 copy to the existing Central receiver")
    parser.add_argument("--udp-port", type=int, default=5005)
    parser.add_argument("--record-dir", type=Path, default=Path.home() / "pauseable-mmwave-captures")
    parser.add_argument("--duration", type=float, default=0, help="0 = until Ctrl+C; 600 = ten minutes")
    parser.add_argument("--check-log", type=Path, help="Validate a saved log without serial/network access")
    args = parser.parse_args()
    if args.check_log:
        return check_log(args.check_log, args.sensor_id)
    if sys.platform != "linux":
        parser.error("Live USB mode must run on the Pi3")
    if sys.stdout.isatty():
        parser.error("Pipe stdout through SSH to the Pi5 FIFO")
    if not (0 < args.udp_port <= 65535) or not (0 <= args.duration < float("inf")):
        parser.error("Invalid port or duration")
    if args.udp_host:
        try:
            ipaddress.IPv4Address(args.udp_host)
        except ValueError:
            parser.error("--udp-host requires an IPv4 address")

    decoder = SerialDecoder(args.sensor_id)
    serial_fd = None
    udp = None
    record = None
    written = udp_sent = udp_errors = 0
    started = time.monotonic()
    last_report = started
    record_path = None
    result = 0
    try:
        args.record_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        record_path = args.record_dir / ("capture-" + stamp + ".jsonl")
        record = record_path.open("xb")
        serial_fd = open_serial(args.device, args.baud)
        if args.udp_host:
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.setblocking(False)
        stdout_fd = sys.stdout.fileno()
        os.set_blocking(stdout_fd, False)
        announce("READY", device=args.device, baud=args.baud, recording=str(record_path))
        while True:
            now = time.monotonic()
            if args.duration and now - started >= args.duration:
                break
            if select.select([serial_fd], [], [], 0.25)[0]:
                try:
                    data = os.read(serial_fd, 4096)
                except BlockingIOError:
                    data = None
                if data == b"":
                    raise OSError("USB serial device stopped providing data")
                if data:
                    for payload, event in decoder.feed(data):
                        record.write(payload + b"\n")
                        if udp is not None:
                            try:
                                udp.sendto(payload, (args.udp_host, args.udp_port))
                                udp_sent += 1
                            except OSError:
                                udp_errors += 1
                        write_pipe(stdout_fd, payload)
                        written += 1
            if time.monotonic() - last_report >= 5:
                record.flush()
                elapsed = time.monotonic() - started
                announce("RUNNING", elapsed_seconds=round(elapsed, 1),
                         stream_written=written, udp_send_calls=udp_sent, udp_errors=udp_errors,
                         **decoder.summary())
                last_report = time.monotonic()
    except KeyboardInterrupt:
        announce("STOP_REQUESTED")
    except (OSError, ValueError) as error:
        announce("ERROR", message=str(error))
        result = 2
    finally:
        if serial_fd is not None:
            os.close(serial_fd)
        if udp is not None:
            udp.close()
        if record is not None:
            record.close()
        announce("STOPPED", elapsed_seconds=round(time.monotonic() - started, 1),
                 stream_written=written, udp_send_calls=udp_sent, udp_errors=udp_errors,
                 recording=str(record_path) if record_path is not None else None, **decoder.summary())
    return result


if __name__ == "__main__":
    raise SystemExit(main())
