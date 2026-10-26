
import hashlib
import json
import os

import numpy as np
import pandas as pd

from ha_behavior_feedback import local_time
from ha_repetition_policy import family, observed_patterns, protected_rule

MIN_DAYS = 3
MIN_SAMPLES = 6
MAX_AGE_DAYS = 14


def context(stamp):
    stamp = local_time(stamp)
    return f'{stamp.weekday()}:{stamp.hour // 4}'


def fit_routine(frame, labels, before, source, household, revision):
    cutoff = local_time(before)
    result = {'format': 'ha_reviewed_routine_v1', 'source_type': source, 'household_id': household,
              'feedback_revision': revision, 'fit_before': str(cutoff), 'profiles': {},
              'minimum_days': MIN_DAYS, 'minimum_half_hour_samples': MIN_SAMPLES,
              'clinical_validation': False}
    if frame.empty or labels.empty:
        result['profile_id'] = 'no-reviewed-routine'
        return result
    reviewed = labels.loc[labels['label'].eq('normal')].copy()
    reviewed_times = pd.to_datetime(reviewed['reviewed_at'], utc=True).dt.tz_convert(os.getenv('HA_TIMEZONE', 'Asia/Seoul')).dt.tz_localize(None)
    reviewed = reviewed.loc[reviewed_times <= cutoff]
    eligible = frame.loc[frame['window_end'].isin(reviewed['window_end']) & frame['history_complete'].eq(1)].copy()
    times = pd.to_datetime(eligible['window_end'])
    eligible = eligible.loc[(times < cutoff) & (times >= cutoff - pd.Timedelta(days=45))].copy()
    if not eligible['source_type'].eq(source).all() or not eligible['household_id'].eq(household).all():
        raise ValueError('Routine history provenance mismatch')
    columns = [name for name in eligible if '_count_' in name]
    result['count_features'] = columns
    if not columns:
        result['profile_id'] = 'no-reviewed-routine'
        return result
    values = eligible[columns].apply(pd.to_numeric, errors='coerce')
    valid = np.isfinite(values).all(axis=1) & values.ge(0).all(axis=1)
    eligible = eligible.loc[valid].sort_values('window_end')
    groups = {}
    for values in eligible.itertuples(index=False, name=None):
        row = dict(zip(eligible.columns, values))
        stamp = local_time(row['window_end'])
        for pattern in observed_patterns(row):
            if protected_rule(row):
                continue
            key = context(stamp) + ':' + pattern

            groups.setdefault(key, {})[str(stamp.floor('30min'))] = row
    for key, buckets in groups.items():
        samples = pd.DataFrame(list(buckets.values()))
        days = pd.to_datetime(samples['window_end']).dt.date.nunique()
        if days < MIN_DAYS or len(samples) < MIN_SAMPLES:
            continue
        result['profiles'][key] = {
            'samples': len(samples), 'days': int(days),
            'last_observed': str(samples['window_end'].max()),
            'limits': {name: float(samples[name].quantile(.95)) for name in columns},
            'examples': [
                {'day': str(local_time(row['window_end']).date()), 'values': [float(row[name]) for name in columns]}
                for row in samples.drop_duplicates(subset=columns + ['window_end']).to_dict('records')],
        }
    result['profile_id'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:24]
    return result


class PersonalRoutine:
    def __init__(self, profile, labels, source, household, feedback=None):
        if profile.get('source_type') != source or profile.get('household_id') != household:
            raise ValueError('Routine profile identity mismatch')
        self.profile, self.source, self.household = profile, source, household
        self.feedback = feedback
        self.labels = labels.set_index('window_end')['label'].to_dict() if not labels.empty else {}

    def apply(self, decisions, features):
        result = decisions.copy()
        result['pre_personal_level'], result['pre_personal_score'] = result['level'], result['risk_score']
        result['personalization_status'] = 'no_reviewed_routine'
        result['routine_profile_id'] = self.profile['profile_id']
        result['feedback_revision'] = self.profile['feedback_revision']
        if self.feedback is not None and self.feedback.revision() != self.profile['feedback_revision']:
            result['personalization_status'] = 'feedback_changed_retry_next_cycle'
            return result
        indexed = features.set_index('window_end')
        for index, decision in result.iterrows():
            if decision['level'] not in {'attention', 'risk'}:
                continue
            row = indexed.loc[decision['window_end']].to_dict()
            row['window_end'] = decision['window_end']
            if row.get('source_type') != self.source or row.get('household_id') != self.household:
                raise ValueError('Decision/profile provenance mismatch')
            if row.get('history_complete') != 1:
                result.at[index, 'personalization_status'] = 'incomplete_history'
                continue
            if self.labels.get(str(decision['window_end'])) in {'repetitive', 'uncertain'}:
                result.at[index, 'personalization_status'] = 'review_blocks_suppression'
                continue
            if protected_rule(row):
                result.at[index, 'personalization_status'] = 'protected_rule_preserved'
                continue
            stamp = local_time(decision['window_end'])
            if stamp < local_time(self.profile['fit_before']):
                result.at[index, 'personalization_status'] = 'profile_not_causal'
                continue
            patterns = observed_patterns(row)

            matched = bool(patterns)
            for pattern in patterns:
                key = context(stamp) + ':' + family(pattern)
                profile = self.profile['profiles'].get(key)
                if profile is None or stamp - local_time(profile['last_observed']) > pd.Timedelta(days=MAX_AGE_DAYS):
                    matched = False
                    break
                for name, limit in profile['limits'].items():
                    try:
                        value = float(row[name])
                    except (KeyError, ValueError, TypeError):
                        matched = False
                        break
                    if not np.isfinite(value) or value < 0 or value > limit:
                        matched = False
                        break
                if matched:
                    columns = self.profile['count_features']
                    current = np.asarray([float(row[name]) for name in columns])
                    supporting_days = {example['day'] for example in profile['examples']
                                       if np.greater_equal(np.asarray(example['values']), current).all()}
                    if len(supporting_days) < 2:
                        matched = False
                if not matched:
                    break
            if not matched:
                continue
            normal_models = (decision.get('model_status') == 'shadow' and decision.get('model_source') == self.source
                             and decision.get('ae_level') == 'normal' and decision.get('if_level') == 'normal')
            if not normal_models:
                result.at[index, 'personalization_status'] = 'routine_found_models_not_normal'
                continue
            result.at[index, 'level'], result.at[index, 'risk_score'] = 'normal', 0
            result.at[index, 'personalization_status'] = 'reviewed_routine_confirmed_by_models'
            result.at[index, 'decision_policy'] = 'reviewed_routine_with_validated_if_ae'
            result.at[index, 'reasons'] = str(decision.get('reasons') or '') + '; Reviewed past routine and both models normal; advisory alert cleared'
        return result
