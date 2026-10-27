#!/bin/sh
# Run on the Pi as root from this checkout. Does NOT play music or restart Central.
set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$SOURCE/../../.." && pwd)
BASE=/data/pauseable/favorite-music
STATE=/data/pauseable/favorite-music-state
HA=/data/ha_ai_fullcycle_20260911
WANDERING=/data/pauseable/wandering-voice
YOUTUBE=/var/lib/pauseable/youtube
BACKUP=/data/pauseable/backups/favorite-music-$(date -u +%Y%m%dT%H%M%SZ)-$$
UNIT=pauseable-favorite-music.service

[ "$(id -u)" = 0 ] || { echo 'Run this installer as root on the Pi.' >&2; exit 1; }
for directory in "$HA/config" "$WANDERING" "$YOUTUBE" /etc/systemd/system /run/systemd/system; do
    if [ ! -d "$directory" ] || [ ! -w "$directory" ]; then
        echo "Not writable: $directory. No changes made; see README for read-only ATLAS roots." >&2
        exit 1
    fi
done
for file in "$SOURCE/player.py" "$SOURCE/play.sh" "$SOURCE/request.sh" \
    "$SOURCE/youtube-control.sh" "$SOURCE/$UNIT" \
    "$REPO/Pauseable.ai/ha/src/play_lg_tv_youtube.py" \
    "$REPO/Pauseable.ai/ha/deploy/repetitive-central-output-watch.sh" \
    "$REPO/Pauseable.ai/ha/deploy/pauseable-washer-youtube-tts.service" \
    "$REPO/Pauseable.edge/central/deploy/wandering-voice/watch.sh" \
    /var/lib/pauseable/ha.env \
    "$HA/config/repetitive-central-output-watch.sh" "$WANDERING/watch.sh" \
    "$YOUTUBE/pauseable-youtube-control.sh"; do
    test -r "$file" || { echo "Missing required file: $file" >&2; exit 1; }
done
grep -q '^PAUSEABLE_DEVICE_TOKEN=.' /var/lib/pauseable/ha.env || {
    echo 'The existing device token must be configured in /var/lib/pauseable/ha.env.' >&2; exit 1;
}
/usr/bin/docker image inspect ha-ai-runner:review-20260908 >/dev/null
/usr/bin/docker image inspect pauseable-youtube:1 >/dev/null
for script in play.sh request.sh youtube-control.sh; do /bin/sh -n "$SOURCE/$script"; done

umask 077
mkdir -p "$BACKUP" "$BASE" "$STATE"
# Back up only these exact runtime files. Preserve other appliance/local settings.
for file in "$HA/config/repetitive-central-output-watch.sh" \
    "$HA/config/pauseable-washer-youtube-tts.service" "$WANDERING/watch.sh" \
    "$YOUTUBE/pauseable-youtube-control.sh" \
    "/run/systemd/system/pauseable-washer-youtube-tts.service"; do
    if [ -f "$file" ]; then
        destination="$BACKUP$file"
        mkdir -p "$(dirname -- "$destination")"
        cp -p "$file" "$destination"
    fi
done
if [ -f "$BASE/player.env" ]; then cp -p "$BASE/player.env" "$BACKUP/player.env"; fi
for file in player.py play.sh request.sh youtube-control.sh "$UNIT"; do
    install -m 0644 "$SOURCE/$file" "$BASE/$file"
done
install -m 0644 "$REPO/Pauseable.ai/ha/src/play_lg_tv_youtube.py" "$BASE/play_lg_tv_youtube.py"
if [ ! -f "$BASE/player.env" ]; then
    install -m 0600 "$SOURCE/player.env.example" "$BASE/player.env"
fi
install -m 0644 "$REPO/Pauseable.ai/ha/deploy/repetitive-central-output-watch.sh" \
    "$HA/config/repetitive-central-output-watch.sh"
install -m 0644 "$REPO/Pauseable.ai/ha/deploy/pauseable-washer-youtube-tts.service" \
    "$HA/config/pauseable-washer-youtube-tts.service"
install -m 0644 "$REPO/Pauseable.ai/ha/deploy/pauseable-washer-youtube-tts.service" \
    /run/systemd/system/pauseable-washer-youtube-tts.service
install -m 0644 "$REPO/Pauseable.edge/central/deploy/wandering-voice/watch.sh" "$WANDERING/watch.sh"
install -m 0755 "$REPO/Pauseable.edge/actions/youtube/pauseable-youtube-control.sh" \
    "$YOUTUBE/pauseable-youtube-control.sh"
systemctl link "$BASE/$UNIT"
systemctl daemon-reload
systemctl restart pauseable-youtube-control.service
# Only restart already-running output watchers, never start detectors/Central,
# safety gateways, camera, API, or previously-disabled appliance actions.
for watcher in pauseable-repetitive-central-output.service pauseable-wandering-tts.service; do
    if systemctl is-active --quiet "$watcher"; then systemctl restart "$watcher"; fi
done
printf 'FAVORITE_MUSIC_INSTALLED backup=%s\n' "$BACKUP"
echo "Check $BASE/player.env and the app's saved songs before a device test."
