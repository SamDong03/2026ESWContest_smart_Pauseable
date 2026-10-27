import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError


BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[2]
spec = importlib.util.spec_from_file_location("favorite_music_player", BASE / "player.py")
player = importlib.util.module_from_spec(spec)
spec.loader.exec_module(player)
FIRST = "dQw4w9WgXcQ"
SECOND = "9bZkp7q19f0"


class Response:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.body[:size]


def song(video_id=FIRST):
    return {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}


class FavoriteMusicTest(unittest.TestCase):
    def test_device_auth_and_patient_scoped_random_endpoint(self):
        opener = Mock()
        opener.open.return_value = Response(song())
        self.assertEqual(player.fetch_random_song(
            "https://api.example.test/", "byunwoojin", "device-test", opener=opener,
        ), FIRST)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url,
                         "https://api.example.test/api/device/patients/byunwoojin/favorite-songs/random")
        self.assertEqual(request.get_header("Authorization"), "Bearer device-test")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 30)

    def test_response_cannot_supply_an_arbitrary_url_or_command(self):
        bad = [[], {}, {"video_id": "$(touch /tmp/pwned)"},
               {"video_id": FIRST, "url": "https://youtube.com.evil.test/watch?v=" + FIRST},
               {"video_id": FIRST, "url": "https://www.youtube.com/watch?v=" + SECOND}]
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                opener = Mock()
                opener.open.return_value = Response(payload)
                player.fetch_random_song("https://api.example.test", "patient1", "device-test", opener=opener)

    def test_invalid_configuration_never_sends_credentials(self):
        for url, patient, token in [
            ("http://api.example.test", "patient1", "secret"),
            ("https://user:pass@api.example.test", "patient1", "secret"),
            ("https://api.example.test?q=x", "patient1", "secret"),
            ("https://api.example.test", "../other", "secret"),
            ("https://api.example.test", "patient1", ""),
        ]:
            opener = Mock()
            with self.subTest(url=url), self.assertRaises(ValueError):
                player.fetch_random_song(url, patient, token, opener=opener)
            opener.open.assert_not_called()

    def test_redirects_are_not_followed_with_device_token(self):
        self.assertIsNone(player.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.test"))

    def test_every_request_uses_current_server_selection_and_cooldown(self):
        with tempfile.TemporaryDirectory() as temporary:
            fetch = Mock(side_effect=[FIRST, SECOND])
            atlas = Mock()
            env = {"PATIENT_ID": "byunwoojin", "PAUSEABLE_DEVICE_TOKEN": "device-test"}
            player.request_playback(env, temporary, now=1000, fetch=fetch, atlas=atlas)
            player.request_playback(env, temporary, now=1001, fetch=fetch, atlas=atlas)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(atlas.call_count, 1)
            player.request_playback(env, temporary, now=1300, fetch=fetch, atlas=atlas)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual([call.args[0] for call in atlas.call_args_list], [FIRST, SECOND])

    def test_empty_list_or_auth_failure_does_not_touch_player_or_cooldown(self):
        for status in (404, 401, 403, 503):
            with tempfile.TemporaryDirectory() as temporary:
                fetch = Mock(side_effect=HTTPError("https://api.example.test", status, "", {}, None))
                atlas = Mock()
                player.request_playback({}, temporary, fetch=fetch, atlas=atlas)
                atlas.assert_not_called()
                self.assertFalse((Path(temporary) / "last-request.json").exists())

    def test_disabled_does_not_fetch_or_play(self):
        fetch, atlas = Mock(), Mock()
        with tempfile.TemporaryDirectory() as temporary:
            player.request_playback({"PAUSEABLE_FAVORITE_MUSIC_ENABLED": "0"}, temporary, fetch=fetch, atlas=atlas)
        fetch.assert_not_called()
        atlas.assert_not_called()

    def test_failed_fifo_does_not_consume_cooldown(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(OSError):
                player.request_playback({}, temporary, fetch=lambda *args: FIRST,
                                        atlas=Mock(side_effect=OSError("not running")))
            self.assertFalse((Path(temporary) / "last-request.json").exists())

    def test_bad_cooldown_fails_before_api(self):
        for value in ("-1", "nan", "inf", "999999", "bad"):
            with tempfile.TemporaryDirectory() as temporary:
                fetch = Mock()
                with self.assertRaises(ValueError):
                    player.request_playback({"PAUSEABLE_MUSIC_COOLDOWN_SECONDS": value}, temporary, fetch=fetch)
                fetch.assert_not_called()

    def test_main_handles_network_failure_without_logging_credentials(self):
        fake_fcntl = types.SimpleNamespace(flock=Mock(), LOCK_EX=2, LOCK_NB=4)
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "PAUSEABLE_FAVORITE_MUSIC_ENABLED": "1", "PAUSEABLE_MUSIC_STATE_DIR": temporary,
        }), patch.dict(sys.modules, {"fcntl": fake_fcntl}), patch.object(
            player, "request_playback", side_effect=URLError("secret-device-token"),
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(player.main(), 0)
        self.assertIn("FAVORITE_MUSIC_SKIPPED", output.getvalue())
        self.assertNotIn("secret-device-token", output.getvalue())

    def test_regular_file_is_not_accepted_as_player_fifo(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "not-a-fifo"
            path.write_text("untouched", encoding="utf-8")
            with self.assertRaises(ValueError):
                player.play_atlas(FIRST, str(path))
            self.assertEqual(path.read_text(encoding="utf-8"), "untouched")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_fifo_gets_only_the_validated_video_id_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "player.fifo"
            os.mkfifo(path)
            descriptor = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            try:
                player.play_atlas(FIRST, str(path))
                self.assertEqual(os.read(descriptor, 128), f"PLAY_VIDEO {FIRST}\n".encode())
            finally:
                os.close(descriptor)

    def test_both_approved_watchers_queue_after_guidance_not_sensor_arrival(self):
        paths = [ROOT / "Pauseable.ai/ha/deploy/repetitive-central-output-watch.sh",
                 ROOT / "Pauseable.edge/central/deploy/wandering-voice/watch.sh"]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIn("already_claimed", text)
            self.assertIn("music_request=/data/pauseable/favorite-music/request.sh", text)
            self.assertIn('/bin/sh "$music_request" || true', text)
            self.assertLess(text.index('"$claim/completed"'), text.index("music_request="))

    def test_controller_has_no_fixed_or_stale_song_fallback(self):
        text = (BASE / "youtube-control.sh").read_text(encoding="utf-8")
        self.assertIn("'PLAY_VIDEO '*", text)
        self.assertIn('"${#video_id}" -ne 11', text)
        self.assertIn('play_video "${request#PLAY_VIDEO }" || true', text)
        self.assertNotIn("SUIM5wHIU7o", text)
        self.assertNotIn("washer-favorite-url.txt", text)
        for path in [ROOT / "Pauseable.ai/ha/scripts/pauseable-youtube-control.sh",
                     ROOT / "Pauseable.edge/actions/youtube/pauseable-youtube-control.sh"]:
            self.assertIn("/data/pauseable/favorite-music/youtube-control.sh", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
