from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


BASE = Path(__file__).resolve().parents[1]
SRC = BASE / "src"
sys.path.insert(0, str(SRC))

import run_repetitive_mqtt_stream as stream
import publish_repetitive_mqtt as publisher


def payload(*, risk_level: str = "caution", risk_score: int = 60) -> dict:
    return {
        "event_id": "evt-repetitive-1",
        "occurred_at": "2026-09-20T10:00:00Z",
        "source": "repetitive-ai",
        "behavior": "repetitive",
        "risk_level": risk_level,
        "risk_score": risk_score,
        "inference_status": "ok",
        "evidence": {"pattern_code": "repeated_appliance_use"},
    }


class RepetitiveMqttStreamStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_path = self.root / "state.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_selection_does_not_commit_before_publish(self) -> None:
        selected, next_state = stream.select_new_payloads([payload()], self.state_path)

        self.assertEqual(len(selected), 1)
        self.assertFalse(self.state_path.exists())
        self.assertIn("episode_signatures", next_state)

    def test_committed_signature_suppresses_same_decision(self) -> None:
        _, next_state = stream.select_new_payloads([payload()], self.state_path)
        stream.save_json(self.state_path, next_state)

        selected, _ = stream.select_new_payloads([payload()], self.state_path)

        self.assertEqual(selected, [])

    def test_changed_decision_uses_stable_retry_event_id(self) -> None:
        _, next_state = stream.select_new_payloads([payload()], self.state_path)
        stream.save_json(self.state_path, next_state)
        changed = payload(risk_level="danger", risk_score=95)

        first, _ = stream.select_new_payloads([changed], self.state_path)
        second, _ = stream.select_new_payloads([changed], self.state_path)

        self.assertNotEqual(first[0]["event_id"], changed["event_id"])
        self.assertEqual(first[0]["event_id"], second[0]["event_id"])

    def test_publish_failure_does_not_commit_state(self) -> None:
        selected, next_state = stream.select_new_payloads([payload()], self.state_path)
        args = argparse.Namespace(mqtt_host="127.0.0.1", mqtt_port=1883)
        output = self.root / "new.jsonl"

        with patch.object(
            stream,
            "run_step",
            side_effect=subprocess.CalledProcessError(1, ["publisher"]),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                stream.publish_and_commit(
                    args,
                    selected,
                    next_state,
                    output,
                    self.state_path,
                )

        self.assertFalse(self.state_path.exists())
        written = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(written[0]["event_id"], selected[0]["event_id"])


class PublisherAcknowledgementTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(topic="pauseable/ai/repetitive/decision", qos=1, retain=False, dry_run=False)

    def test_zero_return_code_without_puback_is_not_success(self):
        client = Mock()
        info = Mock(rc=0)
        info.is_published.return_value = False
        client.publish.return_value = info
        with patch.object(publisher, "wait_until_connected", return_value=True), \
                patch.object(publisher, "PUBLISH_RETRY_COUNT", 2), patch.object(publisher.time, "sleep"), \
                self.assertRaisesRegex(RuntimeError, "not confirmed"):
            publisher.publish_payload(client, self.args(), payload())
        self.assertEqual(client.publish.call_count, 2)
        self.assertEqual(client.publish.call_args_list[0].args, client.publish.call_args_list[1].args)

    def test_retried_payload_succeeds_only_after_acknowledgement(self):
        client = Mock()
        pending, confirmed = Mock(rc=0), Mock(rc=0)
        pending.is_published.return_value, confirmed.is_published.return_value = False, True
        client.publish.side_effect = [pending, confirmed]
        with patch.object(publisher, "wait_until_connected", return_value=True), \
                patch.object(publisher.time, "sleep"):
            publisher.publish_payload(client, self.args(), payload())
        self.assertEqual(client.publish.call_count, 2)


if __name__ == "__main__":
    unittest.main()
