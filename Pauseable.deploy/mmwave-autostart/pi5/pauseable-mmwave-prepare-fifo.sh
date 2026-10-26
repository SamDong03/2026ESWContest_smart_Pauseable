#!/bin/sh
set -eu
fifo=/run/pauseable-wandering-input.fifo
if [ -p "$fifo" ]; then
    exit 0
fi
if [ -e "$fifo" ] || [ -L "$fifo" ]; then
    echo "Pauseable FIFO path exists and is not a FIFO; refusing to replace it" >&2
    exit 1
fi

mkfifo -m 0666 "$fifo"
echo "PAUSEABLE_FIFO_CREATED"
