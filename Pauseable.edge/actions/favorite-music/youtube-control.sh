#!/bin/sh
# Canonical FIFO controller shared by the HA and edge deployment entrypoints.
set -eu

FIFO=/run/pauseable-youtube-request.fifo
LAUNCH_MARKER=/run/pauseable-youtube-launch.once
MUSIC_REQUEST=/data/pauseable/favorite-music/request.sh

if [ ! -p "$FIFO" ]; then
    printf 'YOUTUBE_CONTROL_ERROR: FIFO unavailable\n' >&2
    exit 1
fi

start_browser() {
    : > "$LAUNCH_MARKER"
    systemctl restart pauseable-youtube-browser.service || return 1
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

play_video() {
    video_id=$1
    case "$video_id" in
        ''|*[!A-Za-z0-9_-]*)
            printf 'YOUTUBE_VIDEO_ID_REJECTED\n' >&2
            return 1
            ;;
    esac
    if [ "${#video_id}" -ne 11 ]; then
        printf 'YOUTUBE_VIDEO_ID_REJECTED\n' >&2
        return 1
    fi
    url="https://www.youtube.com/watch?v=$video_id&autoplay=1"

    start_browser || return 1
    if /usr/bin/docker -H unix:///run/docker.sock exec \
        --user 1004:1004 \
        pauseable-youtube-bridge \
        chromium \
        --user-data-dir=/tmp/pauseable-bridge-profile \
        "$url"
    then
        printf 'YOUTUBE_OPEN_REQUEST_SENT video_id=%s\n' "$video_id"
    else
        printf 'YOUTUBE_OPEN_REQUEST_FAILED\n' >&2
        return 1
    fi
}

exec 3<>"$FIFO"
printf 'YOUTUBE_CONTROL_READY\n'

while IFS= read -r request <&3; do
    case "$request" in
        PLAY_FAVORITE|PLAY_WASHER_FAVORITE|PLAY_TROT)
            # Legacy requests now use the SAME Render-backed selector. Do not
            # silently play a hardcoded or stale local-file song.
            if [ -r "$MUSIC_REQUEST" ]; then
                /bin/sh "$MUSIC_REQUEST" || true
            else
                printf 'YOUTUBE_REQUEST_SKIPPED reason=music_service_not_installed\n' >&2
            fi
            ;;
        'PLAY_VIDEO '*)
            # Only the trusted selector writes this bounded video-ID command.
            # A failed player must not terminate the FIFO controller.
            play_video "${request#PLAY_VIDEO }" || true
            ;;
        STOP_YOUTUBE)
            systemctl stop pauseable-youtube-browser.service || true
            printf 'YOUTUBE_STOPPED\n'
            ;;
        *)
            printf 'YOUTUBE_REQUEST_REJECTED\n' >&2
            ;;
    esac
done
