import sqlite3
import unittest

from mmwave_pipeline import Flow
from test_runtime_pipeline import FixedScorer
from test_rolling_windows import frame
from wandering_runtime import WanderingRuntime


class Emitter:
    last_signature = None
    stale_after_ms = 300

    def emit(self, *_, **__):
        return None


class RollingRuntimeTest(unittest.TestCase):
    def test_real_flow_persists_every_ten_seconds_and_only_activates_at_ninety(self):
        with sqlite3.connect(":memory:") as database:
            flow = Flow(database, FixedScorer())
            seen = []
            runtime = WanderingRuntime(flow, Emitter(), sample_ms=100, window_ms=30000,
                                       step_ms=10000, on_result=lambda w, r: seen.append((w, r)))
            for index in range(901):
                runtime.process_event(frame(index))
            self.assertEqual([w["window_end_ms"] for w, _ in seen], list(range(30000, 90001, 10000)))
            self.assertEqual(database.execute("SELECT count(*) FROM windows").fetchone()[0], 7)
            self.assertEqual([r["experimental_decision"] for _, r in seen],
                             ["partial_evidence"] * 6 + ["shape_review_candidate"])
            self.assertEqual(seen[-1][1]["temporal_evidence"]["shape"]["high_ms"], 90000)
            self.assertEqual(flow.summary()["pending_test_notifications"], 0)


if __name__ == "__main__":
    unittest.main()
