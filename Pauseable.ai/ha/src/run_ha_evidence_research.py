
import argparse
from contextlib import redirect_stdout
from datetime import datetime
import json
from pathlib import Path
import platform
import time

import pandas as pd

from build_baseline import build_baseline
from entity_mapper import convert_rows
from ha_anomaly_models import score_frame, sha256
from ha_evidence_scenarios import PAIRS, REGISTRY, choose_hour, load_registry, scenario, summarize_observation
from ha_evidence_report import write_study_report
from infer_ha_baseline import infer_dataframe
from make_ha_features import FEATURE_COLUMNS, build_features, prepare_events
from profile_minder_kitchen import profile_archive
from ha_model_lifecycle import combine

HOUSE = "synthetic-evidence-research"
LEVELS = {"normal": 0, "attention": 1, "risk": 2, "unavailable": -1}


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def nominal_feature_frame(standard, origin, days):
    prepared = prepare_events(standard)
    frames = []
    for day in range(days):

        start = origin + pd.Timedelta(days=day, minutes=(42 + 17 * day) % 60)
        end = start + pd.Timedelta(hours=23)
        context = prepared.loc[(prepared["time"] >= start - pd.Timedelta(hours=2)) & (prepared["time"] <= end)]
        frames.append(build_features(context, start.to_pydatetime(), end.to_pydatetime(), step_minutes=60))
    result = pd.concat(frames, ignore_index=True)
    result["source_type"], result["household_id"] = "synthetic", HOUSE
    result["history_complete"] = (pd.to_datetime(result["window_end"]) >= origin + pd.Timedelta(hours=2)).astype(int)
    return result


def run(output_dir, seeds, intensities, minder_zip=None):
    output = Path(output_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty research output directory; never overwrite household models")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Seeds must be nonempty and unique")
    if not intensities or len(set(intensities)) != len(intensities) or not set(intensities) <= {"low", "medium", "high"}:
        raise ValueError("Select unique low/medium/high engineering intensity values")
    from train_ha_anomaly_models import chronological_split, train_models
    from verify_ha_month_cycle import scenario as normal_month
    from ha_model_lifecycle import SCHEMA

    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    registry = load_registry()
    save_json(output / "evidence_registry.json", registry)
    journal_path = output / "run_log.jsonl"

    def log(stage, **details):
        message = {"stage": stage, "elapsed_seconds": round(time.monotonic() - started, 3), **details}
        print(json.dumps(message), flush=True)
        with journal_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(message) + "\n")

    reference = None
    if minder_zip:
        log("profile_public_data")
        reference = profile_archive(minder_zip)
        save_json(output / "minder_reference.json", reference)
        log("profile_complete", rows=reference["rows"], households=reference["households_used"])
    log("generate_nominal_history", days=30, feature_step_minutes=60)
    raw, origin = normal_month(30)
    standard = pd.DataFrame([item for row in raw.to_dict("records") for item in convert_rows(row)
                             if item["action"] != "skip"])
    training = nominal_feature_frame(standard, origin, 30)
    training["schema_version"] = SCHEMA
    training["label"] = "normal"
    training["review_status"] = "synthetic_nominal_by_construction"
    training = training.loc[training["history_complete"].eq(1)].copy()
    standard.assign(source_type="synthetic").to_csv(output / "nominal_standard_events.csv", index=False)
    training_path = output / "nominal_features.csv"
    training.to_csv(training_path, index=False)
    predictors = [c for c in FEATURE_COLUMNS if c != "window_end"]
    first, _, _ = chronological_split(training)
    baseline = build_baseline(first[FEATURE_COLUMNS])
    baseline.update(source_type="synthetic", production_eligible=False,
                    description="Nominal simulation fixture; not a patient baseline")
    save_json(output / "synthetic_baseline.json", baseline)
    model_dir = output / "synthetic_model"
    log("train_shadow_if_ae", feature_rows=len(training))
    with (output / "training_log.txt").open("w", encoding="utf-8") as stream, redirect_stdout(stream):
        manifest, validation = train_models(
            training_path, model_dir, "synthetic", HOUSE,
            "Existing nominal synthetic month; no symptom injections, no public patient labels; engineering fixture only",
            feature_columns=predictors, seed=42)
    manifest["production_eligible"] = False
    manifest["clinical_ground_truth"] = False
    save_json(model_dir / "manifest.json", manifest)
    save_json(output / "runtime_versions.json", {"python": platform.python_version(),
              "pandas": pd.__version__, "sklearn": manifest["sklearn_version"],
              "source_sha256": {name: sha256(Path(__file__).parent / name) for name in
                                ["run_ha_evidence_research.py", "ha_evidence_scenarios.py", "profile_minder_kitchen.py",
                                 "make_ha_features.py", "build_baseline.py", "infer_ha_baseline.py", "train_ha_anomaly_models.py"]}})
    log("models_ready", optimizer_converged=manifest["optimizer_converged"])
    summaries, ambiguity, comparisons = [], [], {}
    cases_dir = output / "cases"
    cases_dir.mkdir()
    for index, seed in enumerate(seeds):
        hour = choose_hour(seed, reference)
        for intensity in intensities:
            for spec in registry["scenarios"]:
                case_id = spec["id"]
                case_name = f"{case_id}_{intensity}_{seed}"
                folder = cases_dir / case_name
                folder.mkdir()
                events, metadata = scenario(case_id, intensity, seed, hour, day=index * 3)
                metadata["timing_reference"] = "MINDER fit-only equal-household hours" if reference else "engineering clock grid"
                events.assign(source_type="synthetic").to_csv(folder / "events.csv", index=False)
                save_json(folder / "provenance.json", metadata)
                observation = summarize_observation(events)
                save_json(folder / "observation_summary.json", observation)
                features = build_features(events, datetime.fromisoformat(metadata["assessment_start"]),
                                          datetime.fromisoformat(metadata["assessment_end"]))
                features["source_type"] = "synthetic"
                features["household_id"] = HOUSE
                features["history_complete"] = metadata["history_complete"]
                features["schema_version"] = training["schema_version"].iloc[0]
                features.to_csv(folder / "features.csv", index=False)
                models = score_frame(features, model_dir)
                expected_status = "shadow" if metadata["history_complete"] else "insufficient_history"
                if not models["model_status"].eq(expected_status).all():
                    raise RuntimeError(f"Unexpected model status in {case_name}: {models['model_status'].unique()}")
                if metadata["history_complete"]:
                    rules = pd.DataFrame(infer_dataframe(features, baseline))
                    scores = rules.merge(models, on="window_end", validate="one_to_one")
                    guarded = combine(rules, models, 'hybrid', features)
                    scores['guarded_level'] = guarded['level']
                    scores['guarded_score'] = guarded['risk_score']
                    scores['repetition_observed'] = guarded['repetition_observed']
                    scores['model_only_anomaly_held'] = guarded['model_only_anomaly_held']
                else:
                    scores = models.assign(level="unavailable", risk_score=None,
                                           primary_pattern="coverage_unknown", reasons="Sensor dropout fixture; withhold judgment",
                                           guarded_level='unavailable', guarded_score=None, repetition_observed=False,
                                           model_only_anomaly_held=False)
                scores.to_csv(folder / "scores.csv", index=False)
                summary = {"case": case_id, "family": spec["family"], "seed": seed,
                           "intensity": intensity, "start_hour": datetime.fromisoformat(metadata["assessment_start"]).hour, "rows": len(events),
                           "clinical_ground_truth": False, "history_complete": metadata["history_complete"]}
                for name, column in [("rule", "level"), ("if", "if_level"), ("ae", "ae_level")]:
                    summary[name + "_max_level"] = max(scores[column], key=lambda v: LEVELS[v])
                    summary[name + "_alert_windows"] = int(scores[column].isin(["attention", "risk"]).sum())
                summary["model_statuses"] = ",".join(sorted(scores["model_status"].unique()))
                summary['guarded_max_level'] = max(scores['guarded_level'], key=lambda v: LEVELS[v])
                summary['guarded_alert_windows'] = int(scores['guarded_level'].isin(['attention', 'risk']).sum())
                if case_id in {'normal_single_use', 'normal_washer_full_cycle'} and metadata['history_complete']:
                    if summary['guarded_alert_windows']:
                        raise RuntimeError(f'Single normal use became repetitive behavior: {case_name}')
                summary["fridge_open_peak_10m"] = int(features["fridge_door_open_count_10m"].max())
                summary["microwave_start_peak_10m"] = int(features["microwave_start_count_10m"].max())
                summary["washer_start_peak_2h"] = int(features["washer_start_count_2h"].max())
                summary["assessment_minutes"] = int((pd.Timestamp(metadata["assessment_end"]) -
                                                     pd.Timestamp(metadata["assessment_start"])).total_seconds() / 60)
                summary["signal_semantics"] = metadata["signal_semantics"]
                summary["rule_peak_reason"] = str(scores.sort_values("risk_score", ascending=False).iloc[0]["reasons"])
                summary["feature_sha256"] = sha256(folder / "features.csv")
                summaries.append(summary)
                comparisons[(case_id, intensity, seed)] = summary
                log("case_complete", case=case_name, rule=summary["rule_max_level"],
                    if_level=summary["if_max_level"], ae=summary["ae_max_level"])
            for symptom, benign in PAIRS:
                left, right = [comparisons[(name, intensity, seed)] for name in (symptom, benign)]
                ambiguity.append({"symptom_hypothesis": symptom, "benign_explanation": benign,
                                  "intensity": intensity, "seed": seed,
                                  "identical_observed_features": left["feature_sha256"] == right["feature_sha256"],
                                  "conclusion": "Intent cannot be inferred from these identical appliance events alone"})
    pd.DataFrame(summaries).to_csv(output / "scenario_results.csv", index=False)
    save_json(output / "observability_pairs.json", ambiguity)

    report = {"completed": True, "production_eligible": False, "clinical_validation": False,
              "pi_accessed": False, "mqtt_published": False, "architecture": platform.machine(),
              "source_type": "synthetic", "registry_sha256": sha256(REGISTRY),
              "public_reference_used": reference is not None, "cases": len(summaries),
              "seeds": seeds, "intensities": intensities, "train_days": 30,
              "scenario_types": len(registry["scenarios"]), "evidence_sources": len(registry["sources"]),
              "nominal_feature_step_minutes": 60, "scenario_feature_step_minutes": 1,
              "nominal_sampling": "24 endpoints/day; minute phase (42 + 17*day) mod 60 to avoid fixed-hour aliasing",
              "model_feature_count": len(predictors), "optimizer_converged": manifest["optimizer_converged"],
              "all_pair_features_identical": all(item["identical_observed_features"] for item in ambiguity),
              "normal_synthetic_holdout_alert_fraction": validation["normal_holdout_alert_fraction"],
              "limits": ["Neither synthetic case hit rate nor nominal holdout alarm rate measures clinical accuracy.",
                         "Future scenarios are separate from training; paired/seed variants remain correlated, not independent patients.",
                         "Phase-rotated hourly sampling accelerates the fixture and may still miss patterns; production features remain minute-based.",
                         "Repetition vs meal preparation can be observationally identical; counts cannot recover intent.",
                         "Task omission and prolonged use are separate coverage tests, not repetitive positives.",
                         "Dropout masking here uses known injected fault metadata; this is not a new live dropout detector.",
                         "Existing numeric rule thresholds are unchanged and are not clinical cutoffs.",
                         "The nominal history is not calibrated to MINDER; only scenario start hours optionally use its aggregate fit subset.",
                         "Washer power scenarios use the demo's operation adapter; no washer patient dataset was imported.",
                         "State duration diagnostics are reported separately; the trained 54-feature schema is unchanged."],
              "seconds": round(time.monotonic() - started, 3)}
    save_json(output / "report.json", report)
    write_study_report(output, report, summaries, registry, baseline, manifest)
    log("complete", report=str(output / "report.json"))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[41, 83])
    parser.add_argument("--intensities", nargs="+", choices=["low", "medium", "high"], default=["low", "medium", "high"])
    parser.add_argument("--minder-zip", help="Optional, locally obtained COVID_kitchen.csv.zip; never downloads automatically")
    args = parser.parse_args()
    run(args.output_dir, args.seeds, args.intensities, args.minder_zip)


if __name__ == "__main__":
    main()
