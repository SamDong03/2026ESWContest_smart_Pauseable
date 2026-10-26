#!/bin/sh
set -eu

FIFO=/run/pauseable-youtube-request.fifo

if [ ! -p "$FIFO" ]; then
    printf 'YOUTUBE_CONTROL_ERROR: FIFO unavailable\n' >&2
    exit 1
fi

exec 3<>"$FIFO"

printf 'YOUTUBE_CONTROL_READY\n'

while IFS= read -r request <&3; do
    case "$request" in
        PLAY_TROT)
            if /usr/bin/docker -H unix:///run/docker.sock exec \
                --user 1004:1004 \
                pauseable-youtube-bridge \
                chromium \
                --user-data-dir=/tmp/pauseable-bridge-profile \
                'https://www.youtube.com/watch?v=SUIM5wHIU7o&autoplay=1'
            then
                printf 'YOUTUBE_OPEN_REQUEST_SENT\n'
            else
                printf 'YOUTUBE_OPEN_REQUEST_FAILED\n' >&2
            fi
            ;;
        *)
            printf 'YOUTUBE_REQUEST_REJECTED\n' >&2
            ;;
    esac
done
