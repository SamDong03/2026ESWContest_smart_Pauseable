

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from typing import Any
from urllib.parse import urlsplit

from app.push_subscription_store import PushSubscriptionStore


logger = logging.getLogger(__name__)
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_PUSH_HOSTS = (
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
)
_PUSH_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com")


def is_configured() -> bool:
    return (
        os.getenv("PAUSEABLE_WEB_PUSH_ENABLED") == "1"
        and bool(os.getenv("PAUSEABLE_VAPID_PUBLIC_KEY", "").strip())
        and bool(os.getenv("PAUSEABLE_VAPID_PRIVATE_KEY", "").strip())
        and bool(os.getenv("PAUSEABLE_VAPID_SUBJECT", "").strip())
    )


def public_key() -> str:
    return os.getenv("PAUSEABLE_VAPID_PUBLIC_KEY", "").strip()


def validate_subscription(subscription: dict[str, Any]) -> dict[str, Any]:
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys")
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        raise ValueError("Invalid push endpoint")
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in (None, 443)
        or not (
            host in _PUSH_HOSTS
            or any(host.endswith(suffix) for suffix in _PUSH_HOST_SUFFIXES)
        )
    ):
        raise ValueError("Push endpoint must be a supported HTTPS push service")
    if not isinstance(keys, dict):
        raise ValueError("Push encryption keys are missing")
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not isinstance(p256dh, str) or not (60 <= len(p256dh) <= 256):
        raise ValueError("Invalid push p256dh key")
    if not isinstance(auth, str) or not (16 <= len(auth) <= 128):
        raise ValueError("Invalid push auth key")
    if not _KEY_PATTERN.fullmatch(p256dh) or not _KEY_PATTERN.fullmatch(auth):
        raise ValueError("Invalid push encryption keys")
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


def _webpush_send(subscription: dict[str, Any], payload: str) -> None:
    from pywebpush import webpush

    webpush(
        subscription_info={
            "endpoint": subscription["endpoint"],
            "keys": subscription["keys"],
        },
        data=payload,
        vapid_private_key=os.environ["PAUSEABLE_VAPID_PRIVATE_KEY"],
        vapid_claims={"sub": os.environ["PAUSEABLE_VAPID_SUBJECT"]},
        ttl=300,
        timeout=5,
        headers={"Urgency": "high"},
    )


async def send_test_notification(
    patient_id: str, endpoint: str, store: PushSubscriptionStore,
    *, sound_enabled: bool = True,
) -> dict[str, int]:
    pass
    if not is_configured():
        return {"attempted": 0, "accepted": 0}
    subscription = await asyncio.to_thread(store.get, patient_id, endpoint)
    if subscription is None:
        return {"attempted": 0, "accepted": 0}
    payload = json.dumps({
        "type": "push_test", "alert_id": f"push-test-{uuid.uuid4().hex}",
        "sound_enabled": sound_enabled,
    })
    try:
        await asyncio.to_thread(_webpush_send, validate_subscription(subscription), payload)
        return {"attempted": 1, "accepted": 1}
    except Exception as error:
        status = getattr(error, "status_code", None) or getattr(
            getattr(error, "response", None), "status_code", None,
        )
        if status in {404, 410}:
            try:
                store.delete(patient_id, endpoint)
            except Exception:
                logger.warning("Expired Web Push test subscription could not be removed")
        logger.warning("Web Push test delivery failed (status=%s)", status)
        return {"attempted": 1, "accepted": 0}


async def send_behavior_alert(
    patient_id: str,
    alert: dict[str, Any],
    store: PushSubscriptionStore,
    *, sound_enabled: bool = True,
) -> dict[str, int]:
    pass
    if (
        not is_configured()
        or alert.get("alert_type") not in {"repetitive_behavior", "wandering"}
        or alert.get("risk_level") not in {"caution", "danger"}
    ):
        return {"attempted": 0, "accepted": 0}

    body = (
        "배회 의심 행동이 감지되었습니다. 앱에서 확인해 주세요."
        if alert["alert_type"] == "wandering"
        else "반복 행동이 감지되었습니다. 앱에서 확인해 주세요."
    )
    payload = json.dumps(
        {
            "title": "PAUSEABLE 안전 알림",
            "body": body,
            "alert_id": alert["alert_id"],
            "sound_enabled": sound_enabled,
        },
        ensure_ascii=False,
    )
    try:
        subscriptions = store.list_for_patient(patient_id)
    except Exception:
        logger.warning("Web Push subscription list could not be loaded")
        return {"attempted": 0, "accepted": 0}
    attempted = accepted = 0
    for subscription in subscriptions:
        attempted += 1
        try:
            await asyncio.to_thread(_webpush_send, subscription, payload)
            accepted += 1
        except Exception as error:
            status = getattr(error, "status_code", None) or getattr(
                getattr(error, "response", None), "status_code", None
            )
            if status in {404, 410}:
                try:
                    store.delete(patient_id, subscription["endpoint"])
                except Exception:
                    logger.warning("Expired Web Push subscription could not be removed")
            logger.warning("Web Push delivery failed (status=%s)", status)
    logger.info(
        "Web Push alert=%s attempted=%s accepted=%s",
        alert["alert_id"], attempted, accepted,
    )
    return {"attempted": attempted, "accepted": accepted}
