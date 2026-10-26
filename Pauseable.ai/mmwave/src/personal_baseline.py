import json
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.ensemble import IsolationForest

from features import FEATURE_NAMES, extract_features
from personal_records import FEATURE_SCHEMA, validate_record


class PersonalBaseline:
    pass

    def __init__(self, profile_id, sensor_id, origin="live"):
        if origin not in ("live", "simulated"):
            raise ValueError("Use live or simulated, never mix them.")

        self.scope = (profile_id, sensor_id, origin)
        self.model = None

    def _rows(self, records):
        rows = []

        for record in records:
            start, end, reasons = validate_record(record)

            scope = (
                record["profile_id"],
                record["sensor_id"],
                record["data_origin"],
            )

            if scope != self.scope:
                raise ValueError("Profile, sensor or data origin differs.")


            blocked = set(reasons) - {"not_live"}
            if blocked:
                raise ValueError(
                    f"Unusable observation: {sorted(blocked)}"
                )

            values = [
                record["features"][name]
                for name in FEATURE_NAMES
            ]
            rows.append((start, end, values))

        rows.sort(key=lambda row: row[0])

        for previous, current in zip(rows, rows[1:]):
            if current[0] < previous[1]:
                raise ValueError("Observation windows overlap.")

        return rows

    def fit(self, historical_records, reference_records):
        if self.model is not None:
            raise ValueError(
                "Create a new candidate instead of overwriting."
            )

        historical = self._rows(historical_records)
        reference = self._rows(reference_records)


        if len(historical) < 20 or len(reference) < 10:
            raise ValueError(
                "Need at least 20 historical + 10 reference windows."
            )

        if reference[0][0] < historical[-1][1]:
            raise ValueError(
                "Reference windows must follow historical windows."
            )

        duration = historical[0][1] - historical[0][0]

        if any(
            end - start != duration
            for start, end, _ in historical + reference
        ):
            raise ValueError(
                "Use the same observation-window duration."
            )

        x_train = np.asarray(
            [row[2] for row in historical],
            dtype=float,
        )
        x_reference = np.asarray(
            [row[2] for row in reference],
            dtype=float,
        )

        if len(np.unique(x_train, axis=0)) < 2:
            raise ValueError(
                "Historical features contain no variation."
            )

        model = IsolationForest(
            n_estimators=200,
            max_samples="auto",
            contamination="auto",
            random_state=42,
            n_jobs=1,
        )


        model.fit(x_train)


        reference_scores = -model.score_samples(x_reference)

        self.duration = duration
        self.reference_end = reference[-1][1]
        self.reference_scores = reference_scores

        self.metadata = {
            "profile_id": self.scope[0],
            "sensor_id": self.scope[1],
            "data_origin": self.scope[2],
            "feature_schema": FEATURE_SCHEMA,
            "window_seconds": duration.total_seconds(),
            "historical_windows": len(historical),
            "reference_windows": len(reference),
            "fit_end": historical[-1][1].isoformat(),
            "reference_end": self.reference_end.isoformat(),
            "random_seed": 42,
            "status": "experimental_candidate",
        }

        self.model = model
        return dict(self.metadata)

    def score(self, record):
        if self.model is None:
            raise ValueError("Fit a historical reference first.")

        start, end, values = self._rows([record])[0]

        if start < self.reference_end:
            raise ValueError(
                "Score only windows after the reference period."
            )

        if end - start != self.duration:
            raise ValueError("Observation-window duration differs.")


        rarity = float(
            -self.model.score_samples([values])[0]
        )

        lower = np.count_nonzero(
            self.reference_scores < rarity
        )
        equal = np.count_nonzero(
            self.reference_scores == rarity
        )


        rank = (
            100.0
            * (lower + 0.5 * equal)
            / len(self.reference_scores)
        )

        return {
            "profile_id": self.scope[0],
            "data_origin": self.scope[2],
            "raw_rarity": round(rarity, 6),
            "reference_percentile": round(rank, 1),
            "wandering_decision": "not_evaluated",
            "baseline_updated": False,
            "alert": False,
        }


def demo():
    rng = np.random.default_rng(42)
    t = np.linspace(0.0, 1.0, 64)

    def previous_pattern():

        amplitude = rng.uniform(0.10, 0.18)
        frequency = rng.uniform(1.8, 2.2)
        phase = rng.uniform(-0.15, 0.15)

        return np.column_stack([
            t,
            amplitude * np.sin(
                frequency * np.pi * t + phase
            ),
        ])

    def make_record(index, points):


        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        start += timedelta(seconds=index * 31)

        features = extract_features(points)

        return {
            "profile_id": "demo-person",
            "sensor_id": "demo-radar",
            "session_id": "baseline-demo-001",
            "data_origin": "simulated",
            "identity_status": "assigned",
            "time_status": "synced",
            "start_utc": start.isoformat(),
            "end_utc": (
                start + timedelta(seconds=30)
            ).isoformat(),
            "expected_samples": len(points),
            "observed_samples": len(points),
            "feature_schema": FEATURE_SCHEMA,
            "features": {
                name: float(value)
                for name, value in zip(FEATURE_NAMES, features)
            },
        }

    records = [
        make_record(i, previous_pattern())
        for i in range(60)
    ]

    baseline = PersonalBaseline(
        "demo-person",
        "demo-radar",
        origin="simulated",
    )


    metadata = baseline.fit(records[:40], records[40:])


    similar = make_record(
        60,
        np.column_stack([
            t,
            0.14 * np.sin(2.0 * np.pi * t),
        ]),
    )

    angle = 6.0 * np.pi * t
    loop = make_record(
        61,
        np.column_stack([
            np.cos(angle),
            np.sin(angle),
        ]),
    )

    print(
        "DEMO ONLY: synthetic paths, "
        "no database/model files changed."
    )

    print(json.dumps({
        "historical_windows": metadata["historical_windows"],
        "reference_windows": metadata["reference_windows"],
        "similar_shape": baseline.score(similar),
        "loop_shape": baseline.score(loop),
        "live_baseline_created": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    demo()
