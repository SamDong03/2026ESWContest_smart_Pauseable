

from dataclasses import asdict, dataclass
import hashlib
import json
import math


@dataclass(frozen=True)
class EvidencePolicy:
    version: str = "temporal-review-v2"
    minimum_windows: int = 3
    minimum_duration_ms: int = 90000
    shape_release_margin: float = 0.10
    personal_on: float = 95.0
    personal_off: float = 90.0

    def __post_init__(self):
        for value in (self.minimum_windows, self.minimum_duration_ms):
            if type(value) is not int or value <= 0:
                raise ValueError("Evidence windows and duration must be positive integers.")
        if not _number(self.shape_release_margin, 1) or self.shape_release_margin >= 1:
            raise ValueError("Invalid shape release margin.")
        if (not _number(self.personal_off, 100) or not _number(self.personal_on, 100)
                or self.personal_off >= self.personal_on):
            raise ValueError("Invalid personal evidence thresholds.")


def _number(value, maximum):
    return (type(value) in (int, float) and math.isfinite(value)
            and 0 <= value <= maximum)


def _lane(previous, score, onset, release, duration, policy, *, new_ms=None):
    if score is None:
        return {"active": False, "high_windows": 0, "high_ms": 0, "support_ms": 0}
    high = score >= onset
    retained = previous.get("active", False) and score >= release
    count = previous.get("high_windows", 0) + 1 if high else 0


    increment = duration if not previous.get("high_windows", 0) else new_ms
    if increment is None:
        increment = duration
    high_ms = previous.get("high_ms", 0) + increment if high else 0
    active = retained or (count >= policy.minimum_windows
                          and high_ms >= policy.minimum_duration_ms)
    support_increment = duration if not previous.get("support_ms", 0) else new_ms
    if support_increment is None:
        support_increment = duration
    support = previous.get("support_ms", 0) + support_increment if high or retained else 0
    return {"active": active, "high_windows": count,
            "high_ms": high_ms, "support_ms": support}


def advance_evidence(previous, window, result, *, percentile=None,
                     baseline_version=None, profile_id=None, policy=None):
    policy = policy or EvidencePolicy()
    threshold = result["decision_threshold"]
    if not _number(threshold, 1):
        raise ValueError("Invalid model decision threshold.")
    start, end = window["window_start_ms"], window["window_end_ms"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise ValueError("Invalid monotonic observation interval.")
    if percentile is not None and not _number(percentile, 100):
        raise ValueError("Invalid reference percentile.")
    score = result["rf_shape_score_not_calibrated"]
    step = window.get("window_step_ms", end - start)
    if (type(step) is not int or not 0 < step <= end - start
            or (end - start) % step or step % window["expected_period_ms"]):
        raise ValueError("Invalid rolling observation stride.")
    valid = result["status"] == "scored_research_only" and _number(score, 1)
    signature = hashlib.sha256(json.dumps([
        window["sensor_id"], window["data_origin"], window["session_id"],
        window["target_id"], window["time_basis"], window["expected_period_ms"],
        end - start, result["model_sha256"], threshold,
        asdict(policy),
        *([step] if "window_step_ms" in window else []),
    ], sort_keys=True).encode()).hexdigest()
    same_stream = previous.get("signature") == signature
    rolling = "window_step_ms" in window
    if same_stream and (end <= previous["end_ms"] if rolling else start < previous["end_ms"]):
        return previous, {"experimental_decision": "out_of_order_not_evaluated",
                          "temporal_evidence": {"status": "ignored_overlap_or_old"}}
    continuous = same_stream and (
        end - previous["end_ms"] == step if rolling else previous["end_ms"] == start
    )
    prior = previous if continuous else {}
    shape_off = max(0.0, threshold - policy.shape_release_margin)
    shape = _lane(prior.get("shape", {}), score if valid else None,
                  threshold, shape_off, end - start, policy,
                  new_ms=step if continuous else end - start)
    personal_signature = [baseline_version, profile_id]
    personal_prior = (prior.get("personal", {})
                      if prior.get("personal_signature") == personal_signature else {})
    personal = _lane(personal_prior, percentile if valid else None,
                     policy.personal_on, policy.personal_off, end - start, policy,
                     new_ms=step if continuous else end - start)
    if not valid:
        decision = "insufficient_evidence"
    elif shape["active"] and personal["active"]:
        decision = "combined_review_candidate"
    elif shape["active"]:
        decision = "shape_review_candidate"
    elif personal["active"]:
        decision = "personal_change_candidate"
    else:
        decision = "no_current_rule_flag" if percentile is not None else "partial_evidence"
    state = {"signature": signature, "end_ms": end, "shape": shape, "personal": personal,
             "personal_signature": personal_signature}
    return state, {
        "experimental_decision": decision,
        "consecutive_windows": {"shape": shape["high_windows"],
                                "personal": personal["high_windows"]},
        "temporal_evidence": {
            "status": "evaluated" if valid else "reset_missing_evidence",
            "continuous": continuous,
            "minimum_windows": policy.minimum_windows,
            "minimum_duration_ms": policy.minimum_duration_ms,
            "window_step_ms": step,
            "new_observation_ms": step if continuous else end - start,
            "shape_on": threshold, "shape_off": shape_off,
            "personal_on": policy.personal_on, "personal_off": policy.personal_off,
            "shape": shape, "personal": personal,
        },
    }
