from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import uuid

from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[3]

SCHEMA_PATH = (
    REPO_ROOT
    / "Pauseable.contracts"
    / "communication-v1"
    / "schemas"
    / "behavior-inference.schema.json"
)

CONTRACT_VERSION = "1.0"
PATIENT_ID = "byunwoojin"
DEVICE_ID = "pi5-home-01"
SOURCE = "wandering-ai"


BEHAVIOR_SCHEMA = json.loads(
    SCHEMA_PATH.read_text(encoding="utf-8")
)

Draft202012Validator.check_schema(BEHAVIOR_SCHEMA)

VALIDATOR = Draft202012Validator(
    BEHAVIOR_SCHEMA,
    format_checker=FormatChecker(),
)


def utc_text(value: datetime | str) -> str:

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise ValueError(
                f"Invalid occurred_at timestamp: {value}"
            ) from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TypeError(
            "occurred_at must be a datetime or ISO timestamp"
        )

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            "occurred_at must include timezone information"
        )

    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def new_event_id() -> str:
    return f"evt-{uuid.uuid4()}"


def validate_behavior_payload(
    payload: dict[str, Any],
) -> None:

    errors = sorted(
        VALIDATOR.iter_errors(payload),
        key=lambda error: "/".join(
            str(part) for part in error.absolute_path
        ),
    )

    if not errors:
        return

    messages = []

    for error in errors:
        location = "$"

        if error.absolute_path:
            location += "." + ".".join(
                str(part) for part in error.absolute_path
            )

        messages.append(f"{location}: {error.message}")

    raise ValueError(
        "Invalid behavior-inference payload: "
        + "; ".join(messages)
    )


def build_behavior_payload(
    classification: dict[str, Any],
    *,
    occurred_at: datetime | str,
    event_id: str | None = None,
    observation_count: int = 0,
    window_seconds: int | None = None,
    model_version: str | None = None,
    reason_text: str | None = None,
) -> dict[str, Any]:

    if classification is None:
        raise ValueError(
            "Ignored decisions must not be converted to a payload"
        )

    evidence: dict[str, Any] = {
        "observation_count": observation_count,
        "pattern_code": classification["pattern_code"],
        "decision_policy": classification[
            "decision_policy"
        ],
        "model_status": classification["model_status"],
        "reason_codes": list(
            classification["reason_codes"]
        ),
    }

    if window_seconds is not None:
        evidence["window_seconds"] = window_seconds

    if reason_text:
        evidence["reason_text"] = reason_text

    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "event_id": event_id or new_event_id(),
        "occurred_at": utc_text(occurred_at),
        "patient_id": PATIENT_ID,
        "device_id": DEVICE_ID,
        "source": SOURCE,
        "behavior": classification["behavior"],
        "risk_level": classification["risk_level"],
        "risk_score": classification["risk_score"],
        "inference_status": classification[
            "inference_status"
        ],
        "evidence": evidence,
    }

    if model_version:
        payload["model_version"] = model_version

    validate_behavior_payload(payload)

    return payload


def serialize_behavior_payload(
    payload: dict[str, Any],
) -> str:

    validate_behavior_payload(payload)

    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
