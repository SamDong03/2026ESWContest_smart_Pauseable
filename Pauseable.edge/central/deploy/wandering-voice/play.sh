#!/bin/sh
set -eu

BASE=${PAUSEABLE_WANDERING_VOICE_BASE:-/data/pauseable/wandering-voice}
PIPER=/var/lib/pauseable/piper-guardian
MESSAGE=${1:-$BASE/message.txt}
TAG=${2:-guidance}
case "$TAG" in
    ''|*[!A-Za-z0-9_-]*) echo "Invalid audio tag: $TAG" >&2; exit 2 ;;
esac
test -r "$MESSAGE"
OUTPUT=${HOME:?}/pauseable-wandering-$TAG.wav
export LD_LIBRARY_PATH="$PIPER/lib:/usr/lib"
export PULSE_SERVER=unix:/run/pulse/native


"$PIPER/bin/piper" \
    --model "$PIPER/models/ko_KR-guardian-medium.onnx" \
    --config "$PIPER/models/ko_KR-guardian-medium.onnx.json" \
    --espeak_data "$PIPER/share/espeak-ng-data" \
    --length_scale 1.06 \
    --output_file "$OUTPUT" < "$MESSAGE"
"$PIPER/bin/paplay" "$OUTPUT"
