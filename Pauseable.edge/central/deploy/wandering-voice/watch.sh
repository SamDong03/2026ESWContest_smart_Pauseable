#!/bin/sh
set -eu

BASE=/data/pauseable/wandering-voice
STATE=/data/pauseable/wandering-voice-state
UNIT=am.com.atlas.app.pauseableatlas.service
CENTRAL_HOME=/data/profiles/0/appdata/com.atlas.app.pauseableatlas/home
HA_CONFIG=/var/lib/pauseable/weather-light-control/config.json
DEVICE_ENV=/var/lib/pauseable/ha.env
STYLER_CONFIG=$BASE/styler-config.json
COMFORT_CONFIG=$BASE/comfort-config.json
DOCKER=/usr/bin/docker
IMAGE=ha-ai-runner:review-20260908
test -d "$STATE"
test -r "$HA_CONFIG"
test -r "$DEVICE_ENV"
test -r "$BASE/tts_context.py"
test -r "$STYLER_CONFIG"
test -r "$COMFORT_CONFIG"

run_styler_bridge() {
    "$DOCKER" run --rm --pull=never --network host \
        --security-opt apparmor=unconfined \
        --mount type=bind,src="$BASE",dst=/app,readonly \
        --mount type=bind,src="$HA_CONFIG",dst=/run/secrets/ha-config.json,readonly \
        --entrypoint python3 "$IMAGE" \
        /app/styler_bridge.py \
        --ha-config /run/secrets/ha-config.json \
        --styler-config /app/styler-config.json "$@"
}

run_comfort_bridge() {
    "$DOCKER" run --rm --pull=never --network host \
        --security-opt apparmor=unconfined \
        --mount type=bind,src="$BASE",dst=/app,readonly \
        --mount type=bind,src="$HA_CONFIG",dst=/run/secrets/ha-config.json,readonly \
        --entrypoint python3 "$IMAGE" \
        /app/comfort_bridge.py \
        --ha-config /run/secrets/ha-config.json \
        --comfort-config /app/comfort-config.json "$@"
}

play_message() (
    app_user=$1
    message=$2
    tag=$3
    personalized=$(mktemp /run/pauseable-wandering-message.XXXXXX)
    trap 'rm -f "$personalized"' EXIT HUP INT TERM
    chmod 0600 "$personalized"
    if ! "$DOCKER" run --rm --pull=never --network host \
        --security-opt apparmor=unconfined \
        --env-file "$DEVICE_ENV" \
        --mount type=bind,src="$BASE",dst=/app,readonly \
        --entrypoint python3 "$IMAGE" \
        /app/tts_context.py --template "/app/$(basename "$message")" \
        > "$personalized"; then
        sed 's/{{patient_call_name}}/할머니/g' "$message" > "$personalized"
    fi
    chown "$app_user" "$personalized"
    if runuser -u "$app_user" -- env HOME="$CENTRAL_HOME" \
        /bin/sh "$BASE/play.sh" "$personalized" "$tag"; then
        result=0
    else
        result=$?
    fi
    exit "$result"
)

run_styler_bridge discover
echo WANDERING_STYLER_READY
run_comfort_bridge discover
echo WANDERING_COMFORT_READY


journalctl --unit="$UNIT" --boot --lines=0 --follow --output=cat --no-pager |
    awk -f "$BASE/route-filter.awk" |
    while IFS= read -r event_id; do
        claim="$STATE/$event_id"
        if ! mkdir "$claim" 2>/dev/null; then
            echo "WANDERING_VOICE_SKIPPED event_id=$event_id reason=already_claimed"
            continue
        fi
        app_user=$(systemctl show "$UNIT" --property=User --value)
        case "$app_user" in
            u0_a[0-9]*) ;;
            *) echo "WANDERING_VOICE_FAILED event_id=$event_id reason=app_user_unavailable"; rmdir "$claim"; continue ;;
        esac
        hour=$(date +%H)
        selected=$(/bin/sh "$BASE/time-router.sh" "$hour")
        outcome=failed
        echo "WANDERING_OUTPUT_SELECTED event_id=$event_id hour=$hour output=$selected"

        case "$selected" in
            styler)
                echo "WANDERING_STYLER_STARTED event_id=$event_id"
                if run_styler_bridge run --event-id "$event_id"; then
                    echo "WANDERING_STYLER_COMPLETED event_id=$event_id"
                    echo "WANDERING_STYLER_VOICE_STARTED event_id=$event_id"
                    if play_message "$app_user" "$BASE/message.txt" styler; then
                        outcome=completed
                        echo "WANDERING_STYLER_VOICE_COMPLETED event_id=$event_id"
                    else
                        echo "WANDERING_STYLER_VOICE_FAILED event_id=$event_id reason=synthesis_or_playback"
                    fi
                else
                    echo "WANDERING_STYLER_FAILED event_id=$event_id reason=styler_cycle"
                fi
                ;;
            water_purifier)
                echo "WANDERING_WATER_STARTED event_id=$event_id"
                if output_result=$(run_comfort_bridge run --output water_purifier --event-id "$event_id"); then
                    printf '%s\n' "$output_result"
                    case "$output_result" in
                        *"backend=disabled"*)
                            outcome=skipped
                            echo "WANDERING_WATER_SKIPPED event_id=$event_id reason=disabled"
                            ;;
                        *)
                            echo "WANDERING_WATER_COMPLETED event_id=$event_id"
                            echo "WANDERING_WATER_VOICE_STARTED event_id=$event_id"
                            if play_message "$app_user" "$BASE/water-message.txt" water; then
                                outcome=completed
                                echo "WANDERING_WATER_VOICE_COMPLETED event_id=$event_id"
                            else
                                echo "WANDERING_WATER_VOICE_FAILED event_id=$event_id reason=synthesis_or_playback"
                            fi
                            ;;
                    esac
                else
                    echo "WANDERING_WATER_FAILED event_id=$event_id reason=water_cycle"
                fi
                ;;
            tiiun)
                echo "WANDERING_TIIUN_STARTED event_id=$event_id"
                if output_result=$(run_comfort_bridge run --output tiiun --event-id "$event_id"); then
                    printf '%s\n' "$output_result"
                    case "$output_result" in
                        *"backend=disabled"*)
                            outcome=skipped
                            echo "WANDERING_TIIUN_SKIPPED event_id=$event_id reason=disabled"
                            ;;
                        *)
                            echo "WANDERING_TIIUN_COMPLETED event_id=$event_id"
                            echo "WANDERING_TIIUN_VOICE_STARTED event_id=$event_id"
                            if play_message "$app_user" "$BASE/tiiun-message.txt" tiiun; then
                                outcome=completed
                                echo "WANDERING_TIIUN_VOICE_COMPLETED event_id=$event_id"
                            else
                                echo "WANDERING_TIIUN_VOICE_FAILED event_id=$event_id reason=synthesis_or_playback"
                            fi
                            ;;
                    esac
                else
                    echo "WANDERING_TIIUN_FAILED event_id=$event_id reason=tiiun_cycle"
                fi
                ;;
        esac

        if [ "$outcome" = completed ] || [ "$outcome" = skipped ]; then
            : > "$claim/completed"
            echo "WANDERING_OUTPUT_COMPLETED event_id=$event_id output=$selected outcome=$outcome"
        else
            : > "$claim/failed"
            echo "WANDERING_OUTPUT_FAILED event_id=$event_id output=$selected"
        fi
    done
