#!/bin/sh
set -eu

exec python /app/src/run_repetitive_mqtt_stream.py \
  --raw-output "${RAW_OUTPUT:-data/raw/repetitive_live_events.csv}" \
  --baseline "${BASELINE:-outputs/normal_demo_baseline_v2.json}" \
  --prefix "${PREFIX:-repetitive_live}" \
  --schema "${SCHEMA:-/app/deploy/contracts/behavior-inference.schema.json}" \
  --state-file "${STATE_FILE:-outputs/repetitive_mqtt_stream_state.json}" \
  --interval-seconds "${INTERVAL_SECONDS:-30}" \
  --mqtt-host "${MQTT_HOST:-127.0.0.1}" \
  --mqtt-port "${MQTT_PORT:-1883}" \
  --write-initial-snapshot \
  "$@"
