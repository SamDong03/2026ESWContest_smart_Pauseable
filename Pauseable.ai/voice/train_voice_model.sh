#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  echo "Usage:"
  echo "  $0 --patient-id ID --job-id ID --dataset-dir DIR --output-dir DIR [--clip-count 160..240]"
}

PATIENT_ID=""
JOB_ID=""
DATASET_DIR=""
OUTPUT_DIR=""
CLIP_COUNT="160"

while (($# > 0)); do
  case "$1" in
    --patient-id)
      PATIENT_ID="${2:?Missing value for --patient-id}"
      shift 2
      ;;
    --job-id)
      JOB_ID="${2:?Missing value for --job-id}"
      shift 2
      ;;
    --dataset-dir)
      DATASET_DIR="${2:?Missing value for --dataset-dir}"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="${2:?Missing value for --output-dir}"
      shift 2
      ;;
    --clip-count)
      CLIP_COUNT="${2:?Missing value for --clip-count}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$PATIENT_ID" || -z "$JOB_ID" ||
      -z "$DATASET_DIR" || -z "$OUTPUT_DIR" ]]; then
  echo "ERROR: All four options are required." >&2
  usage >&2
  exit 2
fi

if [[ ! "$CLIP_COUNT" =~ ^[0-9]+$ ]] ||
   ((CLIP_COUNT < 160 || CLIP_COUNT > 240)); then
  echo "ERROR: --clip-count must be between 160 and 240." >&2
  exit 2
fi

SCRIPT_DIR="$(
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
  pwd
)"
cd "$SCRIPT_DIR"

if [[ ! -d "$DATASET_DIR" ]]; then
  echo "ERROR: Dataset directory does not exist: $DATASET_DIR" >&2
  exit 1
fi

DATASET_DIR="$(realpath "$DATASET_DIR")"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(realpath "$OUTPUT_DIR")"

CONFIG_PATH="$SCRIPT_DIR/configs/guardian-medium-v1.json"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "ERROR: Pipeline configuration is missing: $CONFIG_PATH" >&2
  exit 1
fi

IMAGE_NAME="$(
  python3 -c '
import json
with open("configs/guardian-medium-v1.json", encoding="utf-8") as file:
    print(json.load(file)["docker_image"])
'
)"

IMAGE_ID="$(
  docker image inspect "$IMAGE_NAME" --format '{{.Id}}'
)"

LOCAL_UID="$(id -u)"
LOCAL_GID="$(id -g)"

echo "Patient ID:  $PATIENT_ID"
echo "Job ID:      $JOB_ID"
echo "Dataset:     $DATASET_DIR"
echo "Output root: $OUTPUT_DIR"
echo "Clip count:  $CLIP_COUNT"
echo "Docker image: $IMAGE_NAME"
echo "Docker image ID: $IMAGE_ID"
echo
echo "Starting the Piper voice-training pipeline..."

exec env \
  LOCAL_UID="$LOCAL_UID" \
  LOCAL_GID="$LOCAL_GID" \
  docker compose \
    -f compose.yaml \
    -f compose.pipeline.yaml \
    run --rm -T --no-deps \
    -e PIPELINE_DOCKER_IMAGE="$IMAGE_NAME" \
    -e PIPELINE_DOCKER_IMAGE_ID="$IMAGE_ID" \
    -v "$DATASET_DIR:/job/input:ro" \
    -v "$OUTPUT_DIR:/job/output" \
    trainer \
    python /workspace/pipeline/run_pipeline.py \
      --patient-id "$PATIENT_ID" \
      --job-id "$JOB_ID" \
      --input-dir /job/input \
      --output-dir /job/output \
      --clip-count "$CLIP_COUNT" \
      --config /workspace/configs/guardian-medium-v1.json
