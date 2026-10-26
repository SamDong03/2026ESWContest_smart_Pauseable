import pathlib
import subprocess
import unittest


ROUTER = pathlib.Path(__file__).resolve().parents[1] / "time-router.sh"


def route(hour):
    return subprocess.run(
        ["sh", str(ROUTER), hour],
        check=False,
        capture_output=True,
        text=True,
    )


class TimeRouterTest(unittest.TestCase):
    def test_water_window(self):
        for hour in ("08", "09", "13"):
            with self.subTest(hour=hour):
                self.assertEqual(route(hour).stdout.strip(), "water_purifier")

    def test_tiiun_window(self):
        for hour in ("14", "15", "17"):
            with self.subTest(hour=hour):
                self.assertEqual(route(hour).stdout.strip(), "tiiun")

    def test_styler_window_wraps_midnight(self):
        for hour in ("18", "23", "00", "07"):
            with self.subTest(hour=hour):
                self.assertEqual(route(hour).stdout.strip(), "styler")

    def test_invalid_hour_fails_closed(self):
        result = route("24")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Invalid hour", result.stderr)


if __name__ == "__main__":
    unittest.main()
