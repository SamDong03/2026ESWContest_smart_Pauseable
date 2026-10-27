"""Render selection -> HA/webOS payload checks; no real network or appliance."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


player = load("lg_music_player", BASE / "player.py")
launcher = load("lg_tv_launcher", ROOT / "Pauseable.ai/ha/src/play_lg_tv_youtube.py")
VIDEO = "9bZkp7q19f0"
ENV = {
    "PAUSEABLE_MUSIC_BACKEND": "lg_tv", "PATIENT_ID": "patient1",
    "PAUSEABLE_DEVICE_TOKEN": "fake-device-token",
    "HA_URL": "http://ha.example.test:8123", "HA_TOKEN": "fake-ha-token",
    "TV_ENTITY": "media_player.test_tv",
}


class LgTvTest(unittest.TestCase):
    def test_render_response_reaches_ha_webos_payload_without_atlas(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({
            "video_id": VIDEO, "url": "https://www.youtube.com/watch?v=" + VIDEO,
        }).encode()
        opener = Mock()
        opener.open.return_value = response

        def fetch(*args):
            return player.fetch_random_song(*args, opener=opener)

        def execute(command, **kwargs):
            self.assertEqual(command[-2:], ["--video-id", VIDEO])
            self.assertNotIn(ENV["HA_TOKEN"], " ".join(command))
            self.assertTrue(Path(command[1]).is_file())
            with patch.dict(os.environ, kwargs["env"], clear=True), patch.object(
                sys, "argv", command[1:],
            ):
                launcher.main()

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            player.subprocess, "run", side_effect=execute,
        ), patch.object(launcher, "state", return_value="on"), patch.object(
            launcher, "call_service",
        ) as service, patch.object(launcher.time, "sleep"), patch.object(
            player, "play_atlas",
        ) as atlas:
            player.request_playback(ENV, temporary, now=1000, fetch=fetch)
            service.assert_any_call("webostv", "command", {
                "entity_id": "media_player.test_tv", "command": "system.launcher/launch",
                "payload": {"id": "youtube.leanback.v4", "contentId": "v=" + VIDEO},
            })
            atlas.assert_not_called()
            self.assertEqual(json.loads((Path(temporary) / "last-request.json").read_text())["backend"], "lg_tv")

    def test_tv_failure_does_not_consume_cooldown_or_fallback_to_atlas(self):
        with tempfile.TemporaryDirectory() as temporary:
            atlas = Mock()
            with self.assertRaises(subprocess.CalledProcessError):
                player.request_playback(ENV, temporary, fetch=Mock(return_value=VIDEO), atlas=atlas,
                    lg_tv=Mock(side_effect=subprocess.CalledProcessError(1, "launcher")))
            atlas.assert_not_called()
            self.assertFalse((Path(temporary) / "last-request.json").exists())

    def test_invalid_backend_is_rejected_before_api_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            fetch = Mock()
            with self.assertRaises(ValueError):
                player.request_playback({**ENV, "PAUSEABLE_MUSIC_BACKEND": "typo"}, temporary, fetch=fetch)
            fetch.assert_not_called()

    def test_invalid_video_or_missing_ha_credentials_never_launches(self):
        with patch.object(player.subprocess, "run") as run:
            for video, env in [("bad", ENV), (VIDEO, {**ENV, "HA_TOKEN": ""})]:
                with self.assertRaises(ValueError):
                    player.play_lg_tv(video, env)
            run.assert_not_called()

    def test_backend_change_does_not_reuse_atlas_cooldown(self):
        with tempfile.TemporaryDirectory() as temporary:
            atlas, tv = Mock(), Mock()
            player.request_playback({**ENV, "PAUSEABLE_MUSIC_BACKEND": "atlas"}, temporary,
                now=1000, fetch=Mock(return_value=VIDEO), atlas=atlas)
            player.request_playback(ENV, temporary, now=1001, fetch=Mock(return_value=VIDEO), lg_tv=tv)
            tv.assert_called_once()


if __name__ == "__main__":
    unittest.main()
