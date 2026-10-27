#!/bin/sh
# Optional post-guidance action: always return success to the safety/TTS caller.
set -u
UNIT=pauseable-favorite-music.service
if [ "$(systemctl show "$UNIT" --property=LoadState --value 2>/dev/null)" != loaded ]; then
    echo "FAVORITE_MUSIC_SKIPPED reason=service_not_installed"
elif systemctl start --no-block "$UNIT"; then
    echo "FAVORITE_MUSIC_QUEUED"
else
    echo "FAVORITE_MUSIC_SKIPPED reason=service_unavailable"
fi
exit 0
