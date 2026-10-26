#!/bin/sh
set -eu

FIFO=/run/pauseable-youtube-request.fifo
LAUNCH_MARKER=/run/pauseable-youtube-launch.once
URL_FILE=/var/lib/pauseable/youtube/washer-favorite-url.txt
DEFAULT_URL='https://www.youtube.com/watch?v=SUIM5wHIU7o&autoplay=1'

if [ ! -p "$FIFO" ]; then
    printf 'YOUTUBE_CONTROL_ERROR: FIFO unavailable\n' >&2
    exit 1
fi

start_browser() {
    : > "$LAUNCH_MARKER"
    systemctl restart pauseable-youtube-browser.service
    attempts=0
    while [ "$attempts" -lt 30 ]; do
        if /usr/bin/docker -H unix:///run/docker.sock inspect \
            -f '{{.State.Running}}' pauseable-youtube-bridge 2>/dev/null | grep -q '^true$'; then
            return 0
        fi
        attempts=$((attempts + 1))
        sleep 1
    done
    printf 'YOUTUBE_BROWSER_START_TIMEOUT\n' >&2
    return 1
}

play_favorite() {
    url=$DEFAULT_URL
    if [ -s "$URL_FILE" ]; then
        url=$(head -n 1 "$URL_FILE" | tr -d '\r\n')
    fi
    case "$url" in
        https://www.youtube.com/*|https://youtube.com/*|https://youtu.be/*) ;;
        *)
            printf 'YOUTUBE_URL_REJECTED\n' >&2
            return 1
            ;;
    esac

    start_browser
    if /usr/bin/docker -H unix:///run/docker.sock exec \
        --user 1004:1004 \
        pauseable-youtube-bridge \
        chromium \
        --user-data-dir=/tmp/pauseable-bridge-profile \
        "$url"
    then
        printf 'YOUTUBE_OPEN_REQUEST_SENT\n'
    else
        printf 'YOUTUBE_OPEN_REQUEST_FAILED\n' >&2
        return 1
    fi
}

exec 3<>"$FIFO"
printf 'YOUTUBE_CONTROL_READY\n'

while IFS= read -r request <&3; do
    case "$request" in
        PLAY_WASHER_FAVORITE|PLAY_TROT)
            play_favorite
            ;;
        STOP_YOUTUBE)
            systemctl stop pauseable-youtube-browser.service
            printf 'YOUTUBE_STOPPED\n'
            ;;
        *)
            printf 'YOUTUBE_REQUEST_REJECTED\n' >&2
            ;;
    esac
done
