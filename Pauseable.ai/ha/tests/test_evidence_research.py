import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ha_evidence_scenarios import PAIRS, choose_hour, load_registry, scenario, summarize_observation
from make_ha_features import build_features, prepare_events
from profile_minder_kitchen import profile_archive, summarize
from run_ha_evidence_research import nominal_feature_frame, run


class EvidenceScenariosTest(unittest.TestCase):
    def test_registry_has_resolved_evidence_and_no_clinical_numbers(self):
        registry = load_registry()
        ids = {source["id"] for source in registry["sources"]}
        self.assertFalse(registry["production_eligible"])
        for spec in registry["scenarios"]:
            self.assertTrue(set(spec["sources"]) <= ids)
        self.assertIn("NOT dementia severity", registry["parameters"]["basis"])

    def test_all_scenarios_are_reproducible_and_physically_ordered(self):
        for spec in load_registry()["scenarios"]:
            for intensity in ("low", "medium", "high"):
                events, metadata = scenario(spec["id"], intensity)
                repeated, _ = scenario(spec["id"], intensity)
                pd.testing.assert_frame_equal(events, repeated)
                self.assertFalse(metadata["production_eligible"])
                self.assertIsNone(metadata["diagnosis"])
                self.assertTrue(pd.to_datetime(events["event_time"]).is_monotonic_increasing)
                for _, group in events.drop_duplicates().groupby("entity_id"):
                    actions = group["action"].tolist()
                    allowed = ({"close": {"open"}, "open": {"close"}} if "door" in group["signal_type"].iloc[0]
                               else {"idle": {"running"}, "running": {"done", "idle"}, "done": {"idle"}})
                    for before, after in zip(actions, actions[1:]):
                        self.assertIn(after, allowed[before])

    def test_ambiguous_contexts_really_have_identical_observations(self):
        for symptom, benign in PAIRS:
            a, _ = scenario(symptom)
            b, _ = scenario(benign)
            pd.testing.assert_frame_equal(a, b)

    def test_two_second_open_is_counted_and_duplicates_do_not_add_actions(self):
        normal, meta = scenario("normal_single_use")
        duplicate, _ = scenario("sensor_duplicate")
        endpoint = pd.Timestamp(meta["assessment_start"]) + pd.Timedelta(minutes=1)
        a = build_features(normal, endpoint, endpoint)
        b = build_features(duplicate, endpoint, endpoint)
        self.assertEqual(a.iloc[0]["fridge_door_open_count_10m"], 1)
        pd.testing.assert_frame_equal(a, b)
        self.assertFalse(prepare_events(normal).iloc[0]["_countable"])

    def test_dropout_not_called_normal(self):
        _, meta = scenario("sensor_dropout")
        self.assertEqual(meta["history_complete"], 0)
        self.assertEqual(meta["family"], "sensor_fault")

    def test_intensity_changes_event_density_not_diagnosis(self):
        low, _ = scenario("fridge_recheck", "low")
        high, meta = scenario("fridge_recheck", "high")
        self.assertLess(len(low), len(high))
        self.assertFalse(meta["clinical_ground_truth"])

    def test_distributed_rechecks_exercise_longer_windows_without_a_short_burst(self):
        burst, _ = scenario("fridge_recheck", "high")
        distributed, meta = scenario("fridge_distributed_rechecks", "high")
        start, end = pd.Timestamp(meta["assessment_start"]), pd.Timestamp(meta["assessment_end"])
        a, b = build_features(burst, start, end), build_features(distributed, start, end)
        self.assertLess(b["fridge_door_open_count_10m"].max(), a["fridge_door_open_count_10m"].max())
        self.assertGreater(b["fridge_door_open_count_1h"].max(), b["fridge_door_open_count_10m"].max())

    def test_washer_power_is_explicitly_an_adapter_not_a_washing_measurement(self):
        events, meta = scenario("washer_power_recheck", "medium")
        features = build_features(events, pd.Timestamp(meta["assessment_start"]), pd.Timestamp(meta["assessment_end"]))
        self.assertEqual(features["washer_start_count_2h"].max(), 6)
        self.assertEqual(meta["signal_semantics"], "power_toggles_adapted_to_operation")
        self.assertFalse(features.filter(like="done_to_restart").to_numpy().any())

    def test_one_complete_wash_is_one_start_and_duration_is_diagnostic_only(self):
        events, meta = scenario("normal_washer_full_cycle")
        features = build_features(events, pd.Timestamp(meta["assessment_start"]), pd.Timestamp(meta["assessment_end"]))
        self.assertEqual(features["washer_start_count_2h"].max(), 1)
        observation = summarize_observation(events)
        self.assertEqual(observation["completed_state_durations_seconds"]["washer_running_seconds"], [4200])
        self.assertEqual(observation["unclosed_observed_states"], [])
        self.assertNotIn("washer_running_seconds", features.columns)

    def test_dropout_keeps_unclosed_state_instead_of_inventing_duration(self):
        events, _ = scenario("sensor_dropout")
        observation = summarize_observation(events)
        self.assertEqual(observation["unclosed_observed_states"], ["fridge_door"])
        self.assertNotIn("fridge_open_seconds", observation["completed_state_durations_seconds"])

    def test_nominal_sampling_captures_short_events_between_hour_boundaries(self):
        events, _ = scenario("normal_single_use", hour=7)
        events["event_time"] = (pd.to_datetime(events["event_time"]) + pd.Timedelta(minutes=40)).astype(str)
        frame = nominal_feature_frame(events, pd.Timestamp("2026-04-01"), 1)
        self.assertEqual(len(frame), 24)
        self.assertEqual(frame["fridge_door_open_count_10m"].max(), 1)
        self.assertEqual(frame["microwave_start_count_10m"].max(), 1)

    def test_reference_uses_fit_days_only(self):
        rows = []
        for house in (1, 2):
            for day in range(20):
                rows.append({"household": house, "start_date": str(pd.Timestamp("2020-01-01") + pd.Timedelta(days=day, hours=8 if day < 14 else 23)), "device_type": "door", "activity": "fridge door"})
        profile = summarize(pd.DataFrame(rows))
        self.assertEqual(profile["households_used"], 2)
        self.assertEqual(profile["fridge_hour_weights"][8], 1)
        self.assertEqual(profile["fridge_hour_weights"][23], 0)
        self.assertEqual(profile["holdout_hour_total_variation"], 1)
        self.assertEqual(choose_hour(1, profile), 8)
        self.assertNotIn("household", profile)
        self.assertNotIn("start_date", profile)

    def test_zip_ignores_macos_metadata_and_uses_activity_not_sensor_type(self):
        rows = [{"household": 1, "start_date": str(pd.Timestamp("2020-01-01") + pd.Timedelta(days=d, hours=8)),
                 "device_type": "door", "activity": "fridge door"} for d in range(20)]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "fixture.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("COVID_kitchen.csv", pd.DataFrame(rows).to_csv(index=False))
                archive.writestr("__MACOSX/._COVID_kitchen.csv", "not a csv")
            profile = profile_archive(path)
        self.assertEqual(profile["record_categories"], {"fridge door": 20})
        self.assertEqual(profile["sensor_categories"], {"door": 20})
        self.assertEqual(len(profile["archive_sha256"]), 64)

    def test_transition_csv_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            summarize(pd.DataFrame({"source": ["fridge"], "sink": ["kitchen"]}))

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "manifest.json"
            path.write_text("keep", encoding="utf-8")
            with self.assertRaises(ValueError):
                run(root, [1], ["low"])
            self.assertEqual(path.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
