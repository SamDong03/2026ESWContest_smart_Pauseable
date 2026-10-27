"""Linux FIFO/controller integration with fake Docker/systemctl, not a real Pi."""

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "requires Linux FIFO/shell")
class ControllerTest(unittest.TestCase):
    def run_commands(self, commands, expected_count, *, fail_player=False):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            fifo = directory / "request.fifo"
            os.mkfifo(fifo)
            log = directory / "calls.txt"
            docker = directory / "docker"
            docker.write_text(
                '#!/bin/sh\ncase "$*" in\n'
                '*inspect*) echo true ;;\n'
                '*exec*) printf "PLAYER %s\\n" "$*" >> "$FAKE_LOG"; exit "$FAKE_PLAYER_STATUS" ;;\n'
                'esac\n', encoding="utf-8",
            )
            systemctl = directory / "systemctl"
            systemctl.write_text('#!/bin/sh\nexit 0\n', encoding="utf-8")
            music = directory / "request.sh"
            music.write_text('#!/bin/sh\nprintf "SELECT_RANDOM\\n" >> "$FAKE_LOG"\n', encoding="utf-8")
            docker.chmod(0o700)
            systemctl.chmod(0o700)
            script = (BASE / "youtube-control.sh").read_text(encoding="utf-8")
            script = script.replace("/run/pauseable-youtube-request.fifo", str(fifo))
            script = script.replace("/run/pauseable-youtube-launch.once", str(directory / "launch.once"))
            script = script.replace("/data/pauseable/favorite-music/request.sh", str(music))
            script = script.replace("/usr/bin/docker", str(docker))
            controller = directory / "controller.sh"
            controller.write_text(script, encoding="utf-8")
            env = dict(os.environ, PATH=f"{directory}:{os.environ.get('PATH', '')}",
                       FAKE_LOG=str(log), FAKE_PLAYER_STATUS="1" if fail_player else "0")
            descriptor = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            process = subprocess.Popen(["sh", str(controller)], stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=env, text=True)
            try:
                os.write(descriptor, ("\n".join(commands) + "\n").encode())
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
                    if len(lines) >= expected_count:
                        break
                    time.sleep(0.02)
                self.assertEqual(process.poll(), None, "controller must survive rejected/failed commands")
                self.assertEqual(len(lines), expected_count)
                return lines
            finally:
                process.terminate()
                process.communicate(timeout=5)
                os.close(descriptor)

    def test_random_api_choice_reaches_browser_as_canonical_youtube_url(self):
        lines = self.run_commands(["PLAY_VIDEO dQw4w9WgXcQ"], 1)
        self.assertIn("https://www.youtube.com/watch?v=dQw4w9WgXcQ&autoplay=1", lines[0])

    def test_invalid_ids_are_rejected_before_a_valid_request(self):
        lines = self.run_commands([
            "PLAY_VIDEO $(touch nope)", "PLAY_VIDEO ../bad", "PLAY_VIDEO short",
            "PLAY_VIDEO 9bZkp7q19f0",
        ], 1)
        self.assertIn("9bZkp7q19f0", lines[0])

    def test_player_failure_does_not_stop_following_commands(self):
        self.run_commands(["PLAY_VIDEO dQw4w9WgXcQ", "PLAY_VIDEO 9bZkp7q19f0"], 2, fail_player=True)

    def test_legacy_trigger_uses_random_selector_not_demo_video(self):
        self.assertEqual(self.run_commands(["PLAY_TROT"], 1), ["SELECT_RANDOM"])


if __name__ == "__main__":
    unittest.main()
