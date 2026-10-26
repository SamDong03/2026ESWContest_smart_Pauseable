#!/usr/bin/env python3

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import json
import logging
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import httpx


LOGGER = logging.getLogger("pauseable.voice_worker")
VOICE_ROOT = Path(__file__).resolve().parents[1]
TRAIN_SCRIPT = VOICE_ROOT / "train_voice_model.sh"
PATIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
JOB_ID_PATTERN = re.compile(r"^voice-job-[0-9a-f]{12}$")
MIN_TRAINING_CLIPS = 160
MAX_TRAINING_CLIPS = 240


def expected_file_names(count: int) -> tuple[str, ...]:
    return tuple(f"S{index:03d}.wav" for index in range(1, count + 1))
RESULT_ARTIFACTS = (
    "model.onnx",
    "model.onnx.json",
    "test.wav",
    "manifest.json",
    "status.json",
    "training.log",
)
LOCAL_STATE_MAP = {
    "VALIDATING": "preprocessing",
    "PREPROCESSING": "preprocessing",
    "TRAINING": "training",
    "EXPORTING": "exporting",
    "VALIDATING_MODEL": "validating_model",
}


class WorkerConfigurationError(RuntimeError):
    pass


class WorkerJobError(RuntimeError):
    def __init__(self, message: str, *, stage: str, retryable: bool) -> None:
        super().__init__(message)
        self.stage = stage
        self.retryable = retryable


@dataclass(frozen=True)
class WorkerSettings:
    api_url: str
    worker_token: str
    worker_id: str
    work_root: Path
    output_root: Path
    poll_seconds: int = 30
    lease_seconds: int = 300
    heartbeat_seconds: int = 60

    @classmethod
    def from_environment(cls) -> "WorkerSettings":
        api_url = os.getenv("PAUSEABLE_API_URL", "").strip().rstrip("/")
        worker_token = os.getenv("PAUSEABLE_WORKER_TOKEN", "").strip()
        worker_id = os.getenv("PAUSEABLE_WORKER_ID", "").strip()
        if not worker_id:
            worker_id = re.sub(r"[^A-Za-z0-9._-]", "-", socket.gethostname())

        missing = []
        if not api_url:
            missing.append("PAUSEABLE_API_URL")
        if not worker_token:
            missing.append("PAUSEABLE_WORKER_TOKEN")
        if missing:
            raise WorkerConfigurationError(
                "Missing Worker environment variables: " + ", ".join(missing)
            )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", worker_id):
            raise WorkerConfigurationError("PAUSEABLE_WORKER_ID is invalid")

        default_root = Path.home() / ".local" / "share" / "pauseable" / "voice-worker"
        work_root = Path(
            os.getenv("PAUSEABLE_WORK_ROOT", str(default_root))
        ).expanduser()
        output_root = Path(
            os.getenv("PAUSEABLE_TRAINING_OUTPUT_ROOT", str(work_root / "output"))
        ).expanduser()

        def integer(name: str, default: int, minimum: int, maximum: int) -> int:
            raw_value = os.getenv(name, str(default)).strip()
            try:
                value = int(raw_value)
            except ValueError as error:
                raise WorkerConfigurationError(f"{name} must be an integer") from error
            if not minimum <= value <= maximum:
                raise WorkerConfigurationError(
                    f"{name} must be between {minimum} and {maximum}"
                )
            return value

        lease_seconds = integer("PAUSEABLE_WORKER_LEASE_SECONDS", 300, 30, 3600)
        heartbeat_seconds = integer(
            "PAUSEABLE_WORKER_HEARTBEAT_SECONDS", 60, 5, 1200
        )
        if heartbeat_seconds >= lease_seconds:
            raise WorkerConfigurationError(
                "PAUSEABLE_WORKER_HEARTBEAT_SECONDS must be shorter than the lease"
            )

        return cls(
            api_url=api_url,
            worker_token=worker_token,
            worker_id=worker_id,
            work_root=work_root.resolve(),
            output_root=output_root.resolve(),
            poll_seconds=integer("PAUSEABLE_WORKER_POLL_SECONDS", 30, 1, 3600),
            lease_seconds=lease_seconds,
            heartbeat_seconds=heartbeat_seconds,
        )


class WorkerApi:
    def __init__(self, settings: WorkerSettings) -> None:
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.api_url,
            headers={"Authorization": f"Bearer {settings.worker_token}"},
            timeout=30,
        )

    def close(self) -> None:
        self.client.close()

    def claim(self) -> dict[str, Any] | None:
        response = self.client.post(
            "/api/worker/voice-training/claims",
            json={
                "worker_id": self.settings.worker_id,
                "lease_seconds": self.settings.lease_seconds,
            },
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise WorkerJobError(
                "Claim response is not a JSON object",
                stage="CLAIMING",
                retryable=True,
            )
        return payload

    def update_status(
        self,
        claim: dict[str, Any],
        *,
        state: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        return self._job_post(
            claim,
            "status",
            {
                "claim_id": claim["claim_id"],
                "lease_token": claim["lease_token"],
                "state": state,
                "message": message,
                "lease_seconds": self.settings.lease_seconds,
            },
        )

    def create_upload_plan(
        self,
        claim: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return self._job_post(
            claim,
            "upload-plan",
            {
                "claim_id": claim["claim_id"],
                "lease_token": claim["lease_token"],
                "artifacts": artifacts,
                "expires_seconds": 3600,
            },
        )

    def complete(self, claim: dict[str, Any]) -> dict[str, Any]:
        return self._job_post(
            claim,
            "complete",
            {
                "claim_id": claim["claim_id"],
                "lease_token": claim["lease_token"],
            },
        )

    def create_model_upload_plan(
        self,
        claim: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        response = self.client.post(
            "/api/worker/voice-models/upload-plan",
            json={
                "patient_id": claim["patient_id"],


                "version": claim["job_id"],
                "source_job_id": claim["job_id"],
                "artifacts": artifacts,
                "expires_seconds": 3600,
            },
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise WorkerJobError(
                "Model upload-plan response is invalid",
                stage="PUBLISHING",
                retryable=True,
            )
        return result

    def publish_model(
        self,
        claim: dict[str, Any],
        model_id: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/api/worker/voice-models/{model_id}/publish",
            json={"patient_id": claim["patient_id"]},
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise WorkerJobError(
                "Model publish response is invalid",
                stage="PUBLISHING",
                retryable=True,
            )
        return result

    def fail(
        self,
        claim: dict[str, Any],
        *,
        stage: str,
        error: str,
        retryable: bool,
    ) -> dict[str, Any]:
        return self._job_post(
            claim,
            "fail",
            {
                "claim_id": claim["claim_id"],
                "lease_token": claim["lease_token"],
                "failed_stage": stage[:64],
                "error": error[:1000],
                "retryable": retryable,
                "retry_delay_seconds": 300,
            },
        )

    def _job_post(
        self,
        claim: dict[str, Any],
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        patient_id = claim["patient_id"]
        job_id = claim["job_id"]
        response = self.client.post(
            f"/api/worker/voice-training/jobs/{patient_id}/{job_id}/{action}",
            json=payload,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise WorkerJobError(
                f"Worker API {action} response is invalid",
                stage=action.upper(),
                retryable=True,
            )
        return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _md5_base64(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return base64.b64encode(digest.digest()).decode("ascii")


def _validate_wave(path: Path) -> None:
    try:
        with wave.open(str(path), "rb") as source:
            if source.getnchannels() < 1 or source.getframerate() < 1:
                raise WorkerJobError(
                    f"Invalid WAV header: {path.name}",
                    stage="DOWNLOADING",
                    retryable=False,
                )
            if source.getnframes() < 1:
                raise WorkerJobError(
                    f"WAV contains no audio frames: {path.name}",
                    stage="DOWNLOADING",
                    retryable=False,
                )
    except (EOFError, wave.Error) as error:
        raise WorkerJobError(
            f"Unreadable WAV file: {path.name}",
            stage="DOWNLOADING",
            retryable=False,
        ) from error


def _validate_claim(claim: dict[str, Any]) -> None:
    patient_id = str(claim.get("patient_id", ""))
    job_id = str(claim.get("job_id", ""))
    if not PATIENT_ID_PATTERN.fullmatch(patient_id):
        raise WorkerJobError("Claim contains an invalid patient id", stage="CLAIMING", retryable=False)
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise WorkerJobError("Claim contains an invalid job id", stage="CLAIMING", retryable=False)
    if not claim.get("claim_id") or not claim.get("lease_token"):
        raise WorkerJobError("Claim credentials are missing", stage="CLAIMING", retryable=False)

    manifest = claim.get("manifest")
    input_files = claim.get("input_files")
    if not isinstance(manifest, dict) or not isinstance(input_files, list):
        raise WorkerJobError("Claim manifest or input list is missing", stage="CLAIMING", retryable=False)

    clips = manifest.get("clips")
    if not isinstance(clips, list) or not MIN_TRAINING_CLIPS <= len(clips) <= MAX_TRAINING_CLIPS or len(input_files) != len(clips):
        raise WorkerJobError("Claim must contain 160 to 240 clips", stage="CLAIMING", retryable=False)

    expected_names = expected_file_names(len(clips))
    clip_names = [str(clip.get("file_name", "")) for clip in clips]
    input_names = [str(item.get("file_name", "")) for item in input_files]
    if tuple(clip_names) != expected_names or tuple(input_names) != expected_names:
        raise WorkerJobError("Claim WAV filenames are incomplete or out of order", stage="CLAIMING", retryable=False)

    if len(set(clip_names)) != len(clips):
        raise WorkerJobError("Claim contains duplicate WAV filenames", stage="CLAIMING", retryable=False)
    for clip in clips:
        if not str(clip.get("prompt_text", "")).strip():
            raise WorkerJobError("Claim contains an empty prompt", stage="CLAIMING", retryable=False)


def validate_local_dataset(
    dataset_dir: Path,
    metadata_file: Path | None = None,
) -> int:
    dataset_dir = dataset_dir.expanduser().resolve(strict=True)
    if not dataset_dir.is_dir():
        raise WorkerConfigurationError("Dry-run dataset path is not a directory")

    wav_by_name: dict[str, Path] = {}
    for path in sorted(dataset_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() != ".wav":
            continue
        if path.name in wav_by_name:
            raise WorkerConfigurationError(
                f"Dry-run duplicate WAV filename: {path.name}"
            )
        wav_by_name[path.name] = path

    actual_names = set(wav_by_name)
    expected_count = max(MIN_TRAINING_CLIPS, min(MAX_TRAINING_CLIPS, len(actual_names)))
    ordered_names = expected_file_names(expected_count)
    expected_names = set(ordered_names)
    if actual_names != expected_names:
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise WorkerConfigurationError(
            f"Dry-run WAV filename mismatch: missing={missing}, extra={extra}"
        )

    if metadata_file is None:
        metadata_candidates = sorted(
            path
            for path in dataset_dir.rglob("recording_script.csv")
            if path.is_file()
        )
        if len(metadata_candidates) != 1:
            raise WorkerConfigurationError(
                "Dry-run requires exactly one recording_script.csv; "
                f"found {len(metadata_candidates)}"
            )
        metadata_path = metadata_candidates[0]
    else:
        metadata_path = metadata_file.expanduser().resolve(strict=True)
        if not metadata_path.is_file():
            raise WorkerConfigurationError(
                "Dry-run metadata path is not a file"
            )
    rows = []
    for line_number, raw_line in enumerate(
        metadata_path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        if "|" not in raw_line:
            raise WorkerConfigurationError(
                f"Dry-run metadata line {line_number} has no separator"
            )
        file_name, prompt = raw_line.split("|", 1)
        if not prompt.strip():
            raise WorkerConfigurationError(
                f"Dry-run metadata line {line_number} has an empty prompt"
            )
        rows.append(file_name.strip())

    if tuple(rows) != ordered_names:
        raise WorkerConfigurationError(
            "Dry-run metadata must match the consecutive WAV filenames in order"
        )

    for file_name in ordered_names:
        _validate_wave(wav_by_name[file_name])
    return expected_count


class TrainingWorker:
    def __init__(
        self,
        settings: WorkerSettings,
        *,
        api: Any | None = None,
        transfer_client: httpx.Client | None = None,
        pipeline_runner: Callable[[list[str], dict[str, Any]], int] | None = None,
    ) -> None:
        self.settings = settings
        self.api = api or WorkerApi(settings)
        self.transfer_client = transfer_client or httpx.Client(timeout=300)
        self.pipeline_runner = pipeline_runner or self._run_pipeline
        self.stop_event = threading.Event()
        self._last_heartbeat = 0.0
        self._last_local_status: tuple[str, str] | None = None

    def close(self) -> None:
        close_api = getattr(self.api, "close", None)
        if close_api:
            close_api()
        self.transfer_client.close()

    def request_stop(self, *_: Any) -> None:
        self.stop_event.set()

    def _heartbeat(self, claim: dict[str, Any], *, force: bool = False) -> None:
        current = time.monotonic()
        if force or current - self._last_heartbeat >= self.settings.heartbeat_seconds:
            self.api.update_status(claim)
            self._last_heartbeat = current

    def _download_dataset(self, claim: dict[str, Any]) -> Path:
        patient_id = claim["patient_id"]
        job_id = claim["job_id"]
        dataset_dir = self.settings.work_root / "downloads" / patient_id / job_id
        dataset_dir.mkdir(parents=True, exist_ok=True)

        input_by_name = {
            item["file_name"]: item
            for item in claim["input_files"]
        }
        clips_by_name = {
            clip["file_name"]: clip
            for clip in claim["manifest"]["clips"]
        }

        file_names = expected_file_names(len(claim["manifest"]["clips"]))
        for file_name in file_names:
            if self.stop_event.is_set():
                raise WorkerJobError("Worker shutdown requested", stage="DOWNLOADING", retryable=True)
            item = input_by_name[file_name]
            destination = dataset_dir / file_name
            expected_size = int(item["size_bytes"])
            if destination.is_file() and destination.stat().st_size == expected_size:
                _validate_wave(destination)
                self._heartbeat(claim)
                continue

            temporary = destination.with_suffix(".wav.part")
            try:
                response = self.transfer_client.get(item["download_url"])
                response.raise_for_status()
            except httpx.HTTPError as error:
                raise WorkerJobError(
                    f"Failed to download WAV: {file_name}",
                    stage="DOWNLOADING",
                    retryable=True,
                ) from None
            temporary.write_bytes(response.content)
            if temporary.stat().st_size != expected_size:
                temporary.unlink(missing_ok=True)
                raise WorkerJobError(
                    f"Downloaded WAV size mismatch: {file_name}",
                    stage="DOWNLOADING",
                    retryable=True,
                )
            _validate_wave(temporary)
            temporary.replace(destination)
            self._heartbeat(claim)

        metadata_path = dataset_dir / "recording_script.csv"
        metadata_text = "".join(
            f"{name}|{clips_by_name[name]['prompt_text']}\n"
            for name in file_names
        )
        temporary_metadata = metadata_path.with_suffix(".csv.tmp")
        temporary_metadata.write_text(metadata_text, encoding="utf-8", newline="\n")
        temporary_metadata.replace(metadata_path)
        return dataset_dir

    def _training_command(self, claim: dict[str, Any], dataset_dir: Path) -> list[str]:
        return [
            "bash",
            str(TRAIN_SCRIPT),
            "--patient-id",
            claim["patient_id"],
            "--job-id",
            claim["job_id"],
            "--dataset-dir",
            str(dataset_dir),
            "--output-dir",
            str(self.settings.output_root),
            "--clip-count",
            str(len(claim["manifest"]["clips"])),
        ]

    def _run_pipeline(self, command: list[str], claim: dict[str, Any]) -> int:
        process = subprocess.Popen(
            command,
            cwd=VOICE_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        while process.poll() is None:
            if self.stop_event.wait(timeout=2):
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise WorkerJobError(
                    "Worker shutdown requested",
                    stage="TRAINING",
                    retryable=True,
                )
            self._publish_local_status(claim)
            self._heartbeat(claim)
        return int(process.returncode)

    def _publish_local_status(self, claim: dict[str, Any]) -> None:
        status_path = (
            self.settings.output_root
            / ".jobs"
            / claim["patient_id"]
            / claim["job_id"]
            / "status.json"
        )
        if not status_path.is_file():
            return
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        cloud_state = LOCAL_STATE_MAP.get(str(status.get("state", "")))
        if cloud_state:
            message = str(status.get("message", ""))[:1000]
            current_status = (cloud_state, message)
            if current_status == self._last_local_status:
                return
            self.api.update_status(
                claim,
                state=cloud_state,
                message=message or None,
            )
            self._last_local_status = current_status

    def _artifact_descriptors(self, final_dir: Path) -> dict[str, dict[str, Any]]:
        descriptors = {}
        for name in RESULT_ARTIFACTS:
            path = final_dir / name
            if not path.is_file() or path.stat().st_size <= 0:
                raise WorkerJobError(
                    f"Pipeline result is missing or empty: {name}",
                    stage="VALIDATING_MODEL",
                    retryable=False,
                )
            descriptors[name] = {
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "content_md5": _md5_base64(path),
            }
        return descriptors

    def _upload_artifacts(
        self,
        claim: dict[str, Any],
        final_dir: Path,
        descriptors: dict[str, dict[str, Any]],
    ) -> None:
        plan = self.api.create_upload_plan(claim, descriptors)
        for name in RESULT_ARTIFACTS:
            artifact = plan["artifacts"][name]
            path = final_dir / name
            with path.open("rb") as source:
                try:
                    response = self.transfer_client.put(
                        artifact["upload_url"],
                        headers=artifact["headers"],
                        content=source,
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    raise WorkerJobError(
                        f"Failed to upload artifact: {name}",
                        stage="UPLOADING",
                        retryable=True,
                    ) from None
            self._heartbeat(claim)

    def _publish_model_release(
        self,
        claim: dict[str, Any],
        final_dir: Path,
        descriptors: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        self.api.update_status(
            claim,
            state="uploading",
            message="Publishing the verified model release for device deployment",
        )
        try:
            plan = self.api.create_model_upload_plan(claim, descriptors)
        except httpx.HTTPError:
            raise WorkerJobError(
                "Model upload-plan request failed",
                stage="PUBLISHING",
                retryable=True,
            ) from None
        model_id = str(plan.get("model_id", ""))
        artifacts = plan.get("artifacts")
        if not model_id or not isinstance(artifacts, dict):
            raise WorkerJobError(
                "Model upload plan is incomplete",
                stage="PUBLISHING",
                retryable=True,
            )

        for name in RESULT_ARTIFACTS:
            target = artifacts.get(name)
            if not isinstance(target, dict):
                raise WorkerJobError(
                    f"Model upload plan is missing artifact: {name}",
                    stage="PUBLISHING",
                    retryable=True,
                )
            path = final_dir / name
            with path.open("rb") as source:
                try:
                    response = self.transfer_client.put(
                        target["upload_url"],
                        headers=target["headers"],
                        content=source,
                    )
                    response.raise_for_status()
                except httpx.HTTPError:
                    raise WorkerJobError(
                        f"Failed to upload model release artifact: {name}",
                        stage="PUBLISHING",
                        retryable=True,
                    ) from None
            self._heartbeat(claim)

        try:
            return self.api.publish_model(claim, model_id)
        except httpx.HTTPError:
            raise WorkerJobError(
                "Model publish request failed",
                stage="PUBLISHING",
                retryable=True,
            ) from None

    def process_claim(self, claim: dict[str, Any]) -> None:
        _validate_claim(claim)
        self._last_heartbeat = 0.0
        self._last_local_status = None
        dataset_dir = (
            self.settings.work_root
            / "downloads"
            / claim["patient_id"]
            / claim["job_id"]
        )
        final_dir = (
            self.settings.output_root / claim["patient_id"] / claim["job_id"]
        )
        try:
            self.api.update_status(
                claim,
                state="downloading",
                message=f"Downloading and validating {len(claim['manifest']['clips'])} WAV clips",
            )
            dataset_dir = self._download_dataset(claim)
            command = self._training_command(claim, dataset_dir)
            self.api.update_status(
                claim,
                state="preprocessing",
                message="Starting the local Piper training pipeline",
            )
            exit_code = self.pipeline_runner(command, claim)
            if exit_code != 0:
                raise WorkerJobError(
                    f"Training pipeline exited with code {exit_code}",
                    stage="TRAINING",
                    retryable=True,
                )

            descriptors = self._artifact_descriptors(final_dir)
            self._upload_artifacts(claim, final_dir, descriptors)
            release = self._publish_model_release(
                claim,
                final_dir,
                descriptors,
            )
            self.api.complete(claim)
            LOGGER.info(
                "Voice training job completed and model published: job=%s model=%s",
                claim["job_id"],
                release.get("model_id"),
            )
        except WorkerJobError as error:
            try:
                self.api.fail(
                    claim,
                    stage=error.stage,
                    error=str(error),
                    retryable=error.retryable,
                )
            except Exception:
                LOGGER.error("Could not report the Worker failure to the API")
            raise
        except Exception as error:
            try:
                self.api.fail(
                    claim,
                    stage="WORKER",
                    error=f"Unexpected Worker error: {type(error).__name__}",
                    retryable=True,
                )
            except Exception:
                LOGGER.error("Could not report the Worker failure to the API")
            raise
        finally:


            for path, root in (
                (dataset_dir, self.settings.work_root),
                (final_dir, self.settings.output_root),
            ):
                resolved = path.resolve()
                if root.resolve() in resolved.parents:
                    shutil.rmtree(resolved, ignore_errors=True)

    def run_once(self) -> bool:
        claim = self.api.claim()
        if claim is None:
            return False
        self.process_claim(claim)
        return True

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                worked = self.run_once()
            except Exception:
                LOGGER.error("Voice training Worker job failed")
                worked = True
            if not worked:
                self.stop_event.wait(self.settings.poll_seconds)


def _acquire_process_lock(work_root: Path) -> Any:
    work_root.mkdir(parents=True, exist_ok=True)
    lock_file = (work_root / "worker.lock").open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        lock_file.close()
        raise WorkerConfigurationError(
            "Another PAUSEABLE voice training Worker is already running"
        ) from error
    return lock_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PAUSEABLE GPU training Worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued job and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate a local dataset without API, R2, Docker or GPU access",
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        help="Local dataset for --dry-run",
    )
    parser.add_argument(
        "--metadata-file",
        type=Path,
        help="Optional recording_script.csv path for --dry-run",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if args.dry_run:
        if args.dataset_dir is None:
            parser.error("--dry-run requires --dataset-dir")
        try:
            clip_count = validate_local_dataset(args.dataset_dir, args.metadata_file)
        except (OSError, WorkerConfigurationError, WorkerJobError) as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        print("PAUSEABLE WORKER DRY RUN: PASS")
        print(f"Validated WAV files: {clip_count}")
        print(f"Validated metadata rows: {clip_count}")
        print("API calls: 0")
        print("Training subprocesses: 0")
        return 0

    settings = WorkerSettings.from_environment()
    lock_file = _acquire_process_lock(settings.work_root)
    worker = TrainingWorker(settings)
    signal.signal(signal.SIGINT, worker.request_stop)
    signal.signal(signal.SIGTERM, worker.request_stop)
    try:
        if args.once:
            worker.run_once()
        else:
            worker.run_forever()
    finally:
        worker.close()
        lock_file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
