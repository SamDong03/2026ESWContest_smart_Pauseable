# Home Assistant Real-Time Collection Guide

## Why Snapshot Polling Is Not Enough

`collect_ha_states.py` calls `/api/states` every few seconds and stores the current state. This is useful for checking whether Home Assistant and LG ThinQ are connected, but it can miss short events.

Example:

```text
12:00:03 fridge door open
12:00:08 fridge door close
12:00:10 collector polls /api/states
```

The collector only sees `close`, so the short `open` event can be missed.

## Better Collection Strategy

Use two collection paths:

```text
Real-time path:
collect_ha_events_ws.py
-> WebSocket /api/websocket
-> subscribe_events: state_changed
-> write one CSV row whenever a selected entity state changes

Fallback path:
collect_ha_states.py
-> REST /api/states snapshot
-> quick connection check and initial inventory
```

Home Assistant's WebSocket API supports authentication with a long-lived access token and event subscription through `subscribe_events`. Subscribing to `state_changed` lets the collector receive state changes as they happen.

## Recommended Test Flow

In the Docker container:

```bash
cd /app/ecoai-tutorial/ha_ai
source /app/venv/bin/activate
```

Make sure these environment variables are already set:

```bash
echo "$HA_URL"
echo ${#HA_TOKEN}
```

For the current VirtualBox setup, `HA_URL` usually looks like:

```bash
export HA_URL="http://172.x.x.1:8124"
```

Use the Home Assistant long-lived access token, not the LG ThinQ token:

```bash
read -s HA_TOKEN
export HA_TOKEN
```

Run a short real-time collection test:

```bash
python src/collect_ha_events_ws.py \
  --ha-url "$HA_URL" \
  --token "$HA_TOKEN" \
  --output data/raw/ha_live_events_ws_5min.csv \
  --duration-seconds 300 \
  --write-initial-snapshot \
  --truncate
```

While it is running, operate one device:

```text
- open/close the fridge door
- change air purifier mode or speed
- turn air purifier power on/off
```

Then check the CSV:

```bash
head -20 data/raw/ha_live_events_ws_5min.csv
tail -20 data/raw/ha_live_events_ws_5min.csv
```

Run the existing pipeline:

```bash
python src/run_ha_pipeline.py \
  --input data/raw/ha_live_events_ws_5min.csv \
  --baseline models/user_001_real_baseline_v2.json \
  --prefix ha_live_ws_5min
```

Check the result:

```bash
head -30 outputs/ha_live_ws_5min_result.csv
cat outputs/ha_live_ws_5min_episode_summary.csv
```

## Long-Running Collection

For longer data collection:

```bash
python src/collect_ha_events_ws.py \
  --ha-url "$HA_URL" \
  --token "$HA_TOKEN" \
  --output data/raw/ha_live_events_ws.csv \
  --write-initial-snapshot
```

Stop it with `Ctrl+C`.

## Useful Options

```text
--duration-seconds 600
  Stop automatically after 10 minutes.

--max-events 50
  Stop after 50 selected state_changed events.

--write-initial-snapshot
  Save the current selected states first, then listen for changes.

--include-all
  Do not restrict collection to LG ThinQ keywords.

--include-telemetry
  Include non-behavior entities too. This is useful for entity audits, not baseline inference.

--include-attribute-only
  Also save events where the entity state is unchanged but attributes changed.

--truncate
  Replace the output CSV at startup.
```

## Presentation Claim

Safe claim:

```text
The initial collector used periodic snapshots to verify Home Assistant connectivity.
For real operation, the system uses Home Assistant's state_changed event stream so short state changes such as fridge open/close are captured more reliably.
```

Avoid claiming:

```text
This guarantees no event can ever be missed.
```

More accurate:

```text
WebSocket event streaming reduces missed short events compared with polling. For higher reliability, the collector can be run as a service and complemented with Home Assistant Recorder/History backfill.
```
