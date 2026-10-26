#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")

    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    os.replace(temporary, path)


def sha256_file(path):
    hasher = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)

    return hasher.hexdigest()


def update_status(status_path, state, **extra):
    status = load_json(status_path)
    status.setdefault("schema_version", 1)
    status.setdefault("created_at", utc_now())

    status["state"] = state
    status["updated_at"] = utc_now()

    if state != "FAILED":
        status.pop("error", None)
        status.pop("failed_stage", None)

    status.update(extra)
    atomic_json(status_path, status)
    return status


def run_logged(command, log_path, append=False):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"

    with log_path.open(mode, encoding="utf-8", newline="\n") as log_file:
        log_file.write(f"\n=== COMMAND START {utc_now()} ===\n")
        log_file.write(" ".join(command) + "\n\n")
        log_file.flush()

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert process.stdout is not None

        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_file.write(line)
            log_file.flush()

        exit_code = process.wait()

        log_file.write(
            f"\n=== COMMAND END {utc_now()} EXIT={exit_code} ===\n"
        )
        log_file.flush()

    if exit_code != 0:
        raise RuntimeError(
            f"Command failed with exit code {exit_code}: {' '.join(command)}"
        )


def latest_last_checkpoint(checkpoint_root):
    candidates = [
        path
        for path in checkpoint_root.rglob("last.ckpt")
        if path.is_file() and path.stat().st_size > 0
    ]

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def validate_final_package(final_dir, input_sha256, config_sha256):
    required = [
        "model.onnx",
        "model.onnx.json",
        "manifest.json",
        "test.wav",
        "training.log",
        "status.json",
    ]

    missing = [
        name
        for name in required
        if not (final_dir / name).is_file()
        or (final_dir / name).stat().st_size == 0
    ]

    if missing:
        raise RuntimeError(
            f"Existing final package is incomplete: {missing}"
        )

    manifest = load_json(final_dir / "manifest.json")

    if manifest.get("input_sha256") != input_sha256:
        raise RuntimeError(
            "Existing final package belongs to different input data"
        )

    if manifest.get("pipeline_config_sha256") != config_sha256:
        raise RuntimeError(
            "Existing final package was produced with a different configuration"
        )

    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Run the complete Piper guardian voice-training pipeline"
    )
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--clip-count", type=int, default=160)
    parser.add_argument(
        "--config",
        default="/workspace/configs/guardian-medium-v1.json",
    )
    args = parser.parse_args()
    if not 160 <= args.clip_count <= 240:
        parser.error("--clip-count must be between 160 and 240")

    input_root = Path(args.input_dir).resolve(strict=True)
    output_root = Path(args.output_dir).resolve(strict=True)
    config_path = Path(args.config).resolve(strict=True)

    config = load_json(config_path)
    config_sha256 = sha256_file(config_path)

    job_dir = output_root / ".jobs" / args.patient_id / args.job_id
    work_dir = job_dir / "work"
    dataset_dir = work_dir / "dataset"
    checkpoint_root = work_dir / "checkpoints"
    cache_dir = work_dir / "cache"
    export_dir = work_dir / "export"

    status_path = job_dir / "status.json"
    context_path = job_dir / "pipeline_context.json"
    training_log = job_dir / "training.log"
    export_log = job_dir / "export.log"
    inference_log = job_dir / "inference.log"

    final_dir = output_root / args.patient_id / args.job_id
    publishing_root = output_root / ".publishing"

    model_onnx = export_dir / "model.onnx"
    model_json = export_dir / "model.onnx.json"
    test_wav = export_dir / "test.wav"

    base_checkpoint = Path(config["checkpoint"]["base_path"])
    expected_base_sha256 = config["checkpoint"]["base_sha256"]

    docker_image = os.environ.get(
        "PIPELINE_DOCKER_IMAGE",
        config["docker_image"],
    )
    docker_image_id = os.environ.get(
        "PIPELINE_DOCKER_IMAGE_ID",
        "unknown",
    )

    stage = "VALIDATING"
    temporary_publish_dir = None

    try:
        job_dir.mkdir(parents=True, exist_ok=True)

        prepare_command = [
            sys.executable,
            "/workspace/pipeline/prepare_dataset.py",
            "--patient-id",
            args.patient_id,
            "--job-id",
            args.job_id,
            "--input-dir",
            str(input_root),
            "--output-dir",
            str(output_root),
            "--config",
            str(config_path),
            "--clip-count",
            str(args.clip_count),
        ]

        subprocess.run(prepare_command, check=True)

        prepared_status = load_json(status_path)

        if prepared_status.get("preprocessing_complete") is not True:
            raise RuntimeError(
                "Dataset preparation did not report successful completion"
            )

        input_sha256 = prepared_status["input_sha256"]

        context = {
            "schema_version": 1,
            "patient_id": args.patient_id,
            "job_id": args.job_id,
            "clip_count": args.clip_count,
            "input_sha256": input_sha256,
            "pipeline_config_sha256": config_sha256,
            "docker_image": docker_image,
            "docker_image_id": docker_image_id,
            "piper": config["piper"],
        }

        previous_context = load_json(context_path)

        for key in (
            "input_sha256",
            "clip_count",
            "pipeline_config_sha256",
            "docker_image_id",
        ):
            previous_value = previous_context.get(key)
            current_value = context[key]

            if previous_value and previous_value != current_value:
                raise RuntimeError(
                    f"Job context changed for {key}: "
                    f"previous={previous_value}, current={current_value}. "
                    "Use a new job-id instead of mixing two training runs."
                )

        atomic_json(context_path, context)

        if final_dir.exists():
            manifest = validate_final_package(
                final_dir,
                input_sha256,
                config_sha256,
            )

            update_status(
                status_path,
                "COMPLETED",
                message="Final package already exists; idempotent skip",
                input_sha256=input_sha256,
                pipeline_config_sha256=config_sha256,
                stage_result="SKIPPED_ALREADY_COMPLETE",
                output_relative_dir=str(
                    Path(args.patient_id) / args.job_id
                ),
                completed_at=manifest.get("completed_at"),
            )

            print()
            print("PIPELINE: SKIPPED_ALREADY_COMPLETE")
            print(f"Final package: {final_dir}")
            return 0

        if not base_checkpoint.is_file():
            raise RuntimeError(
                f"Base checkpoint does not exist: {base_checkpoint}"
            )

        actual_base_sha256 = sha256_file(base_checkpoint)

        if actual_base_sha256 != expected_base_sha256:
            raise RuntimeError(
                "Base checkpoint SHA-256 mismatch. "
                f"Expected={expected_base_sha256}, "
                f"Actual={actual_base_sha256}"
            )

        checkpoint_root.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        export_dir.mkdir(parents=True, exist_ok=True)

        stage = "TRAINING"

        resume_checkpoint = latest_last_checkpoint(checkpoint_root)

        update_status(
            status_path,
            "TRAINING",
            message=(
                "Resuming training from the latest last.ckpt"
                if resume_checkpoint
                else "Starting training from the base warm-start checkpoint"
            ),
            input_sha256=input_sha256,
            pipeline_config_sha256=config_sha256,
            docker_image=docker_image,
            docker_image_id=docker_image_id,
            resume_checkpoint=(
                str(resume_checkpoint)
                if resume_checkpoint
                else None
            ),
        )

        training = config["training"]
        model = config["model"]

        train_command = [
            sys.executable,
            "-m",
            "piper.train",
            "fit",
            f"--trainer.accelerator={training['accelerator']}",
            f"--trainer.devices={training['devices']}",
            f"--trainer.precision={training['precision']}",
            f"--trainer.max_steps={training['max_steps']}",
            f"--trainer.default_root_dir={checkpoint_root}",
            (
                "--trainer.check_val_every_n_epoch="
                f"{training['check_val_every_n_epoch']}"
            ),
            (
                "--trainer.log_every_n_steps="
                f"{training['log_every_n_steps']}"
            ),
            (
                "--trainer.num_sanity_val_steps="
                f"{training['num_sanity_val_steps']}"
            ),
            f"--data.voice_name={model['voice_name']}",
            f"--data.csv_path={dataset_dir / 'metadata' / 'metadata.csv'}",
            f"--data.audio_dir={dataset_dir / 'wavs'}",
            f"--data.cache_dir={cache_dir}",
            f"--data.config_path={model_json}",
            f"--data.espeak_voice={model['espeak_voice']}",
            f"--data.batch_size={training['batch_size']}",
            f"--data.num_workers={training['num_workers']}",
            f"--data.validation_split={training['validation_split']}",
            f"--data.num_test_examples={training['num_test_examples']}",
            (
                "--data.trim_silence="
                f"{str(training['trim_silence']).lower()}"
            ),
            f"--model.sample_rate={model['sample_rate']}",
            f"--model.num_speakers={model['num_speakers']}",
            f"--model.use_mrd={str(model['use_mrd']).lower()}",
            f"--model.mos_metric={model['mos_metric']}",
            f"--model.warmstart_ckpt={base_checkpoint}",
        ]

        if resume_checkpoint:
            train_command.append(
                f"--ckpt_path={resume_checkpoint}"
            )

        run_logged(
            train_command,
            training_log,
            append=training_log.exists(),
        )

        trained_checkpoint = latest_last_checkpoint(checkpoint_root)

        if trained_checkpoint is None:
            raise RuntimeError(
                "Training exited successfully but no last.ckpt was found"
            )

        stage = "EXPORTING"

        update_status(
            status_path,
            "EXPORTING",
            message="Exporting the trained checkpoint to ONNX",
            trained_checkpoint=str(trained_checkpoint),
            input_sha256=input_sha256,
            pipeline_config_sha256=config_sha256,
        )

        if model_onnx.exists():
            model_onnx.unlink()

        run_logged(
            [
                sys.executable,
                "-m",
                "piper.train.export_onnx",
                "--checkpoint",
                str(trained_checkpoint),
                "--output-file",
                str(model_onnx),
            ],
            export_log,
        )

        if not model_json.is_file() or model_json.stat().st_size == 0:
            raise RuntimeError(
                f"Piper model configuration was not created: {model_json}"
            )

        stage = "VALIDATING_MODEL"

        update_status(
            status_path,
            "VALIDATING_MODEL",
            message="Checking ONNX and generating a real Korean test WAV",
            trained_checkpoint=str(trained_checkpoint),
            input_sha256=input_sha256,
            pipeline_config_sha256=config_sha256,
        )

        if test_wav.exists():
            test_wav.unlink()

        run_logged(
            [
                sys.executable,
                "-m",
                "piper",
                "-m",
                str(model_onnx),
                "-c",
                str(model_json),
                "-f",
                str(test_wav),
                "--",
                config["validation"]["test_text"],
            ],
            inference_log,
        )

        if not model_onnx.is_file() or model_onnx.stat().st_size == 0:
            raise RuntimeError("Exported ONNX file is missing or empty")

        with model_json.open("r", encoding="utf-8") as file:
            json.load(file)

        import onnx
        import soundfile as sf

        onnx.checker.check_model(str(model_onnx))

        wav_info = sf.info(str(test_wav))

        if wav_info.frames <= 0:
            raise RuntimeError("Generated test WAV contains no audio frames")

        if wav_info.samplerate != int(model["sample_rate"]):
            raise RuntimeError(
                f"Test WAV sample rate mismatch: {wav_info.samplerate}"
            )

        final_dir.parent.mkdir(parents=True, exist_ok=True)
        publishing_root.mkdir(parents=True, exist_ok=True)

        temporary_publish_dir = publishing_root / (
            f"{args.patient_id}--{args.job_id}--{uuid.uuid4().hex}"
        )
        temporary_publish_dir.mkdir(parents=True)

        artifact_sources = {
            "model.onnx": model_onnx,
            "model.onnx.json": model_json,
            "test.wav": test_wav,
            "training.log": training_log,
        }

        for target_name, source_path in artifact_sources.items():
            shutil.copy2(
                source_path,
                temporary_publish_dir / target_name,
            )

        artifacts = {}

        for name in artifact_sources:
            artifact_path = temporary_publish_dir / name
            artifacts[name] = {
                "size_bytes": artifact_path.stat().st_size,
                "sha256": sha256_file(artifact_path),
            }

        checkpoint_relative_path = str(
            trained_checkpoint.relative_to(job_dir)
        )

        manifest = {
            "schema_version": 1,
            "pipeline_version": config["pipeline_version"],
            "patient_id": args.patient_id,
            "job_id": args.job_id,
            "voice_name": model["voice_name"],
            "input_sha256": input_sha256,
            "pipeline_config_sha256": config_sha256,
            "docker_image": docker_image,
            "docker_image_id": docker_image_id,
            "piper": config["piper"],
            "base_checkpoint_sha256": actual_base_sha256,
            "trained_checkpoint": {
                "relative_path": checkpoint_relative_path,
                "size_bytes": trained_checkpoint.stat().st_size,
                "sha256": sha256_file(trained_checkpoint),
            },
            "training": training,
            "model": model,
            "test_text": config["validation"]["test_text"],
            "test_wav": {
                "sample_rate": wav_info.samplerate,
                "channels": wav_info.channels,
                "frames": wav_info.frames,
                "duration_seconds": wav_info.duration,
            },
            "artifacts": artifacts,
            "completed_at": utc_now(),
        }

        atomic_json(
            temporary_publish_dir / "manifest.json",
            manifest,
        )

        final_status = load_json(status_path)
        final_status.update(
            {
                "state": "COMPLETED",
                "message": "Training, export and model validation completed",
                "updated_at": utc_now(),
                "completed_at": manifest["completed_at"],
                "input_sha256": input_sha256,
                "pipeline_config_sha256": config_sha256,
                "trained_checkpoint": checkpoint_relative_path,
                "output_relative_dir": str(
                    Path(args.patient_id) / args.job_id
                ),
                "artifacts": artifacts,
            }
        )
        final_status.pop("error", None)
        final_status.pop("failed_stage", None)

        atomic_json(
            temporary_publish_dir / "status.json",
            final_status,
        )

        os.replace(temporary_publish_dir, final_dir)
        temporary_publish_dir = None

        atomic_json(status_path, final_status)

        print()
        print("PIPER VOICE TRAINING PIPELINE: COMPLETED")
        print(f"Final package: {final_dir}")
        print(f"Model: {final_dir / 'model.onnx'}")
        print(f"Configuration: {final_dir / 'model.onnx.json'}")
        print(f"Test WAV: {final_dir / 'test.wav'}")
        print(f"Manifest: {final_dir / 'manifest.json'}")
        return 0

    except Exception as error:
        if temporary_publish_dir and temporary_publish_dir.exists():
            shutil.rmtree(temporary_publish_dir)

        update_status(
            status_path,
            "FAILED",
            message=str(error),
            error=str(error),
            failed_stage=stage,
        )

        print(
            f"\nPIPELINE FAILED during {stage}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
