

from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
import importlib.util
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

RECEIVER: Path | None = None
CONTRACT_DIR: Path | None = None
SIMULATOR: Path | None = None
CONTRACT = None


def event(seq=0, *, origin="simulated", session="integration-session",
          status="ok", count=1, age=0, uptime=None):
    sources = {"live": "esp32-ld6004", "simulated": "pauseable-simulator", "replay": "pauseable-replay"}
    packet = {
        "schema_version": "1.0", "event_id": f"test-radar:{session}:{seq}",
        "source": sources[origin], "data_origin": origin,
        "sensor_id": "test-radar", "session_id": session, "seq": seq,
        "occurred_at": None, "time_status": "unsynced",
        "uptime_ms": seq * 100 if uptime is None else uptime,
        "measurement_profile": "ld6004-target-raw-v1", "sensor_status": status,
        "frame_age_ms": age if status == "ok" else None,
        "target_count": count, "targets_truncated": False,
        "targets": [{"id": index + 1, "x": -1.2 + index, "y": 0.5,
                     "z": 1.3, "doppler": -1} for index in range(count)],
        "replay": None,
    }
    if origin == "replay":
        packet["replay"] = {
            "log_id": "integration-log", "frame_index": seq,
            "original_origin": "simulated", "original_event_id": "old:session:0",
            "original_occurred_at": None,
        }
    encoded(packet)
    return packet


def encoded(packet):
    payload = json.dumps(packet, separators=(",", ":"), allow_nan=False).encode("utf-8")
    CONTRACT.parse_event(payload)
    return payload


class Receiver(AbstractContextManager):
    pass

    def __init__(self, *options, duration=900):
        self.messages = []
        self.errors = []
        self.output = queue.Queue()
        self.sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.process = subprocess.Popen(
            [str(RECEIVER), "--bind", "127.0.0.1", "--port", "0",
             "--duration-ms", str(duration), "--summary-ms", "50", *options],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="strict", bufsize=1,
        )
        self.stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()
        try:
            ready = self.wait_for(lambda message: message.get("kind") == "mmwave_ready", timeout=5)
            self.address = (ready["address"], ready["port"])
            if not 1 <= ready["port"] <= 65535:
                raise AssertionError("--port 0 did not select a usable port")
        except BaseException:
            self.close()
            raise

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                self.output.put(json.loads(line))
        except BaseException as error:
            self.output.put({"test_reader_error": str(error)})
        finally:
            self.output.put(None)

    def _read_stderr(self):
        try:
            for line in self.process.stderr:
                self.errors.append(line)
        except BaseException as error:
            self.errors.append(str(error))

    def _record(self, message):
        if message is None:
            return False
        if "test_reader_error" in message:
            raise AssertionError(message["test_reader_error"])
        self.messages.append(message)
        return True

    def wait_for(self, predicate, timeout=2):
        for message in self.messages:
            if predicate(message):
                return message
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.output.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                break
            if not self._record(message):
                break
            if predicate(message):
                return message
        raise AssertionError(f"Receiver report not observed. stderr={''.join(self.errors)!r}; "
                             f"reports={self.messages[-4:]!r}")

    def send_raw(self, payload):
        sent = self.sender.sendto(payload, self.address)
        if sent != len(payload):
            raise AssertionError("Short UDP send")

    def send(self, packet):
        self.send_raw(encoded(packet))

    def finish(self, timeout=5):
        self.process.wait(timeout=timeout)
        self.stdout_thread.join(timeout=1)
        self.stderr_thread.join(timeout=1)
        while True:
            try:
                self._record(self.output.get_nowait())
            except queue.Empty:
                break
        if self.process.returncode != 0:
            raise AssertionError(f"Receiver exited {self.process.returncode}: {self.errors!r}")
        final = [item for item in self.messages if item.get("kind") == "mmwave_stopped"]
        if len(final) != 1:
            raise AssertionError("Expected exactly one normal stopped summary")
        return final[0]

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.stdout_thread.join(timeout=1)
        self.stderr_thread.join(timeout=1)
        self.process.stdout.close()
        self.process.stderr.close()
        self.sender.close()

    def __exit__(self, *_):
        self.close()


class ReceiverIntegrationTests(unittest.TestCase):
    def setUp(self):
        if RECEIVER is None:
            self.skipTest("Native integration is opt-in: run this script with --receiver PATH")

    def test_valid_detected_empty_and_error_packets_are_preserved(self):
        packets = [event(0), event(1, count=0), event(2, status="error", count=0)]
        with Receiver() as receiver:
            for packet in packets:
                receiver.send(packet)
            final = receiver.finish()
            reports = [m for m in receiver.messages if m.get("kind") == "mmwave_event"]
        self.assertEqual([m["event"] for m in reports], packets)
        self.assertEqual([m["stream"]["observation"] for m in reports],
                         ["target_detected", "no_target_detected", "unknown"])
        self.assertEqual(reports[2]["stream"]["quality"], "sensor_error")
        self.assertEqual(final["counters"]["accepted"], 3)
        self.assertEqual(final["transport"]["invalid"], 0)
        self.assertIsNone(final["streams"][0]["last_event"]["occurred_at"])

    def test_malformed_datagrams_do_not_stop_the_receiver(self):
        duplicate = encoded(event()).replace(b'"seq":0', b'"seq":0,"seq":0')
        invalid = [b"{", b"\xff", b"", duplicate, encoded(event()) + b"\0junk"]
        with Receiver() as receiver:
            for payload in invalid:
                receiver.send_raw(payload)
            receiver.send(event())
            final = receiver.finish()
        self.assertEqual(final["transport"]["invalid"], len(invalid))
        self.assertEqual(final["counters"]["accepted"], 1)

    def test_oversized_datagrams_are_rejected_without_poisoning_next_packet(self):
        with Receiver() as receiver:
            receiver.send_raw(b" " * 4097)
            receiver.send_raw(b" " * 6000)
            receiver.send(event())
            final = receiver.finish()
        self.assertEqual(final["transport"]["oversize"], 2)
        self.assertEqual(final["counters"]["accepted"], 1)

    def test_exact_4096_byte_packet_is_accepted(self):
        payload = encoded(event())
        with Receiver() as receiver:
            receiver.send_raw(payload + b" " * (4096 - len(payload)))
            final = receiver.finish()
        self.assertEqual(final["counters"]["accepted"], 1)
        self.assertEqual(final["transport"]["oversize"], 0)

    def test_duplicate_out_of_order_and_sequence_gap_are_distinguished(self):
        with Receiver() as receiver:
            for seq in (0, 2, 2, 1, 3):
                receiver.send(event(seq))
            final = receiver.finish()
        self.assertEqual(final["counters"]["accepted"], 3)
        self.assertEqual(final["counters"]["duplicate"], 1)
        self.assertEqual(final["counters"]["out_of_order"], 1)
        self.assertEqual(final["counters"]["sequence_gaps_observed"], 1)
        self.assertEqual(final["streams"][0]["last_seq"], 3)

    def test_stale_frame_cannot_be_reported_as_current_presence(self):
        with Receiver("--stale-ms", "100") as receiver:
            receiver.send(event(age=150, uptime=1000))
            report = receiver.wait_for(lambda m: m.get("kind") == "mmwave_event")
        self.assertEqual(report["stream"]["quality"], "stale_frame")
        self.assertEqual(report["stream"]["observation"], "unknown")
        self.assertEqual(report["event"]["frame_age_ms"], 150)

    def test_silence_is_not_misreported_as_zero_targets(self):
        with Receiver("--stale-ms", "120") as receiver:
            receiver.send(event())
            silent = receiver.wait_for(
                lambda m: m.get("kind") == "mmwave_summary" and m["stream_count"] == 1
                and m["streams"][0]["quality"] == "silent")
        self.assertEqual(silent["streams"][0]["observation"], "unknown")
        self.assertEqual(silent["streams"][0]["last_event"]["target_count"], 1)

    def test_no_packets_produces_empty_state_and_stops_on_duration(self):
        with Receiver(duration=180) as receiver:
            final = receiver.finish()
        self.assertEqual(final["stream_count"], 0)
        self.assertEqual(final["transport"]["datagrams"], 0)

    def test_new_session_accepts_reset_seq_and_rejects_retired_session(self):
        with Receiver() as receiver:
            receiver.send(event(10, session="old-session"))
            receiver.send(event(0, session="new-session"))
            receiver.send(event(11, session="old-session"))
            final = receiver.finish()
        self.assertEqual(final["counters"]["accepted"], 2)
        self.assertEqual(final["counters"]["old_session"], 1)
        self.assertEqual(final["streams"][0]["session_id"], "new-session")
        self.assertEqual(final["streams"][0]["last_seq"], 0)

    def test_live_simulated_and_replay_streams_do_not_merge(self):
        with Receiver() as receiver:
            for origin in ("live", "simulated", "replay"):
                receiver.send(event(origin=origin))
            final = receiver.finish()
        self.assertEqual(final["counters"]["accepted"], 3)
        self.assertEqual(final["stream_count"], 3)
        self.assertEqual({s["data_origin"] for s in final["streams"]},
                         {"live", "simulated", "replay"})

    def test_busy_port_fails_cleanly_instead_of_silent_reuse(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as occupied:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            occupied.bind(("127.0.0.1", 0))
            result = subprocess.run(
                [str(RECEIVER), "--bind", "127.0.0.1", "--port",
                 str(occupied.getsockname()[1]), "--duration-ms", "100"],
                capture_output=True, text=True, encoding="utf-8", timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bind", json.loads(result.stderr)["detail"].lower())
        self.assertNotIn("mmwave_ready", result.stdout)

    def test_peer_filter_accepts_matching_ipv4(self):
        with Receiver("--allow-peer", "127.0.0.1") as receiver:
            receiver.send(event())
            final = receiver.finish()
        self.assertEqual(final["counters"]["accepted"], 1)
        self.assertEqual(final["transport"]["peer_rejected"], 0)

    def test_peer_filter_rejects_nonmatching_ipv4(self):
        with Receiver("--allow-peer", "127.0.0.2") as receiver:
            receiver.send(event())
            final = receiver.finish()
        self.assertEqual(final["counters"]["accepted"], 0)
        self.assertEqual(final["transport"]["peer_rejected"], 1)

    def test_rate_cap_counts_drops_and_recovers_in_next_window(self):
        with Receiver("--max-pps", "2", duration=2000) as receiver:
            for seq in range(8):
                receiver.send(event(seq))
            summary = receiver.wait_for(lambda m: m.get("kind") == "mmwave_summary"
                                        and m["transport"]["datagrams"] >= 8)
            self.assertEqual(summary["counters"]["accepted"], 2)
            self.assertEqual(summary["transport"]["rate_limited"], 6)
            time.sleep(1.05)
            receiver.send(event(8))
            receiver.wait_for(lambda m: m.get("kind") == "mmwave_event" and m["seq"] == 8)
            final = receiver.finish()
        self.assertEqual(final["counters"]["accepted"], 3)

    def test_validate_file_mode_and_invalid_argument_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="pauseable-c-validate-") as folder:
            path = Path(folder) / "packet.json"
            path.write_bytes(encoded(event()))
            result = subprocess.run([str(RECEIVER), "--validate", str(path)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), event())
            path.write_bytes(b"{")
            result = subprocess.run([str(RECEIVER), "--validate", str(path)],
                                    capture_output=True, text=True, encoding="utf-8", timeout=5)
            self.assertNotEqual(result.returncode, 0)
        for options in (("--port", "-1"), ("--max-pps", "0"),
                        ("--bind", "bad-address"), ("--allow-peer", "bad-address")):
            with self.subTest(options=options):
                result = subprocess.run([str(RECEIVER), *options, "--duration-ms", "100"],
                                        capture_output=True, text=True, encoding="utf-8", timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stderr)["kind"], "mmwave_error")

    def test_b_simulator_demo_sends_nine_valid_packets(self):
        if SIMULATOR is None:
            self.skipTest("B simulate.py unavailable; pass --simulator PATH")
        with Receiver(duration=1800) as receiver:
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(CONTRACT_DIR) + os.pathsep + environment.get("PYTHONPATH", "")
            sender = subprocess.run(
                [sys.executable, str(SIMULATOR), "--scenario", "demo", "--count", "9",
                 "--interval-ms", "30", "--send", "--host", "127.0.0.1",
                 "--port", str(receiver.address[1]), "--quiet"],
                env=environment, capture_output=True, text=True, encoding="utf-8", timeout=6)
            self.assertEqual(sender.returncode, 0, sender.stderr)
            final = receiver.finish()
            packets = [m["event"] for m in receiver.messages if m.get("kind") == "mmwave_event"]
        self.assertEqual(final["counters"]["accepted"], 9)
        self.assertEqual([p["sensor_status"] for p in packets], ["ok"] * 6 + ["error"] * 3)
        self.assertTrue(all(p["data_origin"] == "simulated" for p in packets))


def main(argv=None):
    global RECEIVER, CONTRACT_DIR, CONTRACT, SIMULATOR
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receiver", type=Path)
    parser.add_argument("--contract-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--simulator", type=Path)
    args, unittest_args = parser.parse_known_args(argv)
    if unittest_args:
        parser.error("Unknown arguments: " + " ".join(unittest_args))
    if args.receiver is None:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReceiverIntegrationTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    RECEIVER = args.receiver.resolve()
    CONTRACT_DIR = args.contract_dir.resolve()
    if not RECEIVER.is_file():
        parser.error("--receiver must name the built native executable")
    validator = CONTRACT_DIR / "validate_event.py"
    if not validator.is_file():
        parser.error("A validate_event.py is missing; provide --contract-dir PATH")
    spec = importlib.util.spec_from_file_location("pauseable_a_contract", validator)
    CONTRACT = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CONTRACT)
    simulator = args.simulator or Path(__file__).resolve().with_name("simulate.py")
    if args.simulator and not simulator.is_file():
        parser.error("--simulator must name an existing B simulate.py")
    SIMULATOR = simulator.resolve() if simulator.is_file() else None
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReceiverIntegrationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
