#!/bin/sh

set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BASE=/data/pauseable/wandering-voice
STATE=/data/pauseable/wandering-voice-state
ENSURE=/data/pauseable/bin/pauseable-central-ensure.sh
UNIT=pauseable-wandering-tts.service
ENV=/data/profiles/0/appdata/com.atlas.app.pauseableatlas/home/ha.env
BACKUP=/data/pauseable/backups/wandering-voice-$(date -u +%Y%m%dT%H%M%SZ)
changed_root=0
restore_root() {
    if [ "$changed_root" = 1 ]; then
        sync
        mount -o remount,ro /
        changed_root=0
    fi
}
trap restore_root EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

test -r "$ENSURE"
test -r /var/lib/pauseable/weather-light-control/config.json
test -r /var/lib/pauseable/ha.env
grep -q '^PAUSEABLE_DEVICE_TOKEN=' /var/lib/pauseable/ha.env

grep -Fxq AI_LOCAL_TTS_ENABLED=0 "$ENV"
test ! -e "/etc/systemd/system/$UNIT"
test ! -e "$BASE"
test ! -e "$STATE"
sh -n "$SOURCE/play.sh"
sh -n "$SOURCE/watch.sh"
sh -n "$SOURCE/time-router.sh"
mkdir -p "$BACKUP" "$BASE" "$STATE"
chmod 0700 "$BACKUP" "$STATE"
chmod 0755 "$BASE"
cp -p "$ENSURE" "$BACKUP/pauseable-central-ensure.sh"
for file in message.txt water-message.txt tiiun-message.txt play.sh watch.sh time-router.sh \
    tts_context.py \
    route-filter.awk styler_bridge.py comfort_bridge.py \
    styler-config.example.json comfort-config.example.json "$UNIT"; do
    cp "$SOURCE/$file" "$BASE/$file"
    chmod 0644 "$BASE/$file"
done
cp "$SOURCE/styler-config.example.json" "$BASE/styler-config.json"
chmod 0600 "$BASE/styler-config.json"
cp "$SOURCE/comfort-config.example.json" "$BASE/comfort-config.json"
chmod 0600 "$BASE/comfort-config.json"


awk '
    /^ensure_voice_model_timer$/ {
        print "ensure_wandering_voice_service() {"
        print "    if [ \"$(systemctl show pauseable-wandering-tts.service -p LoadState --value 2>/dev/null || true)\" != loaded ]; then"
        print "        systemctl daemon-reload || return 0"
        print "    fi"
        print "    if ! systemctl is-active --quiet pauseable-wandering-tts.service; then"
        print "        systemctl start pauseable-wandering-tts.service || logger -t pauseable-central-ensure \"Could not start wandering voice service\""
        print "    fi"
        print "}"
        print ""
        print "ensure_wandering_voice_service"
    }
    { print }
' "$ENSURE" > "$BASE/central-ensure.updated.sh"
sh -n "$BASE/central-ensure.updated.sh"
grep -q '^ensure_wandering_voice_service$' "$BASE/central-ensure.updated.sh"

cat "$BASE/central-ensure.updated.sh" > "$ENSURE"

options=$(awk '$2 == "/" {print $4; exit}' /proc/mounts)
case ",$options," in
    *,rw,*) ;;
    *) mount -o remount,rw /; changed_root=1 ;;
esac
ln -s "$BASE/$UNIT" "/etc/systemd/system/$UNIT"
systemctl daemon-reload
systemctl enable "$UNIT"
restore_root
systemctl start "$UNIT"
systemctl is-active "$UNIT"
printf 'WANDERING_VOICE_INSTALLED backup=%s\n' "$BACKUP"
awk '$2 == "/" {print "ROOT_OPTIONS=" $4; exit}' /proc/mounts
