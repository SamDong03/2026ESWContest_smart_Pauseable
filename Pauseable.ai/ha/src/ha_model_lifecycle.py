
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
import zlib

import numpy as np
import pandas as pd

from ha_anomaly_models import score_frame, sha256, unavailable
from train_ha_anomaly_models import train_models
from ha_repetition_policy import evidence_frame, family
from ha_behavior_feedback import FeedbackStore
from ha_personal_routine import fit_routine, PersonalRoutine
from ha_observation_reader import read_observations

SCHEMA = 'ha_behavior_v3'
META = ['source_type', 'household_id', 'schema_version']


def store_frame(path, frame):
    if frame.empty:
        return
    cutoff = (pd.to_datetime(frame['window_end']).max() - pd.Timedelta(days=45)).strftime('%Y-%m-%d %H:%M:%S')
    with sqlite3.connect(path) as database:
        database.execute('CREATE TABLE IF NOT EXISTS observations (window_end TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        for offset in range(0, len(frame), 512):
            records = json.loads(frame.iloc[offset:offset+512].to_json(orient='records'))
            database.executemany('INSERT INTO observations VALUES (?, ?) ON CONFLICT(window_end) DO UPDATE SET payload=excluded.payload',
                                 [(item['window_end'], zlib.compress(json.dumps(item, allow_nan=False, separators=(',', ':')).encode('utf-8')))
                                  for item in records])
        database.execute('DELETE FROM observations WHERE window_end < ?', (cutoff,))


def load_frame(path):
    return read_observations(path)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    temp.replace(path)
    if os.name == 'posix':
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class Lifecycle:
    def __init__(self, root, source, household, allow_screened=False, policy='shadow', retrain_days=0):
        self.root = Path(root)
        self.source, self.household = source, household
        self.allow_screened, self.policy = allow_screened, policy
        if not np.isfinite(retrain_days) or retrain_days < 0:
            raise ValueError('retrain_days must be finite and non-negative')
        self.retrain_days = float(retrain_days)
        if source not in ('local', 'synthetic') or not household.strip() or policy not in ('shadow', 'hybrid'):
            raise ValueError('Specify local/synthetic provenance, household and a valid policy')
        self.root.mkdir(parents=True, exist_ok=True)
        identity = {'source_type': source, 'household_id': household, 'schema_version': SCHEMA}
        path = self.root / 'identity.json'
        if path.exists() and json.loads(path.read_text()) != identity:
            raise ValueError('Lifecycle store belongs to a different source, household or schema')
        atomic_json(path, identity)
        self.feedback = FeedbackStore(self.root, source, household)

    def log(self, status, **details):
        data = {'utc': datetime.now(timezone.utc).isoformat(), 'status': status, **details}
        with (self.root / 'lifecycle.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(data, allow_nan=False) + '\n')
        atomic_json(self.root / 'status.json', data)
        return data

    def ingest(self, frame, rule_result):
        for name, expected in zip(META, (self.source, self.household, SCHEMA)):
            if name not in frame or not frame[name].eq(expected).all():
                raise ValueError('History provenance mismatch: ' + name)
        if frame.empty:
            return
        if frame['window_end'].duplicated().any():
            raise ValueError('Duplicate feature timestamps')
        current = frame.copy()
        levels = rule_result.set_index('window_end')['level']
        approved = current['window_end'].map(levels).eq('normal') & current['history_complete'].eq(1)
        existing_review = current.get('review_status', pd.Series('', index=current.index))
        current['review_status'] = np.where(current['history_complete'].eq(1) & existing_review.eq('reviewed_normal') & (self.source == 'synthetic'),
                                            'reviewed_normal', np.where(approved, 'baseline_screened', 'excluded'))
        current = self.feedback.reviewed_frame(current)
        path = self.root / 'history.sqlite3'
        previous = read_observations(path, limit=1) if path.exists() else current.iloc[:0]
        if set(previous.columns) != set(current.columns):
            raise ValueError('History feature schema changed')
        store_frame(path, current)
        self.feedback.prune_retired_context()

    def active_dir(self):
        pointer = self.root / 'active.json'
        if not pointer.exists():
            return None
        data = json.loads(pointer.read_text())
        return self.pointer_dir(data)

    def pointer_dir(self, data):
        if data['source_type'] != self.source or data['household_id'] != self.household:
            raise ValueError('Active pointer provenance mismatch')
        path = (self.root / data['directory']).resolve()
        if not path.is_relative_to((self.root / 'versions').resolve()):
            raise ValueError('Active model path escapes version store')
        if sha256(path / 'manifest.json') != data['manifest_sha256']:
            raise ValueError('Active model manifest checksum mismatch')
        manifest = json.loads((path / 'manifest.json').read_text())
        if self.feedback.invalidates(data, manifest):
            raise ValueError('A later behavior review invalidates this model training cohort')
        if manifest.get('optimizer_converged') is False or manifest.get('training_warnings'):
            raise ValueError('Active model has unresolved training warnings')
        if sha256(path / 'isolation_forest.joblib') != manifest['forest_sha256']:
            raise ValueError('Active forest checksum mismatch')
        return path

    def rollback(self, reason):
        if not str(reason).strip():
            raise ValueError('An explicit rollback reason is required')
        previous = json.loads((self.root / 'previous.json').read_text())
        self.pointer_dir(previous)
        current = json.loads((self.root / 'active.json').read_text())
        self.pointer_dir(current)
        previous['activated_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(self.root / 'active.json', previous)

        return self.log('rolled_back', model_id=previous['model_id'],
                        replaced_model_id=current['model_id'], reason=str(reason))

    def maybe_train(self, now=None):
        now = pd.Timestamp(now or datetime.now(timezone.utc))
        now = now.tz_localize('UTC') if now.tzinfo is None else now.tz_convert('UTC')
        previous = None
        if (self.root / 'active.json').exists():
            try:
                self.active_dir()
                previous = json.loads((self.root / 'active.json').read_text())
            except Exception as error:
                (self.root / 'active.json').replace(self.root / ('invalid_pointer_' + uuid.uuid4().hex + '.json'))
                self.log('fallback', reason=type(error).__name__)
        if previous is not None:
            if not self.retrain_days:
                return self.log('active', policy=self.policy, source_type=self.source,
                                model_id=previous['model_id'], retraining='disabled')
            if 'activated_at' not in previous or 'trained_through' not in previous:
                manifest = json.loads((self.active_dir() / 'manifest.json').read_text())
                previous.update(activated_at=now.isoformat(), trained_through=manifest['splits']['test']['end'])
                atomic_json(self.root / 'active.json', previous)
            age = (now - pd.Timestamp(previous['activated_at'])).total_seconds()
            if age < self.retrain_days * 86400:
                return self.log('active', model_id=previous['model_id'], retraining='not_due')
        path = self.root / 'history.sqlite3'
        if not path.exists():
            return self.log('collecting', observed_days=0)
        frame = load_frame(path)
        times = pd.to_datetime(frame['window_end'], utc=True, errors='raise')
        local_now = now.tz_convert(os.getenv('HA_TIMEZONE', 'Asia/Seoul')).tz_localize(None)
        if (times.dt.tz_localize(None) > local_now).any():
            return self.log('rejected', reason='future_data')
        for name, expected in zip(META, (self.source, self.household, SCHEMA)):
            if not frame[name].eq(expected).all():
                return self.log('rejected', reason='history_provenance')
        labels, feedback_revision = self.feedback.snapshot()
        frame = self.feedback.reviewed_frame(frame, labels)
        accepted = frame['review_status'].eq('reviewed_normal')
        if self.allow_screened or self.source == 'synthetic':
            accepted |= frame['review_status'].eq('baseline_screened')
        accepted &= frame['history_complete'].eq(1)
        if previous is not None:
            new = times.dt.tz_localize(None) > pd.Timestamp(previous['trained_through']).tz_localize(None)
            new_hours = times[accepted & new].dt.floor('h').nunique()
            if new_hours < 24:
                return self.log('active', model_id=previous['model_id'], retraining='waiting_for_new_data',
                                new_eligible_hours=int(new_hours), required_new_hours=24)

        hours = times[accepted].dt.floor('h').drop_duplicates()
        daily = hours.groupby(hours.dt.date).size()
        days = int((daily >= 12).sum())
        if days < 30 or len(hours) < 360:
            return self.log('collecting', observed_days=days, required_days=30,
                            accepted_rows=int(accepted.sum()), allow_screened=self.allow_screened)
        last_attempt = self.root / 'attempt.json'
        day = now.date().isoformat()
        if last_attempt.exists() and json.loads(last_attempt.read_text()).get('day') == day:
            return self.log('retry_deferred', reason='at most one training attempt per day')
        if shutil.disk_usage(self.root).free < 64 * 1024 * 1024:
            return self.log('deferred', reason='less than 64 MiB free; baseline retained')
        atomic_json(last_attempt, {'day': day})
        version = self.root / 'versions' / uuid.uuid4().hex
        version.mkdir(parents=True)
        indices = np.flatnonzero(accepted.to_numpy())

        if len(indices) > 6000:
            indices = indices[np.linspace(0, len(indices) - 1, 6000, dtype=int)]
        training = frame.iloc[indices].copy()
        training_path = version / 'training.csv'
        training.to_csv(training_path, index=False)
        model_dir = version / 'bundle'
        try:
            self.log('training', observed_days=days, rows=len(training), directory=str(version.name))
            manifest, validation = train_models(training_path, model_dir, self.source, self.household,
                'synthetic scenario normal periods' if self.source == 'synthetic' else
                ('complete windows screened by baseline; not human-labelled truth' if self.allow_screened else
                 'human reviewed normal periods'), min_days=30, allow_screened_normal=self.allow_screened)
            self.log('validating', model_id=manifest['model_id'])
            if manifest.get('optimizer_converged') is False or manifest.get('training_warnings'):
                return self.log('rejected', reason='training_warnings', model_id=manifest['model_id'],
                                warnings=manifest.get('training_warnings', []))
            rate = validation['normal_holdout_alert_fraction']['or']
            probe = score_frame(training.tail(1), model_dir)
            if not np.isfinite(rate) or rate > .15 or not probe['model_status'].eq('shadow').all():
                return self.log('rejected', reason='validation_gate', assumed_normal_alert_fraction=rate)
            pointer = {
                'directory': model_dir.relative_to(self.root).as_posix(),
                'manifest_sha256': sha256(model_dir / 'manifest.json'),
                'source_type': self.source, 'household_id': self.household,
                'policy': self.policy, 'model_id': manifest['model_id'],
                'activated_at': now.isoformat(), 'trained_through': str(training['window_end'].max()),
                'feedback_revision': feedback_revision}

            self.pointer_dir(pointer)
            if previous is not None:
                atomic_json(self.root / 'previous.json', previous)
            atomic_json(self.root / 'active.json', pointer)
            return self.log('active', model_id=manifest['model_id'], policy=self.policy,
                            source_type=self.source, assumed_normal_alert_fraction=rate)
        except Exception as error:
            return self.log('training_failed', reason=type(error).__name__, message=str(error))

    def score(self, frame):
        try:
            path = self.active_dir()
            if path is None:
                return unavailable(frame, 'not_trained', 'Baseline until 30 eligible days and validation')
            return score_frame(frame, path)
        except Exception as error:
            return unavailable(frame, 'invalid_model', f'Baseline fallback: {type(error).__name__}')

    def routine_policy(self, before):
        labels, revision = self.feedback.snapshot()
        profile = fit_routine(self.feedback.history(), labels, before, self.source, self.household, revision)
        atomic_json(self.root / 'routine_profile.json', profile)
        return PersonalRoutine(profile, labels, self.source, self.household, self.feedback)


def combine(rules, models, policy='shadow', features=None, routine=None):
    result = rules.rename(columns={'level': 'rule_level', 'risk_score': 'rule_score'}).merge(
        models, on='window_end', how='left', validate='one_to_one')
    result['level'], result['risk_score'] = result['rule_level'], result['rule_score']
    for column in ('primary_pattern', 'reasons'):
        if column not in result:
            result[column] = ''
        result[column] = result[column].fillna('').astype('string')
    result['decision_policy'] = 'rules_with_shadow_models'
    if features is not None:
        result = result.merge(evidence_frame(features), on='window_end', how='left', validate='one_to_one')
        if result['repetition_observed'].isna().any():
            raise ValueError('Repetition evidence is missing for decision timestamps')

        result['raw_rule_level'], result['raw_rule_score'] = result['rule_level'], result['rule_score']
        unsupported = ~result['repetition_observed'] & result['level'].isin(['attention', 'risk'])
        for index, row in result.iterrows():
            pattern = family(str(row.get('primary_pattern') or ''))
            observed = str(row['repetition_patterns']).split('|')
            if row['level'] in {'attention', 'risk'} and pattern and pattern != 'feature_anomaly' and pattern not in observed:
                unsupported.at[index] = True
        result.loc[unsupported, 'level'] = 'normal'
        result.loc[unsupported, 'risk_score'] = 0
        result.loc[unsupported, 'reasons'] = 'No observable repetition; anomaly retained for audit only'
    else:
        result['repetition_observed'] = False
        result['repetition_patterns'], result['repetition_pattern'], result['protected_rule'] = '', '', ''
    if policy == 'hybrid':
        ready = result['model_status'].eq('shadow') & result['repetition_observed']
        attention = ready & (result['ae_level'].isin(['attention', 'risk']) | result['if_level'].isin(['attention', 'risk']))
        risk = ready & result['ae_level'].eq('risk') & result['if_level'].eq('risk')
        promote = attention & result['level'].eq('normal')
        result.loc[promote, 'level'] = 'attention'
        result.loc[promote, 'risk_score'] = 35
        promote_risk = risk & result['level'].ne('risk')
        result.loc[promote_risk, 'level'] = 'risk'
        result.loc[promote_risk, 'risk_score'] = np.maximum(result.loc[promote_risk, 'risk_score'], 70)
        result.loc[promote | promote_risk, 'primary_pattern'] = result.loc[promote | promote_risk, 'repetition_pattern']
        mask = promote | promote_risk
        result.loc[mask, 'reasons'] = result.loc[mask, 'reasons'].map(
            lambda reason: '; '.join(filter(None, [reason, 'Learned model alert; not a medical diagnosis'])))
        result.loc[ready, 'decision_policy'] = 'rules_plus_validated_if_ae'
    result['model_only_anomaly_held'] = ~result['repetition_observed'] & (
        result['ae_level'].isin(['attention', 'risk']) | result['if_level'].isin(['attention', 'risk']))
    if routine is not None and features is not None and policy == 'hybrid':
        result = routine.apply(result, features)
    return result
