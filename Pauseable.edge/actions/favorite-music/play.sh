#!/bin/sh
set -eu
BASE=/data/pauseable/favorite-music
STATE=/data/pauseable/favorite-music-state
DEVICE_ENV=/var/lib/pauseable/ha.env
FIFO=/run/pauseable-youtube-request.fifo

test -r "$DEVICE_ENV"
test -r "$BASE/player.env"
test -r "$BASE/player.py"
set -- run --rm --pull=never --name pauseable-favorite-music-runner --network host --user 0:0 \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
    --env-file "$DEVICE_ENV" --env-file "$BASE/player.env" \
    --env PYTHONDONTWRITEBYTECODE=1 --env PAUSEABLE_MUSIC_STATE_DIR=/state \
    --mount "type=bind,src=$BASE,dst=/app,readonly" \
    --mount "type=bind,src=$STATE,dst=/state"
test -p "$FIFO"
set -- "$@" --mount "type=bind,src=$FIFO,dst=$FIFO"
exec /usr/bin/docker "$@" --entrypoint python3 ha-ai-runner:review-20260908 /app/player.py
