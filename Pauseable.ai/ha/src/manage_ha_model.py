
import argparse
import json
import os
from pathlib import Path

from ha_model_lifecycle import Lifecycle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lifecycle-dir', required=True)
    parser.add_argument('--rollback-reason', help='Opt-in rollback; service must be stopped')
    args = parser.parse_args()
    root = Path(args.lifecycle_dir).resolve()
    identity = json.loads((root / 'identity.json').read_text())
    if not args.rollback_reason:
        pointer = root / 'active.json'
        print(json.dumps({'identity': identity,
                          'active': json.loads(pointer.read_text()) if pointer.exists() else None}, indent=2))
        return
    if os.name != 'posix':
        parser.error('Rollback requires the Linux service lock; inspect-only is supported here')
    import fcntl
    with (root.parent / 'service.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        life = Lifecycle(root, identity['source_type'], identity['household_id'])
        print(json.dumps(life.rollback(args.rollback_reason), indent=2))


if __name__ == '__main__':
    main()
