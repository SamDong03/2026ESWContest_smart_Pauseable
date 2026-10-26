
from datetime import datetime


def recorder_time(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Recorder state has no timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Recorder timestamps must include a timezone")
    return result


def validate_history(history, start, end, entity_id=None):
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("Invalid Recorder observation window")
    if not history:
        raise ValueError("Recorder returned no observation history")
    previous = None
    for row in history:
        state = str(row.get("state", "")).lower()
        if state in {"", "unknown", "unavailable", "none"}:
            raise ValueError("Recorder contains an unavailable state; coverage is incomplete")
        if entity_id and row.get("entity_id") not in {None, entity_id}:
            raise ValueError("Recorder returned a different entity")
        at = recorder_time(row.get("last_changed") or row.get("last_updated"))
        if at > end or (previous is not None and at < previous):
            raise ValueError("Recorder timestamps are future or out of order")
        if previous is None and at > start:
            raise ValueError("Recorder has no initial state at the requested window start")
        previous = at

    return {"initial_state_at_window_start": True, "device_delivery_completeness": "not_measured"}
