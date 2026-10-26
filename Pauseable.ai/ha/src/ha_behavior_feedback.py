
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

import pandas as pd
from jsonschema import ValidationError

from validate_repetitive_mqtt_payload import payload_validator
from ha_observation_reader import read_observations

SCHEMA = Path(__file__).resolve().parents[1] / 'deploy/contracts/repetitive-feedback.schema.json'


def local_time(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError('Missing observation timestamp')
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert(os.getenv('HA_TIMEZONE', 'Asia/Seoul')).tz_localize(None)
    return stamp


def utc_time(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError('A timezone-aware timestamp is required')
    return stamp.tz_convert('UTC')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


class FeedbackStore:
    def __init__(self, root, source, household):
        self.root, self.source, self.household = Path(root), source, household
        identity = json.loads((self.root / 'identity.json').read_text(encoding='utf-8'))
        if source not in ('local', 'synthetic') or identity['source_type'] != source or identity['household_id'] != household:
            raise ValueError('Feedback store identity mismatch')
        self.path = self.root / 'feedback.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS event_context (
                    event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, window_end TEXT NOT NULL, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS feedback (
                    revision INTEGER PRIMARY KEY AUTOINCREMENT, feedback_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL, label TEXT NOT NULL, reviewed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_labels (
                    window_end TEXT PRIMARY KEY, label TEXT NOT NULL, revision INTEGER NOT NULL,
                    reviewed_at TEXT NOT NULL, reviewer_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS review_changes (
                    revision INTEGER NOT NULL, window_end TEXT NOT NULL, label TEXT NOT NULL,
                    PRIMARY KEY(revision, window_end));
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def revision(self):
        with self.connect() as db:
            return int(db.execute('SELECT COALESCE(MAX(revision), 0) FROM feedback').fetchone()[0])

    def history(self, start=None, end=None):
        path = self.root / 'history.sqlite3'
        if not path.exists():
            return pd.DataFrame()
        clauses, params = [], []
        for value, operator in ((start, '>='), (end, '<=')):
            if value is not None:
                clauses.append('window_end ' + operator + ' ?')
                params.append(str(local_time(value)))
        return read_observations(path, clauses, params)

    def check_rows(self, frame):
        required = {'window_end', 'source_type', 'household_id', 'history_complete'}
        if frame.empty or not required.issubset(frame):
            raise ValueError('No matching collected observations for this review')
        if not frame['source_type'].eq(self.source).all() or not frame['household_id'].eq(self.household).all():
            raise ValueError('Reviewed observations belong to another source/household')

    def register_event(self, payload, window_end):
        frame = self.history(window_end, window_end)
        self.check_rows(frame)
        if (len(frame) != 1 or payload.get('patient_id') != 'byunwoojin' or payload.get('device_id') != 'pi5-home-01'
                or payload.get('source') != 'repetitive-ai'):
            raise ValueError('Event context does not match the collected observation')
        body = canonical(payload)
        snapshot = canonical(json.loads(frame.to_json(orient='records'))[0])
        with self.connect() as db:
            existing = db.execute('SELECT payload FROM event_context WHERE event_id=?', (payload['event_id'],)).fetchone()
            if existing and existing[0] != body:
                raise ValueError('Conflicting event_id in review context')
            db.execute('INSERT OR IGNORE INTO event_context VALUES (?, ?, ?, ?)',
                       (payload['event_id'], body, str(local_time(window_end)), snapshot))

    def apply(self, message, now=None):
        payload_validator(SCHEMA).validate(message)
        if message['source_type'] != self.source or message['household_id'] != self.household:
            raise ValueError('Feedback source/household mismatch')
        body = canonical(message)
        if len(body.encode('utf-8')) > 16384:
            raise ValueError('Feedback exceeds the size limit')
        reviewed = utc_time(message['reviewed_at'])
        now = utc_time(now or datetime.now(timezone.utc))
        if reviewed > now + pd.Timedelta(seconds=30):
            raise ValueError('Review time is in the future')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT payload, revision FROM feedback WHERE feedback_id=?', (message['feedback_id'],)).fetchone()
            if previous:
                if previous[0] != body:
                    raise ValueError('Conflicting feedback_id')
                return {'status': 'duplicate', 'revision': previous[1], 'applied_rows': 0}
            if 'event_id' in message:
                target = db.execute('SELECT window_end, snapshot FROM event_context WHERE event_id=?', (message['event_id'],)).fetchone()
                if target is None:
                    raise ValueError('Unknown event_id; an arbitrary alert ID is not a training target')
                frame = self.history(target[0], target[0])
                if frame.empty:
                    raise ValueError('The reviewed event is outside retained training history')
                current = json.loads(frame.to_json(orient='records'))[0]
                original = json.loads(target[1])
                if {k: v for k, v in current.items() if k != 'review_status'} != {k: v for k, v in original.items() if k != 'review_status'}:
                    raise ValueError('Event observations changed; review the collected period explicitly')
            else:
                period = message['period']
                start, end = utc_time(period['start']), utc_time(period['end'])
                if end < start or end - start > pd.Timedelta(hours=24):
                    raise ValueError('Review periods must be ordered and at most 24 hours')
                if end > reviewed:
                    raise ValueError('A review cannot label a future period')
                frame = self.history(start, end)
            self.check_rows(frame)
            latest = pd.to_datetime(frame['window_end']).max()
            reviewed_local = reviewed.tz_convert(os.getenv('HA_TIMEZONE', 'Asia/Seoul')).tz_localize(None)
            if latest > reviewed_local:
                raise ValueError('A review cannot precede the observations it labels')
            if message['label'] == 'normal' and not frame['history_complete'].eq(1).all():
                raise ValueError('Missing/disconnected observations cannot be certified normal')
            reviewed_text = reviewed.isoformat()
            revision = db.execute('INSERT INTO feedback(feedback_id,payload,label,reviewed_at) VALUES(?,?,?,?)',
                (message['feedback_id'], body, message['label'], reviewed_text)).lastrowid
            applied = 0
            for window in frame['window_end']:
                existing = db.execute('SELECT label,reviewed_at FROM review_labels WHERE window_end=?', (str(window),)).fetchone()
                if existing:
                    old_time = utc_time(existing[1])
                    if old_time > reviewed:
                        continue
                    if old_time == reviewed and existing[0] != message['label']:
                        raise ValueError('Conflicting labels at the same review time')
                db.execute('INSERT INTO review_labels VALUES(?,?,?,?,?) ON CONFLICT(window_end) DO UPDATE SET '
                           'label=excluded.label, revision=excluded.revision, reviewed_at=excluded.reviewed_at, reviewer_id=excluded.reviewer_id',
                           (str(window), message['label'], revision, reviewed_text, message['reviewer_id']))
                db.execute('INSERT INTO review_changes VALUES(?,?,?)', (revision, str(window), message['label']))
                applied += 1
        return {'status': 'applied', 'revision': revision, 'applied_rows': applied, 'label': message['label']}

    def labels(self):
        return self.snapshot()[0]

    def snapshot(self):
        with self.connect() as db:
            db.execute('BEGIN')
            labels = pd.read_sql_query('SELECT * FROM review_labels ORDER BY window_end', db)
            revision = int(db.execute('SELECT COALESCE(MAX(revision), 0) FROM feedback').fetchone()[0])
        return labels, revision

    def reviewed_frame(self, frame, labels=None):
        result = frame.copy()
        labels = (self.labels() if labels is None else labels).set_index('window_end')['label']
        mapped = result['window_end'].map(labels)
        result.loc[mapped.eq('normal') & result['history_complete'].eq(1), 'review_status'] = 'reviewed_normal'
        result.loc[mapped.eq('repetitive'), 'review_status'] = 'excluded'
        result.loc[mapped.eq('uncertain'), 'review_status'] = 'quarantined'
        return result

    def invalidates(self, pointer, manifest):
        splits = manifest.get('splits', {})
        if 'train' not in splits or 'test' not in splits:
            return False
        with self.connect() as db:
            row = db.execute('SELECT 1 FROM review_changes WHERE revision>? AND label!=? '
                             'AND window_end>=? AND window_end<=? LIMIT 1',
                             (pointer.get('feedback_revision', 0), 'normal', splits['train']['start'], splits['test']['end'])).fetchone()
        return row is not None

    def prune_retired_context(self):
        with sqlite3.connect(self.root / 'history.sqlite3') as history:
            oldest = history.execute('SELECT MIN(window_end) FROM observations').fetchone()[0]
        if oldest is not None:
            with self.connect() as db:
                db.execute('DELETE FROM event_context WHERE window_end<?', (oldest,))
                db.execute('DELETE FROM review_labels WHERE window_end<?', (oldest,))

                db.execute('DELETE FROM review_changes WHERE window_end<? AND label=?', (oldest, 'normal'))

    def drain_inbox(self, now=None):
        inbox = self.root / 'feedback_inbox'
        inbox.mkdir(exist_ok=True)
        counts = {'applied': 0, 'duplicate': 0, 'rejected': 0}
        for path in sorted(inbox.glob('*.json'))[:100]:
            try:
                if path.is_symlink() or path.stat().st_size > 16384:
                    raise ValueError('Feedback file is a link or exceeds the size limit')
                result = self.apply(json.loads(path.read_text(encoding='utf-8-sig')), now)
                category = 'processed'
                counts[result['status']] += 1
            except Exception as error:
                result = {'status': 'rejected', 'reason': type(error).__name__,
                          'message': 'schema_validation_failed' if isinstance(error, ValidationError) else str(error)[:500]}
                category = 'rejected'
                counts['rejected'] += 1
            archive = inbox / category
            archive.mkdir(exist_ok=True)
            path.replace(archive / (path.stem + '_' + uuid.uuid4().hex + '.json'))
            with (self.root / 'feedback_inbox_audit.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(canonical({'file': path.name, **result}) + '\n')
        return counts


def queue_review(root, message):
    root = Path(root)
    identity = json.loads((root / 'identity.json').read_text(encoding='utf-8'))
    payload_validator(SCHEMA).validate(message)
    if message['source_type'] != identity['source_type'] or message['household_id'] != identity['household_id']:
        raise ValueError('Feedback queue identity mismatch')
    body = canonical(message).encode('utf-8')
    if len(body) > 16384:
        raise ValueError('Feedback exceeds the size limit')
    inbox = root / 'feedback_inbox'
    inbox.mkdir(exist_ok=True)
    if sum(1 for _ in inbox.glob('*.json')) >= 1000:
        raise ValueError('Feedback inbox is full; inspect the consumer before retrying')
    name = hashlib.sha256(message['feedback_id'].encode()).hexdigest()[:24]
    path = inbox / (name + '_' + uuid.uuid4().hex + '.json')
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    return {'status': 'queued_not_yet_applied', 'feedback_id': message['feedback_id']}
