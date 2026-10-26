#!/bin/sh
set -eu

APP_DIR=${APP_DIR:-/data/ha_ai}
IMAGE=${HA_AI_IMAGE:-ha-ai-runner:pi}
ENV_FILE=${HA_AI_ENV_FILE:-$APP_DIR/deploy/systemd/ha-ai.env}
DOCKER=${DOCKER:-docker}

cd "$APP_DIR"

if ! $DOCKER info >/dev/null 2>&1; then
  echo "[runner] starting dockerd"
  dockerd >/tmp/dockerd.log 2>&1 &
  i=0
  until $DOCKER info >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
      echo "[runner] docker daemon did not become ready" >&2
      exit 1
    fi
    sleep 1
  done
fi

$DOCKER start homeassistant >/dev/null 2>&1 || true
$DOCKER start mosquitto >/dev/null 2>&1 || true

if [ "$#" -eq 0 ]; then
  set -- python src/run_ha_automation_loop.py
elif [ "$1" != "python" ] && [ "$1" != "sh" ]; then
  set -- python src/run_ha_automation_loop.py "$@"
fi

cleanup_named_container() {
  if [ -n "${HA_AI_CONTAINER_NAME:-}" ]; then
    $DOCKER rm -f "$HA_AI_CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
}

if [ -n "${HA_AI_CONTAINER_NAME:-}" ]; then
  cleanup_named_container
  trap cleanup_named_container INT TERM EXIT
  $DOCKER run --rm \
    --name "$HA_AI_CONTAINER_NAME" \
    --network host \
    --security-opt apparmor=unconfined \
    --env-file "$ENV_FILE" \
    -v "$APP_DIR":/app \
    -w /app \
    "$IMAGE" "$@"
else
  $DOCKER run --rm \
    --network host \
    --security-opt apparmor=unconfined \
    --env-file "$ENV_FILE" \
    -v "$APP_DIR":/app \
    -w /app \
    "$IMAGE" "$@"
fi
