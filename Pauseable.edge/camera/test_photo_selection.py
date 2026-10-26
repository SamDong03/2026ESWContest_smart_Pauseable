
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    "camera_photo_timing_test", Path(__file__).with_name("camera_buffer.py")
)
camera = importlib.util.module_from_spec(spec)
with mock.patch.dict(sys.modules, {"gi": mock.MagicMock(), "gi.repository": mock.MagicMock()}):
    spec.loader.exec_module(camera)


class PhotoSelectionTests(unittest.TestCase):
    def test_exit_uses_photo_before_trigger_instead_of_old_motion_peak(self):
        jpeg, selection = camera.select_representative_photo(
            "EXIT", 100,
            [(80, b"old-peak"), (99.0, b"before"), (99.5, b"after-target"), (100.1, b"late")],
            [(102.5, b"return")], [(80, 0.9, True)], [],
        )
        self.assertEqual(jpeg, b"before")
        self.assertEqual(selection["requested_offset_seconds"], -0.75)
        self.assertEqual(selection["selected_offset_seconds"], -1.0)
        self.assertEqual(selection["selection_error_seconds"], 0.25)

    def test_return_uses_photo_at_two_and_half_seconds_instead_of_later_motion_peak(self):
        jpeg, selection = camera.select_representative_photo(
            "RETURN", 100, [(99.25, b"exit")],
            [(102.4, b"near"), (103, b"later"), (109, b"peak")], [], [(109, 0.9, True)],
        )
        self.assertEqual(jpeg, b"near")
        self.assertEqual(selection["requested_offset_seconds"], 2.5)
        self.assertEqual(selection["selected_offset_seconds"], 2.4)
        self.assertEqual(selection["selection_error_seconds"], 0.1)

    def test_missing_exit_buffer_does_not_replace_it_with_return_photo(self):
        jpeg, selection = camera.select_representative_photo(
            "EXIT", 100, [], [(102.5, b"wrong-phase")], [], [],
        )
        self.assertIsNone(jpeg)
        self.assertEqual(selection["status"], "missing")

    def test_unconfirmed_direction_keeps_motion_based_selection(self):
        for decision in ("NO_PASSAGE", "UNKNOWN_ACTIVE_BOTH"):
            with self.subTest(decision=decision):
                jpeg, selection = camera.select_representative_photo(
                    decision, 100, [(99, b"before")], [(104, b"after")],
                    [(99, 0.01, False)], [(104, 0.5, True)],
                )
                self.assertEqual(jpeg, b"after")
                self.assertEqual(selection["policy"], "strongest_motion_unconfirmed_direction")

    def test_save_event_preserves_direction_and_writes_selected_photo_and_timing(self):
        for decision in ("EXIT", "RETURN"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as output:
                camera.recent_photos.clear()
                camera.motion_history.clear()
                camera.recent_photos.extend([(80, b"old"), (99.25, b"exit"), (100.1, b"late")])
                for at in (98, 98.2, 98.4):
                    moving = decision == "EXIT"
                    camera.motion_history.append((at, 0.1 if moving else 0, moving))

                def collect_post_frames(_seconds):
                    camera.active_photo_collector.extend([(102.5, b"return"), (109, b"late-peak")])
                    for at in (101, 101.2, 101.4):
                        moving = decision == "RETURN"
                        camera.active_motion_collector.append((at, 0.1 if moving else 0, moving))

                with mock.patch.object(camera, "OUTPUT_DIR", output), \
                     mock.patch.object(camera.time, "sleep", side_effect=collect_post_frames):
                    result = camera.save_event(100)

                event_dir = Path(output) / result["event"]
                self.assertEqual(result["decision"], decision)
                self.assertEqual(result["event_time"], "1970-01-01T00:01:40+00:00")
                self.assertEqual((event_dir / "representative.jpg").read_bytes(),
                                 b"exit" if decision == "EXIT" else b"return")
                self.assertEqual(result["photo_selection"]["selection_error_seconds"], 0)
                self.assertEqual(json.loads((event_dir / "result.json").read_text())["photo_selection"],
                                 result["photo_selection"])
                self.assertIsNone(camera.active_photo_collector)
                self.assertIsNone(camera.active_motion_collector)


if __name__ == "__main__":
    unittest.main()
