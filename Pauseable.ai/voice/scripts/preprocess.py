#!/usr/bin/env python3

import argparse
import csv
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf
import soxr


TARGET_SAMPLE_RATE = 22050


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def read_metadata(path: Path) -> list[tuple[str, str]]:
    rows = []

    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, raw_line in enumerate(file, start=1):
            line = raw_line.rstrip("\r\n")

            if "|" not in line:
                raise ValueError(
                    f"Line {line_number}: missing | delimiter"
                )

            wav_name, sentence = line.split("|", 1)
            wav_name = wav_name.strip()
            sentence = sentence.strip()

            if not wav_name or not sentence:
                raise ValueError(
                    f"Line {line_number}: empty filename or sentence"
                )

            rows.append((wav_name, sentence))

    duplicates = [
        name
        for name, count in Counter(name for name, _ in rows).items()
        if count > 1
    ]

    if duplicates:
        raise ValueError(f"Duplicate filenames: {duplicates}")

    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("/workspace/dataset"),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without creating converted files",
    )
    args = parser.parse_args()

    incoming_dir = args.root / "incoming"
    output_dir = args.root / "wavs"
    metadata_dir = args.root / "metadata"
    reports_dir = args.root / "reports"

    source_csv = metadata_dir / "recording_script.csv"
    output_csv = metadata_dir / "metadata.csv"

    rows = read_metadata(source_csv)
    expected_names = {name for name, _ in rows}
    actual_names = {
        path.name for path in incoming_dir.glob("*.wav")
    }

    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)

    if missing or extra:
        print("Missing WAV files:", missing)
        print("Extra WAV files:", extra)
        return 1

    reports = []
    failures = []

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
        reports_dir.mkdir(parents=True, exist_ok=True)

    for wav_name, sentence in rows:
        source_path = incoming_dir / wav_name
        destination_path = output_dir / wav_name
        temporary_path = output_dir / f".{wav_name}.tmp.wav"

        try:
            audio, sample_rate = sf.read(
                source_path,
                dtype="float32",
                always_2d=True,
            )

            if not np.isfinite(audio).all():
                raise ValueError("contains non-finite samples")

            source_channels = audio.shape[1]
            mono_audio = audio.mean(axis=1)

            peak = float(np.max(np.abs(mono_audio)))
            rms = float(np.sqrt(np.mean(np.square(mono_audio))))
            rms_dbfs = 20 * math.log10(max(rms, 1e-12))
            clipping_ratio = float(
                np.mean(np.abs(mono_audio) >= (32760 / 32768))
            )
            duration_seconds = len(mono_audio) / sample_rate

            if peak < 0.001:
                raise ValueError("silent or nearly silent")

            warning_messages = []

            if rms_dbfs < -35:
                warning_messages.append("low volume")

            if clipping_ratio > 0.001:
                warning_messages.append("possible clipping")

            if not 1.0 <= duration_seconds <= 15.0:
                warning_messages.append("unusual duration")

            output_sha256 = ""

            if not args.dry_run:
                converted = soxr.resample(
                    mono_audio,
                    sample_rate,
                    TARGET_SAMPLE_RATE,
                    quality="HQ",
                )

                sf.write(
                    temporary_path,
                    converted,
                    TARGET_SAMPLE_RATE,
                    subtype="PCM_16",
                    format="WAV",
                )

                converted_info = sf.info(temporary_path)

                if converted_info.samplerate != TARGET_SAMPLE_RATE:
                    raise ValueError("output sample rate verification failed")

                if converted_info.channels != 1:
                    raise ValueError("output channel verification failed")

                if converted_info.subtype != "PCM_16":
                    raise ValueError("output PCM verification failed")

                os.replace(temporary_path, destination_path)
                output_sha256 = sha256_file(destination_path)

            reports.append({
                "filename": wav_name,
                "sentence": sentence,
                "source_sample_rate": sample_rate,
                "source_channels": source_channels,
                "source_duration_seconds": round(duration_seconds, 4),
                "source_peak": round(peak, 6),
                "source_rms_dbfs": round(rms_dbfs, 3),
                "source_clipping_percent": round(
                    clipping_ratio * 100,
                    6,
                ),
                "source_sha256": sha256_file(source_path),
                "output_sample_rate": TARGET_SAMPLE_RATE,
                "output_sha256": output_sha256,
                "status": (
                    "WARN" if warning_messages else "PASS"
                ),
                "warnings": "; ".join(warning_messages),
            })

        except Exception as exc:
            failures.append((wav_name, str(exc)))

            if temporary_path.exists():
                temporary_path.unlink()

    print("Input files:", len(rows))
    print("Validated files:", len(reports))
    print("Failures:", len(failures))

    for wav_name, reason in failures:
        print(f"FAIL {wav_name}: {reason}")

    if failures:
        return 1

    if args.dry_run:
        print("PREPROCESS DRY RUN: PASS")
        return 0

    metadata_text = "".join(
        f"{wav_name}|{sentence}\n"
        for wav_name, sentence in rows
    )
    output_csv.write_text(metadata_text, encoding="utf-8")

    json_path = reports_dir / "preprocess_report.json"
    json_path.write_text(
        json.dumps(reports, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = reports_dir / "preprocess_report.csv"

    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(reports[0].keys()),
        )
        writer.writeheader()
        writer.writerows(reports)

    print("Converted files:", len(reports))
    print("Metadata:", output_csv)
    print("JSON report:", json_path)
    print("CSV report:", csv_path)
    print("PREPROCESS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
