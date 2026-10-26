
import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid

import pandas as pd
from ha_model_lifecycle import atomic_json, store_frame
from ha_runtime_health import load_baseline, selection_identity, check_runtime_identity, validate_selection, validate_cycle

BASE = Path(__file__).resolve().parents[1]


def stop_process(process):
    if process.poll() is not None:
        return
    try:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        process.wait()
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()


def run_analysis(command, output_path, heartbeat, should_stop, timeout=900):
    with Path(output_path).open('w', encoding='utf-8') as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=os.name == 'posix',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        began = time.monotonic()
        try:
            while process.poll() is None:
                heartbeat()
                if should_stop():
                    return 130
                if time.monotonic() - began > timeout:
                    return 124
                time.sleep(1)
            return process.returncode
        finally:
            stop_process(process)


def snapshot_raw(path, destination, end):

    with path.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = [row for row in reader if None not in row and all(v is not None for v in row.values())]
    frame = pd.DataFrame(rows, columns=fields)
    if not frame.empty:
        times = pd.to_datetime(frame['recorded_at'], utc=True, errors='coerce')
        cutoff = end - pd.Timedelta(hours=3)
        before = frame.loc[times < cutoff].groupby('entity_id', sort=False).tail(1).copy()
        before['record_type'], before['recorded_at'] = 'state_snapshot', cutoff.isoformat()
        frame = pd.concat([before, frame.loc[times.between(cutoff, end)]], ignore_index=True)
    frame.to_csv(destination, index=False)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir', default='runtime/local')
    p.add_argument('--household-id', required=True)
    p.add_argument('--cycle-seconds', type=float, default=600)
    p.add_argument('--max-cycles', type=int, default=0)
    p.add_argument('--allow-screened-training', action='store_true')
    p.add_argument('--model-policy', choices=['shadow', 'hybrid'], default='shadow')
    p.add_argument('--retrain-days', type=float, default=0)
    p.add_argument('--publish-mqtt', action='store_true', help='Opt-in current-decision delivery; no second collector')
    p.add_argument('--mqtt-dry-run', action='store_true')
    p.add_argument('--receive-feedback', action='store_true', help='Opt-in explicit behavior reviews from a trusted MQTT broker')
    p.add_argument('--allow-insecure-feedback-test-broker', action='store_true')
    p.add_argument('--personalize', action=argparse.BooleanOptionalAction, default=True)
    p.add_argument('--patient-id', default='byunwoojin')
    p.add_argument('--device-id', default='pi5-home-01')
    p.add_argument('--entity-keyword', action='append', default=[])
    p.add_argument('--entity-id', action='append', default=[])
    p.add_argument('--exclude-entity-id', action='append', default=[])
    p.add_argument('--baseline', default='models/user_001_real_baseline_v2.json')
    args = p.parse_args()
    if not 10 <= args.cycle_seconds <= 3600:
        p.error('cycle-seconds must be at least 10')
    if not 0 <= args.retrain_days <= 365:
        p.error('retrain-days must be finite and in 0..365')
    if args.receive_feedback and not args.allow_insecure_feedback_test_broker and (not os.getenv('MQTT_USER') or not os.getenv('MQTT_PASSWORD')):
        p.error('Authenticated MQTT_USER/MQTT_PASSWORD and broker ACLs are required for feedback')
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
    root = Path(args.state_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    baseline = Path(args.baseline)
    baseline = baseline if baseline.is_absolute() else BASE / baseline
    try:
        load_baseline(baseline)
        validate_selection(args.entity_id, args.exclude_entity_id)
    except (ValueError, OSError) as error:
        atomic_json(root / 'service_status.json', {'status':'configuration_error',
                    'reason':str(error), 'utc':datetime.now(timezone.utc).isoformat()})
        raise

    import fcntl
    lock = (root / 'service.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    identity = selection_identity(args.household_id, baseline, args.entity_id, args.exclude_entity_id, args.entity_keyword)
    try:
        check_runtime_identity(root, identity)
    except (ValueError, OSError) as error:
        atomic_json(root / 'service_status.json', {'status':'configuration_error',
                    'reason':str(error), 'utc':datetime.now(timezone.utc).isoformat()})
        lock.close()
        raise
    stopped = False

    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    raw = root / 'live_events.csv'
    if raw.exists():
        snapshot_raw(raw, root / 'trimmed.csv', pd.Timestamp.now(tz='UTC'))
        (root / 'trimmed.csv').replace(raw)
    collector_cmd = [sys.executable, '-u', str(BASE / 'src/collect_ha_events_ws.py'),
                     '--output', str(raw), '--write-initial-snapshot']
    for keyword in args.entity_keyword:
        collector_cmd += ['--entity-keyword', keyword]
    selection_args = []
    for flag, values in [('--entity-id', args.entity_id), ('--exclude-entity-id', args.exclude_entity_id)]:
        for value in values:
            selection_args += [flag, value]
    collector_cmd += selection_args
    collector = None
    feedback_reader = None
    cycles = 0
    completed = False
    cursor_path = root / 'cursor.json'
    start = json.loads(cursor_path.read_text())['end'] if cursor_path.exists() else datetime.now(timezone.utc).isoformat()
    current_status = {'status':'starting', 'cycle_seconds':args.cycle_seconds}
    last_heartbeat = 0
    last_collector_start = 0
    last_feedback_start = 0
    log = None
    feedback_log = None
    feedback_cmd = [sys.executable, '-u', str(BASE / 'src/receive_ha_behavior_feedback.py'),
                    '--lifecycle-dir', str(root / 'models')]
    if args.allow_insecure_feedback_test_broker:
        feedback_cmd.append('--allow-insecure-test-broker')

    def heartbeat(force=False):
        nonlocal last_heartbeat, last_collector_start, collector, feedback_reader, last_feedback_start
        if (not stopped and log is not None and not log.closed and
                (collector is None or collector.poll() is not None) and time.monotonic() - last_collector_start >= 15):
            collector = subprocess.Popen(collector_cmd, stdout=log, stderr=subprocess.STDOUT)
            last_collector_start = time.monotonic()
            current_status['collector_starts'] = current_status.get('collector_starts', 0) + 1
        if (args.receive_feedback and not stopped and feedback_log is not None and not feedback_log.closed
                and (root / 'models/identity.json').exists()
                and (feedback_reader is None or feedback_reader.poll() is not None)
                and time.monotonic() - last_feedback_start >= 15):
            feedback_reader = subprocess.Popen(feedback_cmd, stdout=feedback_log, stderr=subprocess.STDOUT)
            last_feedback_start = time.monotonic()
        if force or time.monotonic() - last_heartbeat >= 15:
            current_status.update(utc=datetime.now(timezone.utc).isoformat(),
                                  collector_running=collector is not None and collector.poll() is None,
                                  feedback_receiver_enabled=args.receive_feedback,
                                  feedback_receiver_running=feedback_reader is not None and feedback_reader.poll() is None)
            atomic_json(root / 'service_status.json', current_status)
            last_heartbeat = time.monotonic()

    def report(**values):
        if 'status' in values and 'reason' not in values:
            current_status.pop('reason', None)
        current_status.update(values)
        heartbeat(True)

    try:
        if (root / 'collector.log').exists() and (root / 'collector.log').stat().st_size > 5 * 1024**2:
            (root / 'collector.log').replace(root / 'collector.previous.log')
        if (root / 'feedback.log').exists() and (root / 'feedback.log').stat().st_size > 5 * 1024**2:
            (root / 'feedback.log').replace(root / 'feedback.previous.log')
        with (root / 'collector.log').open('a', encoding='utf-8') as log, (root / 'feedback.log').open('a', encoding='utf-8') as feedback_log:
            while not stopped and (args.max_cycles == 0 or cycles < args.max_cycles):
                heartbeat(True)
                interval = args.cycle_seconds if completed else min(args.cycle_seconds, 60)
                until = time.monotonic() + interval
                while not stopped and time.monotonic() < until:
                    heartbeat()
                    time.sleep(min(1, max(0, until - time.monotonic())))
                if stopped:
                    break
                if shutil.disk_usage(root).free < 64 * 1024 * 1024:
                    report(status='low_disk')
                    raise RuntimeError('Less than 64 MiB free; stopping to protect persistent storage')
                coverage_path = raw.with_suffix('.coverage.json')
                if collector is None or collector.poll() is not None or not raw.exists() or not coverage_path.exists():
                    report(status='waiting_for_ha')
                    cycles += 1
                    continue
                try:
                    coverage = json.loads(coverage_path.read_text())
                    confirmed = pd.Timestamp(coverage['confirmed_at'])
                    if confirmed.tzinfo is None or not 0 <= (pd.Timestamp.now(tz='UTC') - confirmed).total_seconds() <= 40:
                        raise ValueError('Unconfirmed HA clock/connection')
                except (ValueError, KeyError, OSError):
                    report(status='ha_disconnected')
                    cycles += 1
                    continue
                end = confirmed.floor('min')
                if end <= pd.Timestamp(start):
                    cycles += 1
                    continue

                start = max(pd.Timestamp(start), end - pd.Timedelta(hours=3)).isoformat()
                snapshot_raw(raw, root / 'cycle.csv', end)
                atomic_json(root / 'cycle.coverage.json', coverage)
                run_id = uuid.uuid4().hex
                cmd = [sys.executable, '-u', str(BASE / 'src/run_ha_pipeline.py'), '--input', str(root / 'cycle.csv'),
                       '--baseline', str(baseline), '--run-id', run_id,
                       '--data-source', 'local', '--household-id', args.household_id,
                       '--window-start', start, '--window-end', end.isoformat(),
                       '--coverage-file', str(root / 'cycle.coverage.json'),
                       '--event-history', str(root / 'event_context.csv'), '--prefix', 'ha_live_full',
                       '--lifecycle-dir', str(root / 'models'), '--model-policy', args.model_policy]
                cmd += ['--retrain-days', str(args.retrain_days)]
                if not args.personalize:
                    cmd.append('--no-personalize')
                cmd += selection_args
                if args.allow_screened_training:
                    cmd.append('--allow-screened-training')
                if selection_identity(args.household_id, baseline, args.entity_id, args.exclude_entity_id, args.entity_keyword) != identity:
                    report(status='configuration_error', reason='Baseline changed during service; restart with a new state directory')
                    raise ValueError('Baseline changed during service')
                report(status='analyzing', run_id=run_id, start=start, end=end.isoformat())
                code = run_analysis(cmd, root / 'last_pipeline.log', heartbeat, lambda: stopped)
                status = {'status': 'ok' if code == 0 else 'pipeline_failed', 'exit_code': code,
                          'start': start, 'end': end.isoformat(), 'collector_running': collector.poll() is None,
                          'utc': datetime.now(timezone.utc).isoformat()}
                if code == 0:
                    try:
                        quality, current = validate_cycle(BASE / 'outputs', 'ha_live_full', run_id)
                        learning_path = root / 'models/status.json'
                        learning = json.loads(learning_path.read_text()) if learning_path.exists() else {}
                        store_frame(root / 'decisions.sqlite3', current)
                        status.update(data_quality=quality['status'], observation=quality.get('observation'),
                                      learning_status=learning.get('status', 'unknown'), eligible_days=learning.get('observed_days'),
                                      last_success_utc=datetime.now(timezone.utc).isoformat())
                        if args.publish_mqtt:
                            atomic_json(root / 'current_decision.json', json.loads(current.tail(1).to_json(orient='records'))[0])
                            delivery_cmd = [sys.executable, '-u', str(BASE / 'src/ha_decision_delivery.py'),
                                            '--input', str(root / 'current_decision.json'),
                                            '--state-file', str(root / 'delivery_state.json'),
                                            '--status-file', str(root / 'delivery_status.json'),
                                            '--lifecycle-dir', str(root / 'models'),
                                            '--patient-id', args.patient_id, '--device-id', args.device_id]
                            if args.mqtt_dry_run:
                                delivery_cmd.append('--dry-run')
                            delivery_code = run_analysis(delivery_cmd, root / 'last_delivery.log', heartbeat,
                                                         lambda: stopped, timeout=45)
                            status['mqtt_delivery_exit_code'] = delivery_code
                            status['mqtt_delivery'] = 'checked' if delivery_code == 0 else 'failed_pending_retry'
                    except (ValueError, KeyError, OSError, sqlite3.Error) as error:
                        code = 65
                        status.update(status='invalid_artifacts', exit_code=code, reason=type(error).__name__)
                if code == 0:
                    completed = True
                    start = end.isoformat()
                    atomic_json(cursor_path, {'end': start})
                status['run_id'] = run_id
                report(**status)
                print(json.dumps(status), flush=True)
                cycles += 1
                if (raw.stat().st_size > 10 * 1024**2 or (root / 'collector.log').stat().st_size > 5 * 1024**2
                        or (root / 'feedback.log').stat().st_size > 5 * 1024**2):


                    break
    finally:
        if feedback_reader is not None and feedback_reader.poll() is None:
            feedback_reader.terminate()
            try:
                feedback_reader.wait(timeout=5)
            except subprocess.TimeoutExpired:
                feedback_reader.kill()
                feedback_reader.wait()
        if collector is not None and collector.poll() is None:
            collector.terminate()
            try:
                collector.wait(timeout=5)
            except subprocess.TimeoutExpired:
                collector.kill()
                collector.wait()
        report(status='stopped' if stopped else current_status.get('status', 'stopped'))
        lock.close()


if __name__ == '__main__':
    main()
