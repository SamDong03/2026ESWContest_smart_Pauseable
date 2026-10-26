

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid
from urllib.request import Request, urlopen

import joblib
import numpy as np
import sklearn

from features import FEATURE_NAMES, extract_features
from personal_baseline import PersonalBaseline
from personal_records import FEATURE_SCHEMA, utc_time
from score_windows import DEFAULT_MODEL, WindowScorer, event_windows
from temporal_evidence import EvidencePolicy, advance_evidence
from trajectory_windows import TrajectoryWindows, demo_event


POLICY = {
    **asdict(EvidencePolicy()),
    "cooldown_seconds": 300,
    "baseline_max_days": 30,
}


VERSIONS = {
    "sklearn": sklearn.__version__,
    "numpy": np.__version__,
    "joblib": joblib.__version__,
    "features": FEATURE_SCHEMA,
}


def js(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(js(value).encode()).hexdigest()


class Flow:
    pass

    def __init__(self, connection, scorer):
        self.db = connection
        self.scorer = scorer
        self.cache = {}

        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(
          k TEXT PRIMARY KEY,
          v TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS windows(
          id TEXT PRIMARY KEY,
          hash TEXT NOT NULL,
          record TEXT,
          result TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS models(
          version TEXT PRIMARY KEY,
          metadata TEXT NOT NULL,
          sha TEXT NOT NULL,
          payload BLOB NOT NULL
        );

        CREATE TABLE IF NOT EXISTS selections(
          id INTEGER PRIMARY KEY,
          old_version TEXT,
          new_version TEXT,
          note TEXT NOT NULL,
          selected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS outbox(
          id TEXT PRIMARY KEY,
          payload TEXT NOT NULL,
          sent INTEGER NOT NULL DEFAULT 0
        );
        """)

    def get(self, key, default=None):
        row = self.db.execute(
            "SELECT v FROM meta WHERE k=?",
            (key,),
        ).fetchone()

        return json.loads(row[0]) if row else default

    def put(self, key, value):
        self.db.execute(
            "INSERT OR REPLACE INTO meta VALUES (?,?)",
            (key, js(value)),
        )

    def load_model(self, version):
        if version in self.cache:
            return self.cache[version]

        row = self.db.execute(
            "SELECT metadata,sha,payload FROM models WHERE version=?",
            (version,),
        ).fetchone()

        if row is None:
            raise ValueError("Unknown baseline version.")

        metadata = json.loads(row[0])

        if metadata["versions"] != VERSIONS:
            raise ValueError("Baseline code/library versions differ.")

        if hashlib.sha256(row[2]).hexdigest() != row[1]:
            raise ValueError("Baseline checksum differs.")


        bundle = joblib.load(io.BytesIO(row[2]))
        model = bundle["baseline"]

        if not isinstance(model, PersonalBaseline):
            raise ValueError("Invalid personal model.")

        if list(model.scope) != metadata["scope"]:
            raise ValueError("Baseline scope differs.")

        self.cache[version] = model
        return model

    def record_for(self, window, assignment):
        if assignment is None:
            return None


        for key in (
            "sensor_id",
            "session_id",
            "target_id",
            "data_origin",
        ):
            if assignment.get(key) != window[key]:
                raise ValueError(
                    "Identity assignment does not match this exact window."
                )

        profile = assignment.get("profile_id")

        if not isinstance(profile, str) or not profile.strip():
            raise ValueError("An explicit profile_id is required.")

        if window["data_origin"] not in ("live", "simulated"):
            return None

        if not window["ready_for_shape_features"]:
            return None

        points = window["points"]


        offsets = [
            utc_time(point["occurred_at"])
            - timedelta(milliseconds=point["uptime_ms"])
            for point in points
        ]

        epoch_key = "epoch:" + digest([
            window["sensor_id"],
            window["data_origin"],
            window["session_id"],
        ])

        stored = self.get(epoch_key)
        epoch = utc_time(stored) if stored else offsets[0]

        if any(
            abs((value - epoch).total_seconds()) > 0.1
            for value in offsets
        ):
            raise ValueError(
                "Source clock changed; do not merge these observations."
            )

        values = extract_features([
            (point["x"], point["y"])
            for point in points
        ])

        start = epoch + timedelta(
            milliseconds=window["window_start_ms"]
        )
        end = epoch + timedelta(
            milliseconds=window["window_end_ms"]
        )

        scope = [
            profile,
            window["sensor_id"],
            window["data_origin"],
            window["window_end_ms"] - window["window_start_ms"],
            window["expected_period_ms"],
            FEATURE_SCHEMA,
        ]

        existing = self.get("scope")

        if existing is not None and existing != scope:
            raise ValueError(
                "Use a separate database for each "
                "person/sensor/origin/config."
            )

        self.put("scope", scope)
        self.put(epoch_key, epoch.isoformat())

        return {
            "profile_id": profile,
            "sensor_id": window["sensor_id"],
            "session_id": window["session_id"],
            "data_origin": window["data_origin"],
            "identity_status": "assigned",
            "time_status": "synced",
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),


            "expected_samples": window["expected_slots"],
            "observed_samples": window["occupied_slots"],

            "feature_schema": FEATURE_SCHEMA,
            "features": dict(
                zip(FEATURE_NAMES, map(float, values))
            ),
        }

    def process(self, window, assignment=None, emit_test=False):
        identity = digest([window["data_origin"], window["window_id"]])
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            active = self.get("active")
            payload_hash = digest([
                window, assignment, emit_test, self.scorer.model_id, POLICY, active,
            ])
            old = self.db.execute(
                "SELECT hash,result FROM windows WHERE id=?", (identity,),
            ).fetchone()
            if old:
                if old[0] != payload_hash:
                    raise ValueError(
                        "Window input/model/policy differs from saved result; "
                        "use a new database to rescore."
                    )
                return json.loads(old[1])

            result = self.scorer.score(window)
            record = None
            personal_status = "not_assigned" if assignment is None else "not_available"
            if result["status"] == "scored_research_only":
                try:
                    record = self.record_for(window, assignment)
                except ValueError as error:
                    result["personal_detail"] = str(error)
                    personal_status = "record_unavailable"

            percentile = None
            if record and active:
                try:
                    model = self.load_model(active)
                    end = utc_time(record["end_utc"])
                    if end - model.reference_end > timedelta(days=POLICY["baseline_max_days"]):
                        personal_status = "expired_for_shadow_policy"
                    else:
                        personal = model.score(record)
                        percentile = personal["reference_percentile"]
                        personal_status = "scored"
                except ValueError as error:
                    personal_status = "baseline_unavailable"
                    result["personal_detail"] = str(error)
            elif record:
                personal_status = "no_active_baseline"

            profile = record["profile_id"] if record else None
            result.update(
                profile_id=profile,
                identity_status="assigned" if record else "unknown",
                personal_baseline={"status": personal_status, "version": active,
                                   "reference_percentile": percentile},
                policy=POLICY,
                baseline_updated=False,
                wandering_decision="not_clinically_evaluated",
                test_notification_queued=False,
                alert=False,
            )
            state_key = "temporal-v2:" + digest([
                window["sensor_id"], window["data_origin"], window["target_id"],
            ])
            state, evidence = advance_evidence(
                self.get(state_key, {}), window, result, percentile=percentile,
                baseline_version=active, profile_id=profile,
            )
            self.put(state_key, state)
            result.update(evidence)


            candidate = result["experimental_decision"].endswith("_candidate")
            if emit_test and candidate and record and window["data_origin"] == "simulated":
                end = utc_time(record["end_utc"])
                notice_key = "notice-v2:" + digest([profile, window["sensor_id"]])
                last_notice = self.get(notice_key)
                cooled = (last_notice is None or
                          (end - utc_time(last_notice)).total_seconds() >= POLICY["cooldown_seconds"])
                if cooled:
                    notice = {
                        "event_id": "mmwave-test-" + identity,
                        "occurred_at": end.isoformat(), "data_origin": "simulated",
                        "profile_id": profile, "sensor_id": window["sensor_id"],
                        "decision": result["experimental_decision"],
                        "rf_shape_score": result["rf_shape_score_not_calibrated"],
                        "personal_percentile": percentile, "baseline_version": active,
                        "policy_version": POLICY["version"], "test_only": True,
                    }
                    self.db.execute("INSERT INTO outbox(id,payload) VALUES (?,?)",
                                    (notice["event_id"], js(notice)))
                    self.put(notice_key, end.isoformat())
                    result["test_notification_queued"] = True
            self.db.execute("INSERT INTO windows VALUES (?,?,?,?)",
                            (identity, payload_hash, js(record) if record else None, js(result)))
        return result

    def records(self):
        rows = self.db.execute(
            "SELECT id,record FROM windows "
            "WHERE record IS NOT NULL"
        ).fetchall()

        return sorted(
            [
                (key, json.loads(raw))
                for key, raw in rows
            ],
            key=lambda pair: utc_time(
                pair[1]["start_utc"]
            ),
        )

    def train(self, history_before, reference_before):
        pass

        cutoff = utc_time(history_before)
        stop = utc_time(reference_before)

        if cutoff >= stop:
            raise ValueError(
                "History cutoff must precede reference cutoff."
            )

        pairs = self.records()

        history = [
            (key, record)
            for key, record in pairs
            if utc_time(record["end_utc"]) <= cutoff
        ]

        reference = [
            (key, record)
            for key, record in pairs
            if (
                utc_time(record["start_utc"]) >= cutoff
                and utc_time(record["end_utc"]) <= stop
            )
        ]

        scope = self.get("scope")

        if not scope:
            raise ValueError("No usable assigned records.")

        model = PersonalBaseline(
            scope[0],
            scope[1],
            scope[2],
        )

        model.fit(
            [record for _, record in history],
            [record for _, record in reference],
        )

        version = "candidate-" + uuid.uuid4().hex[:12]

        metadata = {
            **model.metadata,
            "version": version,
            "parent": self.get("active"),
            "scope": list(model.scope),
            "config": scope,
            "versions": VERSIONS,
            "history_ids": [
                key for key, _ in history
            ],
            "reference_ids": [
                key for key, _ in reference
            ],
            "input_sha256": digest(history + reference),
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "validated_for_real_alerts": False,
        }

        buffer = io.BytesIO()
        joblib.dump({"baseline": model}, buffer)
        blob = buffer.getvalue()

        with self.db:
            self.db.execute(
                "INSERT INTO models VALUES (?,?,?,?)",
                (
                    version,
                    js(metadata),
                    hashlib.sha256(blob).hexdigest(),
                    blob,
                ),
            )

        return version

    def select(self, version, note):
        if not note.strip():
            raise ValueError(
                "Record why you selected or rolled back "
                "this shadow candidate."
            )

        model = self.load_model(version)

        if list(model.scope) != self.get("scope")[:3]:
            raise ValueError("Different candidate scope.")

        with self.db:
            self.db.execute(
                "INSERT INTO selections("
                "old_version,new_version,note,selected_at"
                ") VALUES (?,?,?,?)",
                (
                    self.get("active"),
                    version,
                    note,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

            self.put("active", version)

        return {
            "active_shadow_version": version,
            "real_alerts_enabled": False,
        }

    def compare(self, version):
        candidate = self.load_model(version)
        active = self.get("active")

        previous = (
            self.load_model(active)
            if active
            else None
        )

        output = []

        for key, record in self.records():
            start = utc_time(record["start_utc"])

            if start < candidate.reference_end:
                continue

            if previous and start < previous.reference_end:
                continue

            output.append({
                "record_id": key,
                "start_utc": record["start_utc"],
                "candidate_percentile": candidate.score(
                    record
                )["reference_percentile"],
                "active_percentile": (
                    previous.score(record)[
                        "reference_percentile"
                    ]
                    if previous
                    else None
                ),
            })

        return {
            "later_windows": output,
            "accuracy_comparison": "no_ground_truth",
            "automatically_selected": False,
        }

    def summary(self):
        return {
            "stored_windows": self.db.execute(
                "SELECT COUNT(*) FROM windows"
            ).fetchone()[0],
            "usable_records": len(self.records()),
            "versions": [
                row[0]
                for row in self.db.execute(
                    "SELECT version FROM models"
                )
            ],
            "active_shadow_version": self.get("active"),
            "pending_test_notifications": self.db.execute(
                "SELECT COUNT(*) FROM outbox WHERE sent=0"
            ).fetchone()[0],
            "automatic_training": False,
            "real_alerts_enabled": False,
        }


def synthetic_windows(session="demo-session"):
    rng = np.random.default_rng(42)
    t = np.arange(64) / 63.0
    builder = TrajectoryWindows(500, 32000)

    for window_index in range(68):
        if window_index < 62:
            amplitude = rng.uniform(.10, .18)
            frequency = rng.uniform(1.8, 2.2)
            phase = rng.uniform(-.15, .15)

            xy = np.column_stack([
                t,
                amplitude * np.sin(
                    frequency * np.pi * t + phase
                ),
            ])
        else:
            xy = np.column_stack([
                np.cos(6 * np.pi * t),
                np.sin(6 * np.pi * t),
            ])

        for point_index, (x, y) in enumerate(xy):
            index = window_index * 64 + point_index
            event = demo_event(0)
            uptime = index * 500

            timestamp = (
                datetime(2026, 1, 1, tzinfo=timezone.utc)
                + timedelta(milliseconds=uptime)
            )

            event.update(
                seq=index,
                session_id=session,
                event_id=f"demo-radar:{session}:{index}",
                uptime_ms=uptime,
                occurred_at=timestamp.isoformat().replace(
                    "+00:00",
                    "Z",
                ),
                targets=[{
                    "id": 1,
                    "x": float(x),
                    "y": float(y),
                    "z": 1.3,
                    "doppler": 0,
                }],
            )

            yield from builder.feed(event)

    timestamp = (
        datetime(2026, 1, 1, tzinfo=timezone.utc)
        + timedelta(milliseconds=68 * 32000)
    )

    event.update(
        seq=68 * 64,
        event_id=f"demo-radar:{session}:{68 * 64}",
        uptime_ms=68 * 32000,
        target_count=0,
        targets=[],
        occurred_at=timestamp.isoformat().replace(
            "+00:00",
            "Z",
        ),
    )

    yield from builder.feed(event)
    yield from builder.finish()


def assigned(window):
    return {
        **{
            key: window[key]
            for key in (
                "sensor_id",
                "session_id",
                "target_id",
                "data_origin",
            )
        },
        "profile_id": "demo-person",
    }


def demo(flow, session="demo-session"):
    if flow.summary()["stored_windows"]:
        raise ValueError(
            "Demo requires a new database path; "
            "old files are not overwritten."
        )

    windows = list(synthetic_windows(session))
    assert len(windows) == 68


    for window in windows[:60]:
        flow.process(window, assigned(window))

    records = flow.records()


    version = flow.train(
        records[39][1]["end_utc"],
        records[59][1]["end_utc"],
    )

    flow.select(
        version,
        "Synthetic wiring test only; not clinical approval.",
    )

    before = flow.load_model(version)
    query = flow.record_for(
        windows[60],
        assigned(windows[60]),
    )
    expected = before.score(query)


    flow.cache.clear()
    assert flow.load_model(version).score(query) == expected
    flow.db.commit()


    for window in windows[60:]:
        result = flow.process(
            window,
            assigned(window),
            emit_test=True,
        )

        print(js({
            key: result[key]
            for key in (
                "window_id",
                "rf_shape_score_not_calibrated",
                "personal_baseline",
                "experimental_decision",
                "test_notification_queued",
                "alert",
            )
        }))

    last = flow.process(
        windows[-1],
        assigned(windows[-1]),
        emit_test=True,
    )

    assert flow.process(
        windows[-1],
        assigned(windows[-1]),
        emit_test=True,
    ) == last

    assert flow.summary()["stored_windows"] == 68

    print(js({"kind": "demo_summary", "data_origin": "simulated", **flow.summary()}))


def send_test(flow, url):
    allowed = (
        "http://127.0.0.1:8010/api/test/mmwave",
        "http://localhost:8010/api/test/mmwave",
    )

    if url not in allowed:
        raise ValueError(
            "Test sender only supports the local "
            "test backend on port 8010."
        )

    token = os.environ.get(
        "PAUSEABLE_MMWAVE_TEST_TOKEN",
        "",
    )

    if len(token) < 24:
        raise ValueError(
            "Set the same test token as the backend "
            "(at least 24 characters)."
        )

    rows = flow.db.execute(
        "SELECT id,payload FROM outbox WHERE sent=0"
    ).fetchall()

    for key, raw in rows:
        request = Request(
            url,
            data=raw.encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Mmwave-Test-Token": token,
            },
        )

        with urlopen(request, timeout=5) as response:
            acknowledgement = json.load(response)

        if (
            acknowledgement.get("event_id") != key
            or acknowledgement.get("status")
            not in ("stored", "duplicate")
        ):
            raise ValueError(
                "Unexpected test backend acknowledgement."
            )

        with flow.db:
            flow.db.execute(
                "UPDATE outbox SET sent=1 WHERE id=?",
                (key,),
            )

    print(js({
        "test_backend_acknowledged": len(rows),
        "caregiver_delivery_confirmed": False,
    }))


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "command",
        choices=[
            "demo",
            "run",
            "train",
            "select",
            "compare",
            "show",
            "send-test",
        ],
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--trust-local-model", action="store_true")
    parser.add_argument("--trust-local-db", action="store_true",
                        help="Allow loading your own serialized personal baselines")
    parser.add_argument("--emit-test", action="store_true",
                        help="Queue synthetic review candidates for explicit send-test")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--assignments", type=Path)
    parser.add_argument("--sample-ms", type=int, default=500)
    parser.add_argument("--window-ms", type=int, default=32000)
    parser.add_argument("--history-before")
    parser.add_argument("--reference-before")
    parser.add_argument("--version")
    parser.add_argument("--note", default="")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8010/api/test/mmwave",
    )

    args = parser.parse_args()

    if (args.db.is_file() and args.command in ("run", "select", "compare")
            and not (args.trust_local_db or args.trust_local_model)):
        parser.error("Existing personal models require --trust-local-db for your own database.")

    if args.command == "run" and args.input is None:
        parser.error(
            "run requires an original v1 event JSONL --input."
        )

    if args.command == "train" and (
        not args.history_before
        or not args.reference_before
    ):
        parser.error(
            "train requires --history-before "
            "and --reference-before UTC timestamps."
        )

    if args.command in ("select", "compare") and not args.version:
        parser.error("This command requires --version.")

    if (
        args.command not in ("demo", "run")
        and not args.db.is_file()
    ):
        parser.error("Database does not exist.")

    scorer = WindowScorer(args.model, args.trust_local_model)
    args.db.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(args.db) as database:
        flow = Flow(database, scorer)

        if args.command == "demo":
            demo(
                flow,
                session="demo-" + uuid.uuid4().hex[:12],
            )

        elif args.command == "run":
            assignments = (
                json.loads(
                    args.assignments.read_text(
                        encoding="utf-8"
                    )
                )
                if args.assignments
                else {}
            )

            for window in event_windows(
                args.input,
                args.sample_ms,
                args.window_ms,
            ):
                print(js(flow.process(
                    window,
                    assignments.get(window["window_id"]),
                    emit_test=args.emit_test,
                )))

        elif args.command == "train":
            print(js({
                "candidate_version": flow.train(
                    args.history_before,
                    args.reference_before,
                ),
                "active_unchanged": True,
            }))

        elif args.command == "select":
            print(js(flow.select(
                args.version,
                args.note,
            )))

        elif args.command == "compare":
            print(js(flow.compare(args.version)))

        elif args.command == "send-test":
            send_test(flow, args.url)

        else:
            print(js(flow.summary()))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
