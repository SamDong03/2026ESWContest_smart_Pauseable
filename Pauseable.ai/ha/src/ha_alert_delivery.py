
from datetime import datetime, timezone
import json
import os
from pathlib import Path


RANK = {"normal": 0, "attention": 1, "risk": 2}


def load_state(path):
    path = Path(path)
    if not path.exists():
        return {"active": False}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("active"), bool):
        raise ValueError("Invalid alert state; repair explicitly instead of re-arming silently")
    pending = state.get("pending")
    if pending is not None and (not isinstance(pending, dict) or
                               not isinstance(pending.get("payload"), dict) or
                               not isinstance(pending.get("target"), dict)):
        raise ValueError("Invalid pending alert state")
    return state


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name == 'posix':
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def deliver_transition(path, level, build_alert, build_normal, send, *, pattern="",
                       dry_run=False, now=None, delivery_epoch=None):
    pass


    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Delivery clock must be timezone-aware")
    if delivery_epoch is not None and (type(delivery_epoch) is not int or delivery_epoch < 0):
        raise ValueError("Delivery epoch must be a non-negative review revision")
    state = load_state(path)
    if dry_run:
        payload = build_alert() if level in {"attention", "risk"} else None
        if payload is not None:
            send(payload)
        return {"status": "dry_run", "state_changed": False}
    pending = state.get("pending")
    if pending:
        occurred = datetime.fromisoformat(pending["payload"]["occurred_at"].replace("Z", "+00:00"))
        age = (now - occurred).total_seconds()
        epoch_changed = delivery_epoch is not None and pending.get("delivery_epoch") != delivery_epoch
        cancel = (epoch_changed or age >= 300 or age < -30 or
                  (pending["target"].get("active") and level not in {"attention", "risk"}))
        if cancel:
            state.pop("pending")
            if epoch_changed and level in {"attention", "risk"}:

                state["active"] = False
            elif pending["target"].get("active") and (level == "normal" or epoch_changed):

                state["active"] = True
            state["last_discarded_event_id"] = pending["payload"]["event_id"]
            state["discard_reason"] = "review_context_changed" if epoch_changed else "expired_or_superseded"
            save_state(path, state)
        else:
            send(pending["payload"])
            state.update(pending["target"], last_event_id=pending["payload"]["event_id"])
            state.pop("pending")
            save_state(path, state)
            return {"status": "retried", "event_id": state["last_event_id"]}
    if level not in RANK:
        return {"status": "unknown_held", "active": state["active"]}
    if level == "normal":
        if not state["active"]:
            return {"status": "normal_idle"}
        payload = build_normal()
        target = {"active": False, "alert_level": "normal", "pattern": ""}
    else:
        previous = state.get("alert_level", state.get("level", "attention"))
        same_episode = state["active"] and state.get("pattern", pattern) == pattern
        if same_episode and RANK.get(previous, 1) >= RANK[level]:
            return {"status": "suppressed", "alert_level": previous}
        payload = build_alert()
        target = {"active": True, "alert_level": level, "pattern": pattern}
    state["pending"] = {"payload": payload, "target": target}
    if delivery_epoch is not None:
        state["pending"]["delivery_epoch"] = delivery_epoch
    save_state(path, state)
    send(payload)
    state.update(target, last_event_id=payload["event_id"])
    state.pop("pending")
    save_state(path, state)
    return {"status": "published", "event_id": payload["event_id"], "alert_level": level}


def alert_score(row):
    if row.get("level") not in {"attention", "risk"}:
        raise ValueError("Only explicit alert decisions can create alert messages")
    value = float(row["risk_score"])
    if not 0 <= value <= 100 or not value.is_integer():
        raise ValueError("risk_score must be a finite integer in 0..100")
    return int(value)


def model_version(row, args):
    value = row.get("model_id") or getattr(args, "model_version", None) or "baseline-only"
    return str(value)[:64]
