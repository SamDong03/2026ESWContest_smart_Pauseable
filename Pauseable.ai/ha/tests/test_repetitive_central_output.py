import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
FILTER = ROOT / "deploy/repetitive-central-route-filter.awk"
TIME_ROUTER = ROOT / "deploy/repetitive-central-time-router.sh"


def accepted(event, source="repetitive-ai", decision="repetitive_behavior", risk="caution"):
    return (
        f"CENTRAL_DECISION_ACCEPTED event_id={event} source={source} "
        f"decision={decision} risk={risk} score=80\n"
    )


def routed(event, disposition="execute", speak="true"):
    return (
        f"CENTRAL_ACTION_ROUTED event_id={event} disposition={disposition} "
        f"reason=first_risk_event notify=true speak={speak} control=false\n"
    )


class RepetitiveCentralOutputTest(unittest.TestCase):
    def run_filter(self, records):
        result = subprocess.run(
            [shutil.which("awk") or "awk", "-f", str(FILTER)],
            input=records,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.splitlines()

    def route_hour(self, hour):
        return subprocess.run(
            ["sh", str(TIME_ROUTER), hour],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_same_central_approved_event_is_emitted(self):
        records = (
            accepted("evt-a")
            + accepted("evt-b", risk="danger")
            + routed("evt-b")
            + routed("evt-a")
        )
        self.assertEqual(self.run_filter(records), ["evt-b", "evt-a"])

    def test_unapproved_suppressed_or_wandering_events_are_rejected(self):
        records = (
            accepted("evt-normal", decision="normal", risk="normal")
            + routed("evt-normal")
            + accepted("evt-wandering", source="wandering-ai", decision="wandering_suspected")
            + routed("evt-wandering")
            + accepted("evt-cooldown")
            + routed("evt-cooldown", disposition="suppressed")
            + accepted("evt-retry")
            + routed("evt-retry", speak="false")
            + routed("evt-missing")
        )
        self.assertEqual(self.run_filter(records), [])

    def test_invalid_or_duplicate_event_id_is_rejected(self):
        records = (
            accepted("evt-a")
            + routed("evt-a")
            + routed("evt-a")
            + accepted("../../bad")
            + routed("../../bad")
        )
        self.assertEqual(self.run_filter(records), ["evt-a"])

    def test_time_boundaries(self):
        expected = {
            "07": "air_purifier",
            "08": "tv",
            "17": "tv",
            "18": "air_purifier",
            "23": "air_purifier",
            "00": "air_purifier",
        }
        for hour, output in expected.items():
            with self.subTest(hour=hour):
                result = self.route_hour(hour)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), output)

    def test_invalid_hour_fails_closed(self):
        result = self.route_hour("24")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Invalid hour", result.stderr)


if __name__ == "__main__":
    unittest.main()
