#!/bin/sh

set -eu

APP_ID="com.atlas.app.pauseableatlas"
APP_MANAGER="com.atlas.AppManager1"
VOICE_MODEL_TIMER="pauseable-voice-model-update.timer"

ensure_voice_model_timer() {
    timer_wants="$(
        systemctl show timers.target --property=Wants --value 2>/dev/null || true
    )"

    case " ${timer_wants} " in
        *" ${VOICE_MODEL_TIMER} "*)
            ;;
        *)
            logger -t pauseable-central-ensure \
                "Reloading systemd to discover the persistent voice-model timer"
            if ! systemctl daemon-reload; then
                logger -t pauseable-central-ensure \
                    "Could not reload systemd for ${VOICE_MODEL_TIMER}"
                return
            fi
            ;;
    esac

    if systemctl is-active --quiet "${VOICE_MODEL_TIMER}"; then
        return
    fi

    if systemctl start "${VOICE_MODEL_TIMER}"; then
        logger -t pauseable-central-ensure \
            "Started ${VOICE_MODEL_TIMER} after persistent storage became available"
    else
        logger -t pauseable-central-ensure \
            "Could not start ${VOICE_MODEL_TIMER}"
    fi
}

is_running() {
    abusctl call "${APP_MANAGER}" GetStatus "${APP_ID}" 2>/dev/null \
        | grep -q '"data" : "Running"'
}

ensure_voice_model_timer

if is_running; then
    exit 0
fi

logger -t pauseable-central-ensure "Central is not running; requesting AppManager start"
if ! abusctl call "${APP_MANAGER}" Start "${APP_ID}" >/dev/null; then


    APP_UNIT="am.${APP_ID}.service"
    if [ "$(systemctl show "${APP_UNIT}" -p Transient --value 2>/dev/null)" = "yes" ]; then
        logger -t pauseable-central-ensure "AppManager start failed; starting existing ${APP_UNIT}"
        systemctl start "${APP_UNIT}"
    else
        logger -t pauseable-central-ensure "AppManager start failed without a reusable transient unit"
        exit 1
    fi
fi

attempt=0
while [ "${attempt}" -lt 15 ]; do
    if is_running; then
        logger -t pauseable-central-ensure "Central reached Running state"
        exit 0
    fi

    attempt=$((attempt + 1))
    sleep 1
done

logger -t pauseable-central-ensure "Central did not reach Running state within 15 seconds"
exit 1
