
import argparse
import json
from pathlib import Path
import shutil

from ha_runtime_health import read_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', default='runtime/local')
    args = parser.parse_args()
    root = Path(args.state_dir).resolve()
    probe = root
    while not probe.exists():
        probe = probe.parent
    report = read_status(root, shutil.disk_usage(probe).free)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report['health'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
