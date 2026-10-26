#!/bin/sh
set -eu

BROKER_CONTAINER="${BROKER_CONTAINER:-mosquitto}"
BROKER_HOST="${MQTT_HOST:-127.0.0.1}"
BROKER_PORT="${MQTT_PORT:-1883}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
REPETITIVE_ID="evt-central-test-repetitive-${STAMP}"
WANDERING_ID="evt-central-test-wandering-${STAMP}"

publish() {
    topic="$1"
    payload="$2"
    docker exec "$BROKER_CONTAINER" mosquitto_pub \
        -h "$BROKER_HOST" -p "$BROKER_PORT" -q 1 \
        -t "$topic" -m "$payload"
}

repetitive_payload="$(printf '%s' \
    "{\"contract_version\":\"1.0\",\"event_id\":\"${REPETITIVE_ID}\",\"occurred_at\":\"${NOW}\",\"patient_id\":\"byunwoojin\",\"device_id\":\"pi5-home-01\",\"source\":\"repetitive-ai\",\"behavior\":\"normal\",\"risk_level\":\"normal\",\"risk_score\":0,\"model_version\":\"integration-test-v1\",\"inference_status\":\"ok\",\"evidence\":{\"window_seconds\":600,\"observation_count\":1,\"pattern_code\":\"integration_test\",\"model_status\":\"test_only\"}}")"

wandering_payload="$(printf '%s' \
    "{\"contract_version\":\"1.0\",\"event_id\":\"${WANDERING_ID}\",\"occurred_at\":\"${NOW}\",\"patient_id\":\"byunwoojin\",\"device_id\":\"pi5-home-01\",\"source\":\"wandering-ai\",\"behavior\":\"normal\",\"risk_level\":\"normal\",\"risk_score\":0,\"model_version\":\"integration-test-v1\",\"inference_status\":\"ok\",\"evidence\":{\"window_seconds\":90,\"observation_count\":3,\"pattern_code\":\"no_current_rule_flag\",\"model_status\":\"research_review_only\"}}")"

conflict_payload="$(printf '%s' \
    "{\"contract_version\":\"1.0\",\"event_id\":\"${REPETITIVE_ID}\",\"occurred_at\":\"${NOW}\",\"patient_id\":\"byunwoojin\",\"device_id\":\"pi5-home-01\",\"source\":\"repetitive-ai\",\"behavior\":\"normal\",\"risk_level\":\"normal\",\"risk_score\":1,\"model_version\":\"integration-test-v1\",\"inference_status\":\"ok\"}")"

stale_payload="$(printf '%s' \
    "{\"contract_version\":\"1.0\",\"event_id\":\"evt-central-test-stale-${STAMP}\",\"occurred_at\":\"2000-01-01T00:00:00Z\",\"patient_id\":\"byunwoojin\",\"device_id\":\"pi5-home-01\",\"source\":\"repetitive-ai\",\"behavior\":\"normal\",\"risk_level\":\"normal\",\"risk_score\":0,\"inference_status\":\"ok\"}")"

echo "[1/6] valid repetitive event: $REPETITIVE_ID"
publish "pauseable/ai/repetitive/decision" "$repetitive_payload"

echo "[2/6] valid wandering event: $WANDERING_ID"
publish "pauseable/ai/wandering/decision" "$wandering_payload"

echo "[3/6] duplicate repetitive event"
publish "pauseable/ai/repetitive/decision" "$repetitive_payload"

echo "[4/6] conflicting payload with the same event_id"
publish "pauseable/ai/repetitive/decision" "$conflict_payload"

echo "[5/6] stale event"
publish "pauseable/ai/repetitive/decision" "$stale_payload"

echo "[6/6] malformed event"
publish "pauseable/ai/repetitive/decision" '{"contract_version":"1.0"}'

echo "Published all cases. Expected Central log markers:"
echo "  CENTRAL_DECISION_ACCEPTED (2)"
echo "  MQTT_DECISION_DUPLICATE (1)"
echo "  MQTT_DECISION_CONFLICT (1)"
echo "  MQTT_DECISION_REJECTED (2)"

if [ "${VERIFY_RESTART:-0}" = "1" ]; then
    echo "[restart] restarting Central through AppManager"
    abusctl call com.atlas.AppManager1 Stop com.atlas.app.pauseableatlas
    sleep 3
    abusctl call com.atlas.AppManager1 Start com.atlas.app.pauseableatlas
    sleep 6

    echo "[restart] publishing the original repetitive event again"
    publish "pauseable/ai/repetitive/decision" "$repetitive_payload"
    sleep 2
    echo "Expected one additional MQTT_DECISION_DUPLICATE after restart."
fi
