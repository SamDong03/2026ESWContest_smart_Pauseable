
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from ha_behavior_feedback import FeedbackStore, queue_review, utc_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lifecycle-dir', required=True)
    parser.add_argument('--input', help='A complete explicit behavior-label JSON document')
    parser.add_argument('--label', choices=['normal', 'repetitive', 'uncertain'])
    parser.add_argument('--reviewer-id')
    parser.add_argument('--event-id')
    parser.add_argument('--start', help='Timezone-aware beginning of a reviewed period')
    parser.add_argument('--end', help='Timezone-aware end, at most 24 hours after start')
    parser.add_argument('--reason', default='')
    parser.add_argument('--apply-now', action='store_true', help='Apply locally now instead of queueing for the next service cycle')
    args = parser.parse_args()
    root = Path(args.lifecycle_dir).resolve()
    identity = json.loads((root / 'identity.json').read_text(encoding='utf-8'))
    if args.input:
        if args.label or args.event_id or args.start or args.end or args.reviewer_id:
            parser.error('--input cannot be combined with hand-written review fields')
        message = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
    else:
        if not args.label or not args.reviewer_id or bool(args.event_id) == bool(args.start or args.end):
            parser.error('Specify label/reviewer and either event-id or both start/end')
        message = {'contract_version': '1.0', 'feedback_id': 'review-' + uuid.uuid4().hex,
                   'source_type': identity['source_type'], 'household_id': identity['household_id'],
                   'patient_id': 'byunwoojin', 'device_id': 'pi5-home-01', 'review_kind': 'behavior_label',
                   'label': args.label, 'reviewer_id': args.reviewer_id,
                   'reviewed_at': datetime.now(timezone.utc).isoformat(), 'reason': args.reason}
        if args.event_id:
            message['event_id'] = args.event_id
        else:
            if not args.start or not args.end:
                parser.error('Both start and end are required')
            message['period'] = {'start': utc_time(args.start).isoformat(), 'end': utc_time(args.end).isoformat()}
    if args.apply_now:
        result = FeedbackStore(root, identity['source_type'], identity['household_id']).apply(message)
    else:
        result = queue_review(root, message)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
