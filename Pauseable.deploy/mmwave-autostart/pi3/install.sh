#!/bin/sh
set -eu
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
if [ "${1:-}" = --check ]; then
    test -f "$SOURCE_DIR/Pauseable.edge/mmwave-relay/relay_supervisor.py"
    test -f "$SOURCE_DIR/Pauseable.edge/mmwave-relay/validate_event.py"
    test -f "$SOURCE_DIR/Pauseable.contracts/mmwave-target-event.schema.json"
    test -f "$SOURCE_DIR/Pauseable.deploy/mmwave-autostart/pi3/pauseable-mmwave-relay.service"
    echo 'PI3_BUNDLE_OK'
    exit 0
fi
if [ "${1:-}" != --apply ]; then
    echo 'Usage: sh install.sh --check | --apply'
    exit 0
fi

test "$(id -u)" = 0
id pauseable >/dev/null
test -x /usr/bin/python3
test ! -e /opt/pauseable-mmwave-relay
test ! -e /etc/systemd/system/pauseable-mmwave-relay.service
mkdir -p /opt/pauseable-mmwave-relay/Pauseable.edge/mmwave-relay /opt/pauseable-mmwave-relay/Pauseable.contracts
for name in relay_serial.py relay_supervisor.py validate_event.py; do
    cp "$SOURCE_DIR/Pauseable.edge/mmwave-relay/$name" "/opt/pauseable-mmwave-relay/Pauseable.edge/mmwave-relay/$name"
    chmod 0644 "/opt/pauseable-mmwave-relay/Pauseable.edge/mmwave-relay/$name"
done
cp "$SOURCE_DIR/Pauseable.contracts/mmwave-target-event.schema.json" /opt/pauseable-mmwave-relay/Pauseable.contracts/
chmod 0644 /opt/pauseable-mmwave-relay/Pauseable.contracts/mmwave-target-event.schema.json
cp "$SOURCE_DIR/Pauseable.deploy/mmwave-autostart/pi3/pauseable-mmwave-relay.service" /etc/systemd/system/pauseable-mmwave-relay.service
chmod 0644 /etc/systemd/system/pauseable-mmwave-relay.service
systemctl daemon-reload

echo 'PI3_FILES_INSTALLED'
