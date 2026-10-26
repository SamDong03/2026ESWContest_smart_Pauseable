#!/bin/sh

set -eu

SOURCE_DIR="${1:-.}"
ROOT_OPTIONS="$(awk '$2 == "/" { print $4; exit }' /proc/mounts)"
REMOUNTED_ROOT=0

restore_root_mount() {
    if [ "${REMOUNTED_ROOT}" -eq 1 ]; then
        sync
        mount -o remount,ro /
    fi
}

trap restore_root_mount EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p /data/pauseable/bin
cp "${SOURCE_DIR}/pauseable-central-ensure.sh" /data/pauseable/bin/pauseable-central-ensure.sh
chmod 0755 /data/pauseable/bin/pauseable-central-ensure.sh

case ",${ROOT_OPTIONS}," in
    *,rw,*) ;;
    *)
        mount -o remount,rw /
        REMOUNTED_ROOT=1
        ;;
esac

cp "${SOURCE_DIR}/pauseable-central-ensure.service" /etc/systemd/system/pauseable-central-ensure.service
cp "${SOURCE_DIR}/pauseable-central-watchdog.timer" /etc/systemd/system/pauseable-central-watchdog.timer
chmod 0644 /etc/systemd/system/pauseable-central-ensure.service
chmod 0644 /etc/systemd/system/pauseable-central-watchdog.timer

systemctl daemon-reload
systemctl enable --now pauseable-central-watchdog.timer

echo "Pauseable Central watchdog installed and enabled"
