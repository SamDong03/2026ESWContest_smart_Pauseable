from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from wandering_contract import build_behavior_payload
from wandering_policy import classify_wandering


Signature = tuple[str, str, str, str]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def decision_signature(
    classification: dict[str, Any],
) -> Signature:
    return (
        classification["behavior"],
        classification["risk_level"],
        classification["inference_status"],
        classification["pattern_code"],
    )


class WanderingDecisionEmitter:
    def __init__(
        self,
        publisher: Any,
        *,
        stale_after_ms: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if type(stale_after_ms) is not int or stale_after_ms <= 0:
            raise ValueError(
                "stale_after_ms must be a positive integer"
            )

        self.publisher = publisher
        self.stale_after_ms = stale_after_ms
        self.clock = clock
        self.last_signature: Signature | None = None
        self.pending_signature: Signature | None = None
        self.pending_payload: dict[str, Any] | None = None

    def emit(
        self,
        event: dict[str, Any] | None,
        result: dict[str, Any] | None,
        *,
        input_missing: bool = False,
        occurred_at: datetime | str | None = None,
        observation_count: int = 0,
        window_seconds: int | None = None,
        model_version: str | None = None,
    ) -> dict[str, Any] | None:
        classification = classify_wandering(
            event,
            result,
            input_missing=input_missing,
            stale_after_ms=self.stale_after_ms,
        )

        if classification is None:
            return None

        signature = decision_signature(classification)

        if signature == self.last_signature:
            return None

        if (
            signature == self.pending_signature
            and self.pending_payload is not None
        ):
            payload = self.pending_payload
        else:
            timestamp = occurred_at

            if timestamp is None and event is not None:
                timestamp = event.get("occurred_at")

            if timestamp is None:
                timestamp = self.clock()

            payload = build_behavior_payload(
                classification,
                occurred_at=timestamp,
                observation_count=observation_count,
                window_seconds=window_seconds,
                model_version=model_version,
            )

            self.pending_signature = signature
            self.pending_payload = payload

        self.publisher.publish(payload)

        self.last_signature = signature
        self.pending_signature = None
        self.pending_payload = None

        return payload
