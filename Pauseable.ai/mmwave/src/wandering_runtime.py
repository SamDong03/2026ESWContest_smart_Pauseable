from __future__ import annotations

import math
from typing import Any

from trajectory_windows import TrajectoryWindows
from rolling_windows import RollingTrajectoryWindows
from datetime import datetime
from wandering_decision import WanderingDecisionEmitter


STATE_KEY = "wandering-publisher-signature-v1"

INTERRUPTION_PATTERNS = {
    "mmwave_data_missing",
    "mmwave_sensor_error",
    "mmwave_sensor_disconnected",
    "invalid_sensor_status",
    "targets_truncated",
    "invalid_frame_age",
    "mmwave_stale_frame",
    "no_target_observations",
}

DECISION_PRIORITY = {
    "combined_review_candidate": 50,
    "shape_review_candidate": 40,
    "personal_change_candidate": 30,
    "no_current_rule_flag": 20,
    "partial_evidence": 20,
    "insufficient_evidence": 10,
}


class WanderingRuntime:
    def __init__(
        self,
        flow: Any,
        emitter: WanderingDecisionEmitter,
        *,
        sample_ms: int,
        window_ms: int,
        assignments: dict[str, Any] | None = None,
        builder: Any | None = None,
        step_ms: int | None = None,
        max_gap_ms: int | None = None,
        on_result: Any | None = None,
    ) -> None:
        self.flow = flow
        self.emitter = emitter
        self.assignments = assignments or {}
        self.on_result = on_result
        self.builder = builder or (
            TrajectoryWindows(sample_ms, window_ms, max_gap_ms=max_gap_ms)
            if step_ms is None or step_ms == window_ms
            else RollingTrajectoryWindows(sample_ms, window_ms, step_ms,
                                          max_gap_ms=max_gap_ms)
        )
        self.event_count = 0
        self.session_id: str | None = None
        self._restore_signature()

    def _restore_signature(self) -> None:
        stored = self.flow.get(STATE_KEY)

        if stored is None:
            return

        if (
            not isinstance(stored, list)
            or len(stored) != 4
            or not all(isinstance(value, str) for value in stored)
        ):
            raise ValueError(
                "Invalid stored wandering publisher signature"
            )

        self.emitter.last_signature = tuple(stored)

    def _persist_signature(self) -> None:
        signature = self.emitter.last_signature

        if signature is None:
            return

        with self.flow.db:
            self.flow.put(
                STATE_KEY,
                list(signature),
            )

    def _publish(
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
        payload = self.emitter.emit(
            event,
            result,
            input_missing=input_missing,
            occurred_at=occurred_at,
            observation_count=observation_count,
            window_seconds=window_seconds,
            model_version=model_version,
        )

        if payload is not None:
            self._persist_signature()

        return payload

    def _priority(
        self,
        window: dict[str, Any],
        result: dict[str, Any],
    ) -> tuple[int, float, int]:
        decision = result.get("experimental_decision")
        priority = DECISION_PRIORITY.get(decision, 1)
        score = result.get("rf_shape_score_not_calibrated")

        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
        ):
            score = -1.0

        return (
            priority,
            float(score),
            int(window.get("window_end_ms", 0)),
        )

    def _process_windows(
        self,
        windows: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        evaluated = []

        for window in windows:
            result = self.flow.process(
                window,
                self.assignments.get(window["window_id"]),
                emit_test=False,
            )
            if self.on_result is not None:
                self.on_result(window, result)

            if (
                result.get("experimental_decision")
                == "out_of_order_not_evaluated"
            ):
                continue

            evaluated.append((window, result))

        if not evaluated:
            return None

        return max(
            evaluated,
            key=lambda pair: self._priority(
                pair[0],
                pair[1],
            ),
        )

    def _publish_result(
        self,
        event: dict[str, Any],
        window: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        observation_count = window.get(
            "occupied_slots",
            window.get("observed_samples", 0),
        )

        if (
            type(observation_count) is not int
            or observation_count < 0
        ):
            observation_count = 0

        start = window.get("window_start_ms")
        end = window.get("window_end_ms")
        window_seconds = None

        if (
            type(start) is int
            and type(end) is int
            and end > start
            and (end - start) % 1000 == 0
        ):
            window_seconds = (end - start) // 1000

        model_version = result.get("model_sha256")

        if (
            not isinstance(model_version, str)
            or not model_version
        ):
            model_version = None

        return self._publish(
            event,
            result,
            observation_count=observation_count,
            window_seconds=window_seconds,
            model_version=model_version,
        )

    def _raw_requires_unknown(
        self,
        event: dict[str, Any],
    ) -> bool:
        if event["sensor_status"] != "ok":
            return True

        if event["targets_truncated"]:
            return True

        frame_age_ms = event["frame_age_ms"]

        if (
            type(frame_age_ms) is not int
            or frame_age_ms < 0
            or frame_age_ms > self.emitter.stale_after_ms
        ):
            return True

        return event["target_count"] == 0


    def has_source_gap_before(
        self,
        event: dict[str, Any],
        *,
        silence_timeout: float,
    ) -> bool:
        scope = (
            event["sensor_id"],
            event["data_origin"],
        )

        if self.builder.scope != scope:
            return False

        if self.builder.session != event["session_id"]:
            return False

        if event["seq"] <= self.builder.last_seq:
            return False

        if event["uptime_ms"] < self.builder.last_uptime:
            return False

        return (
            event["uptime_ms"] - self.builder.last_uptime
            > silence_timeout * 1000.0
        )

    def process_event(
        self,
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        counter_names = (
            "duplicate_or_old",
            "old_sessions",
            "cached_frames",
        )

        before = {
            name: self.builder.counts.get(name, 0)
            for name in counter_names
        }

        uptime_regressions = self.builder.counts.get(
            "uptime_regressions",
            0,
        )
        previous_session = self.session_id
        windows = self.builder.feed(event)
        self.event_count += 1

        ignored = any(
            self.builder.counts.get(name, 0)
            > before[name]
            for name in counter_names
        )

        uptime_regressed = (
            self.builder.counts.get(
                "uptime_regressions",
                0,
            )
            > uptime_regressions
        )

        if ignored:
            return None

        self.session_id = event["session_id"]

        session_changed = (
            previous_session is not None
            and previous_session != self.session_id
        )

        selected = self._process_windows(windows)

        if self._raw_requires_unknown(event):
            return self._publish(
                event,
                None,
                observation_count=0,
            )

        if uptime_regressed or session_changed:
            return self._publish(
                event,
                None,
                observation_count=0,
            )

        if selected is not None:
            return self._publish_result(
                event,
                selected[0],
                selected[1],
            )

        if windows:
            return None

        signature = self.emitter.last_signature

        if (
            signature is None
            or signature[3] in INTERRUPTION_PATTERNS
        ):
            return self._publish(
                event,
                None,
                observation_count=0,
            )

        return None

    def mark_input_missing(
        self,
        *,
        occurred_at: datetime | str | None = None,
    ) -> dict[str, Any] | None:
        self._process_windows(
            self.builder.finish()
        )

        return self._publish(
            None,
            None,
            input_missing=True,
            occurred_at=occurred_at,
            observation_count=0,
        )

    def finish(self) -> dict[str, Any] | None:
        return self.mark_input_missing()
