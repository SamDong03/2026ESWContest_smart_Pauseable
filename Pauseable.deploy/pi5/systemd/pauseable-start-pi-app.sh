#!/usr/bin/env bash
set -euo pipefail

: "${PI5_SSH_TARGET:?PI5_SSH_TARGET is not set}"

exec /usr/bin/ssh \
  -o BatchMode=yes \
  -o ConnectTimeout=10 \
  -o ServerAliveInterval=5 \
  -o ServerAliveCountMax=2 \
  "$PI5_SSH_TARGET" \
  'set -e

   PAUSEABLE_APP_ID=com.atlas.app.pauseableatlas
   PAUSEABLE_APP_ROOT=/data/share/usr/atlas/apps/$PAUSEABLE_APP_ID
   PAUSEABLE_APP_BIN=$PAUSEABLE_APP_ROOT/$PAUSEABLE_APP_ID
   PAUSEABLE_APP_DATA=/data/profiles/0/appdata/$PAUSEABLE_APP_ID
   PAUSEABLE_APP_HOME=$PAUSEABLE_APP_DATA/home
   PAUSEABLE_SOURCE_ROOT=/var/lib/pauseable

   if [ ! -x "$PAUSEABLE_APP_BIN" ]; then
       exit 0
   fi

   if [ ! -x "$PAUSEABLE_SOURCE_ROOT/piper-guardian/bin/paplay" ]; then
       cp /usr/bin/pacat "$PAUSEABLE_SOURCE_ROOT/piper-guardian/bin/paplay"
       chmod 755 "$PAUSEABLE_SOURCE_ROOT/piper-guardian/bin/paplay"
   fi

   if [ ! -r "$PAUSEABLE_APP_HOME/ha.env" ] ||
      [ ! -x "$PAUSEABLE_APP_HOME/piper-guardian/bin/piper" ] ||
      [ ! -x "$PAUSEABLE_APP_HOME/piper-guardian/bin/paplay" ]; then
       PAUSEABLE_APP_UID=$(stat -c "%u" "$PAUSEABLE_APP_BIN")
       PAUSEABLE_APP_GID=$(stat -c "%g" "$PAUSEABLE_APP_DATA")

       mkdir -p "$PAUSEABLE_APP_HOME/runtime" "$PAUSEABLE_APP_HOME/piper-guardian"
       cp "$PAUSEABLE_SOURCE_ROOT/ha.env" "$PAUSEABLE_APP_HOME/ha.env"
       cp "$PAUSEABLE_SOURCE_ROOT/ha_config.json" "$PAUSEABLE_APP_HOME/ha_config.json"
       cp -a "$PAUSEABLE_SOURCE_ROOT/piper-guardian/." "$PAUSEABLE_APP_HOME/piper-guardian/"

       sed -i \
         "s|^HA_CONFIG_PATH=.*|HA_CONFIG_PATH=$PAUSEABLE_APP_HOME/ha_config.json|" \
         "$PAUSEABLE_APP_HOME/ha.env"
       sed -i \
         "s|^PIPER_ROOT=.*|PIPER_ROOT=$PAUSEABLE_APP_HOME/piper-guardian|" \
         "$PAUSEABLE_APP_HOME/ha.env"
       sed -i \
         "s|^TTS_OUTPUT_PATH=.*|TTS_OUTPUT_PATH=$PAUSEABLE_APP_HOME/runtime/pauseable-tts.wav|" \
         "$PAUSEABLE_APP_HOME/ha.env"

       chown -R "$PAUSEABLE_APP_UID:$PAUSEABLE_APP_GID" "$PAUSEABLE_APP_HOME"
       find "$PAUSEABLE_APP_HOME" -type d -exec chmod 770 {} \;
       find "$PAUSEABLE_APP_HOME/piper-guardian" -type f -exec chmod 640 {} \;
       chmod 750 "$PAUSEABLE_APP_HOME/piper-guardian/bin/piper"
       chmod 750 "$PAUSEABLE_APP_HOME/piper-guardian/bin/paplay"
       chmod 600 "$PAUSEABLE_APP_HOME/ha.env" "$PAUSEABLE_APP_HOME/ha_config.json"

       if pidof "$PAUSEABLE_APP_ID" >/dev/null 2>&1; then
           /usr/bin/busctl call \
             com.atlas.AppManager1 \
             /com/atlas/AppManager1 \
             com.atlas.AppManager1 \
             Stop \
             s \
             "$PAUSEABLE_APP_ID"
           sleep 1
       fi
   fi

   if ! pidof "$PAUSEABLE_APP_ID" >/dev/null 2>&1; then
      /usr/bin/busctl call \
        com.atlas.AppManager1 \
        /com/atlas/AppManager1 \
        com.atlas.AppManager1 \
        Start \
        s \
        "$PAUSEABLE_APP_ID"
   fi'
