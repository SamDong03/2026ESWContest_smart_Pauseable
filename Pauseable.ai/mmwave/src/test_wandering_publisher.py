from datetime import datetime, timezone
import json
import unittest

from wandering_contract import build_behavior_payload
from wandering_policy import classify_wandering
from wandering_publisher import (
    PublisherConfig,
    QOS,
    RETAIN,
    TOPIC,
    WanderingMqttPublisher,
)


FIXED_TIME = datetime(
    2026,
    9,
    20,
    1,
    30,
    tzinfo=timezone.utc,
)


class FakeMessageInfo:
    def __init__(
        self,
        *,
        rc: int = 0,
        published: bool = True,
    ) -> None:
        self.rc = rc
        self.published = published
        self.timeouts: list[float] = []

    def wait_for_publish(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def is_published(self) -> bool:
        return self.published


class FakeClient:
    def __init__(
        self,
        results: list[FakeMessageInfo],
        *,
        connected: bool = True,
    ) -> None:
        self.results = list(results)
        self.connected = connected
        self.calls: list[dict[str, object]] = []
        self.reconnect_calls = 0

    def is_connected(self) -> bool:
        return self.connected

    def reconnect(self) -> int:
        self.reconnect_calls += 1
        self.connected = True
        return 0

    def publish(
        self,
        topic: str,
        payload: str,
        *,
        qos: int,
        retain: bool,
    ) -> FakeMessageInfo:
        self.calls.append(
            {
                "topic": topic,
                "payload": payload,
                "qos": qos,
                "retain": retain,
            }
        )
        return self.results.pop(0)

    def disconnect(self) -> int:
        self.connected = False
        return 0

    def loop_stop(self) -> None:
        pass


def candidate_payload() -> dict[str, object]:
    classification = classify_wandering(
        {
            "sensor_status": "ok",
            "frame_age_ms": 0,
            "target_count": 1,
            "targets_truncated": False,
        },
        {
            "experimental_decision": "shape_review_candidate",
            "status": "scored_research_only",
            "rf_shape_score_not_calibrated": 0.83,
        },
        stale_after_ms=1500,
    )

    return build_behavior_payload(
        classification,
        event_id="evt-publisher-test-001",
        occurred_at=FIXED_TIME,
        observation_count=30,
        window_seconds=30,
        model_version="mmwave-shape-v2",
    )


def config(
    *,
    publish_retries: int = 3,
) -> PublisherConfig:
    return PublisherConfig(
        host="127.0.0.1",
        connect_timeout=0.1,
        publish_timeout=0.25,
        publish_retries=publish_retries,
    )


class WanderingPublisherTest(unittest.TestCase):
    def test_topic_qos_and_retain(self):
        client = FakeClient([FakeMessageInfo()])
        publisher = WanderingMqttPublisher(
            config(),
            client=client,
            sleeper=lambda seconds: None,
        )

        event_id = publisher.publish(candidate_payload())

        self.assertEqual(
            event_id,
            "evt-publisher-test-001",
        )
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["topic"], TOPIC)
        self.assertEqual(client.calls[0]["qos"], QOS)
        self.assertEqual(client.calls[0]["qos"], 1)
        self.assertEqual(client.calls[0]["retain"], RETAIN)
        self.assertFalse(client.calls[0]["retain"])

        decoded = json.loads(client.calls[0]["payload"])
        self.assertEqual(
            decoded["event_id"],
            "evt-publisher-test-001",
        )

    def test_retry_keeps_identical_payload(self):
        client = FakeClient(
            [
                FakeMessageInfo(published=False),
                FakeMessageInfo(published=True),
            ]
        )
        delays: list[float] = []
        publisher = WanderingMqttPublisher(
            config(publish_retries=2),
            client=client,
            sleeper=delays.append,
        )

        publisher.publish(candidate_payload())

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(
            client.calls[0]["payload"],
            client.calls[1]["payload"],
        )
        self.assertEqual(delays, [1.0])

        first = json.loads(client.calls[0]["payload"])
        second = json.loads(client.calls[1]["payload"])
        self.assertEqual(
            first["event_id"],
            second["event_id"],
        )

    def test_publish_reconnects_when_disconnected(self):
        client = FakeClient(
            [FakeMessageInfo()],
            connected=False,
        )
        publisher = WanderingMqttPublisher(
            config(),
            client=client,
            sleeper=lambda seconds: None,
        )

        publisher.publish(candidate_payload())

        self.assertEqual(client.reconnect_calls, 1)
        self.assertEqual(len(client.calls), 1)

    def test_invalid_payload_is_not_sent(self):
        client = FakeClient([FakeMessageInfo()])
        publisher = WanderingMqttPublisher(
            config(),
            client=client,
            sleeper=lambda seconds: None,
        )
        payload = candidate_payload()
        payload["risk_score"] = None

        with self.assertRaises(ValueError):
            publisher.publish(payload)

        self.assertEqual(client.calls, [])

    def test_missing_ack_exhausts_retries(self):
        client = FakeClient(
            [
                FakeMessageInfo(published=False),
                FakeMessageInfo(published=False),
            ]
        )
        publisher = WanderingMqttPublisher(
            config(publish_retries=2),
            client=client,
            sleeper=lambda seconds: None,
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "MQTT publish failed after 2 attempts",
        ):
            publisher.publish(candidate_payload())

        self.assertEqual(len(client.calls), 2)


if __name__ == "__main__":
    unittest.main()
