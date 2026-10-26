from __future__ import annotations

import math
from typing import Any


DECISION_POLICY = "temporal-review-v2"
MODEL_STATUS = "research_only_unvalidated"

WANDERING_CANDIDATES = {
    "shape_review_candidate",
    "combined_review_candidate",
}


def unknown_result(reason_code: str) -> dict[str, Any]:

    return {
        "behavior": "unknown",
        "risk_level": "unknown",
        "risk_score": None,
        "inference_status": "insufficient_data",
        "pattern_code": reason_code,
        "reason_codes": [reason_code],
        "decision_policy": DECISION_POLICY,
        "model_status": MODEL_STATUS,
    }


def sensor_error_result(reason_code: str) -> dict[str, Any]:
    return {
        "behavior": "unknown",
        "risk_level": "unknown",
        "risk_score": None,
        "inference_status": "sensor_error",
        "pattern_code": reason_code,
        "reason_codes": [reason_code],
        "decision_policy": DECISION_POLICY,
        "model_status": MODEL_STATUS,
    }


def model_error_result(reason_code: str) -> dict[str, Any]:
    return {
        "behavior": "unknown",
        "risk_level": "unknown",
        "risk_score": None,
        "inference_status": "model_error",
        "pattern_code": reason_code,
        "reason_codes": [reason_code],
        "decision_policy": DECISION_POLICY,
        "model_status": MODEL_STATUS,
    }


def classify_wandering(
    event: dict[str, Any] | None,
    result: dict[str, Any] | None,
    *,
    input_missing: bool = False,
    stale_after_ms: int,
) -> dict[str, Any] | None:

    if type(stale_after_ms) is not int or stale_after_ms <= 0:
        raise ValueError("stale_after_ms must be a positive integer")

    if input_missing or event is None:
        return unknown_result("mmwave_data_missing")

    sensor_status = event.get("sensor_status")

    if sensor_status == "error":
        return sensor_error_result("mmwave_sensor_error")

    if sensor_status == "disconnected":
        return sensor_error_result("mmwave_sensor_disconnected")

    if sensor_status != "ok":
        return sensor_error_result("invalid_sensor_status")

    if event.get("targets_truncated") is True:
        return unknown_result("targets_truncated")

    frame_age_ms = event.get("frame_age_ms")

    if type(frame_age_ms) is not int or frame_age_ms < 0:
        return unknown_result("invalid_frame_age")

    if frame_age_ms > stale_after_ms:
        return unknown_result("mmwave_stale_frame")

    if event.get("target_count") == 0:
        return unknown_result("no_target_observations")

    if result is None:
        return unknown_result("insufficient_evidence")

    decision = result.get("experimental_decision")

    if decision == "out_of_order_not_evaluated":
        return None

    if decision in WANDERING_CANDIDATES:
        if result.get("status") != "scored_research_only":
            return unknown_result("low_quality_observation")

        score = result.get("rf_shape_score_not_calibrated")

        if type(score) not in (int, float):
            return model_error_result("invalid_shape_score")

        if not math.isfinite(score) or not 0 <= score <= 1:
            return model_error_result("invalid_shape_score")

        risk_score = max(0, min(100, int(round(score * 100))))

        reason_code = (
            "persistent_shape_and_personal_change"
            if decision == "combined_review_candidate"
            else "persistent_wandering_shape"
        )

        return {
            "behavior": "wandering",
            "risk_level": "caution",
            "risk_score": risk_score,
            "inference_status": "ok",
            "pattern_code": decision,
            "reason_codes": [reason_code],
            "decision_policy": DECISION_POLICY,
            "model_status": MODEL_STATUS,
        }

    if decision == "personal_change_candidate":
        return unknown_result("personal_change_without_shape")

    return unknown_result("low_quality_observation")
