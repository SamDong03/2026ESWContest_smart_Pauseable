import asyncio
import json
import logging
import os
import re
import secrets
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, SecretStr, StrictBool, field_validator

from app.alert_history_store import AlertHistoryConflict, AlertHistoryStore
from app.push_subscription_store import PushSubscriptionStore
from app.native_push_store import NativePushStore, validate_device_token
from app.notification_preferences import DEFAULT_PREFERENCES, NotificationPreferenceStore
from app.voice_consents import CONSENT_ID_PATTERN, VOICE_CONSENT_POLICY_VERSION, VoiceConsentStore
from app.native_push import (
    is_configured as native_push_is_configured,
    send_behavior_alert as send_native_behavior_alert,
    send_door_alert as send_native_door_alert,
    send_test_notification,
)
from app.web_push import (
    is_configured as web_push_is_configured,
    public_key as web_push_public_key,
    send_behavior_alert,
    send_test_notification as send_web_push_test_notification,
    validate_subscription,
)
from app.door_event_store import DoorEventConflict, DoorEventStore
from app.home_environment import load_home_environment, save_home_environment
from app.favorite_songs import choose_song, load_songs, save_songs
from app.care_profiles import load_profile, save_profile
from app.r2_storage import R2Storage
from app.security import (
    require_app_token,
    require_device_token,
    require_worker_token,
)
from app.voice_model_service import (
    InvalidVoiceModelRequest,
    VoiceModelService,
    VoiceModelStateError,
)
from app.voice_training_service import (
    DuplicateVoiceTrainingClip,
    InvalidVoiceTrainingRequest,
    VoiceTrainingClaimError,
    VoiceTrainingJobStateError,
    VoiceTrainingService,
)


SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "guardian_snapshot.json"
DOOR_EVENTS_PATH = Path(__file__).resolve().parent / "data" / "door_events.json"
DOOR_MEDIA_DIR = Path(__file__).resolve().parent / "media"
DOOR_UPLOAD_DIR = Path(__file__).resolve().parent / "uploads" / "door-events"
ALERT_HISTORY_DIR = Path(__file__).resolve().parent / "uploads" / "alert-history"
PUSH_SUBSCRIPTIONS_DIR = Path(__file__).resolve().parent / "uploads" / "push-subscriptions"
NATIVE_PUSH_DIR = Path(__file__).resolve().parent / "uploads" / "native-push"
NOTIFICATION_PREFERENCES_DIR = Path(__file__).resolve().parent / "uploads" / "notification-preferences"
VOICE_CONSENTS_DIR = Path(__file__).resolve().parent / "uploads" / "voice-consents"
MAX_DOOR_IMAGE_BYTES = 3 * 1024 * 1024
DOOR_EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
VOICE_UPLOAD_DIR = Path(__file__).resolve().parent / "uploads" / "voice"
MAX_VOICE_BYTES = 5 * 1024 * 1024
VOICE_MESSAGE_ID_PATTERN = re.compile(r"^voice-[0-9a-f]{12}$")
VOICE_TRAINING_DIR = Path(__file__).resolve().parent / "uploads" / "training"
VOICE_TRAINING_TARGET_SECONDS = 800
MAX_TRAINING_CLIP_BYTES = 2 * 1024 * 1024
TRAINING_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}\.wav$")
PATIENT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
ALERT_WEBSOCKET_TICKET_TTL_SECONDS = 60
TTS_API_URL = os.getenv("TTS_API_URL", "http://127.0.0.1:8001/api/tts")
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()

if STORAGE_BACKEND not in {"local", "r2"}:
    raise RuntimeError(
        "STORAGE_BACKEND must be either 'local' or 'r2'"
    )


@lru_cache(maxsize=1)
def _r2_voice_training_service() -> VoiceTrainingService:
    return VoiceTrainingService(R2Storage.from_environment())


@lru_cache(maxsize=1)
def _r2_voice_model_service() -> VoiceModelService:
    return VoiceModelService(R2Storage.from_environment())


@lru_cache(maxsize=1)
def _door_event_store() -> DoorEventStore:
    r2_storage = (
        R2Storage.from_environment()
        if STORAGE_BACKEND == "r2"
        else None
    )
    return DoorEventStore(
        local_dir=DOOR_UPLOAD_DIR,
        r2_storage=r2_storage,
    )


@lru_cache(maxsize=1)
def _alert_history_store() -> AlertHistoryStore:
    return AlertHistoryStore(
        local_dir=ALERT_HISTORY_DIR,
        r2_storage=R2Storage.from_environment() if STORAGE_BACKEND == "r2" else None,
    )


@lru_cache(maxsize=1)
def _push_subscription_store() -> PushSubscriptionStore:
    return PushSubscriptionStore(
        local_dir=PUSH_SUBSCRIPTIONS_DIR,
        r2_storage=R2Storage.from_environment() if STORAGE_BACKEND == "r2" else None,
    )


@lru_cache(maxsize=1)
def _native_push_store() -> NativePushStore:
    return NativePushStore(
        local_dir=NATIVE_PUSH_DIR,
        r2_storage=R2Storage.from_environment() if STORAGE_BACKEND == "r2" else None,
    )


@lru_cache(maxsize=1)
def _notification_preferences_store() -> NotificationPreferenceStore:
    return NotificationPreferenceStore(
        local_dir=NOTIFICATION_PREFERENCES_DIR,
        r2_storage=R2Storage.from_environment() if STORAGE_BACKEND == "r2" else None,
    )


async def _delivery_preferences(patient_id: str) -> dict[str, bool]:
    try:
        return await asyncio.to_thread(_notification_preferences_store().for_delivery, patient_id)
    except Exception:
        logging.getLogger(__name__).warning("Notification settings store unavailable; safety fallback in use")
        return dict(DEFAULT_PREFERENCES)


@lru_cache(maxsize=1)
def _voice_consent_store() -> VoiceConsentStore:
    return VoiceConsentStore(
        local_dir=VOICE_CONSENTS_DIR,
        r2_storage=R2Storage.from_environment() if STORAGE_BACKEND == "r2" else None,
    )


class VoiceConsentRequest(BaseModel):
    model_config = {"extra": "forbid"}
    request_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    policy_version: Literal[VOICE_CONSENT_POLICY_VERSION]
    accepted: StrictBool

    @field_validator("accepted")
    @classmethod
    def require_explicit_acceptance(cls, value):
        if value is not True:
            raise ValueError("Explicit voice consent is required")
        return value


async def _deliver_alert_notifications(patient_id: str, alert: dict[str, Any]) -> None:
    pass
    behavior = alert["alert_type"] in {"repetitive_behavior", "wandering"}
    web_enabled = behavior and web_push_is_configured()
    native_enabled = (behavior or alert["alert_type"] == "door_event") and native_push_is_configured()
    if not web_enabled and not native_enabled:
        return
    preferences = await _delivery_preferences(patient_id)
    if not preferences["safety_notifications"]:
        return
    sound_enabled = preferences["sound_enabled"]
    if web_enabled:
        try:
            await send_behavior_alert(patient_id, alert, _push_subscription_store(), sound_enabled=sound_enabled)
        except Exception:
            logging.getLogger(__name__).warning("Web Push delivery unavailable; alert remains stored")
    if native_enabled:
        try:
            sender = send_native_behavior_alert if behavior else send_native_door_alert
            await sender(patient_id, alert, _native_push_store(), sound_enabled=sound_enabled)
        except Exception:
            logging.getLogger(__name__).warning("Native Push delivery unavailable; alert remains stored")


DEMO_SCENARIOS: dict[str, dict[str, Any]] = {
    "normal": {
        "label": "정상 상태",
        "description": "특이사항 없이 일상생활 중인 상태",
        "patient": {
            "location": "거실",
            "activity": "휴식 중",
            "safety_label": "안전",
            "day_summary": "특이사항 없음",
        },
    },
    "repetitive_behavior": {
        "label": "현관문 반복 행동",
        "description": "20분 동안 현관문을 7회 여닫은 상황",
        "patient": {
            "location": "현관",
            "activity": "반복 이동",
            "safety_label": "확인 필요",
            "day_summary": "반복 행동 감지",
        },
    },
    "inactivity": {
        "label": "장시간 무활동",
        "description": "거실에서 2시간 동안 움직임이 없는 상황",
        "patient": {
            "location": "거실",
            "activity": "움직임 없음",
            "safety_label": "확인 필요",
            "day_summary": "2시간 무활동",
        },
    },
    "night_movement": {
        "label": "야간 움직임",
        "description": "새벽 시간에 침실에서 거실로 이동한 상황",
        "patient": {
            "location": "거실",
            "activity": "야간 이동",
            "safety_label": "확인 필요",
            "day_summary": "야간 움직임 감지",
        },
    },
    "door_exit": {
        "label": "외출 장면 촬영",
        "description": "현관 카메라에 외출 장면이 촬영된 상황",
        "patient": {
            "location": "현관 밖",
            "activity": "외출 감지",
            "safety_label": "확인 필요",
            "day_summary": "외출 장면 감지",
        },
    },
}

async def _voice_retention_loop() -> None:
    try:
        configured_interval = int(
            os.getenv("VOICE_RETENTION_SWEEP_SECONDS", "3600")
        )
    except ValueError:
        configured_interval = 3600
    interval_seconds = max(300, configured_interval)
    while True:
        try:
            reconciled = await asyncio.to_thread(
                _r2_voice_training_service().reconcile_verified_installations
            )
            if reconciled["jobs_scheduled"]:
                logging.getLogger(__name__).info(
                    "Voice retention backfill completed: jobs=%d",
                    reconciled["jobs_scheduled"],
                )
            result = await asyncio.to_thread(
                _r2_voice_training_service().cleanup_expired_raw_audio
            )
            if result["jobs_cleaned"]:
                logging.getLogger(__name__).info(
                    "Voice retention cleanup completed: jobs=%d objects=%d",
                    result["jobs_cleaned"],
                    result["objects_deleted"],
                )
            model_result = await asyncio.to_thread(
                _r2_voice_model_service().cleanup_expired_models
            )
            if model_result["models_deleted"]:
                logging.getLogger(__name__).info(
                    "Voice model retention cleanup completed: models=%d objects=%d",
                    model_result["models_deleted"],
                    model_result["objects_deleted"],
                )
        except Exception:
            logging.getLogger(__name__).exception(
                "Voice retention cleanup failed; it will be retried"
            )
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    retention_task: asyncio.Task[None] | None = None
    retention_storage_is_configured = all(
        os.getenv(name)
        for name in (
            "R2_ENDPOINT_URL",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET_NAME",
        )
    )
    if STORAGE_BACKEND == "r2" and retention_storage_is_configured:
        retention_task = asyncio.create_task(_voice_retention_loop())
    try:
        yield
    finally:
        if retention_task is not None:
            retention_task.cancel()
            with suppress(asyncio.CancelledError):
                await retention_task


app = FastAPI(
    title="PAUSEABLE Guardian API",
    version="0.1.0",
    description="Flutter 보호자 앱과 실제 센서 데이터 사이의 REST API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip().rstrip("/")
        for origin in os.getenv("PAUSEABLE_WEB_ORIGINS", "").split(",")
        if origin.strip().startswith("https://")
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def private_door_photo_responses(request: Request, call_next):
    response = await call_next(request)


    path = request.url.path
    if path == "/api/door-events" or path.startswith("/api/door-events/") or (
        path.startswith("/api/patients/") and path.endswith("/dashboard")
    ):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        vary = response.headers.get("Vary", "")
        if "authorization" not in {value.strip().lower() for value in vary.split(",")}:
            response.headers["Vary"] = f"{vary}, Authorization".strip(", ")
    return response


class PauseAlertRequest(BaseModel):
    duration_minutes: int = Field(gt=0, le=24 * 60)


class GuardianProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    relationship: str = Field(min_length=1, max_length=80)
    phone_number: str = Field(min_length=8, max_length=30)


class CareProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    patient_name: str = Field(min_length=1, max_length=40)
    relationship: str = Field(default="", max_length=80)
    phone_number: str = Field(default="", max_length=30)
    patient_call_name: str = Field(default="", max_length=40)

    @field_validator("*", mode="before")
    @classmethod
    def trim_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if value and len(re.sub(r"\D", "", value)) < 8:
            raise ValueError("Enter a valid phone number or leave it empty")
        return value

    @field_validator("relationship", "patient_call_name")
    @classmethod
    def validate_spoken_text(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Use a single line without control characters")
        return value


class GuardianPreferencesRequest(BaseModel):
    safety_notifications: StrictBool
    sound_enabled: StrictBool


class HomeEnvironmentRequest(BaseModel):
    region_code: str = Field(pattern=r'^\d{10}$')
    auto_lighting_enabled: bool = False


class NewVoiceTrainingSessionRequest(BaseModel):
    previous_job_id: str = Field(pattern=r"^voice-job-[0-9a-f]{12}$")


class FavoriteSongRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=500)


class FavoriteSongsRequest(BaseModel):
    songs: list[FavoriteSongRequest] = Field(max_length=30)


class WorkerVoiceTrainingClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class WorkerVoiceTrainingStatusRequest(BaseModel):
    claim_id: str = Field(min_length=1, max_length=64)
    lease_token: str = Field(min_length=1, max_length=256)
    state: Literal[
        "claimed",
        "downloading",
        "preprocessing",
        "training",
        "exporting",
        "validating_model",
        "uploading",
    ] | None = None
    message: str | None = Field(default=None, max_length=1000)
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class WorkerArtifactDescriptor(BaseModel):
    size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_md5: str = Field(min_length=24, max_length=24)


class WorkerUploadPlanRequest(BaseModel):
    claim_id: str = Field(min_length=1, max_length=64)
    lease_token: str = Field(min_length=1, max_length=256)
    artifacts: dict[str, WorkerArtifactDescriptor]
    expires_seconds: int = Field(default=3600, ge=300, le=7200)


class WorkerCompleteRequest(BaseModel):
    claim_id: str = Field(min_length=1, max_length=64)
    lease_token: str = Field(min_length=1, max_length=256)


class WorkerFailRequest(WorkerCompleteRequest):
    failed_stage: str = Field(min_length=1, max_length=64)
    error: str = Field(min_length=1, max_length=1000)
    retryable: bool = True
    retry_delay_seconds: int = Field(default=300, ge=0, le=86400)


class VoiceModelUploadPlanRequest(BaseModel):
    patient_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    source_job_id: str | None = Field(
        default=None,
        pattern=r"^voice-job-[0-9a-f]{12}$",
    )
    artifacts: dict[str, WorkerArtifactDescriptor]
    expires_seconds: int = Field(default=3600, ge=300, le=7200)


class VoiceModelPublishRequest(BaseModel):
    patient_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class VoiceModelInstallAckRequest(BaseModel):
    patient_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    status: Literal["installed", "failed", "up_to_date"]
    detail: str | None = Field(default=None, max_length=1000)
    previous_model_id: str | None = Field(
        default=None,
        pattern=r"^voice-model-[0-9a-f]{12}$",
    )


class HaEntityEventRequest(BaseModel):
    event_id: str = Field(min_length=1)
    occurred_at: datetime
    patient_id: str = Field(default="byunwoojin", pattern=PATIENT_ID_PATTERN)
    source: Literal["home-assistant"] = "home-assistant"
    entity_id: str = Field(min_length=1)
    state: str
    previous_state: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class DecisionEventRequest(BaseModel):
    model_config = {"extra": "forbid"}

    contract_version: Literal["1.0"]
    event_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", max_length=128)
    occurred_at: datetime
    patient_id: str = Field(pattern=PATIENT_ID_PATTERN)
    device_id: str = Field(pattern=DEVICE_ID_PATTERN)
    source: Literal["central-atlas-app"]
    decision: Literal["normal", "repetitive_behavior", "wandering_suspected", "unknown"]
    risk_level: Literal["normal", "caution", "danger", "unknown"]
    risk_score: int | None = Field(ge=0, le=100)
    pattern_code: str | None = Field(
        default=None, pattern=r"^[a-z0-9_]+$", max_length=64,
    )
    message: str = Field(default="", max_length=500)
    actions: list[Literal["notify_guardian", "control_appliance"]] = Field(max_length=2)


class PushKeysRequest(BaseModel):
    model_config = {"extra": "forbid"}

    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeysRequest


    expiration_time: float | None = Field(default=None, alias="expirationTime")


class DeletePushSubscriptionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    endpoint: str = Field(min_length=1, max_length=2048)


class WebPushTestRequest(DeletePushSubscriptionRequest):
    delay_seconds: int = Field(default=10, ge=0, le=15, strict=True)


class NativePushTokenRequest(BaseModel):
    model_config = {"extra": "forbid"}

    token: SecretStr


class NativePushRegistrationRequest(NativePushTokenRequest):
    platform: Literal["android"]


class NativePushTestRequest(NativePushTokenRequest):
    delay_seconds: int = Field(default=0, ge=0, le=15, strict=True)


def _native_device_token(request: NativePushTokenRequest) -> str:
    try:
        return validate_device_token(request.token.get_secret_value())
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid FCM registration token") from None


class AlertWebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, patient_id: str) -> None:
        await websocket.accept()
        self._connections[websocket] = patient_id

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.pop(websocket, None)

    async def broadcast(
        self,
        patient_id: str,
        payload: dict[str, Any],
    ) -> None:
        disconnected: list[WebSocket] = []
        for websocket, connected_patient_id in list(self._connections.items()):
            if connected_patient_id != patient_id:
                continue
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(websocket)


_paused_alerts: dict[str, datetime] = {}
_confirmed_door_events: set[str] = set()
_demo_state = {"active_scenario_id": "repetitive_behavior"}
_guardian_profile = {
    "name": "김보호",
    "relationship": "김영희 님의 보호자",
    "phone_number": "010-1234-5678",
}
_alert_websockets = AlertWebSocketManager()
_alert_websocket_tickets: dict[str, tuple[str, datetime]] = {}
_web_push_test_cooldowns: dict[str, datetime] = {}
_web_push_test_results: dict[str, dict[str, Any]] = {}


def _issue_alert_websocket_ticket(patient_id: str) -> str:
    now = datetime.now(timezone.utc)
    expired = [
        ticket
        for ticket, (_, expires_at) in _alert_websocket_tickets.items()
        if expires_at <= now
    ]
    for ticket in expired:
        _alert_websocket_tickets.pop(ticket, None)

    ticket = secrets.token_urlsafe(32)
    _alert_websocket_tickets[ticket] = (
        patient_id,
        now + timedelta(seconds=ALERT_WEBSOCKET_TICKET_TTL_SECONDS),
    )
    return ticket


def _consume_alert_websocket_ticket(ticket: str, patient_id: str) -> bool:
    issued = _alert_websocket_tickets.pop(ticket, None)
    if issued is None:
        return False
    issued_patient_id, expires_at = issued
    return (
        issued_patient_id == patient_id
        and expires_at > datetime.now(timezone.utc)
    )


def _ha_entity_name(event: HaEntityEventRequest) -> str:
    object_id = event.entity_id.partition(".")[2] or event.entity_id
    known_names = {
        "pauseable_washing_machine": "세탁기",
        "setaggi_power": "세탁기 전원",
        "setaggi_remaining_time": "세탁기 남은 시간",
        "setaggi_cycles": "세탁기 동작 횟수",
        "setaggi_error": "세탁기 오류",
        "geonjogi_power": "건조기 전원",
        "geonjogi_remaining_time": "건조기 남은 시간",
        "geonjogi_error": "건조기 오류",
        "naengjanggo_door": "냉장고 문",
    }
    if object_id in known_names:
        return known_names[object_id]

    friendly_name = event.attributes.get("friendly_name")
    if isinstance(friendly_name, str) and friendly_name.strip():
        return friendly_name.strip()
    return object_id.replace("_", " ")


def _ha_state_description(event: HaEntityEventRequest) -> tuple[str, str]:
    domain = event.entity_id.partition(".")[0]
    normalized = event.state.strip().lower()
    device_class = str(event.attributes.get("device_class", "")).lower()

    if domain == "binary_sensor" and device_class in {"door", "garage_door", "opening"}:
        return ("열렸어요", "caution") if normalized == "on" else ("닫혔어요", "normal")
    if domain == "binary_sensor":
        return ("감지됐어요", "caution") if normalized == "on" else ("해제됐어요", "normal")
    if domain in {"switch", "input_boolean", "light"}:
        return ("켜졌어요", "caution") if normalized == "on" else ("꺼졌어요", "normal")
    if domain == "event":
        return ("이벤트가 발생했어요", "caution")
    if normalized in {"on", "open", "opening", "problem", "error", "detected"}:
        return (f"{event.state} 상태예요", "caution")
    return (f"{event.state}(으)로 변경됐어요", "normal")


def _app_alert_for_event(event: HaEntityEventRequest) -> dict[str, Any]:
    entity_name = _ha_entity_name(event)
    state_label, risk_level = _ha_state_description(event)
    return {
        "alert_id": f"ha-{event.event_id}",
        "patient_id": event.patient_id,
        "occurred_at": event.occurred_at.isoformat(),
        "risk_level": risk_level,
        "alert_type": "appliance",
        "device_id": event.entity_id,
        "title": f"{entity_name} · {state_label}",
        "message": f"Home Assistant에서 {entity_name} 상태 변경을 감지했습니다.",
        "related_event_id": event.event_id,
    }


def _app_alert_for_decision(event: DecisionEventRequest) -> dict[str, Any] | None:
    if "notify_guardian" not in event.actions or event.decision == "unknown":
        return None

    if event.decision == "repetitive_behavior":
        alert_type = "repetitive_behavior"
        title = (
            "높은 위험 · 반복 행동 감지"
            if event.risk_level == "danger" else "반복 행동 감지"
        )
        fallback = "평소와 다른 반복 행동이 감지되었습니다. 상황을 확인해 주세요."
    elif event.decision == "wandering_suspected":
        alert_type = "wandering"
        title = "배회 의심 감지"
        fallback = "이동 패턴에 변화가 감지되었습니다. 상황을 확인해 주세요."
    else:
        alert_type = "recovery"
        title = "생활 상태 정상 복귀"
        fallback = "이전에 감지된 행동 변화가 정상 상태로 돌아왔습니다."

    alert = {
        "contract_version": event.contract_version,
        "alert_id": event.event_id,
        "event_id": event.event_id,
        "related_event_id": event.event_id,
        "occurred_at": event.occurred_at.isoformat(),
        "patient_id": event.patient_id,
        "device_id": event.device_id,
        "risk_level": event.risk_level,
        "risk_score": event.risk_score,
        "alert_type": alert_type,
        "title": title,
        "message": event.message.strip() or fallback,
        "requires_guardian_response": event.risk_level in {"caution", "danger"},
    }
    if event.pattern_code is not None:
        alert["pattern_code"] = event.pattern_code
    return alert


async def _request_tts(
    event: HaEntityEventRequest,
    alert: dict[str, Any],
) -> dict[str, Any]:
    request_payload = {
        "request_id": event.event_id,
        "occurred_at": event.occurred_at.isoformat(),
        "situation": "home_assistant_entity_changed",
        "voice_profile_id": "development-default",
        "message_candidates": [
            alert["title"].replace("어요", "습니다")
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(TTS_API_URL, json=request_payload)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as error:
        return {
            "request_id": event.event_id,
            "status": "failed",
            "selected_message": alert["message"],
            "error": str(error),
        }


def _load_snapshot() -> dict[str, Any]:
    with SNAPSHOT_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def _ensure_patient(patient_id: str) -> dict[str, Any]:
    patient = _load_snapshot()["patient"]
    if patient["id"] != patient_id:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@app.get(
    "/api/patients/{patient_id}/home-environment",
    dependencies=[Depends(require_app_token)],
)
def get_home_environment(patient_id: str) -> dict[str, Any]:
    _ensure_patient(patient_id)
    return load_home_environment(patient_id, STORAGE_BACKEND)


@app.put(
    "/api/patients/{patient_id}/home-environment",
    dependencies=[Depends(require_app_token)],
)
def update_home_environment(patient_id: str, body: HomeEnvironmentRequest) -> dict[str, Any]:
    _ensure_patient(patient_id)
    return save_home_environment(
        patient_id, body.region_code, body.auto_lighting_enabled, STORAGE_BACKEND,
    )


@app.get(
    "/api/device/patients/{patient_id}/home-environment",
    dependencies=[Depends(require_device_token)],
)
def get_device_home_environment(patient_id: str, response: Response) -> dict[str, Any]:
    pass
    _ensure_patient(patient_id)
    saved = load_home_environment(patient_id, STORAGE_BACKEND)
    region = saved["region"]
    response.headers["Cache-Control"] = "no-store"
    return {
        "patient_id": patient_id,
        "region": None if region is None else {
            key: region[key]
            for key in ("code", "province", "city", "district", "nx", "ny")
        },
        "storage_backend": saved["storage_backend"],
        "is_persistent": saved["is_persistent"],
    }


@app.get(
    "/api/patients/{patient_id}/favorite-songs",
    dependencies=[Depends(require_app_token)],
)
def get_favorite_songs(patient_id: str) -> dict[str, Any]:
    _ensure_patient(patient_id)
    return {"patient_id": patient_id, "songs": load_songs(patient_id, STORAGE_BACKEND)}


@app.put(
    "/api/patients/{patient_id}/favorite-songs",
    dependencies=[Depends(require_app_token)],
)
def update_favorite_songs(patient_id: str, body: FavoriteSongsRequest) -> dict[str, Any]:
    _ensure_patient(patient_id)
    songs = save_songs(
        patient_id,
        [song.model_dump() for song in body.songs],
        STORAGE_BACKEND,
    )
    return {"patient_id": patient_id, "songs": songs}


@app.get(
    "/api/device/patients/{patient_id}/favorite-songs/random",
    dependencies=[Depends(require_device_token)],
)
def get_random_favorite_song(patient_id: str) -> dict[str, Any]:
    pass
    _ensure_patient(patient_id)
    return choose_song(patient_id, STORAGE_BACKEND)


def _demo_device_connection() -> dict[str, Any]:
    return {
        "device_name": "PAUSEABLE Home",
        "is_online": True,
        "last_checked_label": "방금 전",
        "services": [
            {
                "name": "Home Assistant",
                "is_connected": True,
                "detail": "가상 센서 데이터 수신 중",
            },
            {
                "name": "현관 센서·카메라",
                "is_connected": True,
                "detail": "가상 출입 이벤트 사용 중",
            },
            {
                "name": "Raspberry Pi 5",
                "is_connected": True,
                "detail": "가상 연결 상태",
            },
        ],
    }


def _apply_demo_scenario(snapshot: dict[str, Any]) -> None:
    scenario_id = _demo_state["active_scenario_id"]
    scenario = DEMO_SCENARIOS[scenario_id]
    snapshot["demo_scenario"] = scenario_id
    snapshot["patient"].update(scenario["patient"])

    if scenario_id == "inactivity":
        snapshot["alerts"].insert(
            0,
            {
                "id": "alert-inactivity-demo",
                "type": "inactivity",
                "category": "확인 필요",
                "title": "장시간 움직임 없음",
                "description": "거실에서 2시간 동안 움직임이 감지되지 않았어요.",
                "time_label": "방금 전",
            },
        )
    elif scenario_id == "night_movement":
        night_alert = next(
            alert for alert in snapshot["alerts"]
            if alert["type"] == "night_movement"
        )
        snapshot["alerts"].remove(night_alert)
        snapshot["alerts"].insert(0, night_alert)


def _load_raw_door_events() -> list[dict[str, Any]]:
    with DOOR_EVENTS_PATH.open(encoding="utf-8") as source:
        mock_events = json.load(source)["events"]
    return _door_event_store().list_events() + mock_events


def _raw_door_event(event_id: str) -> dict[str, Any]:
    if not DOOR_EVENT_ID_PATTERN.fullmatch(event_id):
        raise HTTPException(status_code=404, detail="Door event not found")
    stored = _door_event_store().get_event(event_id, use_cache=True)
    if stored is not None:
        return stored

    with DOOR_EVENTS_PATH.open(encoding="utf-8") as source:
        mock_events = json.load(source)["events"]
    for event in mock_events:
        if event["id"] == event_id:
            return event
    raise HTTPException(status_code=404, detail="Door event not found")


def _serialize_door_event(
    event: dict[str, Any],
    request: Request,
) -> dict[str, Any]:
    private_fields = {
        "image_file",
        "image_key",
        "image_storage",
        "image_sha256",
        "image_content_type",
    }
    payload = {
        key: value
        for key, value in event.items()
        if key not in private_fields
    }
    payload["image_url"] = str(
        request.url_for("get_door_event_image", event_id=event["id"]),
    )
    payload["is_confirmed"] = event["id"] in _confirmed_door_events
    return payload


def _alert_exists(alert_id: str) -> bool:
    snapshot = _load_snapshot()
    return any(alert["id"] == alert_id for alert in snapshot["alerts"])


def _active_pause_until(alert_id: str) -> datetime | None:
    pause_until = _paused_alerts.get(alert_id)
    if pause_until is not None and pause_until <= datetime.now(timezone.utc):
        _paused_alerts.pop(alert_id, None)
        return None
    return pause_until


def _voice_message_path(message_id: str) -> Path:
    if not VOICE_MESSAGE_ID_PATTERN.fullmatch(message_id):
        raise HTTPException(status_code=404, detail="Voice message not found")
    path = (VOICE_UPLOAD_DIR / f"{message_id}.wav").resolve()
    if VOICE_UPLOAD_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="Voice message not found")
    return path


def _voice_training_patient_dir(patient_id: str) -> Path:
    patient_dir = (VOICE_TRAINING_DIR / patient_id).resolve()
    if VOICE_TRAINING_DIR.resolve() not in patient_dir.parents:
        raise HTTPException(status_code=400, detail="Invalid patient id")
    return patient_dir


def _load_voice_training_manifest(patient_id: str) -> dict[str, Any]:
    manifest_path = _voice_training_patient_dir(patient_id) / "manifest.json"
    if not manifest_path.is_file():
        return {
            "patient_id": patient_id,
            "target_seconds": VOICE_TRAINING_TARGET_SECONDS,
            "clips": [],
        }
    with manifest_path.open(encoding="utf-8") as source:
        return json.load(source)


def _save_voice_training_manifest(manifest: dict[str, Any]) -> None:
    patient_dir = _voice_training_patient_dir(manifest["patient_id"])
    patient_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = patient_dir / "manifest.json"
    temporary_path = patient_dir / "manifest.tmp"
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(manifest_path)


def _serialize_voice_training_progress(
    manifest: dict[str, Any],
) -> dict[str, Any]:
    recorded_seconds = sum(
        int(clip["duration_seconds"])
        for clip in manifest["clips"]
    )
    target_seconds = int(manifest["target_seconds"])
    return {
        "patient_id": manifest["patient_id"],
        "target_seconds": target_seconds,
        "recorded_seconds": recorded_seconds,
        "remaining_seconds": max(0, target_seconds - recorded_seconds),
        "clip_count": len(manifest["clips"]),
        "is_ready": recorded_seconds >= target_seconds,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/api/patients/{patient_id}/care-profile",
    dependencies=[Depends(require_app_token)],
)
def get_care_profile(patient_id: str, response: Response) -> dict[str, str]:
    _ensure_patient(patient_id)
    response.headers["Cache-Control"] = "no-store"
    return load_profile(patient_id, STORAGE_BACKEND)


@app.put(
    "/api/patients/{patient_id}/care-profile",
    dependencies=[Depends(require_app_token)],
)
def update_care_profile(
    patient_id: str, request: CareProfileRequest, response: Response,
) -> dict[str, str]:
    _ensure_patient(patient_id)
    response.headers["Cache-Control"] = "no-store"
    return save_profile(patient_id, request.model_dump(exclude_unset=True), STORAGE_BACKEND)


@app.get(
    "/api/device/patients/{patient_id}/tts-context",
    dependencies=[Depends(require_device_token)],
)
@app.get(
    "/api/worker/patients/{patient_id}/tts-context",
    dependencies=[Depends(require_worker_token)],
)
def get_tts_context(patient_id: str, response: Response) -> dict[str, Any]:
    pass
    _ensure_patient(patient_id)
    profile = load_profile(patient_id, STORAGE_BACKEND)
    response.headers["Cache-Control"] = "no-store"
    return {
        "patient_id": patient_id,
        "relationship": profile["relationship"],
        "patient_call_name": profile["patient_call_name"],
        "is_configured": bool(profile["patient_call_name"]),
    }


@app.get("/api/guardians/me")
def get_guardian_profile() -> dict[str, Any]:
    return dict(_guardian_profile)


@app.put("/api/guardians/me")
def update_guardian_profile(request: GuardianProfileRequest) -> dict[str, Any]:
    _guardian_profile.update(request.model_dump())
    return dict(_guardian_profile)


@app.get(
    "/api/guardians/me/preferences",
    dependencies=[Depends(require_app_token)],
)
def get_guardian_preferences(
    response: Response, patient_id: str | None = Query(default=None, pattern=PATIENT_ID_PATTERN),
) -> dict[str, bool]:

    selected = patient_id or _load_snapshot()["patient"]["id"]
    _ensure_patient(selected)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    try:
        return _notification_preferences_store().load(selected)
    except Exception:
        raise HTTPException(503, "Notification settings could not be loaded", headers={
            "Cache-Control": "private, no-store", "Vary": "Authorization",
        }) from None


@app.put(
    "/api/guardians/me/preferences",
    dependencies=[Depends(require_app_token)],
)
def update_guardian_preferences(
    request: GuardianPreferencesRequest, response: Response,
    patient_id: str | None = Query(default=None, pattern=PATIENT_ID_PATTERN),
) -> dict[str, bool]:
    selected = patient_id or _load_snapshot()["patient"]["id"]
    _ensure_patient(selected)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    try:
        return _notification_preferences_store().save(selected, request.model_dump())
    except Exception:
        raise HTTPException(503, "Notification settings could not be saved", headers={
            "Cache-Control": "private, no-store", "Vary": "Authorization",
        }) from None


@app.get("/api/patients/{patient_id}/device-connection")
def get_device_connection(patient_id: str) -> dict[str, Any]:
    _ensure_patient(patient_id)
    return _demo_device_connection()


@app.post("/api/patients/{patient_id}/device-connection/check")
def check_device_connection(patient_id: str) -> dict[str, Any]:
    _ensure_patient(patient_id)
    return _demo_device_connection()


@app.post("/api/patients/{patient_id}/care-call")
def request_care_call(patient_id: str) -> dict[str, str]:
    patient = _ensure_patient(patient_id)
    return {
        "title": "보호 전화 요청 완료",
        "message": f"{patient['name']} 님에게 보호 전화를 연결하는 가상 요청을 보냈습니다.",
        "reference_id": f"demo-care-{uuid.uuid4().hex[:8]}",
    }


@app.post("/api/patients/{patient_id}/emergency-contact")
def request_emergency_contact(patient_id: str) -> dict[str, str]:
    _ensure_patient(patient_id)
    return {
        "title": "긴급 연락 요청 완료",
        "message": "등록된 보호자와 긴급 연락망에 가상 요청을 보냈습니다.",
        "reference_id": f"demo-emergency-{uuid.uuid4().hex[:8]}",
    }


@app.websocket("/ws/alerts")
async def alert_websocket(websocket: WebSocket) -> None:
    patient_id = websocket.query_params.get("patient_id", "")
    ticket = websocket.query_params.get("ticket", "")
    if not patient_id or not ticket or not _consume_alert_websocket_ticket(
        ticket,
        patient_id,
    ):
        await websocket.close(code=4401, reason="Invalid or expired ticket")
        return

    await _alert_websockets.connect(websocket, patient_id)
    await websocket.send_json(
        {"type": "ready", "patient_id": patient_id, "contract_version": "1.0"},
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _alert_websockets.disconnect(websocket)


@app.post(
    "/api/events/ha",
    dependencies=[Depends(require_device_token)],
)
async def receive_ha_event(event: HaEntityEventRequest) -> dict[str, Any]:
    _ensure_patient(event.patient_id)
    alert = _app_alert_for_event(event)
    try:
        created = _alert_history_store().create(alert)
    except AlertHistoryConflict as error:
        raise HTTPException(status_code=409, detail="Alert id already exists with different contents") from error
    if not created:
        return {"status": "duplicate", "alert": alert, "voice": {"status": "skipped"}}
    await _alert_websockets.broadcast(
        event.patient_id,
        {"type": "app_alert", "data": alert},
    )
    voice_result = await _request_tts(event, alert)
    return {
        "status": "accepted",
        "alert": alert,
        "voice": voice_result,
    }


@app.post(
    "/api/events/decisions",
    status_code=202,
    dependencies=[Depends(require_device_token)],
)
async def receive_decision_event(
    event: DecisionEventRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    _ensure_patient(event.patient_id)
    if request.headers.get("Idempotency-Key", event.event_id) != event.event_id:
        raise HTTPException(status_code=422, detail="Idempotency-Key must match event_id")
    if event.occurred_at.tzinfo is None or event.occurred_at.utcoffset() != timedelta(0):
        raise HTTPException(status_code=422, detail="occurred_at must be UTC")
    if len(set(event.actions)) != len(event.actions):
        raise HTTPException(status_code=422, detail="actions must be unique")
    valid_risks = {
        "normal": {"normal"},
        "repetitive_behavior": {"caution", "danger"},
        "wandering_suspected": {"caution", "danger"},
        "unknown": {"unknown"},
    }
    if event.risk_level not in valid_risks[event.decision]:
        raise HTTPException(status_code=422, detail="decision and risk_level do not match")

    alert = _app_alert_for_decision(event)
    if alert is None:
        return {"status": "accepted", "event_id": event.event_id, "duplicate": False}

    try:
        created = _alert_history_store().create(alert)
    except AlertHistoryConflict as error:
        raise HTTPException(
            status_code=409, detail="Event id already exists with different contents",
        ) from error
    if not created:
        response.status_code = 200
    else:
        await _alert_websockets.broadcast(
            event.patient_id, {"type": "app_alert", "data": alert},
        )
        background_tasks.add_task(_deliver_alert_notifications, event.patient_id, alert)
    return {
        "status": "accepted" if created else "duplicate",
        "event_id": event.event_id,
        "duplicate": not created,
    }


@app.get(
    "/api/patients/{patient_id}/alerts",
    dependencies=[Depends(require_app_token)],
)
def list_alert_history(
    patient_id: str,
    limit: int = Query(default=100, ge=1, le=100),
) -> dict[str, Any]:
    _ensure_patient(patient_id)
    alerts = _alert_history_store().list_recent(patient_id, limit=limit)
    return {"patient_id": patient_id, "alerts": alerts}


@app.post(
    "/api/patients/{patient_id}/alerts/{alert_id}/read",
    dependencies=[Depends(require_app_token)],
)
def mark_alert_read(patient_id: str, alert_id: str) -> dict[str, str]:
    _ensure_patient(patient_id)
    if not _alert_history_store().mark_read(patient_id, alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "read", "alert_id": alert_id}


@app.get(
    "/api/patients/{patient_id}/push/config",
    dependencies=[Depends(require_app_token)],
)
def get_push_config(patient_id: str) -> dict[str, Any]:
    _ensure_patient(patient_id)
    enabled = web_push_is_configured()
    return {"enabled": enabled, "public_key": web_push_public_key() if enabled else None}


@app.post(
    "/api/patients/{patient_id}/push/subscriptions",
    status_code=201,
    dependencies=[Depends(require_app_token)],
)
def register_push_subscription(
    patient_id: str,
    request: PushSubscriptionRequest,
) -> dict[str, str]:
    _ensure_patient(patient_id)
    if not web_push_is_configured():
        raise HTTPException(status_code=503, detail="Web Push is not configured")
    try:
        subscription = validate_subscription(request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    store = _push_subscription_store()
    existing = store.list_for_patient(patient_id)
    if (
        len(existing) >= 8
        and not any(item["endpoint"] == subscription["endpoint"] for item in existing)
    ):
        raise HTTPException(status_code=409, detail="Too many registered browsers")
    store.save(patient_id, subscription)
    return {"status": "subscribed"}


@app.delete(
    "/api/patients/{patient_id}/push/subscriptions",
    status_code=204,
    dependencies=[Depends(require_app_token)],
)
def remove_push_subscription(
    patient_id: str,
    request: DeletePushSubscriptionRequest,
) -> None:
    _ensure_patient(patient_id)
    _push_subscription_store().delete(patient_id, request.endpoint)


async def _deliver_web_push_test(
    test_id: str, patient_id: str, endpoint: str, delay_seconds: int,
    store: PushSubscriptionStore,
) -> None:
    try:
        if delay_seconds:
            await asyncio.sleep(delay_seconds)
        preferences = await _delivery_preferences(patient_id)
        counts = await send_web_push_test_notification(
            patient_id, endpoint, store, sound_enabled=preferences["sound_enabled"],
        )
        status = "accepted" if counts["accepted"] else "skipped" if not counts["attempted"] else "failed"
    except Exception:
        counts = {"attempted": 0, "accepted": 0}
        status = "failed"
    result = _web_push_test_results.get(test_id)
    if result is not None:
        result.update(status=status, **counts)


@app.post(
    "/api/patients/{patient_id}/push/test", status_code=202,
    dependencies=[Depends(require_app_token)],
)
async def schedule_web_push_test(
    patient_id: str, request: WebPushTestRequest, background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    _ensure_patient(patient_id)
    if not web_push_is_configured():
        raise HTTPException(503, "Web Push is not configured")
    store = _push_subscription_store()
    if await asyncio.to_thread(store.get, patient_id, request.endpoint) is None:
        raise HTTPException(404, "This browser is not registered")
    now = datetime.now(timezone.utc)
    for key, until in list(_web_push_test_cooldowns.items()):
        if until <= now:
            _web_push_test_cooldowns.pop(key, None)
    for key, result in list(_web_push_test_results.items()):
        if result["expires_at"] <= now:
            _web_push_test_results.pop(key, None)
    cooldown_key = f"{patient_id}:{store._digest(request.endpoint)}"
    if cooldown_key in _web_push_test_cooldowns:
        raise HTTPException(429, "Wait 30 seconds before another test", headers={"Retry-After": "30"})
    if len(_web_push_test_results) >= 256:
        raise HTTPException(429, "Too many pending tests; retry later")
    _web_push_test_cooldowns[cooldown_key] = now + timedelta(seconds=30)
    test_id = f"web-push-test-{uuid.uuid4().hex}"
    _web_push_test_results[test_id] = {
        "patient_id": patient_id, "expires_at": now + timedelta(minutes=5),
        "status": "scheduled", "attempted": 0, "accepted": 0,
    }
    background_tasks.add_task(
        _deliver_web_push_test, test_id, patient_id, request.endpoint,
        request.delay_seconds, store,
    )
    return {"test_id": test_id, "status": "scheduled", "delay_seconds": request.delay_seconds}


@app.get(
    "/api/patients/{patient_id}/push/test/{test_id}",
    dependencies=[Depends(require_app_token)],
)
def get_web_push_test_result(patient_id: str, test_id: str) -> dict[str, Any]:
    _ensure_patient(patient_id)
    result = _web_push_test_results.get(test_id)
    if result is None or result["patient_id"] != patient_id or result["expires_at"] <= datetime.now(timezone.utc):
        raise HTTPException(404, "Test result expired or unavailable")
    return {"test_id": test_id, **{key: result[key] for key in ("status", "attempted", "accepted")}}


@app.get(
    "/api/patients/{patient_id}/native-push/config",
    dependencies=[Depends(require_app_token)],
)
def get_native_push_config(patient_id: str) -> dict[str, bool]:
    _ensure_patient(patient_id)
    return {"configured": native_push_is_configured()}


@app.put(
    "/api/patients/{patient_id}/native-push/registration",
    status_code=201,
    dependencies=[Depends(require_app_token)],
)
def register_native_push(
    patient_id: str,
    request: NativePushRegistrationRequest,
    response: Response,
) -> dict[str, bool]:
    _ensure_patient(patient_id)
    token = _native_device_token(request)
    if not native_push_is_configured():
        raise HTTPException(status_code=503, detail="Native Push is not configured")
    store = _native_push_store()
    if store.get(patient_id, token) is None and len(store.list_for_patient(patient_id)) >= 8:
        raise HTTPException(status_code=409, detail="Too many registered Android devices")
    if not store.save(patient_id, token):
        response.status_code = 200
    return {"registered": True}


@app.delete(
    "/api/patients/{patient_id}/native-push/registration",
    status_code=204,
    dependencies=[Depends(require_app_token)],
)
def remove_native_push(patient_id: str, request: NativePushTokenRequest) -> None:
    _ensure_patient(patient_id)
    _native_push_store().delete(patient_id, _native_device_token(request))


@app.post(
    "/api/patients/{patient_id}/native-push/test",
    dependencies=[Depends(require_app_token)],
)
async def test_native_push(
    patient_id: str,
    request: NativePushTestRequest,
) -> dict[str, int]:
    _ensure_patient(patient_id)
    token = _native_device_token(request)
    if not native_push_is_configured():
        raise HTTPException(status_code=503, detail="Native Push is not configured")
    store = _native_push_store()
    registration = await asyncio.to_thread(store.get, patient_id, token)
    if registration is None:
        raise HTTPException(status_code=404, detail="Android device is not registered")
    if request.delay_seconds:
        await asyncio.sleep(request.delay_seconds)

        registration = await asyncio.to_thread(store.get, patient_id, token)
        if registration is None:
            raise HTTPException(status_code=404, detail="Android device is not registered")
    preferences = await _delivery_preferences(patient_id)
    return await send_test_notification(
        patient_id, registration, store, sound_enabled=preferences["sound_enabled"],
    )


@app.post(
    "/api/patients/{patient_id}/alert-websocket-ticket",
    status_code=201,
    dependencies=[Depends(require_app_token)],
)
def create_alert_websocket_ticket(patient_id: str) -> dict[str, Any]:
    _ensure_patient(patient_id)
    return {
        "ticket": _issue_alert_websocket_ticket(patient_id),
        "expires_in_seconds": ALERT_WEBSOCKET_TICKET_TTL_SECONDS,
    }


@app.get(
    "/api/patients/{patient_id}/dashboard",
    dependencies=[Depends(require_app_token)],
)
def get_dashboard(patient_id: str, request: Request) -> dict[str, Any]:
    snapshot = _load_snapshot()
    if snapshot["patient"]["id"] != patient_id:
        raise HTTPException(status_code=404, detail="Patient not found")

    _apply_demo_scenario(snapshot)

    for alert in snapshot["alerts"]:
        pause_until = _active_pause_until(alert["id"])
        alert["is_paused"] = pause_until is not None
        alert["paused_until"] = pause_until.isoformat() if pause_until else None

    snapshot["door_events"] = [
        _serialize_door_event(event, request)
        for event in _load_raw_door_events()
    ]

    return snapshot


@app.get("/api/demo/scenarios")
def get_demo_scenarios() -> dict[str, Any]:
    return {
        "active_scenario_id": _demo_state["active_scenario_id"],
        "scenarios": [
            {"id": scenario_id, **scenario}
            for scenario_id, scenario in DEMO_SCENARIOS.items()
        ],
    }


@app.post("/api/demo/scenarios/{scenario_id}")
def activate_demo_scenario(scenario_id: str) -> dict[str, str]:
    if scenario_id not in DEMO_SCENARIOS:
        raise HTTPException(status_code=404, detail="Demo scenario not found")

    _demo_state["active_scenario_id"] = scenario_id
    _paused_alerts.clear()
    _confirmed_door_events.clear()
    return {
        "status": "activated",
        "scenario_id": scenario_id,
        "label": DEMO_SCENARIOS[scenario_id]["label"],
    }


@app.get("/api/door-events", dependencies=[Depends(require_app_token)])
def get_door_events(request: Request) -> dict[str, list[dict[str, Any]]]:
    return {
        "events": [
            _serialize_door_event(event, request)
            for event in _load_raw_door_events()
        ],
    }


@app.post(
    "/api/devices/{device_id}/door-events",
    status_code=202,
    dependencies=[Depends(require_device_token)],
)
async def upload_door_event(
    device_id: str,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    event_id: str = Form(...),
    event_time: datetime = Form(...),
    decision: Literal[
        "EXIT",
        "RETURN",
        "UNKNOWN_ACTIVE_BOTH",
        "NO_PASSAGE",
    ] = Form(...),
    representative: UploadFile = File(...),
    patient_id: str = Form("byunwoojin"),
    pre_motion: str = Form("{}"),
    post_motion: str = Form("{}"),
) -> dict[str, Any]:
    if not DEVICE_ID_PATTERN.fullmatch(device_id):
        raise HTTPException(status_code=422, detail="Invalid device id")
    if not DOOR_EVENT_ID_PATTERN.fullmatch(event_id):
        raise HTTPException(status_code=422, detail="Invalid event id")
    if not DEVICE_ID_PATTERN.fullmatch(patient_id):
        raise HTTPException(status_code=422, detail="Invalid patient id")
    _ensure_patient(patient_id)
    if event_time.tzinfo is None:
        raise HTTPException(
            status_code=422,
            detail="event_time must include a timezone",
        )

    try:
        pre_statistics = json.loads(pre_motion)
        post_statistics = json.loads(post_motion)
    except json.JSONDecodeError as error:
        raise HTTPException(
            status_code=422,
            detail="Motion statistics must be JSON objects",
        ) from error
    if not isinstance(pre_statistics, dict) or not isinstance(
        post_statistics,
        dict,
    ):
        raise HTTPException(
            status_code=422,
            detail="Motion statistics must be JSON objects",
        )

    image_bytes = await representative.read(MAX_DOOR_IMAGE_BYTES + 1)
    await representative.close()
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Representative image is empty")
    if len(image_bytes) > MAX_DOOR_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="Representative image is too large")
    if not image_bytes.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=415, detail="Representative image must be JPEG")

    direction, title, description = {
        "EXIT": (
            "exit",
            "외출 장면 감지",
            "현관문 이벤트 전 움직임을 분석해 외출 가능성을 감지했어요.",
        ),
        "RETURN": (
            "entry",
            "귀가 장면 감지",
            "현관문 이벤트 후 움직임을 분석해 귀가 가능성을 감지했어요.",
        ),
        "UNKNOWN_ACTIVE_BOTH": (
            "unknown",
            "현관 이동 확인 필요",
            "이벤트 전후 모두 움직임이 있어 보호자 확인이 필요해요.",
        ),
        "NO_PASSAGE": (
            "unknown",
            "통행 장면 없음",
            "현관문 이벤트 전후에 뚜렷한 움직임이 감지되지 않았어요.",
        ),
    }[decision]

    korea_time = event_time.astimezone(timezone(timedelta(hours=9)))
    event = {
        "id": event_id,
        "device_id": device_id,
        "patient_id": patient_id,
        "occurred_at": event_time.isoformat(),
        "time_label": korea_time.strftime("%m월 %d일 %H:%M"),
        "direction": direction,
        "title": title,
        "description": description,
        "source": "pi4_camera",
        "decision": decision,
        "motion_statistics": {
            "pre": pre_statistics,
            "post": post_statistics,
        },
    }

    try:
        stored_event, duplicate = _door_event_store().create_event(
            event,
            image_bytes,
        )
    except (DoorEventConflict, FileExistsError) as error:
        raise HTTPException(
            status_code=409,
            detail="Event id already exists with different contents",
        ) from error

    if duplicate:
        response.status_code = 200

    serialized_event = _serialize_door_event(stored_event, request)
    alert = {
        "alert_id": f"door-{event_id}",
        "patient_id": patient_id,
        "occurred_at": event_time.isoformat(),
        "risk_level": "caution" if decision != "NO_PASSAGE" else "normal",
        "alert_type": "door_event",
        "title": title,
        "message": description,
        "device_id": device_id,
        "related_event_id": event_id,
    }
    try:
        alert_created = _alert_history_store().create(alert)
    except AlertHistoryConflict as error:
        raise HTTPException(status_code=409, detail="Alert id already exists with different contents") from error
    if alert_created:
        await _alert_websockets.broadcast(
            patient_id,
            {"type": "app_alert", "data": alert},
        )
        background_tasks.add_task(_deliver_alert_notifications, patient_id, alert)
    return {
        "status": "duplicate" if duplicate else "accepted",
        "event": serialized_event,
    }


@app.get("/api/door-events/{event_id}", dependencies=[Depends(require_app_token)])
def get_door_event(event_id: str, request: Request) -> dict[str, Any]:
    return _serialize_door_event(_raw_door_event(event_id), request)


@app.get(
    "/api/door-events/{event_id}/image", name="get_door_event_image",
    dependencies=[Depends(require_app_token)],
)
def get_door_event_image(event_id: str) -> Response:
    event = _raw_door_event(event_id)
    if "image_key" in event:
        image_bytes = _door_event_store().get_image(event)
        if image_bytes is None:
            raise HTTPException(status_code=404, detail="Door event image not found")
        return Response(
            content=image_bytes,
            media_type=str(event.get("image_content_type", "image/jpeg")),
        )

    media_path = (DOOR_MEDIA_DIR / event["image_file"]).resolve()
    if DOOR_MEDIA_DIR.resolve() not in media_path.parents or not media_path.is_file():
        raise HTTPException(status_code=404, detail="Door event image not found")
    return FileResponse(media_path, media_type="image/png")


@app.post(
    "/api/door-events/{event_id}/confirm",
    dependencies=[Depends(require_app_token)],
)
def confirm_door_event(event_id: str) -> dict[str, Any]:
    _raw_door_event(event_id)
    _confirmed_door_events.add(event_id)
    return {"status": "confirmed", "event_id": event_id, "is_confirmed": True}


@app.post("/api/alerts/{alert_id}/pause")
def pause_alert(alert_id: str, request: PauseAlertRequest) -> dict[str, Any]:
    if not _alert_exists(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")

    pause_until = datetime.now(timezone.utc) + timedelta(
        minutes=request.duration_minutes,
    )
    _paused_alerts[alert_id] = pause_until

    return {
        "status": "paused",
        "alert_id": alert_id,
        "pause_until": pause_until.isoformat(),
    }


@app.post("/api/alerts/{alert_id}/resume")
def resume_alert(alert_id: str) -> dict[str, str]:
    if not _alert_exists(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")

    _paused_alerts.pop(alert_id, None)
    return {"status": "active", "alert_id": alert_id}


@app.post("/api/voice-messages", status_code=201)
async def upload_voice_message(
    request: Request,
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    duration_seconds: int = Form(..., ge=1, le=30),
) -> dict[str, Any]:
    snapshot = _load_snapshot()
    if snapshot["patient"]["id"] != patient_id:
        raise HTTPException(status_code=404, detail="Patient not found")

    audio = await file.read(MAX_VOICE_BYTES + 1)
    await file.close()
    if len(audio) > MAX_VOICE_BYTES:
        raise HTTPException(status_code=413, detail="Voice message is too large")
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise HTTPException(status_code=415, detail="Only WAV audio is supported")

    message_id = f"voice-{uuid.uuid4().hex[:12]}"
    audio_path = _voice_message_path(message_id)
    VOICE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    audio_path.write_bytes(audio)

    return {
        "id": message_id,
        "patient_id": patient_id,
        "duration_seconds": duration_seconds,
        "size_bytes": len(audio),
        "audio_url": str(
            request.url_for(
                "get_voice_message_audio",
                message_id=message_id,
            ),
        ),
        "status": "uploaded",
    }


@app.post(
    "/api/worker/voice-training/claims",
    dependencies=[Depends(require_worker_token)],
    response_model=None,
)
def claim_voice_training_job(
    request: WorkerVoiceTrainingClaimRequest,
) -> dict[str, Any] | Response:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice training Worker requires STORAGE_BACKEND=r2",
        )

    service = _r2_voice_training_service()
    try:
        claim = service.claim_next_job(
            worker_id=request.worker_id,
            lease_seconds=request.lease_seconds,
        )
    except InvalidVoiceTrainingRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if claim is None:
        return Response(status_code=204)

    input_files = []
    for clip in claim["manifest"].get("clips", []):
        object_key = str(clip["object_key"])
        input_files.append(
            {
                "file_name": clip["file_name"],
                "size_bytes": clip["size_bytes"],
                "download_url": service.storage.create_download_url(
                    object_key,
                    expires_seconds=3600,
                ),
            }
        )

    return {
        **claim,
        "input_files": input_files,
    }


@app.post(
    "/api/worker/voice-training/jobs/{patient_id}/{job_id}/status",
    dependencies=[Depends(require_worker_token)],
)
def update_voice_training_worker_status(
    patient_id: str,
    job_id: str,
    request: WorkerVoiceTrainingStatusRequest,
) -> dict[str, Any]:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice training Worker requires STORAGE_BACKEND=r2",
        )

    try:
        return _r2_voice_training_service().update_claim_status(
            patient_id=patient_id,
            job_id=job_id,
            claim_id=request.claim_id,
            lease_token=request.lease_token,
            state=request.state,
            message=request.message,
            lease_seconds=request.lease_seconds,
        )
    except InvalidVoiceTrainingRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (VoiceTrainingClaimError, VoiceTrainingJobStateError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post(
    "/api/worker/voice-training/jobs/{patient_id}/{job_id}/upload-plan",
    dependencies=[Depends(require_worker_token)],
)
def create_voice_training_upload_plan(
    patient_id: str,
    job_id: str,
    request: WorkerUploadPlanRequest,
) -> dict[str, Any]:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice training Worker requires STORAGE_BACKEND=r2",
        )

    try:
        return _r2_voice_training_service().create_upload_plan(
            patient_id=patient_id,
            job_id=job_id,
            claim_id=request.claim_id,
            lease_token=request.lease_token,
            artifacts={
                name: descriptor.model_dump()
                for name, descriptor in request.artifacts.items()
            },
            expires_seconds=request.expires_seconds,
        )
    except InvalidVoiceTrainingRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (VoiceTrainingClaimError, VoiceTrainingJobStateError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post(
    "/api/worker/voice-training/jobs/{patient_id}/{job_id}/complete",
    dependencies=[Depends(require_worker_token)],
)
def complete_voice_training_job(
    patient_id: str,
    job_id: str,
    request: WorkerCompleteRequest,
) -> dict[str, Any]:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice training Worker requires STORAGE_BACKEND=r2",
        )

    try:
        return _r2_voice_training_service().complete_job(
            patient_id=patient_id,
            job_id=job_id,
            claim_id=request.claim_id,
            lease_token=request.lease_token,
        )
    except InvalidVoiceTrainingRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (VoiceTrainingClaimError, VoiceTrainingJobStateError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post(
    "/api/worker/voice-training/jobs/{patient_id}/{job_id}/fail",
    dependencies=[Depends(require_worker_token)],
)
def fail_voice_training_job(
    patient_id: str,
    job_id: str,
    request: WorkerFailRequest,
) -> dict[str, Any]:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice training Worker requires STORAGE_BACKEND=r2",
        )

    try:
        return _r2_voice_training_service().fail_job(
            patient_id=patient_id,
            job_id=job_id,
            claim_id=request.claim_id,
            lease_token=request.lease_token,
            failed_stage=request.failed_stage,
            error=request.error,
            retryable=request.retryable,
            retry_delay_seconds=request.retry_delay_seconds,
        )
    except InvalidVoiceTrainingRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (VoiceTrainingClaimError, VoiceTrainingJobStateError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post(
    "/api/worker/voice-models/upload-plan",
    dependencies=[Depends(require_worker_token)],
)
def create_voice_model_upload_plan(
    request: VoiceModelUploadPlanRequest,
) -> dict[str, Any]:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice model publishing requires STORAGE_BACKEND=r2",
        )
    try:
        return _r2_voice_model_service().create_upload_plan(
            patient_id=request.patient_id,
            version=request.version,
            source_job_id=request.source_job_id,
            artifacts={
                name: descriptor.model_dump()
                for name, descriptor in request.artifacts.items()
            },
            expires_seconds=request.expires_seconds,
        )
    except InvalidVoiceModelRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except VoiceModelStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post(
    "/api/worker/voice-models/{model_id}/publish",
    dependencies=[Depends(require_worker_token)],
)
def publish_voice_model(
    model_id: str,
    request: VoiceModelPublishRequest,
) -> dict[str, Any]:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice model publishing requires STORAGE_BACKEND=r2",
        )
    try:
        return _r2_voice_model_service().publish(
            patient_id=request.patient_id,
            model_id=model_id,
        )
    except InvalidVoiceModelRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except VoiceModelStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/api/devices/{device_id}/voice-models/latest",
    dependencies=[Depends(require_device_token)],
)
def get_latest_voice_model(
    device_id: str,
    patient_id: str,
) -> dict[str, Any]:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice model deployment requires STORAGE_BACKEND=r2",
        )
    try:
        release = _r2_voice_model_service().create_device_release(
            patient_id=patient_id,
            device_id=device_id,
        )
    except InvalidVoiceModelRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except VoiceModelStateError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if release is None:
        raise HTTPException(status_code=404, detail="No voice model is published")
    return release


@app.post(
    "/api/devices/{device_id}/voice-models/{model_id}/ack",
    dependencies=[Depends(require_device_token)],
)
def acknowledge_voice_model_installation(
    device_id: str,
    model_id: str,
    request: VoiceModelInstallAckRequest,
) -> dict[str, Any]:
    if STORAGE_BACKEND != "r2":
        raise HTTPException(
            status_code=503,
            detail="Voice model deployment requires STORAGE_BACKEND=r2",
        )
    try:
        result = _r2_voice_model_service().record_installation(
            patient_id=request.patient_id,
            device_id=device_id,
            model_id=model_id,
            status=request.status,
            detail=request.detail,
            previous_model_id=request.previous_model_id,
        )
        source_job_id = result.get("source_job_id")
        if request.status == "installed" and isinstance(source_job_id, str):
            retention = _r2_voice_training_service().schedule_raw_audio_deletion(
                patient_id=request.patient_id,
                job_id=source_job_id,
            )
            result["raw_audio_retention"] = retention
        if (
            request.status == "installed"
            and request.previous_model_id is not None
            and request.previous_model_id != model_id
        ):
            result["previous_model_retention"] = (
                _r2_voice_model_service().schedule_previous_model_deletion(
                    patient_id=request.patient_id,
                    model_id=request.previous_model_id,
                )
            )
        return result
    except InvalidVoiceModelRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (VoiceModelStateError, VoiceTrainingJobStateError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/api/patients/{patient_id}/voice-training",
    dependencies=[Depends(require_app_token)],
)
def get_voice_training_progress(patient_id: str) -> dict[str, Any]:
    snapshot = _load_snapshot()
    if snapshot["patient"]["id"] != patient_id:
        raise HTTPException(status_code=404, detail="Patient not found")

    if STORAGE_BACKEND == "r2":
        try:
            return _r2_voice_training_service().get_progress(patient_id)
        except VoiceTrainingJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    manifest = _load_voice_training_manifest(patient_id)
    return _serialize_voice_training_progress(manifest)


@app.post(
    "/api/patients/{patient_id}/voice-training/consents",
    status_code=201,
    dependencies=[Depends(require_app_token)],
)
def accept_voice_consent(patient_id: str, body: VoiceConsentRequest, response: Response):
    _ensure_patient(patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    try:
        return _voice_consent_store().accept(patient_id, body.request_id)
    except Exception:

        raise HTTPException(503, "Voice consent could not be saved; retry shortly") from None


@app.get(
    "/api/patients/{patient_id}/voice-training/consents/{consent_id}",
    dependencies=[Depends(require_app_token)],
)
def get_voice_consent(patient_id: str, consent_id: str, response: Response):
    _ensure_patient(patient_id)
    if not re.fullmatch(CONSENT_ID_PATTERN, consent_id):
        raise HTTPException(422, "Invalid consent ID")
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    try:
        receipt = _voice_consent_store().load(patient_id, consent_id)
    except Exception:
        raise HTTPException(503, "Voice consent storage unavailable") from None
    if receipt is None:
        raise HTTPException(404, "Voice consent receipt not found")
    return receipt


@app.post(
    "/api/patients/{patient_id}/voice-training/sessions",
    status_code=201,
    dependencies=[Depends(require_app_token)],
)
def start_voice_training_session(
    patient_id: str, body: NewVoiceTrainingSessionRequest,
) -> dict[str, Any]:
    _ensure_patient(patient_id)
    if STORAGE_BACKEND != "r2":
        raise HTTPException(503, "New voice training sessions require persistent R2 storage")
    try:
        return _r2_voice_training_service().start_new_session(patient_id, body.previous_job_id)
    except InvalidVoiceTrainingRequest as error:
        raise HTTPException(422, str(error)) from error
    except VoiceTrainingJobStateError as error:
        raise HTTPException(409, str(error)) from error


@app.post(
    "/api/voice-training/clips",
    status_code=201,
    dependencies=[Depends(require_app_token)],
)
async def upload_voice_training_clip(
    file: UploadFile = File(...),
    patient_id: str = Form(...),
    duration_seconds: int = Form(..., ge=1, le=45),
    prompt_text: str = Form(..., min_length=1, max_length=1000),
    job_id: str | None = Form(default=None, pattern=r"^voice-job-[0-9a-f]{12}$"),
) -> dict[str, Any]:
    snapshot = _load_snapshot()
    if snapshot["patient"]["id"] != patient_id:
        raise HTTPException(status_code=404, detail="Patient not found")

    submitted_file_name = file.filename or ""
    if not TRAINING_FILE_NAME_PATTERN.fullmatch(submitted_file_name):
        await file.close()
        raise HTTPException(
            status_code=422,
            detail="Training file name must be a safe WAV file name",
        )

    audio = await file.read(MAX_TRAINING_CLIP_BYTES + 1)
    await file.close()
    if len(audio) > MAX_TRAINING_CLIP_BYTES:
        raise HTTPException(status_code=413, detail="Training clip is too large")
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise HTTPException(status_code=415, detail="Only WAV audio is supported")

    if STORAGE_BACKEND == "r2":
        try:
            return _r2_voice_training_service().upload_clip(
                patient_id=patient_id,
                file_name=submitted_file_name,
                prompt_text=prompt_text,
                duration_seconds=duration_seconds,
                audio=audio,
                job_id=job_id,
            )
        except InvalidVoiceTrainingRequest as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except DuplicateVoiceTrainingClip as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except VoiceTrainingJobStateError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    patient_dir = _voice_training_patient_dir(patient_id)
    patient_dir.mkdir(parents=True, exist_ok=True)
    clip_id = f"clip-{uuid.uuid4().hex[:12]}"
    audio_path = patient_dir / submitted_file_name
    if audio_path.exists():
        raise HTTPException(
            status_code=409,
            detail="A training clip with this file name already exists",
        )
    audio_path.write_bytes(audio)

    manifest = _load_voice_training_manifest(patient_id)
    manifest["clips"].append(
        {
            "id": clip_id,
            "file_name": audio_path.name,
            "duration_seconds": duration_seconds,
            "prompt_text": prompt_text,
            "size_bytes": len(audio),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    _save_voice_training_manifest(manifest)
    return {
        **_serialize_voice_training_progress(manifest),
        "last_clip_id": clip_id,
        "status": "uploaded",
    }


@app.get(
    "/api/voice-messages/{message_id}/audio",
    name="get_voice_message_audio",
)
def get_voice_message_audio(message_id: str) -> FileResponse:
    audio_path = _voice_message_path(message_id)
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Voice message not found")
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=f"{message_id}.wav",
    )
