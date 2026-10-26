#!/bin/sh
set -eu

PREFIX=${1:-repetitive_publish_once}

INPUT=${INPUT:-data/raw/abnormal_events_test.csv}
BASELINE=${BASELINE:-outputs/normal_demo_baseline_v2.json}

if [ -n "${SCHEMA:-}" ]; then
  SCHEMA_PATH=$SCHEMA
elif [ -f "Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json" ]; then
  SCHEMA_PATH="Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json"
elif [ -f "../../Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json" ]; then
  SCHEMA_PATH="../../Pauseable.contracts/communication-v1/schemas/behavior-inference.schema.json"
else
  SCHEMA_PATH="deploy/contracts/behavior-inference.schema.json"
fi

MQTT_HOST=${MQTT_HOST:-127.0.0.1}
MQTT_PORT=${MQTT_PORT:-1883}

echo "[1/4] Run HA repetitive pipeline"
python src/run_ha_pipeline.py \
  --input "$INPUT" \
  --baseline "$BASELINE" \
  --prefix "$PREFIX" \
  --data-source synthetic \
  --no-autoencoder

echo "[2/4] Export MQTT payload"
python src/export_repetitive_mqtt_payload.py \
  --episode-summary "outputs/${PREFIX}_episode_summary.csv" \
  --output "outputs/${PREFIX}_repetitive_mqtt_payloads.jsonl"

echo "[3/4] Validate MQTT payload"
python src/validate_repetitive_mqtt_payload.py \
  --schema "$SCHEMA_PATH" \
  --input "outputs/${PREFIX}_repetitive_mqtt_payloads.jsonl"

echo "[4/4] Publish MQTT payload"
python src/publish_repetitive_mqtt.py \
  --input "outputs/${PREFIX}_repetitive_mqtt_payloads.jsonl" \
  --host "$MQTT_HOST" \
  --port "$MQTT_PORT"

echo "done: $PREFIX"
