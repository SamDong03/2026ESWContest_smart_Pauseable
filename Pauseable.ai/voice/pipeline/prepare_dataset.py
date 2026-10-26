#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


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


def update_hash_from_file(hasher, path):
    with path.open("rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)


def parse_metadata(metadata_path):
    rows = []

    text = metadata_path.read_text(encoding="utf-8-sig")

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if not line:
            continue

        if "|" not in line:
            raise ValueError(
                f"Metadata line {line_number} does not contain '|': {line!r}"
            )

        wav_name, sentence = line.split("|", 1)
        wav_name = wav_name.strip()
        sentence = sentence.strip()

        if not wav_name:
            raise ValueError(
                f"Metadata line {line_number} has an empty WAV filename"
            )

        if not sentence:
            raise ValueError(
                f"Metadata line {line_number} has an empty sentence"
            )

        rows.append((wav_name, sentence))

    return rows


def expected_names_for_config(dataset_config, clip_count=None):
    expected_count = (
        clip_count
        if clip_count is not None
        else int(dataset_config["expected_utterances"])
    )
    if not 160 <= expected_count <= 240:
        raise ValueError("Clip count must be between 160 and 240")
    prefix = dataset_config["filename_prefix"]
    digits = int(dataset_config["filename_digits"])
    first_number = int(dataset_config["first_number"])
    last_number = (
        first_number + expected_count - 1
        if clip_count is not None
        else int(dataset_config["last_number"])
    )
    names = [
        f"{prefix}{number:0{digits}d}.wav"
        for number in range(first_number, last_number + 1)
    ]
    if len(names) != expected_count:
        raise ValueError("Filename range does not match clip count")
    return names


def calculate_input_fingerprint(metadata_path, wav_by_name, expected_names):
    hasher = hashlib.sha256()

    hasher.update(b"recording_script.csv\0")
    update_hash_from_file(hasher, metadata_path)

    for wav_name in expected_names:
        hasher.update(b"\0wav\0")
        hasher.update(wav_name.encode("utf-8"))
        hasher.update(b"\0")
        update_hash_from_file(hasher, wav_by_name[wav_name])

    return hasher.hexdigest()


def run_logged(command, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with log_path.open("w", encoding="utf-8", newline="\n") as log_file:
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

    if exit_code != 0:
        raise RuntimeError(
            f"Command failed with exit code {exit_code}: {' '.join(command)}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Validate and preprocess one Piper voice-training dataset"
    )
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--clip-count", type=int)
    parser.add_argument(
        "--config",
        default="/workspace/configs/guardian-medium-v1.json",
    )
    args = parser.parse_args()

    for label, value in (
        ("patient-id", args.patient_id),
        ("job-id", args.job_id),
    ):
        if not ID_PATTERN.fullmatch(value):
            raise SystemExit(
                f"ERROR: {label} must contain only letters, numbers, '.', '_' or '-' "
                f"and must be 1-64 characters long: {value!r}"
            )

    input_root = Path(args.input_dir).resolve(strict=True)
    output_root = Path(args.output_dir).resolve(strict=True)
    config_path = Path(args.config).resolve(strict=True)

    if not input_root.is_dir():
        raise SystemExit(f"ERROR: Input directory is not a directory: {input_root}")

    config = load_json(config_path)
    dataset_config = config["dataset"]

    expected_count = (
        args.clip_count
        if args.clip_count is not None
        else int(dataset_config["expected_utterances"])
    )
    metadata_filename = dataset_config["metadata_filename"]
    try:
        expected_names = expected_names_for_config(dataset_config, args.clip_count)
    except ValueError as error:
        parser.error(str(error))

    job_dir = output_root / ".jobs" / args.patient_id / args.job_id
    work_dir = job_dir / "work"
    dataset_dir = work_dir / "dataset"
    status_path = job_dir / "status.json"
    input_manifest_path = job_dir / "input_manifest.json"
    preprocess_log_path = job_dir / "preprocess.log"

    job_dir.mkdir(parents=True, exist_ok=True)

    previous_status = load_json(status_path)
    created_at = previous_status.get("created_at", utc_now())

    def write_status(state, **extra):
        status = {
            "schema_version": 1,
            "patient_id": args.patient_id,
            "job_id": args.job_id,
            "state": state,
            "created_at": created_at,
            "updated_at": utc_now(),
        }
        status.update(extra)
        atomic_json(status_path, status)

    write_status(
        "VALIDATING",
        message="Validating the original input dataset",
        preprocessing_complete=False,
    )

    try:
        metadata_candidates = sorted(
            path
            for path in input_root.rglob(metadata_filename)
            if path.is_file()
        )

        if len(metadata_candidates) != 1:
            raise ValueError(
                f"Expected exactly one {metadata_filename}, "
                f"found {len(metadata_candidates)}: {metadata_candidates}"
            )

        metadata_path = metadata_candidates[0]

        wav_paths = sorted(
            path
            for path in input_root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".wav"
        )

        wav_by_name = {}

        for wav_path in wav_paths:
            if wav_path.name in wav_by_name:
                raise ValueError(
                    f"Duplicate WAV filename found in different directories: "
                    f"{wav_path.name}"
                )
            wav_by_name[wav_path.name] = wav_path

        actual_names = set(wav_by_name)
        expected_name_set = set(expected_names)

        missing_names = sorted(expected_name_set - actual_names)
        extra_names = sorted(actual_names - expected_name_set)

        if missing_names or extra_names:
            raise ValueError(
                f"WAV filename mismatch. Missing={missing_names}, Extra={extra_names}"
            )

        rows = parse_metadata(metadata_path)
        row_names = [wav_name for wav_name, _ in rows]

        if len(rows) != expected_count:
            raise ValueError(
                f"Expected {expected_count} metadata rows, found {len(rows)}"
            )

        if len(set(row_names)) != len(row_names):
            duplicates = sorted(
                {
                    name
                    for name in row_names
                    if row_names.count(name) > 1
                }
            )
            raise ValueError(f"Duplicate metadata WAV names: {duplicates}")

        if row_names != expected_names:
            raise ValueError(
                "Metadata rows must be ordered exactly from "
                f"{expected_names[0]} through {expected_names[-1]}"
            )

        input_sha256 = calculate_input_fingerprint(
            metadata_path,
            wav_by_name,
            expected_names,
        )

        previous_sha256 = previous_status.get("input_sha256")

        if previous_sha256 and previous_sha256 != input_sha256:
            raise ValueError(
                "This patient-id/job-id was already used with different input data. "
                f"Previous={previous_sha256}, Current={input_sha256}"
            )

        if (
            previous_status.get("preprocessing_complete") is True
            and previous_sha256 == input_sha256
            and (dataset_dir / "metadata" / "metadata.csv").is_file()
            and len(list((dataset_dir / "wavs").glob("*.wav"))) == expected_count
        ):
            write_status(
                "PREPROCESSING",
                message="Preprocessing already completed; safe idempotent skip",
                input_sha256=input_sha256,
                preprocessing_complete=True,
                stage_result="SKIPPED_ALREADY_COMPLETE",
                next_state="TRAINING",
            )

            print("Input validation: PASS")
            print("Preprocessing: SKIPPED_ALREADY_COMPLETE")
            print(f"Input SHA-256: {input_sha256}")
            print(f"Job directory: {job_dir}")
            return

        write_status(
            "PREPROCESSING",
            message="Copying and normalizing the validated dataset",
            input_sha256=input_sha256,
            preprocessing_complete=False,
        )

        if dataset_dir.exists():
            shutil.rmtree(dataset_dir)

        incoming_dir = dataset_dir / "incoming"
        metadata_dir = dataset_dir / "metadata"

        incoming_dir.mkdir(parents=True, exist_ok=True)
        metadata_dir.mkdir(parents=True, exist_ok=True)

        shutil.copyfile(
            metadata_path,
            metadata_dir / metadata_filename,
        )

        for wav_name in expected_names:
            shutil.copyfile(
                wav_by_name[wav_name],
                incoming_dir / wav_name,
            )

        input_manifest = {
            "schema_version": 1,
            "patient_id": args.patient_id,
            "job_id": args.job_id,
            "input_sha256": input_sha256,
            "metadata_source": str(metadata_path),
            "wav_count": len(wav_paths),
            "metadata_rows": len(rows),
            "expected_names": expected_names,
            "validated_at": utc_now(),
        }
        atomic_json(input_manifest_path, input_manifest)

        run_logged(
            [
                sys.executable,
                "/workspace/scripts/preprocess.py",
                "--root",
                str(dataset_dir),
            ],
            preprocess_log_path,
        )

        normalized_wavs = sorted((dataset_dir / "wavs").glob("*.wav"))
        generated_metadata = dataset_dir / "metadata" / "metadata.csv"

        if len(normalized_wavs) != expected_count:
            raise ValueError(
                f"Expected {expected_count} normalized WAV files, "
                f"found {len(normalized_wavs)}"
            )

        if not generated_metadata.is_file() or generated_metadata.stat().st_size == 0:
            raise ValueError(
                f"Generated metadata is missing or empty: {generated_metadata}"
            )

        write_status(
            "PREPROCESSING",
            message="Dataset preprocessing completed successfully",
            input_sha256=input_sha256,
            preprocessing_complete=True,
            stage_result="COMPLETED",
            next_state="TRAINING",
            normalized_wav_count=len(normalized_wavs),
            dataset_dir=str(dataset_dir),
            preprocess_log=str(preprocess_log_path),
        )

        print()
        print("AUTOMATED DATASET PREPARATION: PASS")
        print(f"Input SHA-256: {input_sha256}")
        print(f"Normalized WAV files: {len(normalized_wavs)}")
        print(f"Job directory: {job_dir}")
        print(f"Status file: {status_path}")

    except Exception as error:
        write_status(
            "FAILED",
            message=str(error),
            failed_stage="VALIDATING_OR_PREPROCESSING",
            preprocessing_complete=previous_status.get(
                "preprocessing_complete",
                False,
            ),
        )
        raise


if __name__ == "__main__":
    main()
