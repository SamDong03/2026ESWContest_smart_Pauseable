#!/bin/sh
set -eu

LAUNCH_MARKER=/run/pauseable-youtube-launch.once
BOOTSTRAP_MARKER=/run/pauseable-repetitive-demo-bootstrap.started
DEMO_START=/data/ha_ai_fullcycle_20260911/scripts/start-repetitive-demo.sh
DEMO_LOG=/data/ha_ai_fullcycle_20260911/outputs/repetitive-demo-bootstrap.log


if [ ! -e "$BOOTSTRAP_MARKER" ]; then
    : > "$BOOTSTRAP_MARKER"
    (
        attempts=0
        while [ "$attempts" -lt 60 ]; do
            if [ -x "$DEMO_START" ] && "$DEMO_START"; then
                printf 'DEMO_BOOTSTRAP_READY\n'
                exit 0
            fi
            attempts=$((attempts + 1))
            sleep 10
        done
        printf 'DEMO_BOOTSTRAP_FAILED\n' >&2
        exit 1
    ) >> "$DEMO_LOG" 2>&1 &
fi


if [ ! -f "$LAUNCH_MARKER" ]; then
    printf 'YOUTUBE_BROWSER_IDLE: waiting for an explicit playback request\n'
    exec sleep infinity
fi
rm -f "$LAUNCH_MARKER"

test -S /run/xdg/wayland-0
test -S /run/pulse/native
test -r /var/lib/pauseable/youtube/chromium-seccomp.json

PAUSEABLE_BRIDGE_UNIT=am.com.atlas.app.pauseableyoutubebridge.service

if ! systemctl is-active --quiet "$PAUSEABLE_BRIDGE_UNIT"; then
    if [ "$(systemctl show "$PAUSEABLE_BRIDGE_UNIT" -p LoadState --value)" = loaded ]; then
        systemctl start "$PAUSEABLE_BRIDGE_UNIT"
    else
        abusctl call com.atlas.AppManager1 Start com.atlas.app.pauseableyoutubebridge
    fi
fi

systemctl is-active --quiet "$PAUSEABLE_BRIDGE_UNIT"

exec /usr/bin/docker -H unix:///run/docker.sock run --rm \
    --name pauseable-youtube-bridge \
    --security-opt apparmor=unconfined \
    --security-opt seccomp=/var/lib/pauseable/youtube/chromium-seccomp.json \
    --user 1004:1004 \
    --network host \
    --shm-size 256m \
    -e HOME=/home/pauseable-browser \
    -e XDG_RUNTIME_DIR=/run/xdg \
    -e WAYLAND_DISPLAY=wayland-0 \
    -e PULSE_SERVER=unix:/run/pulse/native \
    --mount type=bind,src=/run/xdg,dst=/run/xdg,readonly \
    --mount type=bind,src=/run/pulse,dst=/run/pulse,readonly \
    pauseable-youtube:1 \
    chromium \
    --ozone-platform=wayland \
    --no-first-run \
    --disable-gpu \
    --user-data-dir=/tmp/pauseable-bridge-profile \
    --class=com.atlas.app.pauseableyoutubebridge \
    --autoplay-policy=no-user-gesture-required \
    about:blank
