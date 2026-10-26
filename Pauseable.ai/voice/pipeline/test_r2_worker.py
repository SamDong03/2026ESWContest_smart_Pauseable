from __future__ import annotations

import io
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

import httpx

from pipeline.r2_worker import (
    RESULT_ARTIFACTS,
    TrainingWorker,
    WorkerJobError,
    WorkerSettings,
    validate_local_dataset,
)


def make_wave() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(22050)
        destination.writeframes(b"\x00\x00" * 220)
    return output.getvalue()


class FakeApi:
    def __init__(self, claim: dict[str, Any]) -> None:
        self.claim_payload = claim
        self.status_updates: list[dict[str, Any]] = []
        self.upload_descriptors: dict[str, dict[str, Any]] | None = None
        self.model_upload_descriptors: dict[str, dict[str, Any]] | None = None
        self.published_model_id: str | None = None
        self.completed = False
        self.failures: list[dict[str, Any]] = []

    def close(self) -> None:
        pass

    def claim(self) -> dict[str, Any] | None:
        claim = self.claim_payload
        self.claim_payload = None
        return claim

    def update_status(
        self,
        claim: dict[str, Any],
        *,
        state: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        self.status_updates.append({"state": state, "message": message})
        return {"status": state or "heartbeat"}

    def create_upload_plan(
        self,
        claim: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        self.upload_descriptors = artifacts
        return {
            "artifacts": {
                name: {
                    **descriptor,
                    "object_key": f"attempt/artifacts/{name}",
                    "upload_url": f"https://r2.test/output/{name}",
                    "headers": {
                        "Content-Type": "application/octet-stream",
                        "Content-MD5": descriptor["content_md5"],
                        "x-amz-meta-sha256": descriptor["sha256"],
                    },
                }
                for name, descriptor in artifacts.items()
            }
        }

    def complete(self, claim: dict[str, Any]) -> dict[str, Any]:
        self.completed = True
        return {"status": "completed"}

    def create_model_upload_plan(
        self,
        claim: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        self.model_upload_descriptors = artifacts
        return {
            "model_id": "voice-model-0123456789ab",
            "version": claim["job_id"],
            "artifacts": {
                name: {
                    "upload_url": f"https://r2.test/release/{name}",
                    "headers": {
                        "Content-Type": "application/octet-stream",
                        "Content-MD5": descriptor["content_md5"],
                        "x-amz-meta-sha256": descriptor["sha256"],
                    },
                }
                for name, descriptor in artifacts.items()
            },
        }

    def publish_model(
        self,
        claim: dict[str, Any],
        model_id: str,
    ) -> dict[str, Any]:
        self.published_model_id = model_id
        return {
            "patient_id": claim["patient_id"],
            "model_id": model_id,
            "version": claim["job_id"],
        }

    def fail(
        self,
        claim: dict[str, Any],
        *,
        stage: str,
        error: str,
        retryable: bool,
    ) -> dict[str, Any]:
        self.failures.append(
            {"stage": stage, "error": error, "retryable": retryable}
        )
        return {"status": "failed"}


class TrainingWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.wav = make_wave()
        clips = []
        inputs = []
        for index in range(1, 161):
            name = f"S{index:03d}.wav"
            clips.append(
                {
                    "file_name": name,
                    "prompt_text": f"테스트 문장 {index}",
                }
            )
            inputs.append(
                {
                    "file_name": name,
                    "size_bytes": len(self.wav),
                    "download_url": f"https://r2.test/input/{name}",
                }
            )
        self.claim = {
            "patient_id": "patient-001",
            "job_id": "voice-job-0123456789ab",
            "claim_id": "claim-0123456789abcdef0123456789abcdef",
            "lease_token": "test-lease-token",
            "manifest": {"status": "claimed", "clips": clips},
            "input_files": inputs,
        }
        self.api = FakeApi(self.claim)
        self.transfer_requests: list[httpx.Request] = []

        def transfer_handler(request: httpx.Request) -> httpx.Response:
            self.transfer_requests.append(request)
            if request.method == "GET":
                return httpx.Response(200, content=self.wav)
            if request.method == "PUT":
                return httpx.Response(200)
            return httpx.Response(405)

        self.transfer_client = httpx.Client(
            transport=httpx.MockTransport(transfer_handler)
        )
        self.settings = WorkerSettings(
            api_url="https://api.test",
            worker_token="worker-secret",
            worker_id="gpu-pc-test",
            work_root=self.root / "work",
            output_root=self.root / "output",
            poll_seconds=1,
            lease_seconds=300,
            heartbeat_seconds=60,
        )

    def tearDown(self) -> None:
        self.transfer_client.close()
        self.temporary.cleanup()

    def test_mock_pipeline_downloads_runs_uploads_and_completes(self) -> None:
        commands: list[list[str]] = []

        def pipeline_runner(command: list[str], claim: dict[str, Any]) -> int:
            commands.append(command)
            final_dir = (
                self.settings.output_root
                / claim["patient_id"]
                / claim["job_id"]
            )
            final_dir.mkdir(parents=True)
            for name in RESULT_ARTIFACTS:
                (final_dir / name).write_bytes(
                    f"mock result {name}".encode("utf-8")
                )
            return 0

        worker = TrainingWorker(
            self.settings,
            api=self.api,
            transfer_client=self.transfer_client,
            pipeline_runner=pipeline_runner,
        )

        self.assertTrue(worker.run_once())
        self.assertTrue(self.api.completed)
        self.assertEqual(
            self.api.published_model_id,
            "voice-model-0123456789ab",
        )
        self.assertEqual(self.api.failures, [])
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0], "bash")
        self.assertIn("--patient-id", commands[0])
        self.assertIn("--job-id", commands[0])
        self.assertIn("--dataset-dir", commands[0])
        self.assertIn("--output-dir", commands[0])

        dataset_dir = (
            self.settings.work_root
            / "downloads"
            / self.claim["patient_id"]
            / self.claim["job_id"]
        )
        self.assertFalse(dataset_dir.exists())
        self.assertFalse(
            (
                self.settings.output_root
                / self.claim["patient_id"]
                / self.claim["job_id"]
            ).exists()
        )

        get_requests = [
            request for request in self.transfer_requests
            if request.method == "GET"
        ]
        put_requests = [
            request for request in self.transfer_requests
            if request.method == "PUT"
        ]
        self.assertEqual(len(get_requests), 160)
        self.assertEqual(len(put_requests), 12)
        self.assertTrue(
            all("authorization" not in request.headers for request in self.transfer_requests)
        )
        self.assertIsNotNone(self.api.upload_descriptors)
        self.assertEqual(
            self.api.model_upload_descriptors,
            self.api.upload_descriptors,
        )

    def test_mock_pipeline_failure_is_reported_without_completion(self) -> None:
        def pipeline_runner(command: list[str], claim: dict[str, Any]) -> int:
            return 9

        worker = TrainingWorker(
            self.settings,
            api=self.api,
            transfer_client=self.transfer_client,
            pipeline_runner=pipeline_runner,
        )

        with self.assertRaises(WorkerJobError):
            worker.run_once()

        self.assertFalse(self.api.completed)
        self.assertEqual(len(self.api.failures), 1)
        self.assertEqual(self.api.failures[0]["stage"], "TRAINING")
        self.assertTrue(self.api.failures[0]["retryable"])

    def test_model_release_upload_failure_is_retryable_before_completion(self) -> None:
        def pipeline_runner(command: list[str], claim: dict[str, Any]) -> int:
            final_dir = (
                self.settings.output_root
                / claim["patient_id"]
                / claim["job_id"]
            )
            final_dir.mkdir(parents=True)
            for name in RESULT_ARTIFACTS:
                (final_dir / name).write_bytes(
                    f"mock result {name}".encode("utf-8")
                )
            return 0

        def transfer_handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, content=self.wav)
            if request.method == "PUT" and "/release/" in str(request.url):
                return httpx.Response(503)
            if request.method == "PUT":
                return httpx.Response(200)
            return httpx.Response(405)

        transfer_client = httpx.Client(
            transport=httpx.MockTransport(transfer_handler)
        )
        worker = TrainingWorker(
            self.settings,
            api=self.api,
            transfer_client=transfer_client,
            pipeline_runner=pipeline_runner,
        )
        try:
            with self.assertRaisesRegex(
                WorkerJobError,
                "Failed to upload model release artifact",
            ) as raised:
                worker.run_once()
        finally:
            transfer_client.close()

        self.assertEqual(raised.exception.stage, "PUBLISHING")
        self.assertFalse(self.api.completed)
        self.assertIsNone(self.api.published_model_id)
        self.assertEqual(len(self.api.failures), 1)
        self.assertEqual(self.api.failures[0]["stage"], "PUBLISHING")
        self.assertTrue(self.api.failures[0]["retryable"])

    def test_240_clip_claim_reaches_pipeline_with_selected_count(self) -> None:
        for index in range(161, 241):
            name = f"S{index:03d}.wav"
            self.claim["manifest"]["clips"].append(
                {"file_name": name, "prompt_text": f"테스트 문장 {index}"}
            )
            self.claim["input_files"].append(
                {
                    "file_name": name,
                    "size_bytes": len(self.wav),
                    "download_url": f"https://r2.test/input/{name}",
                }
            )
        commands: list[list[str]] = []
        metadata_line_counts: list[int] = []

        def pipeline_runner(command: list[str], claim: dict[str, Any]) -> int:
            commands.append(command)
            dataset_path = Path(command[command.index("--dataset-dir") + 1])
            metadata_line_counts.append(
                len(
                    (dataset_path / "recording_script.csv")
                    .read_text(encoding="utf-8")
                    .splitlines()
                )
            )
            final_dir = self.settings.output_root / claim["patient_id"] / claim["job_id"]
            final_dir.mkdir(parents=True)
            for name in RESULT_ARTIFACTS:
                (final_dir / name).write_bytes(b"mock result")
            return 0

        worker = TrainingWorker(
            self.settings,
            api=self.api,
            transfer_client=self.transfer_client,
            pipeline_runner=pipeline_runner,
        )
        self.assertTrue(worker.run_once())
        self.assertTrue(self.api.completed)
        self.assertEqual(commands[0][-2:], ["--clip-count", "240"])
        self.assertEqual(metadata_line_counts, [240])
        self.assertEqual(
            len([request for request in self.transfer_requests if request.method == "GET"]),
            240,
        )

    def test_local_dry_run_validates_160_wavs_and_metadata(self) -> None:
        dataset_dir = self.root / "dry-run-dataset"
        wav_dir = dataset_dir / "original-wavs"
        metadata_dir = dataset_dir / "metadata"
        wav_dir.mkdir(parents=True)
        metadata_dir.mkdir()
        metadata_lines = []
        for index in range(1, 161):
            name = f"S{index:03d}.wav"
            (wav_dir / name).write_bytes(self.wav)
            metadata_lines.append(f"{name}|테스트 문장 {index}\n")
        (metadata_dir / "recording_script.csv").write_text(
            "".join(metadata_lines),
            encoding="utf-8",
        )

        validate_local_dataset(dataset_dir)

        validate_local_dataset(
            wav_dir,
            metadata_dir / "recording_script.csv",
        )

        (wav_dir / "S160.wav").unlink()
        with self.assertRaisesRegex(RuntimeError, "filename mismatch"):
            validate_local_dataset(dataset_dir)

    def test_local_dry_run_accepts_240_fixed_rows(self) -> None:
        dataset_dir = self.root / "dry-run-240"
        dataset_dir.mkdir()
        lines = []
        for index in range(1, 241):
            name = f"S{index:03d}.wav"
            (dataset_dir / name).write_bytes(self.wav)
            lines.append(f"{name}|테스트 문장 {index}\n")
        (dataset_dir / "recording_script.csv").write_text(
            "".join(lines), encoding="utf-8"
        )
        self.assertEqual(validate_local_dataset(dataset_dir), 240)

    def test_download_failure_does_not_expose_presigned_url(self) -> None:
        secret_url = "https://r2.test/input/S001.wav?signature=do-not-log"
        self.claim["input_files"][0]["download_url"] = secret_url

        transfer_client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(403, request=request)
            )
        )
        worker = TrainingWorker(
            self.settings,
            api=self.api,
            transfer_client=transfer_client,
            pipeline_runner=lambda command, claim: 0,
        )
        try:
            with self.assertRaisesRegex(
                WorkerJobError,
                "Failed to download WAV: S001.wav",
            ):
                worker.run_once()
        finally:
            transfer_client.close()

        self.assertEqual(len(self.api.failures), 1)
        self.assertNotIn("signature", self.api.failures[0]["error"])
        self.assertNotIn("do-not-log", self.api.failures[0]["error"])


if __name__ == "__main__":
    unittest.main()
