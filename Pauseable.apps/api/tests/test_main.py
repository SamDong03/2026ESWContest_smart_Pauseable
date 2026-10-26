import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main as main_module
from app.alert_history_store import AlertHistoryStore
from app.door_event_store import DoorEventStore
from app.push_subscription_store import PushSubscriptionStore
from app.notification_preferences import NotificationPreferenceStore
from app.main import (
    _alert_websocket_tickets,
    _confirmed_door_events,
    _demo_state,
    _guardian_profile,
    _paused_alerts,
    app,
)


class GuardianApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.alert_directory = TemporaryDirectory()
        self.addCleanup(self.alert_directory.cleanup)
        self.alert_store = AlertHistoryStore(local_dir=Path(self.alert_directory.name))
        alert_store_patch = patch(
            "app.main._alert_history_store", return_value=self.alert_store,
        )
        alert_store_patch.start()
        self.addCleanup(alert_store_patch.stop)
        _alert_websocket_tickets.clear()
        _paused_alerts.clear()
        _confirmed_door_events.clear()
        _demo_state["active_scenario_id"] = "repetitive_behavior"
        _guardian_profile.update(
            {
                "name": "김보호",
                "relationship": "김영희 님의 보호자",
                "phone_number": "010-1234-5678",
            },
        )
        self.preferences = NotificationPreferenceStore(local_dir=Path(self.alert_directory.name) / "preferences")
        self.preferences.save("byunwoojin", {"safety_notifications": True, "sound_enabled": True})
        preference_patch = patch("app.main._notification_preferences_store", return_value=self.preferences)
        preference_patch.start()
        self.addCleanup(preference_patch.stop)
        self.client = TestClient(app)

    def test_dashboard_returns_guardian_snapshot(self) -> None:
        response = self.client.get("/api/patients/byunwoojin/dashboard")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["patient"]["name"], "김영희")
        self.assertEqual(len(payload["alerts"]), 2)
        self.assertFalse(payload["alerts"][0]["is_paused"])
        self.assertEqual(len(payload["door_events"]), 1)
        self.assertEqual(payload["door_events"][0]["direction"], "exit")
        self.assertEqual(len(payload["activity"]["events"]), 6)
        self.assertEqual(payload["activity"]["events"][2]["state"], "closed")
        self.assertEqual(payload["activity"]["events"][2]["time_label"], "오전 8:10:19")
        self.assertEqual(payload["activity"]["events"][-1]["title"], "현관문 닫힘")

    def test_pause_and_resume_alert(self) -> None:
        pause_response = self.client.post(
            "/api/alerts/alert-door-001/pause",
            json={"duration_minutes": 60},
        )
        self.assertEqual(pause_response.status_code, 200)
        self.assertEqual(pause_response.json()["status"], "paused")

        paused_dashboard = self.client.get(
            "/api/patients/byunwoojin/dashboard",
        ).json()
        self.assertTrue(paused_dashboard["alerts"][0]["is_paused"])

        resume_response = self.client.post(
            "/api/alerts/alert-door-001/resume",
        )
        self.assertEqual(resume_response.status_code, 200)
        self.assertEqual(resume_response.json()["status"], "active")

    def test_unknown_alert_returns_not_found(self) -> None:
        response = self.client.post(
            "/api/alerts/unknown/pause",
            json={"duration_minutes": 30},
        )

        self.assertEqual(response.status_code, 404)

    def test_door_event_list_detail_and_image(self) -> None:
        list_response = self.client.get("/api/door-events")
        self.assertEqual(list_response.status_code, 200)
        event = list_response.json()["events"][0]
        self.assertNotIn("clothing_summary", event)
        self.assertTrue(event["image_url"].endswith("/api/door-events/door-event-001/image"))

        detail_response = self.client.get("/api/door-events/door-event-001")
        self.assertEqual(detail_response.status_code, 200)

        image_response = self.client.get("/api/door-events/door-event-001/image")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.headers["content-type"], "image/png")
        self.assertGreater(len(image_response.content), 100_000)

    def test_confirm_door_event(self) -> None:
        response = self.client.post("/api/door-events/door-event-001/confirm")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["is_confirmed"])

        event = self.client.get("/api/door-events/door-event-001").json()
        self.assertTrue(event["is_confirmed"])

    def test_door_photo_detail_and_confirmation_do_not_scan_history(self) -> None:
        jpeg = b"\xff\xd8camera\xff\xd9"
        with TemporaryDirectory() as directory:
            store = DoorEventStore(local_dir=Path(directory))
            store.create_event({
                "id": "point-event", "device_id": "test-camera",
                "patient_id": "byunwoojin", "occurred_at": "2026-10-10T00:00:00Z",
                "direction": "exit", "decision": "EXIT",
            }, jpeg)
            with (
                patch("app.main._door_event_store", return_value=store),
                patch.object(store, "list_events", side_effect=AssertionError("Full history scan")),
            ):
                detail = self.client.get("/api/door-events/point-event")
                self.assertEqual(detail.status_code, 200)
                image = self.client.get("/api/door-events/point-event/image")
                self.assertEqual(image.status_code, 200)
                self.assertEqual(image.content, jpeg)
                confirmed = self.client.post("/api/door-events/point-event/confirm")
                self.assertEqual(confirmed.status_code, 200)
                self.assertTrue(confirmed.json()["is_confirmed"])

    def test_invalid_door_event_id_is_rejected_before_storage_access(self) -> None:
        with patch("app.main._door_event_store", side_effect=AssertionError("Storage access")):
            self.assertEqual(self.client.get("/api/door-events/" + "x" * 97).status_code, 404)

    @patch("app.main._alert_websockets.broadcast", new_callable=AsyncMock)
    def test_pi_camera_can_upload_door_event_and_image(
        self,
        broadcast: AsyncMock,
    ) -> None:
        jpeg = b"\xff\xd8" + (b"camera-frame" * 100) + b"\xff\xd9"
        with TemporaryDirectory() as directory:
            store = DoorEventStore(local_dir=Path(directory))
            with (
                patch("app.main._door_event_store", return_value=store),
                patch.dict(
                    os.environ,
                    {
                        "PAUSEABLE_ENV": "production",
                        "PAUSEABLE_DEVICE_TOKEN": "test-device-token",
                        "PAUSEABLE_APP_TOKEN": "test-app-token",
                    },
                ),
            ):
                response = self.client.post(
                    "/api/devices/pi4-front-door-01/door-events",
                    headers={"Authorization": "Bearer test-device-token"},
                    data={
                        "event_id": "event_20260927_220000",
                        "event_time": "2026-09-27T22:00:00+09:00",
                        "decision": "EXIT",
                        "patient_id": "byunwoojin",
                        "pre_motion": json.dumps(
                            {"samples": 100, "movement": True},
                        ),
                        "post_motion": json.dumps(
                            {"samples": 50, "movement": False},
                        ),
                    },
                    files={
                        "representative": (
                            "representative.jpg",
                            jpeg,
                            "image/jpeg",
                        ),
                    },
                )

                self.assertEqual(response.status_code, 202)
                event = response.json()["event"]
                self.assertEqual(event["decision"], "EXIT")
                self.assertEqual(event["direction"], "exit")
                self.assertNotIn("image_key", event)
                broadcast.assert_awaited_once()
                broadcast_patient_id, broadcast_payload = (
                    broadcast.await_args.args
                )
                self.assertEqual(broadcast_patient_id, "byunwoojin")
                self.assertEqual(broadcast_payload["type"], "app_alert")
                self.assertEqual(
                    broadcast_payload["data"]["related_event_id"],
                    "event_20260927_220000",
                )

                image_response = self.client.get(event["image_url"], headers={
                    "Authorization": "Bearer test-app-token",
                })
                self.assertEqual(image_response.status_code, 200)
                self.assertEqual(image_response.headers["content-type"], "image/jpeg")
                self.assertEqual(image_response.content, jpeg)

                duplicate = self.client.post(
                    "/api/devices/pi4-front-door-01/door-events",
                    headers={"Authorization": "Bearer test-device-token"},
                    data={
                        "event_id": "event_20260927_220000",
                        "event_time": "2026-09-27T22:00:00+09:00",
                        "decision": "EXIT",
                        "patient_id": "byunwoojin",
                        "pre_motion": json.dumps(
                            {"samples": 100, "movement": True},
                        ),
                        "post_motion": json.dumps(
                            {"samples": 50, "movement": False},
                        ),
                    },
                    files={
                        "representative": (
                            "representative.jpg",
                            jpeg,
                            "image/jpeg",
                        ),
                    },
                )
                self.assertEqual(duplicate.status_code, 200)
                self.assertEqual(duplicate.json()["status"], "duplicate")
                broadcast.assert_awaited_once()

    def test_activate_demo_scenario_updates_dashboard(self) -> None:
        scenarios = self.client.get("/api/demo/scenarios")
        self.assertEqual(scenarios.status_code, 200)
        self.assertEqual(len(scenarios.json()["scenarios"]), 5)

        response = self.client.post("/api/demo/scenarios/inactivity")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scenario_id"], "inactivity")

        dashboard = self.client.get(
            "/api/patients/byunwoojin/dashboard",
        ).json()
        self.assertEqual(dashboard["demo_scenario"], "inactivity")
        self.assertEqual(dashboard["patient"]["activity"], "움직임 없음")
        self.assertEqual(dashboard["alerts"][0]["type"], "inactivity")

        unknown = self.client.post("/api/demo/scenarios/unknown")
        self.assertEqual(unknown.status_code, 404)

    def test_guardian_profile_and_preferences_are_editable(self) -> None:
        profile = self.client.get("/api/guardians/me")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["name"], "김보호")

        updated_profile = self.client.put(
            "/api/guardians/me",
            json={
                "name": "박보호",
                "relationship": "김영희 님의 딸",
                "phone_number": "010-9999-0000",
            },
        )
        self.assertEqual(updated_profile.status_code, 200)
        self.assertEqual(updated_profile.json()["name"], "박보호")

        updated_preferences = self.client.put(
            "/api/guardians/me/preferences",
            json={"safety_notifications": False, "sound_enabled": True},
        )
        self.assertEqual(updated_preferences.status_code, 200)
        self.assertFalse(updated_preferences.json()["safety_notifications"])
        self.assertTrue(updated_preferences.json()["sound_enabled"])

    def test_device_check_and_contact_actions_return_demo_results(self) -> None:
        device = self.client.get(
            "/api/patients/byunwoojin/device-connection",
        )
        self.assertEqual(device.status_code, 200)
        self.assertTrue(device.json()["is_online"])
        self.assertEqual(len(device.json()["services"]), 3)

        checked = self.client.post(
            "/api/patients/byunwoojin/device-connection/check",
        )
        self.assertEqual(checked.status_code, 200)

        care_call = self.client.post("/api/patients/byunwoojin/care-call")
        emergency = self.client.post(
            "/api/patients/byunwoojin/emergency-contact",
        )
        self.assertEqual(care_call.status_code, 200)
        self.assertTrue(care_call.json()["reference_id"].startswith("demo-care-"))
        self.assertEqual(emergency.status_code, 200)
        self.assertTrue(
            emergency.json()["reference_id"].startswith("demo-emergency-"),
        )

    def test_upload_and_download_guardian_voice_message(self) -> None:
        wave = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + bytes(64)
        with TemporaryDirectory() as directory, patch(
            "app.main.VOICE_UPLOAD_DIR",
            Path(directory),
        ):
            response = self.client.post(
                "/api/voice-messages",
                data={"patient_id": "byunwoojin", "duration_seconds": "2"},
                files={"file": ("guardian.wav", wave, "audio/wav")},
            )

            self.assertEqual(response.status_code, 201)
            payload = response.json()
            self.assertEqual(payload["status"], "uploaded")
            self.assertEqual(payload["duration_seconds"], 2)
            saved_path = Path(directory) / f"{payload['id']}.wav"
            self.assertEqual(saved_path.read_bytes(), wave)

            audio_response = self.client.get(
                f"/api/voice-messages/{payload['id']}/audio",
            )
            self.assertEqual(audio_response.status_code, 200)
            self.assertEqual(audio_response.headers["content-type"], "audio/wav")
            self.assertEqual(audio_response.content, wave)

    def test_rejects_non_wave_voice_message(self) -> None:
        with TemporaryDirectory() as directory, patch(
            "app.main.VOICE_UPLOAD_DIR",
            Path(directory),
        ):
            response = self.client.post(
                "/api/voice-messages",
                data={"patient_id": "byunwoojin", "duration_seconds": "2"},
                files={"file": ("voice.txt", b"not audio", "text/plain")},
            )

        self.assertEqual(response.status_code, 415)

    def test_voice_training_clips_accumulate_toward_800_seconds(self) -> None:
        wave = b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + bytes(64)
        with TemporaryDirectory() as directory, patch(
            "app.main.VOICE_TRAINING_DIR",
            Path(directory),
        ):
            initial = self.client.get(
                "/api/patients/byunwoojin/voice-training",
            )
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.json()["target_seconds"], 800)
            self.assertEqual(initial.json()["recorded_seconds"], 0)

            first = self.client.post(
                "/api/voice-training/clips",
                data={
                    "patient_id": "byunwoojin",
                    "duration_seconds": "20",
                    "prompt_text": "오늘도 편안하게 쉬어 주세요.",
                },
                files={"file": ("S001.wav", wave, "audio/wav")},
            )
            second = self.client.post(
                "/api/voice-training/clips",
                data={
                    "patient_id": "byunwoojin",
                    "duration_seconds": "30",
                    "prompt_text": "제가 곁에서 지켜보고 있어요.",
                },
                files={"file": ("S002.wav", wave, "audio/wav")},
            )

            self.assertEqual(first.status_code, 201)
            self.assertEqual(second.status_code, 201)
            self.assertEqual(second.json()["recorded_seconds"], 50)
            self.assertEqual(second.json()["remaining_seconds"], 750)
            self.assertEqual(second.json()["clip_count"], 2)
            self.assertFalse(second.json()["is_ready"])

            manifest_path = Path(directory) / "byunwoojin" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["clips"]), 2)
            self.assertEqual(manifest["clips"][0]["file_name"], "S001.wav")
            self.assertEqual(
                manifest["clips"][0]["prompt_text"],
                "오늘도 편안하게 쉬어 주세요.",
            )
            self.assertEqual(
                (Path(directory) / "byunwoojin" / "S001.wav").read_bytes(),
                wave,
            )
    @patch("app.main._request_tts", new_callable=AsyncMock)
    def test_ha_event_broadcasts_flutter_alert_and_requests_tts(
        self,
        request_tts: AsyncMock,
    ) -> None:
        request_tts.return_value = {
            "request_id": "event-001",
            "status": "completed",
            "audio_url": "http://127.0.0.1:18001/audio/test.wav",
            "selected_message": "세탁기 전원이 켜졌습니다.",
        }

        with patch.dict(
            os.environ,
            {
                "PAUSEABLE_APP_TOKEN": "test-app-token",
                "PAUSEABLE_DEVICE_TOKEN": "test-device-token",
            },
        ):
            ticket_response = self.client.post(
                "/api/patients/byunwoojin/alert-websocket-ticket",
                headers={"Authorization": "Bearer test-app-token"},
            )
            self.assertEqual(ticket_response.status_code, 201)
            ticket = ticket_response.json()["ticket"]

            websocket_url = (
                "/ws/alerts?patient_id=byunwoojin"
                f"&ticket={ticket}"
            )
            with self.client.websocket_connect(websocket_url) as websocket:
                self.assertEqual(
                    websocket.receive_json(),
                    {
                        "type": "ready",
                        "patient_id": "byunwoojin",
                        "contract_version": "1.0",
                    },
                )
                response = self.client.post(
                    "/api/events/ha",
                    headers={"Authorization": "Bearer test-device-token"},
                    json={
                        "event_id": "event-001",
                        "occurred_at": "2026-08-28T08:43:11.255804+00:00",
                        "patient_id": "byunwoojin",
                        "source": "home-assistant",
                        "entity_id": "input_boolean.pauseable_washing_machine",
                        "previous_state": "off",
                        "state": "on",
                        "attributes": {
                            "friendly_name": "Pauseable Washing Machine",
                        },
                    },
                )
                pushed = websocket.receive_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "accepted")
        self.assertEqual(response.json()["voice"]["status"], "completed")
        self.assertEqual(pushed["type"], "app_alert")
        self.assertEqual(pushed["data"]["risk_level"], "caution")
        self.assertIn("세탁기", pushed["data"]["title"])
        request_tts.assert_awaited_once()

    def test_ha_alert_uses_door_name_and_open_close_state(self) -> None:
        opened = main_module._app_alert_for_event(
            main_module.HaEntityEventRequest(
                event_id="door-open-001",
                occurred_at="2026-09-21T10:20:30+09:00",
                patient_id="byunwoojin",
                entity_id="binary_sensor.naengjanggo_door",
                previous_state="off",
                state="on",
                attributes={"device_class": "door"},
            ),
        )
        closed = main_module._app_alert_for_event(
            main_module.HaEntityEventRequest(
                event_id="door-close-001",
                occurred_at="2026-09-21T10:20:35+09:00",
                patient_id="byunwoojin",
                entity_id="binary_sensor.naengjanggo_door",
                previous_state="on",
                state="off",
                attributes={"device_class": "door"},
            ),
        )

        self.assertEqual(opened["title"], "냉장고 문 · 열렸어요")
        self.assertEqual(opened["risk_level"], "caution")
        self.assertEqual(closed["title"], "냉장고 문 · 닫혔어요")
        self.assertEqual(closed["risk_level"], "normal")

    def test_repetitive_decision_reaches_websocket_and_history_once(self) -> None:
        event = {
            "contract_version": "1.0",
            "event_id": "evt-repeated-fridge-001",
            "occurred_at": "2026-10-04T10:11:12Z",
            "patient_id": "byunwoojin",
            "device_id": "pi5-home-01",
            "source": "central-atlas-app",
            "decision": "repetitive_behavior",
            "risk_level": "caution",
            "risk_score": 58,
            "pattern_code": "fridge_repeated_check",
            "message": "냉장고 문을 반복해서 확인하는 행동이 감지되었습니다.",
            "actions": ["notify_guardian"],
        }
        app_headers = {"Authorization": "Bearer test-app-token"}
        device_headers = {
            "Authorization": "Bearer test-device-token",
            "Idempotency-Key": event["event_id"],
        }
        with patch.dict(
            os.environ,
            {
                "PAUSEABLE_ENV": "production",
                "PAUSEABLE_APP_TOKEN": "test-app-token",
                "PAUSEABLE_DEVICE_TOKEN": "test-device-token",
            },
        ):
            ticket = self.client.post(
                "/api/patients/byunwoojin/alert-websocket-ticket",
                headers=app_headers,
            ).json()["ticket"]
            with self.client.websocket_connect(
                f"/ws/alerts?patient_id=byunwoojin&ticket={ticket}",
            ) as websocket:
                self.assertEqual(websocket.receive_json()["type"], "ready")
                response = self.client.post(
                    "/api/events/decisions", headers=device_headers, json=event,
                )
                pushed = websocket.receive_json()

            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.json()["status"], "accepted")
            self.assertEqual(pushed["type"], "app_alert")
            self.assertEqual(pushed["data"]["alert_id"], event["event_id"])
            self.assertEqual(pushed["data"]["alert_type"], "repetitive_behavior")
            self.assertEqual(pushed["data"]["message"], event["message"])
            self.assertTrue(pushed["data"]["requires_guardian_response"])

            with patch(
                "app.main._alert_websockets.broadcast", new_callable=AsyncMock,
            ) as broadcast:
                duplicate = self.client.post(
                    "/api/events/decisions", headers=device_headers, json=event,
                )
                broadcast.assert_not_awaited()
            self.assertEqual(duplicate.status_code, 200)
            self.assertTrue(duplicate.json()["duplicate"])

            history = self.client.get(
                "/api/patients/byunwoojin/alerts", headers=app_headers,
            ).json()["alerts"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["alert_id"], event["event_id"])
            self.assertFalse(history[0]["is_read"])
            marked = self.client.post(
                f"/api/patients/byunwoojin/alerts/{event['event_id']}/read",
                headers=app_headers,
            )
            self.assertEqual(marked.status_code, 200)

    @patch("app.main._alert_websockets.broadcast", new_callable=AsyncMock)
    def test_decision_endpoint_requires_device_auth_and_valid_event(
        self, broadcast: AsyncMock,
    ) -> None:
        event = {
            "contract_version": "1.0",
            "event_id": "evt-repeated-002",
            "occurred_at": "2026-10-04T10:11:12Z",
            "patient_id": "byunwoojin",
            "device_id": "pi5-home-01",
            "source": "central-atlas-app",
            "decision": "repetitive_behavior",
            "risk_level": "danger",
            "risk_score": 92,
            "actions": ["notify_guardian"],
        }
        endpoint = "/api/events/decisions"
        headers = {"Authorization": "Bearer test-device-token"}
        with patch.dict(
            os.environ,
            {
                "PAUSEABLE_ENV": "production",
                "PAUSEABLE_APP_TOKEN": "test-app-token",
                "PAUSEABLE_DEVICE_TOKEN": "test-device-token",
            },
        ):
            self.assertEqual(self.client.post(endpoint, json=event).status_code, 401)
            self.assertEqual(
                self.client.post(
                    endpoint,
                    headers={"Authorization": "Bearer test-app-token"},
                    json=event,
                ).status_code,
                403,
            )
            invalid = {
                **event,
                "occurred_at": "2026-10-04T10:11:12+09:00",
            }
            self.assertEqual(
                self.client.post(endpoint, headers=headers, json=invalid).status_code,
                422,
            )
            wrong_key = {**headers, "Idempotency-Key": "other-event"}
            self.assertEqual(
                self.client.post(endpoint, headers=wrong_key, json=event).status_code,
                422,
            )
            no_notify = {**event, "actions": []}
            self.assertEqual(
                self.client.post(endpoint, headers=headers, json=no_notify).status_code,
                202,
            )
            self.assertEqual(self.alert_store.list_recent("byunwoojin"), [])
            broadcast.assert_not_awaited()

            first = self.client.post(endpoint, headers=headers, json=event)
            self.assertEqual(first.status_code, 202)
            conflict = self.client.post(
                endpoint, headers=headers, json={**event, "risk_score": 94},
            )
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(len(self.alert_store.list_recent("byunwoojin")), 1)

    def test_wandering_decision_reaches_websocket_and_history(self) -> None:
        event = {
            "contract_version": "1.0",
            "event_id": "evt-wandering-live-001",
            "occurred_at": "2026-10-04T10:11:12Z",
            "patient_id": "byunwoojin",
            "device_id": "pi5-home-01",
            "source": "central-atlas-app",
            "decision": "wandering_suspected",
            "risk_level": "caution",
            "risk_score": 63,
            "actions": ["notify_guardian"],
        }
        app_headers = {"Authorization": "Bearer test-app-token"}
        device_headers = {"Authorization": "Bearer test-device-token"}
        with patch.dict(os.environ, {
            "PAUSEABLE_ENV": "production",
            "PAUSEABLE_APP_TOKEN": "test-app-token",
            "PAUSEABLE_DEVICE_TOKEN": "test-device-token",
        }):
            ticket = self.client.post(
                "/api/patients/byunwoojin/alert-websocket-ticket",
                headers=app_headers,
            ).json()["ticket"]
            with self.client.websocket_connect(
                f"/ws/alerts?patient_id=byunwoojin&ticket={ticket}",
            ) as websocket:
                self.assertEqual(websocket.receive_json()["type"], "ready")
                response = self.client.post(
                    "/api/events/decisions", headers=device_headers, json=event,
                )
                pushed = websocket.receive_json()

            self.assertEqual(response.status_code, 202)
            self.assertEqual(pushed["type"], "app_alert")
            self.assertEqual(pushed["data"]["alert_type"], "wandering")
            self.assertEqual(pushed["data"]["alert_id"], event["event_id"])
            history = self.client.get(
                "/api/patients/byunwoojin/alerts", headers=app_headers,
            ).json()["alerts"]
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["alert_type"], "wandering")

    @patch("app.main.send_behavior_alert", new_callable=AsyncMock)
    def test_web_push_subscription_and_behavior_decisions(
        self, send_push: AsyncMock,
    ) -> None:
        with TemporaryDirectory() as directory:
            store = PushSubscriptionStore(local_dir=Path(directory))
            app_headers = {"Authorization": "Bearer test-app-token"}
            device_headers = {"Authorization": "Bearer test-device-token"}
            path = "/api/patients/byunwoojin/push/subscriptions"
            subscription = {
                "endpoint": "https://fcm.googleapis.com/fcm/send/example-token",
                "expirationTime": None,
                "keys": {"p256dh": "A" * 87, "auth": "B" * 22},
            }
            event = {
                "contract_version": "1.0",
                "event_id": "evt-push-001",
                "occurred_at": "2026-10-04T10:11:12Z",
                "patient_id": "byunwoojin",
                "device_id": "pi5-home-01",
                "source": "central-atlas-app",
                "decision": "repetitive_behavior",
                "risk_level": "caution",
                "risk_score": 58,
                "actions": ["notify_guardian"],
            }
            with (
                patch("app.main._push_subscription_store", return_value=store),
                patch.dict(os.environ, {
                    "PAUSEABLE_ENV": "production",
                    "PAUSEABLE_APP_TOKEN": "test-app-token",
                    "PAUSEABLE_DEVICE_TOKEN": "test-device-token",
                    "PAUSEABLE_WEB_PUSH_ENABLED": "1",
                    "PAUSEABLE_VAPID_PUBLIC_KEY": "test-public-key",
                    "PAUSEABLE_VAPID_PRIVATE_KEY": "test-private-key",
                    "PAUSEABLE_VAPID_SUBJECT": "mailto:test@example.com",
                }),
            ):
                self.assertEqual(self.client.post(path, json=subscription).status_code, 401)
                self.assertEqual(
                    self.client.post(
                        path,
                        headers={"Authorization": "Bearer test-device-token"},
                        json=subscription,
                    ).status_code,
                    403,
                )
                invalid = {**subscription, "endpoint": "https://127.0.0.1/private"}
                self.assertEqual(
                    self.client.post(path, headers=app_headers, json=invalid).status_code,
                    422,
                )
                self.assertEqual(
                    self.client.get(
                        "/api/patients/byunwoojin/push/config", headers=app_headers,
                    ).json()["public_key"],
                    "test-public-key",
                )
                self.assertEqual(
                    self.client.post(path, headers=app_headers, json=subscription).status_code,
                    201,
                )
                self.assertEqual(len(store.list_for_patient("byunwoojin")), 1)
                self.assertNotIn(
                    "expirationTime", store.list_for_patient("byunwoojin")[0],
                )
                self.assertEqual(store.list_for_patient("other"), [])

                first = self.client.post(
                    "/api/events/decisions", headers=device_headers, json=event,
                )
                self.assertEqual(first.status_code, 202)
                send_push.assert_awaited_once()
                retry = self.client.post(
                    "/api/events/decisions", headers=device_headers, json=event,
                )
                self.assertEqual(retry.status_code, 200)
                send_push.assert_awaited_once()
                wandering = {
                    **event,
                    "event_id": "evt-push-wandering-001",
                    "decision": "wandering_suspected",
                }
                self.assertEqual(
                    self.client.post(
                        "/api/events/decisions", headers=device_headers,
                        json=wandering,
                    ).status_code,
                    202,
                )
                self.assertEqual(send_push.await_count, 2)
                self.assertEqual(send_push.await_args.args[1]["alert_type"], "wandering")
                self.assertEqual(
                    self.client.request(
                        "DELETE",
                        path, headers=app_headers,
                        json={"endpoint": subscription["endpoint"]},
                    ).status_code,
                    204,
                )
                self.assertEqual(store.list_for_patient("byunwoojin"), [])

    @patch("app.main._request_tts", new_callable=AsyncMock)
    def test_missed_alert_is_restored_and_read_state_survives_restart(
        self, request_tts: AsyncMock,
    ) -> None:
        request_tts.return_value = {"status": "completed"}
        path = "/api/patients/byunwoojin/alerts"
        with patch.dict(os.environ, {
            "PAUSEABLE_ENV": "production",
            "PAUSEABLE_APP_TOKEN": "test-app-token",
            "PAUSEABLE_DEVICE_TOKEN": "test-device-token",
        }):
            self.assertEqual(self.client.get(path).status_code, 401)
            posted = self.client.post(
                "/api/events/ha",
                headers={"Authorization": "Bearer test-device-token"},
                json={
                    "event_id": "missed-001",
                    "occurred_at": "2026-10-04T10:11:12Z",
                    "patient_id": "byunwoojin",
                    "entity_id": "binary_sensor.naengjanggo_door",
                    "state": "on",
                    "attributes": {"device_class": "door"},
                },
            )
            self.assertEqual(posted.status_code, 200)
            headers = {"Authorization": "Bearer test-app-token"}
            first = self.client.get(path, headers=headers)
            self.assertEqual(first.status_code, 200)
            alert = first.json()["alerts"][0]
            self.assertEqual(alert["alert_id"], "ha-missed-001")
            self.assertFalse(alert["is_read"])
            self.assertEqual(alert["occurred_at"], "2026-10-04T10:11:12+00:00")

            duplicate = self.client.post(
                "/api/events/ha",
                headers={"Authorization": "Bearer test-device-token"},
                json={
                    "event_id": "missed-001",
                    "occurred_at": "2026-10-04T10:11:12Z",
                    "patient_id": "byunwoojin",
                    "entity_id": "binary_sensor.naengjanggo_door",
                    "state": "on",
                    "attributes": {"device_class": "door"},
                },
            )
            self.assertEqual(duplicate.json()["status"], "duplicate")
            self.assertEqual(len(self.client.get(path, headers=headers).json()["alerts"]), 1)
            read = self.client.post(f"{path}/ha-missed-001/read", headers=headers)
            self.assertEqual(read.status_code, 200)
            self.assertEqual(self.client.post(f"{path}/unknown/read", headers=headers).status_code, 404)

            restarted_store = AlertHistoryStore(local_dir=Path(self.alert_directory.name))
            with patch("app.main._alert_history_store", return_value=restarted_store):
                restored = self.client.get(path, headers=headers).json()["alerts"]
            self.assertEqual(len(restored), 1)
            self.assertTrue(restored[0]["is_read"])
        request_tts.assert_awaited_once()

    def test_alert_websocket_ticket_requires_app_token_and_is_single_use(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {"PAUSEABLE_APP_TOKEN": "test-app-token"},
        ):
            unauthorized = self.client.post(
                "/api/patients/byunwoojin/alert-websocket-ticket",
            )
            self.assertEqual(unauthorized.status_code, 401)

            issued = self.client.post(
                "/api/patients/byunwoojin/alert-websocket-ticket",
                headers={"Authorization": "Bearer test-app-token"},
            )
            self.assertEqual(issued.status_code, 201)
            self.assertEqual(issued.json()["expires_in_seconds"], 60)
            ticket = issued.json()["ticket"]

        websocket_url = (
            "/ws/alerts?patient_id=byunwoojin"
            f"&ticket={ticket}"
        )
        with self.client.websocket_connect(websocket_url) as websocket:
            self.assertEqual(websocket.receive_json()["type"], "ready")

        with self.assertRaises(WebSocketDisconnect) as rejected:
            with self.client.websocket_connect(websocket_url) as websocket:
                websocket.receive_json()
        self.assertEqual(rejected.exception.code, 4401)


if __name__ == "__main__":
    unittest.main()
