
import pathlib
import shutil
import subprocess
import unittest

FILTER = pathlib.Path(__file__).resolve().parents[1] / "route-filter.awk"


def accepted(event, source="wandering-ai", decision="wandering_suspected", risk="caution"):
    return f"CENTRAL_DECISION_ACCEPTED event_id={event} source={source} decision={decision} risk={risk} score=95\n"


def routed(event, disposition="execute", speak="true"):
    return f"CENTRAL_ACTION_ROUTED event_id={event} disposition={disposition} reason=first_risk_event notify=true speak={speak} control=false\n"


class RouteFilterTest(unittest.TestCase):
    def run_filter(self, records):
        result = subprocess.run(
            [shutil.which("awk") or "awk", "-f", str(FILTER)],
            input=records, text=True, capture_output=True, check=True,
        )
        return result.stdout.splitlines()

    def test_allowed_wandering_and_same_event_join(self):
        self.assertEqual(self.run_filter(
            accepted("evt-a") + accepted("evt-b", risk="danger") +
            routed("evt-b") + routed("evt-a")
        ), ["evt-b", "evt-a"])

    def test_cooldown_and_speech_disabled(self):
        self.assertEqual(self.run_filter(
            accepted("evt-a") + routed("evt-a", disposition="suppressed") +
            accepted("evt-b") + routed("evt-b", speak="false")
        ), [])

    def test_unknown_normal_repetitive_and_unmatched_routes(self):
        self.assertEqual(self.run_filter(
            accepted("evt-a", decision="unknown", risk="unknown") + routed("evt-a") +
            accepted("evt-b", decision="normal", risk="normal") + routed("evt-b") +
            accepted("evt-c", source="repetitive-ai") + routed("evt-c") +
            routed("evt-missing")
        ), [])

    def test_duplicate_routes_and_invalid_identifier(self):
        self.assertEqual(self.run_filter(
            accepted("evt-a") + routed("evt-a") + routed("evt-a") +
            accepted("../../bad") + routed("../../bad")
        ), ["evt-a"])


if __name__ == "__main__":
    unittest.main()
