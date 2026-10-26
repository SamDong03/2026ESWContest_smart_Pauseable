

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from datetime import timedelta
from functools import lru_cache
from typing import Any

from app.native_push_store import NativePushStore


logger = logging.getLogger(__name__)
_APP_NAME = "pauseable-native-push"
_APP_LOCK = threading.Lock()
ANDROID_NOTIFICATION_CHANNEL = "pauseable_guardian_alerts"
ANDROID_SILENT_NOTIFICATION_CHANNEL = "pauseable_guardian_alerts_silent"


class NativePushConfigurationError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _firebase_app() -> Any:
    pass
    if os.getenv("PAUSEABLE_FCM_ENABLED") != "1":
        raise NativePushConfigurationError("Native Push is not enabled")
    service_account_json = os.getenv("PAUSEABLE_FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    service_account_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if not service_account_json and not service_account_path:
        raise NativePushConfigurationError("Native Push credentials are missing")
    try:
        import firebase_admin
        from firebase_admin import credentials

        source = json.loads(service_account_json) if service_account_json else service_account_path
        credential = credentials.Certificate(source)
        with _APP_LOCK:
            try:
                return firebase_admin.get_app(_APP_NAME)
            except ValueError:
                return firebase_admin.initialize_app(
                    credential, {"httpTimeout": 8}, name=_APP_NAME,
                )
    except Exception:

        raise NativePushConfigurationError("Native Push credentials are invalid") from None


def is_configured() -> bool:
    if os.getenv("PAUSEABLE_FCM_ENABLED") != "1":
        return False
    try:
        _firebase_app()
    except Exception:
        logger.warning("Native Push is enabled but credential configuration is unavailable")
        return False
    return True


def _fcm_send(
    token: str,
    *,
    body: str,
    data: dict[str, str],
    tag: str,
    sound_enabled: bool = True,
) -> None:
    from firebase_admin import messaging

    message = messaging.Message(
        token=token,
        notification=messaging.Notification(title="Pauseable 알림", body=body),
        data=data,
        android=messaging.AndroidConfig(
            priority="high",
            ttl=timedelta(seconds=300),
            restricted_package_name="com.pauseable.pauseable_guardian",
            notification=messaging.AndroidNotification(
                channel_id=(
                    ANDROID_NOTIFICATION_CHANNEL if sound_enabled
                    else ANDROID_SILENT_NOTIFICATION_CHANNEL
                ),
                icon="ic_stat_notification",
                sound="default" if sound_enabled else None,
                default_sound=sound_enabled,
                default_vibrate_timings=sound_enabled,
                priority="high",
                tag=tag,
            ),
        ),
    )
    messaging.send(message, app=_firebase_app())


def _is_expired_token(error: Exception) -> bool:
    from firebase_admin import messaging


    return isinstance(error, messaging.UnregisteredError)


async def _send_registrations(
    patient_id: str,
    registrations: list[dict[str, Any]],
    store: NativePushStore,
    *,
    body: str,
    data: dict[str, str],
    tag: str,
    sound_enabled: bool = True,
) -> dict[str, int]:
    attempted = accepted = 0
    for registration in registrations:
        attempted += 1
        try:
            await asyncio.to_thread(
                _fcm_send, registration["token"], body=body, data=data, tag=tag,
                sound_enabled=sound_enabled,
            )
            accepted += 1
        except Exception as error:
            try:
                expired = _is_expired_token(error)
            except Exception:
                expired = False
            if expired:
                try:
                    await asyncio.to_thread(store.delete, patient_id, registration["token"])
                except Exception:
                    logger.warning("Expired Native Push registration could not be removed")

            logger.warning("Native Push delivery failed (expired=%s)", expired)
    logger.info("Native Push attempted=%s accepted=%s", attempted, accepted)
    return {"attempted": attempted, "accepted": accepted}


async def send_behavior_alert(
    patient_id: str,
    alert: dict[str, Any],
    store: NativePushStore,
    *,
    sound_enabled: bool = True,
) -> dict[str, int]:
    pass
    if (
        not is_configured()
        or alert.get("alert_type") not in {"repetitive_behavior", "wandering"}
        or alert.get("risk_level") not in {"caution", "danger"}
    ):
        return {"attempted": 0, "accepted": 0}
    try:
        registrations = await asyncio.to_thread(store.list_for_patient, patient_id)
    except Exception:
        logger.warning("Native Push registration list could not be loaded")
        return {"attempted": 0, "accepted": 0}
    return await _send_registrations(
        patient_id, registrations, store,
        body="새 보호자 알림이 있습니다. 앱에서 확인해 주세요.",
        data={
            "alert_id": str(alert["alert_id"]), "type": "guardian_alert",
            "sound_enabled": "1" if sound_enabled else "0",
        },
        tag=str(alert["alert_id"]),
        sound_enabled=sound_enabled,
    )


async def send_door_alert(
    patient_id: str,
    alert: dict[str, Any],
    store: NativePushStore,
    *,
    sound_enabled: bool = True,
) -> dict[str, int]:
    pass
    if not is_configured() or alert.get("alert_type") != "door_event":
        return {"attempted": 0, "accepted": 0}
    try:
        registrations = await asyncio.to_thread(store.list_for_patient, patient_id)
    except Exception:
        logger.warning("Native Push registration list could not be loaded")
        return {"attempted": 0, "accepted": 0}
    return await _send_registrations(
        patient_id, registrations, store,
        body="새 출입 사진이 있습니다. 앱에서 확인해 주세요.",
        data={
            "alert_id": str(alert["alert_id"]), "type": "guardian_alert",
            "related_event_id": str(alert["related_event_id"]),
            "sound_enabled": "1" if sound_enabled else "0",
        },
        tag=str(alert["alert_id"]),
        sound_enabled=sound_enabled,
    )


async def send_test_notification(
    patient_id: str,
    registration: dict[str, Any],
    store: NativePushStore,
    *, sound_enabled: bool = True,
) -> dict[str, int]:
    pass
    if not is_configured():
        return {"attempted": 0, "accepted": 0}
    return await _send_registrations(
        patient_id, [registration], store,
        body="알림 연결 시험입니다.",
        data={"type": "push_test", "sound_enabled": "1" if sound_enabled else "0"},
        tag=f"push-test-{uuid.uuid4().hex}",
        sound_enabled=sound_enabled,
    )
