#!/bin/sh
set -eu

BACKUP=${1:?Pass the backup directory printed by install.sh}
case "$BACKUP" in /data/pauseable/backups/wandering-voice-*) ;; *) exit 2 ;; esac
test -s "$BACKUP/pauseable-central-ensure.sh"
UNIT=pauseable-wandering-tts.service
changed_root=0
restore_root() {
    if [ "$changed_root" = 1 ]; then sync; mount -o remount,ro /; fi
}
trap restore_root EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
systemctl stop "$UNIT"
cat "$BACKUP/pauseable-central-ensure.sh" > /data/pauseable/bin/pauseable-central-ensure.sh
options=$(awk '$2 == "/" {print $4; exit}' /proc/mounts)
case ",$options," in *,rw,*) ;; *) mount -o remount,rw /; changed_root=1 ;; esac
systemctl disable "$UNIT"
rm -f "/etc/systemd/system/$UNIT"
systemctl daemon-reload

echo WANDERING_VOICE_STOPPED
