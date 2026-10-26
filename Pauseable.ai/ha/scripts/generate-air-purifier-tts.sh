#!/bin/sh
set -eu

PIPER_ROOT=/var/lib/pauseable/piper-guardian
CURRENT_JSON=$PIPER_ROOT/model-releases/current.json
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEVICE_ENV=/var/lib/pauseable/ha.env
TTS_IMAGE=ha-ai-runner:review-20260908
TEMPLATE=$SCRIPT_DIR/air-purifier-message.txt
MESSAGE_FILE=$(mktemp /run/pauseable-air-purifier-message.XXXXXX)
trap 'rm -f "$MESSAGE_FILE"' EXIT HUP INT TERM
MODEL_ID=$(sed -n 's/.*"model_id": "\([^"]*\)".*/\1/p' "$CURRENT_JSON")

if [ -z "$MODEL_ID" ]; then
  echo "Could not read model_id from $CURRENT_JSON" >&2
  exit 1
fi

MODEL=$PIPER_ROOT/model-releases/releases/$MODEL_ID/ko_KR-guardian-medium.onnx
OUTPUT=/data/profiles/0/appdata/com.atlas.app.pauseableatlas/home/pauseable-air-purifier-tts.wav

if ! docker run --rm \
  --network host \
  --security-opt apparmor=unconfined \
  --env-file "$DEVICE_ENV" \
  -v "$SCRIPT_DIR:/tts:ro" \
  "$TTS_IMAGE" \
  python /tts/tts_context.py --template /tts/air-purifier-message.txt \
  > "$MESSAGE_FILE"; then
  echo "Render TTS context unavailable; using the local fallback" >&2
  sed 's/{{patient_call_name}}/할머니/g' "$TEMPLATE" > "$MESSAGE_FILE"
fi

LD_LIBRARY_PATH=$PIPER_ROOT/lib \
  "$PIPER_ROOT/bin/piper" \
  --model "$MODEL" \
  --config "$MODEL.json" \
  --espeak_data "$PIPER_ROOT/share/espeak-ng-data" \
  --output_file "$OUTPUT" \
  < "$MESSAGE_FILE"

chown 5017:5017 "$OUTPUT"
chmod 0644 "$OUTPUT"
echo "Generated: $OUTPUT"
