

from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

import validate_event as contract


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.event = json.loads(
            (contract.EXAMPLES_PATH / "simulated-detected.json").read_text(
                encoding="utf-8"
            )
        )

    def accept(self, event):
        self.assertEqual(contract.validate_event(event), [])
        payload = json.dumps(event, allow_nan=False).encode("utf-8")
        self.assertEqual(contract.parse_event(payload), event)

    def reject(self, event, path=None):
        errors = contract.validate_event(event)
        self.assertTrue(errors, "Invalid event was accepted")
        if path is not None:
            self.assertTrue(any(path in item for item in errors), errors)
        with self.assertRaises(contract.ContractError):
            contract.parse_event(json.dumps(event).encode("utf-8"))

    def test_all_bundled_examples_pass_and_are_marked_as_test_data(self):
        paths = sorted(contract.EXAMPLES_PATH.glob("*.json"))
        self.assertGreaterEqual(len(paths), 5)
        for path in paths:
            with self.subTest(path=path.name):
                event = contract.parse_event(path.read_bytes())
                self.assertIn(event["data_origin"], ("simulated", "replay"))
                if event["data_origin"] == "replay":
                    self.assertEqual(event["replay"]["original_origin"], "simulated")

    def test_live_source_and_unsynced_clock_are_accepted(self):
        self.event.update(
            source="esp32-ld6004", data_origin="live",
            time_status="unsynced", occurred_at=None,
        )
        self.accept(self.event)

    def test_valid_empty_frame_is_distinct_from_unhealthy_sensor(self):
        self.event.update(target_count=0, targets=[])
        self.accept(self.event)
        self.assertEqual(self.event["sensor_status"], "ok")
        for status in ("disconnected", "error"):
            with self.subTest(status=status):
                event = deepcopy(self.event)
                event.update(sensor_status=status, frame_age_ms=None)
                self.accept(event)

    def test_integer_boundaries_and_maximum_identity_length(self):
        for seq in (0, 4294967295):
            with self.subTest(seq=seq):
                event = deepcopy(self.event)
                event.update(sensor_id="a" * 48, session_id="b" * 48, seq=seq)
                event["event_id"] = f"{event['sensor_id']}:{event['session_id']}:{seq}"
                event["uptime_ms"] = 9007199254740991
                event["frame_age_ms"] = event["uptime_ms"]
                event["targets"][0].update(id=4294967295, doppler=-2147483648)
                self.accept(event)

    def test_seq_out_of_range_or_noninteger(self):
        for value in (-1, 4294967296, 1.0, "1", None, True):
            with self.subTest(seq=value):
                event = deepcopy(self.event)
                event["seq"] = value
                self.reject(event, "$.seq")

    def test_numeric_fields_reject_booleans(self):
        for field in ("uptime_ms", "frame_age_ms", "target_count"):
            for value in (False, True):
                with self.subTest(field=field, value=value):
                    event = deepcopy(self.event)
                    event[field] = value
                    self.reject(event, f"$.{field}")
        for field in ("id", "x", "y", "z", "doppler"):
            with self.subTest(target_field=field):
                event = deepcopy(self.event)
                event["targets"][0][field] = True
                self.reject(event, f"$.targets[0].{field}")

    def test_numeric_ranges_and_strict_boolean_flag(self):
        for field, value in (
            ("uptime_ms", -1), ("uptime_ms", 9007199254740992),
            ("frame_age_ms", -1), ("target_count", -1),
            ("target_count", 5), ("targets_truncated", 0),
            ("targets_truncated", "false"),
        ):
            with self.subTest(field=field, value=value):
                event = deepcopy(self.event)
                event[field] = value
                self.reject(event, f"$.{field}")
        for field in ("id", "doppler"):
            for value in (-2147483649, 4294967296, 0.5):
                with self.subTest(target_field=field, value=value):
                    event = deepcopy(self.event)
                    event["targets"][0][field] = value
                    self.reject(event, f"$.targets[0].{field}")

    def test_event_id_must_match_current_sensor_session_and_seq(self):
        for suffix in ("01", "2", "1:extra"):
            with self.subTest(suffix=suffix):
                event = deepcopy(self.event)
                event["event_id"] = f"test-radar:example-session:{suffix}"
                self.reject(event, "$.event_id")
        for field in ("sensor_id", "session_id"):
            with self.subTest(field=field):
                event = deepcopy(self.event)
                event[field] = "another"
                self.reject(event, "$.event_id")

    def test_sensor_and_session_identifiers_reject_delimiters_and_whitespace(self):
        for field in ("sensor_id", "session_id"):
            for value in ("", "bad:id", "with space", "UPPER", "a" * 49, "a\n"):
                with self.subTest(field=field, value=value):
                    event = deepcopy(self.event)
                    event[field] = value
                    self.reject(event, f"$.{field}")

    def test_source_origin_pairs_cannot_mislabel_data(self):
        for origin in contract.SOURCE_BY_ORIGIN:
            for source in contract.SOURCE_BY_ORIGIN.values():
                if source == contract.SOURCE_BY_ORIGIN[origin]:
                    continue
                with self.subTest(origin=origin, source=source):
                    event = deepcopy(self.event)
                    event.update(source=source, data_origin=origin)
                    self.reject(event, "$.source")

    def test_synced_clock_requires_timestamp_and_unsynced_requires_null(self):
        self.event["occurred_at"] = None
        self.reject(self.event, "$.occurred_at")
        self.event.update(time_status="unsynced", occurred_at="2026-09-08T03:00:00Z")
        self.reject(self.event, "$.occurred_at")

    def test_valid_utc_calendar_dates_and_microseconds(self):
        for value in (
            "2024-02-29T23:59:59Z", "2026-09-08T03:00:00.1Z",
            "2026-09-08T03:00:00.123456Z",
        ):
            with self.subTest(timestamp=value):
                event = deepcopy(self.event)
                event["occurred_at"] = value
                self.accept(event)

    def test_timestamp_rejects_invalid_dates_offsets_and_precision(self):
        for value in (
            "2026-02-29T03:00:00Z", "2026-09-31T03:00:00Z",
            "2026-09-08T24:00:00Z", "2026-09-08T03:00:60Z",
            "2026-09-08 03:00:00Z", "2026-09-08T03:00:00+00:00",
            "2026-09-08T03:00:00+09:00", "2026-09-08T03:00:00",
            "2026-09-08T03:00:00.1234567Z", "2026-09-08T03:00:00z",
        ):
            with self.subTest(timestamp=value):
                event = deepcopy(self.event)
                event["occurred_at"] = value
                self.reject(event, "$.occurred_at")

    def test_frame_age_requires_valid_sensor_state_and_session_time(self):
        for age in (None, self.event["uptime_ms"] + 1):
            with self.subTest(age=age):
                event = deepcopy(self.event)
                event["frame_age_ms"] = age
                self.reject(event, "$.frame_age_ms")
        for status in ("disconnected", "error"):
            with self.subTest(status=status):
                event = deepcopy(self.event)
                event.update(sensor_status=status, target_count=0, targets=[])
                self.reject(event, "$.frame_age_ms")

    def test_unhealthy_sensor_cannot_report_targets_or_truncation(self):
        for status in ("disconnected", "error"):
            with self.subTest(status=status):
                event = deepcopy(self.event)
                event.update(sensor_status=status, frame_age_ms=None)
                self.reject(event, "$.sensor_status")
                event.update(target_count=0, targets=[], targets_truncated=True)
                self.reject(event, "$.sensor_status")

    def test_count_mismatch_duplicate_targets_and_limit(self):
        self.event["target_count"] = 0
        self.reject(self.event, "$.target_count")
        self.event["targets"].append(deepcopy(self.event["targets"][0]))
        self.event["target_count"] = 2
        self.reject(self.event, "duplicate target id")
        self.event["targets"] = [
            dict(self.event["targets"][0], id=index) for index in range(5)
        ]
        self.event["target_count"] = 4
        self.reject(self.event, "$.targets")

    def test_truncation_requires_four_transmitted_targets(self):
        self.event["targets_truncated"] = True
        self.reject(self.event, "$.targets_truncated")
        self.event["targets"] = [
            dict(self.event["targets"][0], id=index) for index in range(4)
        ]
        self.event["target_count"] = 4
        self.accept(self.event)
        self.event["targets_truncated"] = False
        self.accept(self.event)

    def replay_event(self):
        return json.loads(
            (contract.EXAMPLES_PATH / "replay-simulated.json").read_text(
                encoding="utf-8"
            )
        )

    def test_replay_of_unstamped_uart_log_accepts_nullable_original_metadata(self):
        event = self.replay_event()
        event["replay"].update(
            original_origin="unknown", original_event_id=None,
            original_occurred_at=None, frame_index=0,
        )
        self.accept(event)

    def test_replay_requires_provenance_and_a_new_event_identity(self):
        event = self.replay_event()
        event["replay"] = None
        self.reject(event, "$.replay")
        event = self.replay_event()
        event["replay"]["original_event_id"] = event["event_id"]
        self.reject(event, "$.replay.original_event_id")
        self.event["replay"] = self.replay_event()["replay"]
        self.reject(self.event, "$.replay")

    def test_replay_metadata_is_strict(self):
        for field, value in (
            ("frame_index", -1), ("frame_index", True),
            ("original_origin", "replay"), ("log_id", "../log"),
            ("original_event_id", ""),
            ("original_occurred_at", "2026-02-30T00:00:00Z"),
        ):
            with self.subTest(field=field, value=value):
                event = self.replay_event()
                event["replay"][field] = value
                self.reject(event, f"$.replay.{field}")
        event = self.replay_event()
        del event["replay"]["log_id"]
        self.reject(event, "$.replay.log_id")

    def test_missing_required_and_unknown_fields(self):
        for field in contract.SCHEMA["required"]:
            with self.subTest(missing=field):
                event = deepcopy(self.event)
                del event[field]
                self.reject(event, f"$.{field}")
        self.event["confidence"] = 0.99
        self.reject(self.event, "$.confidence")
        del self.event["confidence"]
        self.event["targets"][0]["intensity"] = 123
        self.reject(self.event, "$.targets[0].intensity")
        event = self.replay_event()
        event["replay"]["secret_path"] = "not-in-contract"
        self.reject(event, "$.replay.secret_path")

    def test_unknown_version_profile_state_and_nonobject_payload(self):
        for field, value in (
            ("schema_version", "2.0"), ("measurement_profile", "point-cloud-v1"),
            ("sensor_status", "absent"), ("time_status", "estimated"),
            ("data_origin", "unknown"),
        ):
            with self.subTest(field=field):
                event = deepcopy(self.event)
                event[field] = value
                self.reject(event, f"$.{field}")
        for value in (None, [], "event", 1, False):
            with self.subTest(root=value):
                self.reject(value, "$")

    def test_coordinates_reject_nonfinite_numbers_in_decoded_and_wire_form(self):
        for field in ("x", "y", "z"):
            for value in (float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, value=value):
                    event = deepcopy(self.event)
                    event["targets"][0][field] = value
                    self.reject(event, f"$.targets[0].{field}")
        payload = json.dumps(self.event).replace('"x": -1.2', '"x": 1e999')
        with self.assertRaisesRegex(contract.ContractError, "finite"):
            contract.parse_event(payload.encode("utf-8"))

    def test_duplicate_json_keys_are_rejected_at_all_object_levels(self):
        payload = json.dumps(self.event)
        duplicates = (
            payload.replace('"seq": 1', '"seq": 1, "seq": 1'),
            payload.replace('"id": 1', '"id": 1, "id": 1'),
            payload.replace('"seq": 1', '"seq": 1, "\\u0073eq": 1'),
        )
        for duplicate in duplicates:
            with self.subTest(payload=duplicate):
                with self.assertRaisesRegex(contract.ContractError, "Duplicate JSON key"):
                    contract.parse_event(duplicate.encode("utf-8"))

    def test_payload_size_boundary_counts_whitespace_bytes(self):
        payload = json.dumps(self.event).encode("utf-8")
        exact = payload + b" " * (contract.MAX_PACKET_BYTES - len(payload))
        self.assertEqual(len(exact), 4096)
        self.assertEqual(contract.parse_event(exact), self.event)
        with self.assertRaisesRegex(contract.ContractError, "exceeds"):
            contract.parse_event(exact + b" ")

    def test_invalid_encoding_malformed_json_and_multiple_objects(self):
        payload = json.dumps(self.event).encode("utf-8")
        for invalid in (
            b"", b"\xff", b"{", payload + b"{}", b"NaN", b"Infinity",
            b"-Infinity", b"[" * 1100 + b"]" * 1100,
        ):
            with self.subTest(payload=invalid[:40]):
                with self.assertRaises(contract.ContractError):
                    contract.parse_event(invalid)
        with self.assertRaisesRegex(contract.ContractError, "bytes"):
            contract.parse_event(payload.decode("utf-8"))

    def test_future_schema_keywords_fail_instead_of_being_silently_skipped(self):
        for location in ("root", "target", "replay"):
            with self.subTest(location=location):
                spec = deepcopy(contract.SCHEMA)
                if location == "root":
                    spec["allOf"] = []
                elif location == "target":
                    spec["properties"]["targets"]["items"]["properties"]["x"]["multipleOf"] = 0.1
                else:
                    spec["properties"]["replay"]["dependentRequired"] = {}
                with self.assertRaisesRegex(RuntimeError, "Unsupported contract keywords"):
                    contract._check_schema_support(spec)

    def test_unsupported_schema_formats_and_open_objects_fail_explicitly(self):
        spec = deepcopy(contract.SCHEMA)
        spec["properties"]["occurred_at"]["format"] = "email"
        with self.assertRaisesRegex(RuntimeError, "Unsupported contract format"):
            contract._check_schema_support(spec)
        spec = deepcopy(contract.SCHEMA)
        spec["additionalProperties"] = True
        with self.assertRaisesRegex(RuntimeError, "closed objects"):
            contract._check_schema_support(spec)

    def test_cli_examples_exit_success(self):
        output = StringIO()
        with redirect_stdout(output):
            result = contract.main(["--examples"])
        self.assertEqual(result, 0)
        self.assertIn("0 failed.", output.getvalue())

    def test_cli_missing_file_returns_failure_and_still_checks_next_file(self):
        output, errors = StringIO(), StringIO()
        with tempfile.TemporaryDirectory(prefix="pauseable-contract-") as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            valid = contract.EXAMPLES_PATH / "simulated-detected.json"
            with redirect_stdout(output), redirect_stderr(errors):
                result = contract.main([str(missing), str(valid)])
        self.assertEqual(result, 1)
        self.assertIn("FAIL missing.json:", errors.getvalue())
        self.assertIn("PASS simulated-detected.json", output.getvalue())
        self.assertIn("Checked 2 event(s); 1 failed.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
