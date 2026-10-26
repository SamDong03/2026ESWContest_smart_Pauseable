from __future__ import annotations

import argparse
import base64
import hashlib
import os
from pathlib import Path
from typing import Any

import httpx


CHUNK_SIZE = 1024 * 1024


def file_descriptor(path: Path) -> dict[str, Any]:
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size_bytes = 0
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            size_bytes += len(chunk)
            sha256.update(chunk)
            md5.update(chunk)
    if size_bytes == 0:
        raise ValueError(f"Artifact is empty: {path}")
    return {
        "size_bytes": size_bytes,
        "sha256": sha256.hexdigest(),
        "content_md5": base64.b64encode(md5.digest()).decode("ascii"),
    }


def require_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def checked_response(response: httpx.Response, action: str) -> httpx.Response:
    if response.is_success:
        return response
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    raise RuntimeError(f"{action} failed ({response.status_code}): {detail}")


def publish(args: argparse.Namespace) -> dict[str, Any]:
    api_url = require_environment("PAUSEABLE_API_URL").rstrip("/")
    worker_token = require_environment("PAUSEABLE_WORKER_TOKEN")
    artifacts = {
        "model.onnx": args.onnx.resolve(),
        "model.onnx.json": args.config.resolve(),
    }
    if args.extra_artifact_dir is not None:
        extra_dir = args.extra_artifact_dir.resolve()
        for name in ("test.wav", "manifest.json", "status.json", "training.log"):
            path = extra_dir / name
            if not path.is_file():
                raise ValueError(f"Expected extra artifact does not exist: {path}")
            artifacts[name] = path
    for path in artifacts.values():
        if not path.is_file():
            raise ValueError(f"Artifact does not exist: {path}")

    print("[1/4] Calculating local file hashes...")
    descriptors = {
        name: file_descriptor(path)
        for name, path in artifacts.items()
    }
    headers = {"Authorization": f"Bearer {worker_token}"}
    timeout = httpx.Timeout(connect=30, read=300, write=300, pool=30)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        print("[2/4] Requesting a short-lived R2 upload plan from Render...")
        response = checked_response(
            client.post(
                f"{api_url}/api/worker/voice-models/upload-plan",
                headers=headers,
                json={
                    "patient_id": args.patient_id,
                    "version": args.version,
                    "artifacts": descriptors,
                },
            ),
            "Upload-plan request",
        )
        plan = response.json()

        print("[3/4] Uploading ONNX and config directly to R2...")
        for name, path in artifacts.items():
            target = plan["artifacts"][name]
            with path.open("rb") as source:
                checked_response(
                    client.put(
                        target["upload_url"],
                        headers=target["headers"],
                        content=source,
                    ),
                    f"R2 upload for {name}",
                )
            print(f"      uploaded {name} ({descriptors[name]['size_bytes']} bytes)")

        print("[4/4] Asking Render to verify and publish the release...")
        response = checked_response(
            client.post(
                f"{api_url}/api/worker/voice-models/"
                f"{plan['model_id']}/publish",
                headers=headers,
                json={"patient_id": args.patient_id},
            ),
            "Model publish",
        )
    return response.json()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish an existing Piper ONNX model through Render to R2"
    )
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--onnx", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--extra-artifact-dir",
        type=Path,
        help=(
            "Optional directory containing test.wav, manifest.json, "
            "status.json and training.log"
        ),
    )
    return parser.parse_args()


def main() -> int:
    try:
        result = publish(parse_args())
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
        print(f"ERROR: {error}")
        return 1
    print(
        "Published successfully: "
        f"model_id={result['model_id']} version={result['version']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
