#!/bin/sh
set -eu

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
    --tmpfs /home/pauseable-browser:uid=1004,gid=1004,mode=0700 \
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
