
from collections import Counter
import json
import os
from pathlib import Path
import platform
import shutil

from collect_ha_states import fetch_states, selected_states, DEFAULT_ENTITY_KEYWORDS, state_to_row, utc_now
from entity_mapper import convert_rows


def main():
    states = fetch_states(os.environ['HA_URL'], os.environ['HA_TOKEN'], 10)
    selected = selected_states(states, DEFAULT_ENTITY_KEYWORDS, True)
    physical = [s for s in selected if 'virtual' not in s['entity_id'].lower()]
    rows = [row for s in physical for row in convert_rows(state_to_row(s, 'state_snapshot', utc_now()))
            if row['action'] != 'skip']
    report = {'architecture': platform.machine(), 'ha_entities': len(states),
              'selected_physical_entities': len(physical),
              'mapped_signals_by_device': dict(Counter(row['device_type'] for row in rows)),
              'unavailable_selected': [s['entity_id'] for s in physical if s['state'] in ('unknown', 'unavailable')],
              'free_mib': round(shutil.disk_usage('/app').free / 1024**2, 1),
              'note': 'Read-only inventory; no appliance commands or simulated HA states were sent.'}
    path = Path('/app/outputs/pi_ha_inventory.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
