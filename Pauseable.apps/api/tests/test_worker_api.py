from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class FakeStorage:
    def create_download_url(
        self,
        key: str,
        *,
        expires_seconds: int,
    ) -> str:
        return f"https://r2.test/{key}?expires={expires_seconds}"


class FakeWorkerService:
    def __init__(self) -> None:
        self.storage = FakeStorage()
        self.claim_result = None
        self.claim_arguments = None
        self.status_arguments = None

    def claim_next_job(self, **arguments):
        self.claim_arguments = arguments
        return self.claim_result

    def update_claim_status(self, **arguments):
        self.status_arguments = arguments
        return {
            "patient_id": arguments["patient_id"],
            "job_id": arguments["job_id"],
            "claim_id": arguments["claim_id"],
            "status": arguments["state"],
            "heartbeat_at": "2026-09-11T00:00:00+00:00",
            "lease_expires_at": "2026-09-11T00:05:00+00:00",
        }

    def create_upload_plan(self, **arguments):
        return {"status": "uploading", "artifacts": arguments["artifacts"]}

    def complete_job(self, **arguments):
        return {"status": "completed", "job_id": arguments["job_id"]}

    def fail_job(self, **arguments):
        return {"status": "failed", "job_id": arguments["job_id"]}


class WorkerApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_token = os.environ.get("PAUSEABLE_WORKER_TOKEN")
        os.environ["PAUSEABLE_WORKER_TOKEN"] = "worker-test-token"
        self.service = FakeWorkerService()
        self.storage_backend_patch = patch.object(
            main,
            "STORAGE_BACKEND",
            "r2",
        )
        self.service_patch = patch.object(
            main,
            "_r2_voice_training_service",
            return_value=self.service,
        )
        self.storage_backend_patch.start()
        self.service_patch.start()
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.service_patch.stop()
        self.storage_backend_patch.stop()
        if self.previous_token is None:
            os.environ.pop("PAUSEABLE_WORKER_TOKEN", None)
        else:
            os.environ["PAUSEABLE_WORKER_TOKEN"] = self.previous_token

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer worker-test-token"}

    def test_worker_claim_requires_worker_token(self) -> None:
        response = self.client.post(
            "/api/worker/voice-training/claims",
            json={"worker_id": "gpu-pc-one"},
        )

        self.assertEqual(response.status_code, 401)

    def test_worker_routes_exist_without_queue_route(self) -> None:
        paths = {route.path for route in main.app.routes}
        base = "/api/worker/voice-training"
        job = f"{base}/jobs/{{patient_id}}/{{job_id}}"
        self.assertTrue({
            f"{base}/claims",
            f"{job}/status",
            f"{job}/upload-plan",
            f"{job}/complete",
            f"{job}/fail",
        }.issubset(paths))
        self.assertNotIn(
            "/api/patients/{patient_id}/voice-training/jobs/{job_id}/queue",
            paths,
        )

    def test_no_queued_job_returns_204(self) -> None:
        response = self.client.post(
            "/api/worker/voice-training/claims",
            headers=self.headers,
            json={"worker_id": "gpu-pc-one"},
        )

        self.assertEqual(response.status_code, 204)

    def test_claim_returns_presigned_input_urls(self) -> None:
        self.service.claim_result = {
            "patient_id": "patient-001",
            "job_id": "voice-job-0123456789ab",
            "claim_id": "claim-0123456789abcdef0123456789abcdef",
            "lease_token": "lease-token",
            "worker_id": "gpu-pc-one",
            "attempt": 1,
            "lease_expires_at": "2026-09-11T00:05:00+00:00",
            "manifest": {
                "clips": [
                    {
                        "file_name": "S001.wav",
                        "size_bytes": 100,
                        "object_key": "patients/patient-001/input/S001.wav",
                    }
                ]
            },
        }

        response = self.client.post(
            "/api/worker/voice-training/claims",
            headers=self.headers,
            json={"worker_id": "gpu-pc-one", "lease_seconds": 600},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["claim_id"], self.service.claim_result["claim_id"])
        self.assertEqual(len(payload["input_files"]), 1)
        self.assertTrue(
            payload["input_files"][0]["download_url"].startswith(
                "https://r2.test/"
            )
        )
        self.assertEqual(
            self.service.claim_arguments,
            {"worker_id": "gpu-pc-one", "lease_seconds": 600},
        )

    def test_status_update_uses_claim_credentials(self) -> None:
        response = self.client.post(
            "/api/worker/voice-training/jobs/"
            "patient-001/voice-job-0123456789ab/status",
            headers=self.headers,
            json={
                "claim_id": "claim-0123456789abcdef0123456789abcdef",
                "lease_token": "lease-token",
                "state": "training",
                "message": "Mock training",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "training")
        self.assertEqual(
            self.service.status_arguments["lease_token"],
            "lease-token",
        )

    def test_upload_plan_complete_and_fail_routes(self) -> None:
        job = (
            "/api/worker/voice-training/jobs/"
            "patient-001/voice-job-0123456789ab"
        )
        credentials = {
            "claim_id": "claim-0123456789abcdef0123456789abcdef",
            "lease_token": "lease-token",
        }
        plan = self.client.post(
            f"{job}/upload-plan",
            headers=self.headers,
            json={**credentials, "artifacts": {}},
        )
        complete = self.client.post(
            f"{job}/complete",
            headers=self.headers,
            json=credentials,
        )
        fail = self.client.post(
            f"{job}/fail",
            headers=self.headers,
            json={**credentials, "failed_stage": "TRAINING", "error": "test"},
        )

        self.assertEqual(plan.status_code, 200)
        self.assertEqual(plan.json()["status"], "uploading")
        self.assertEqual(complete.status_code, 200)
        self.assertEqual(complete.json()["status"], "completed")
        self.assertEqual(fail.status_code, 200)
        self.assertEqual(fail.json()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
