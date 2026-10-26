#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ONNX_TARGET_NAME = "ko_KR-guardian-medium.onnx"
CONFIG_TARGET_NAME = "ko_KR-guardian-medium.onnx.json"
CHUNK_SIZE = 1024 * 1024


def required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


@dataclass(frozen=True)
class Settings:
    api_url: str
    device_token: str
    patient_id: str
    device_id: str
    piper_root: Path
    release_root: Path
    validation_text: str

    @classmethod
    def from_environment(cls) -> "Settings":
        api_url = required_environment("PAUSEABLE_API_URL").rstrip("/")
        parsed = urllib.parse.urlparse(api_url)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("PAUSEABLE_API_URL must use HTTPS")
        piper_root = Path(
            os.getenv("PIPER_ROOT", "/var/lib/pauseable/piper-guardian")
        ).resolve()
        release_root = Path(
            os.getenv(
                "PAUSEABLE_MODEL_RELEASE_ROOT",
                str(piper_root / "model-releases"),
            )
        ).resolve()
        return cls(
            api_url=api_url,
            device_token=required_environment("PAUSEABLE_DEVICE_TOKEN"),
            patient_id=required_environment("PATIENT_ID"),
            device_id=required_environment("DEVICE_ID"),
            piper_root=piper_root,
            release_root=release_root,
            validation_text=os.getenv(
                "PAUSEABLE_MODEL_TEST_TEXT",
                "안녕하세요. 음성 모델 설치를 확인합니다.",
            ),
        )


class ApiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.headers = {
            "Authorization": f"Bearer {settings.device_token}",
            "Accept": "application/json",
        }

    def _json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None
        headers = dict(self.headers)
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.settings.api_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get("detail")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                detail = None
            raise RuntimeError(
                f"Render API returned HTTP {error.code}"
                + (f": {detail}" if detail else "")
            ) from None
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach Render API: {error.reason}") from None
        if not isinstance(result, dict):
            raise RuntimeError("Render API returned an invalid JSON response")
        return result

    def latest(self) -> dict[str, Any]:
        query = urllib.parse.urlencode({"patient_id": self.settings.patient_id})
        device_id = urllib.parse.quote(self.settings.device_id, safe="")
        return self._json_request(
            "GET", f"/api/devices/{device_id}/voice-models/latest?{query}"
        )

    def acknowledge(
        self,
        model_id: str,
        status: str,
        *,
        detail: str | None = None,
        previous_model_id: str | None = None,
    ) -> None:
        device_id = urllib.parse.quote(self.settings.device_id, safe="")
        model_id_path = urllib.parse.quote(model_id, safe="")
        self._json_request(
            "POST",
            f"/api/devices/{device_id}/voice-models/{model_id_path}/ack",
            {
                "patient_id": self.settings.patient_id,
                "status": status,
                "detail": detail,
                "previous_model_id": previous_model_id,
            },
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    if urllib.parse.urlparse(url).scheme != "https":
        raise RuntimeError("R2 download URL must use HTTPS")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=300) as response, destination.open("wb") as output:
            while chunk := response.read(CHUNK_SIZE):
                output.write(chunk)
                digest.update(chunk)
    except (OSError, urllib.error.URLError) as error:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"R2 download failed: {type(error).__name__}") from None
    actual = digest.hexdigest()
    if actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA-256 mismatch for {destination.name}: expected {expected_sha256}, got {actual}"
        )


def validate_wav_file(path: Path) -> None:
    file_size = path.stat().st_size
    if file_size < 12:
        raise RuntimeError("Piper validation WAV is too small")

    with path.open("rb") as wav:
        header = wav.read(12)
        if header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise RuntimeError("Piper validation output is not a RIFF/WAVE file")

        declared_riff_size = int.from_bytes(header[4:8], "little")
        declared_size = declared_riff_size + 8
        streaming_header = declared_riff_size >= 0x7FFF0000
        if declared_size > file_size and not streaming_header:
            raise RuntimeError("Piper validation WAV is truncated")

        format_tag: int | None = None
        channels = 0
        sample_rate = 0
        block_align = 0
        data_size = 0

        while wav.tell() + 8 <= file_size:
            chunk_header = wav.read(8)
            chunk_id = chunk_header[:4]
            chunk_size = int.from_bytes(chunk_header[4:8], "little")
            chunk_start = wav.tell()
            chunk_end = chunk_start + chunk_size
            if chunk_end > file_size:
                if chunk_id == b"data" and streaming_header and chunk_size >= 0x7FFF0000:
                    data_size += file_size - chunk_start
                    break
                raise RuntimeError("Piper validation WAV contains a truncated chunk")

            if chunk_id == b"fmt ":
                if chunk_size < 16:
                    raise RuntimeError("Piper validation WAV has an invalid fmt chunk")
                fmt = wav.read(16)
                format_tag = int.from_bytes(fmt[0:2], "little")
                channels = int.from_bytes(fmt[2:4], "little")
                sample_rate = int.from_bytes(fmt[4:8], "little")
                block_align = int.from_bytes(fmt[12:14], "little")
            elif chunk_id == b"data":
                data_size += chunk_size

            wav.seek(chunk_end + (chunk_size & 1))

    if format_tag not in {1, 3, 0xFFFE}:
        raise RuntimeError(
            f"Piper validation WAV uses unsupported format tag {format_tag}"
        )
    if channels <= 0 or sample_rate <= 0 or block_align <= 0:
        raise RuntimeError("Piper validation WAV has invalid audio parameters")
    if data_size < block_align:
        raise RuntimeError("Piper validation WAV contains no audio frames")


def validate_release(settings: Settings, release_dir: Path) -> None:
    onnx_path = release_dir / ONNX_TARGET_NAME
    config_path = release_dir / CONFIG_TARGET_NAME
    with config_path.open("r", encoding="utf-8") as source:
        config = json.load(source)
    if not isinstance(config, dict):
        raise RuntimeError("Piper config must be a JSON object")

    piper = settings.piper_root / "bin" / "piper"
    espeak_data = settings.piper_root / "share" / "espeak-ng-data"
    if not piper.is_file() or not os.access(piper, os.X_OK):
        raise RuntimeError(f"Piper executable is unavailable: {piper}")
    if not espeak_data.is_dir():
        raise RuntimeError(f"eSpeak data is unavailable: {espeak_data}")

    output_path = release_dir / "validation.wav"
    environment = os.environ.copy()
    library_paths = [str(settings.piper_root / "lib"), "/usr/lib"]
    existing = environment.get("LD_LIBRARY_PATH", "")
    if existing:
        library_paths.append(existing)
    environment["LD_LIBRARY_PATH"] = ":".join(library_paths)
    result = subprocess.run(
        [
            str(piper),
            "--model",
            str(onnx_path),
            "--config",
            str(config_path),
            "--espeak_data",
            str(espeak_data),
            "--output_file",
            str(output_path),
        ],
        input=settings.validation_text + "\n",
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=120,
        check=False,
        env=environment,
    )
    if result.returncode != 0:
        message = result.stderr.strip().splitlines()[-1:] or ["unknown Piper error"]
        raise RuntimeError(f"Piper validation failed: {message[0][:300]}")
    try:
        validate_wav_file(output_path)
    except OSError as error:
        raise RuntimeError(f"Piper validation WAV is invalid: {error}") from error


def make_release_runtime_readable(release_dir: Path) -> None:
    pass
    required = [
        release_dir / ONNX_TARGET_NAME,
        release_dir / CONFIG_TARGET_NAME,
    ]
    for path in required:
        if not path.is_file():
            raise RuntimeError(f"Voice model release is incomplete: {path.name}")

    release_dir.chmod(0o755)
    for path in required:
        path.chmod(0o644)
    validation_wav = release_dir / "validation.wav"
    if validation_wav.exists():
        validation_wav.chmod(0o644)


def repair_active_release_permissions(settings: Settings) -> None:
    model_dir = settings.piper_root / "models"
    if not model_dir.exists():
        return
    active_release = model_dir.resolve(strict=True)
    try:
        active_release.relative_to(settings.release_root)
    except ValueError as error:
        raise RuntimeError("Active voice model points outside the release root") from error
    make_release_runtime_readable(active_release)


def read_state(settings: Settings) -> dict[str, Any] | None:
    state_path = settings.release_root / "current.json"
    try:
        with state_path.open("r", encoding="utf-8") as source:
            state = json.load(source)
    except FileNotFoundError:
        return None
    return state if isinstance(state, dict) else None


def write_state(settings: Settings, release: dict[str, Any]) -> None:
    state_path = settings.release_root / "current.json"
    temporary = state_path.with_name(f".{state_path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "model_id": release["model_id"],
                "version": release["version"],
                "onnx_sha256": release["onnx_sha256"],
                "config_sha256": release["config_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, state_path)


def point_models_at(settings: Settings, release_dir: Path) -> Path | None:
    model_dir = settings.piper_root / "models"
    previous: Path | None = None
    if model_dir.is_symlink():
        previous = model_dir.resolve(strict=True)
    elif model_dir.exists():
        bootstrap = settings.release_root / "releases" / "bootstrap"
        if bootstrap.exists():
            raise RuntimeError("Cannot preserve existing model directory: bootstrap exists")
        os.replace(model_dir, bootstrap)
        previous = bootstrap

    temporary_link = model_dir.with_name(f".models.{uuid.uuid4().hex}.tmp")
    temporary_link.symlink_to(release_dir, target_is_directory=True)
    try:
        os.replace(temporary_link, model_dir)
    except Exception:
        temporary_link.unlink(missing_ok=True)
        if previous is not None and not model_dir.exists():
            if previous.name == "bootstrap":
                os.replace(previous, model_dir)
            else:
                model_dir.symlink_to(previous, target_is_directory=True)
        raise
    return previous


def restore_models(settings: Settings, previous: Path | None) -> None:
    model_dir = settings.piper_root / "models"
    if previous is None:
        model_dir.unlink(missing_ok=True)
        return
    temporary_link = model_dir.with_name(f".models.rollback.{uuid.uuid4().hex}.tmp")
    temporary_link.symlink_to(previous, target_is_directory=True)
    os.replace(temporary_link, model_dir)


def remove_duplicate_bootstrap(
    settings: Settings,
    previous: Path | None,
    release: dict[str, Any],
) -> bool:
    bootstrap = settings.release_root / "releases" / "bootstrap"
    if previous != bootstrap or not bootstrap.is_dir():
        return False
    try:
        matches = (
            sha256_file(bootstrap / ONNX_TARGET_NAME) == release["onnx_sha256"]
            and sha256_file(bootstrap / CONFIG_TARGET_NAME)
            == release["config_sha256"]
        )
    except FileNotFoundError:
        return False
    if not matches:
        return False
    shutil.rmtree(bootstrap)
    print("Removed duplicate bootstrap model after SHA-256 verification.")
    return True


def install(settings: Settings, api: ApiClient, release: dict[str, Any]) -> str:
    model_id = str(release["model_id"])
    releases_dir = settings.release_root / "releases"
    releases_dir.mkdir(parents=True, exist_ok=True)
    final_dir = releases_dir / model_id
    if final_dir.exists():
        if (
            sha256_file(final_dir / ONNX_TARGET_NAME) != release["onnx_sha256"]
            or sha256_file(final_dir / CONFIG_TARGET_NAME) != release["config_sha256"]
        ):
            raise RuntimeError("Existing local release has unexpected content")
    else:
        staging = Path(
            tempfile.mkdtemp(prefix=f".{model_id}.", dir=releases_dir)
        )
        try:
            print("[2/5] Downloading ONNX and config from R2...")
            download_verified(
                release["onnx_download_url"],
                staging / ONNX_TARGET_NAME,
                release["onnx_sha256"],
            )
            download_verified(
                release["config_download_url"],
                staging / CONFIG_TARGET_NAME,
                release["config_sha256"],
            )
            print("[3/5] Running a Piper synthesis test in the staging directory...")
            validate_release(settings, staging)
            make_release_runtime_readable(staging)
            os.replace(staging, final_dir)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    make_release_runtime_readable(final_dir)

    state = read_state(settings)
    previous_model_id = state.get("model_id") if state else None
    print("[4/5] Activating the release with an atomic models symlink switch...")
    previous_target = point_models_at(settings, final_dir)
    try:
        validate_release(settings, settings.piper_root / "models")
        write_state(settings, release)
    except Exception:
        restore_models(settings, previous_target)
        raise
    remove_duplicate_bootstrap(settings, previous_target, release)
    print("[5/5] Reporting successful installation to Render...")
    api.acknowledge(
        model_id,
        "installed",
        detail="Piper staging and post-activation validation passed",
        previous_model_id=previous_model_id,
    )
    return model_id


def run() -> int:
    try:
        settings = Settings.from_environment()
        settings.release_root.mkdir(parents=True, exist_ok=True)
        lock_path = settings.release_root / "update.lock"
        with lock_path.open("w", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("Another voice-model update is already running.")
                return 0
            repair_active_release_permissions(settings)
            api = ApiClient(settings)
            print("[1/5] Asking Render for the latest published voice model...")
            release = api.latest()
            state = read_state(settings)
            if state and state.get("model_id") == release.get("model_id"):
                print(
                    "Already up to date: "
                    f"model_id={release['model_id']} version={release['version']}"
                )
                return 0
            try:
                model_id = install(settings, api, release)
            except Exception as error:
                try:
                    api.acknowledge(
                        str(release.get("model_id", "")),
                        "failed",
                        detail=str(error)[:1000],
                        previous_model_id=state.get("model_id") if state else None,
                    )
                except Exception as ack_error:
                    print(f"WARNING: failure ACK could not be sent: {ack_error}")
                raise
        print(
            "Voice model installed successfully: "
            f"model_id={model_id} version={release['version']}"
        )
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
