#!/bin/sh
set -eu

BASE=/data/ha_ai_fullcycle_20260911
CENTRAL_ENV=/data/profiles/0/appdata/com.atlas.app.pauseableatlas/home/ha.env
DEVICE_ENV=/var/lib/pauseable/ha.env
CENTRAL_UNIT=am.com.atlas.app.pauseableatlas.service
RUNNER=$BASE/src/run_repetitive_hybrid_demo.py
WASHER_RUNNER=$BASE/src/run_washer_hybrid_demo.py
PURIFIER_ACTUATOR=$BASE/src/turn_on_air_purifier.py
CENTRAL_OUTPUT_WATCH=$BASE/config/repetitive-central-output-watch.sh
CENTRAL_OUTPUT_FILTER=$BASE/config/repetitive-central-route-filter.awk
CENTRAL_OUTPUT_TIME_ROUTER=$BASE/config/repetitive-central-time-router.sh
CENTRAL_OUTPUT_UNIT=$BASE/config/pauseable-repetitive-central-output.service
BASELINE=$BASE/outputs/normal_demo_baseline_v2.json
LIFECYCLE=$BASE/outputs/fridge_ai_demo_lifecycle_20261004
WASHER_LIFECYCLE=$BASE/outputs/washer_ai_demo_lifecycle_20261005
TTS_CONTEXT=$BASE/scripts/tts_context.py
AIR_PURIFIER_TTS_GENERATOR=$BASE/scripts/generate-air-purifier-tts.sh
WASHER_TTS_GENERATOR=$BASE/scripts/generate-washer-youtube-tts.sh
AIR_PURIFIER_MESSAGE=$BASE/scripts/air-purifier-message.txt
WASHER_MESSAGE=$BASE/scripts/washer-youtube-message.txt

require_file() {
  if [ ! -s "$1" ]; then
    echo "Missing required file: $1" >&2
    exit 1
  fi
}

set_env_value() {
  key=$1
  value=$2
  if grep -q "^${key}=" "$CENTRAL_ENV"; then
    sed -i "s/^${key}=.*/${key}=${value}/" "$CENTRAL_ENV"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$CENTRAL_ENV"
  fi
}

require_file "$CENTRAL_ENV"
require_file "$DEVICE_ENV"
if ! grep -q '^PAUSEABLE_DEVICE_TOKEN=.' "$DEVICE_ENV"; then
  echo "PAUSEABLE_DEVICE_TOKEN is not configured in $DEVICE_ENV" >&2
  exit 1
fi
require_file "$RUNNER"
require_file "$WASHER_RUNNER"
require_file "$PURIFIER_ACTUATOR"
require_file "$CENTRAL_OUTPUT_WATCH"
require_file "$CENTRAL_OUTPUT_FILTER"
require_file "$CENTRAL_OUTPUT_TIME_ROUTER"
require_file "$CENTRAL_OUTPUT_UNIT"
require_file "$BASELINE"
require_file "$LIFECYCLE/active.json"
require_file "$WASHER_LIFECYCLE/active.json"
require_file "$TTS_CONTEXT"
require_file "$AIR_PURIFIER_TTS_GENERATOR"
require_file "$WASHER_TTS_GENERATOR"
require_file "$AIR_PURIFIER_MESSAGE"
require_file "$WASHER_MESSAGE"

for container in homeassistant ha-ai-full; do
  if ! docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -q '^true$'; then
    echo "Required container is not running: $container" >&2
    exit 1
  fi
done

systemctl stop pauseable-repetitive-central-output.service 2>/dev/null || true
systemctl stop pauseable-air-purifier-tts.path 2>/dev/null || true
systemctl stop pauseable-washer-youtube-tts.path 2>/dev/null || true

for pid in $(docker top ha-ai-full 2>/dev/null | awk '/[r]un_repetitive_hybrid_demo.py/ {print $2}'); do
  kill -TERM "$pid" 2>/dev/null || true
done
for pid in $(docker top ha-ai-full 2>/dev/null | awk '/[r]un_washer_hybrid_demo.py/ {print $2}'); do
  kill -TERM "$pid" 2>/dev/null || true
done

for pid in $(docker top ha-ai-full 2>/dev/null | awk '/[r]oute_repetitive_output.py/ {print $2}'); do
  kill -TERM "$pid" 2>/dev/null || true
done
sleep 2

cp "$BASE/config/pauseable-air-purifier-tts.service" /run/systemd/system/
cp "$BASE/config/pauseable-washer-youtube-tts.service" /run/systemd/system/
cp "$CENTRAL_OUTPUT_UNIT" /run/systemd/system/
chmod 0644 \
  /run/systemd/system/pauseable-air-purifier-tts.service \
  /run/systemd/system/pauseable-washer-youtube-tts.service \
  /run/systemd/system/pauseable-repetitive-central-output.service
rm -f \
  /run/systemd/system/pauseable-air-purifier-tts.path \
  /run/systemd/system/pauseable-washer-youtube-tts.path
mkdir -p "$BASE/outputs/repetitive-central-output-state"
chmod 0700 "$BASE/outputs/repetitive-central-output-state"

set_env_value AI_LOCAL_TTS_ENABLED 0
set_env_value PAUSEABLE_YOUTUBE_ENABLED 0
set_env_value DECISION_GATEWAY_ENABLED 1
set_env_value REPETITIVE_ACTIONS_ENABLED 1

systemctl daemon-reload
systemctl restart pauseable-youtube-control.service
systemctl restart "$CENTRAL_UNIT"
systemctl start pauseable-repetitive-central-output.service


rm -f "$BASE/src/route_repetitive_output.py"
printf '\n=== demo runner started ===\n' >> "$BASE/outputs/repetitive_hybrid_live.log"
docker exec -d ha-ai-full sh -c \
  'python -u /app/src/run_repetitive_hybrid_demo.py >> /app/outputs/repetitive_hybrid_live.log 2>&1'
printf '\n=== washer demo runner started ===\n' >> "$BASE/outputs/washer_hybrid_live.log"
docker exec -d ha-ai-full sh -c \
  'python -u /app/src/run_washer_hybrid_demo.py >> /app/outputs/washer_hybrid_live.log 2>&1'

sleep 5
systemctl is-active pauseable-repetitive-central-output.service
systemctl is-active pauseable-youtube-control.service
systemctl is-active "$CENTRAL_UNIT"
docker top ha-ai-full | grep '[r]un_repetitive_hybrid_demo.py'
docker top ha-ai-full | grep '[r]un_washer_hybrid_demo.py'
if docker top ha-ai-full | grep -q '[r]oute_repetitive_output.py'; then
  echo "Obsolete direct MQTT output router is still running" >&2
  exit 1
fi
if systemctl is-active --quiet pauseable-air-purifier-tts.path || \
   systemctl is-active --quiet pauseable-washer-youtube-tts.path; then
  echo "Obsolete direct trigger path is still active" >&2
  exit 1
fi
