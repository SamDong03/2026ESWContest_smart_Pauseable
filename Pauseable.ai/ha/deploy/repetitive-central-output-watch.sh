#!/bin/sh
set -eu

BASE=/data/ha_ai_fullcycle_20260911
STATE=$BASE/outputs/repetitive-central-output-state
CENTRAL_UNIT=am.com.atlas.app.pauseableatlas.service
FILTER=$BASE/config/repetitive-central-route-filter.awk
TIME_ROUTER=$BASE/config/repetitive-central-time-router.sh

test -d "$STATE"
test -r "$FILTER"
test -r "$TIME_ROUTER"


journalctl --unit="$CENTRAL_UNIT" --boot --lines=0 --follow --output=cat --no-pager |
    awk -f "$FILTER" |
    while IFS= read -r event_id; do
        claim="$STATE/$event_id"
        if ! mkdir "$claim" 2>/dev/null; then
            echo "REPETITIVE_CENTRAL_OUTPUT_SKIPPED event_id=$event_id reason=already_claimed"
            continue
        fi

        hour=$(TZ=Asia/Seoul date +%H)
        selected=$(/bin/sh "$TIME_ROUTER" "$hour")
        case "$selected" in
            tv) target_unit=pauseable-washer-youtube-tts.service ;;
            air_purifier) target_unit=pauseable-air-purifier-tts.service ;;
            *)
                : > "$claim/failed"
                echo "REPETITIVE_CENTRAL_OUTPUT_FAILED event_id=$event_id reason=invalid_output"
                continue
                ;;
        esac

        echo "REPETITIVE_CENTRAL_OUTPUT_SELECTED event_id=$event_id hour=$hour output=$selected"
        systemctl reset-failed "$target_unit" 2>/dev/null || true
        if systemctl start "$target_unit"; then
            : > "$claim/completed"
            echo "REPETITIVE_CENTRAL_OUTPUT_COMPLETED event_id=$event_id output=$selected"
        else
            : > "$claim/failed"
            echo "REPETITIVE_CENTRAL_OUTPUT_FAILED event_id=$event_id output=$selected"
        fi
    done
