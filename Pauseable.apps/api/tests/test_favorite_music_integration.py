"""Guardian save -> device random API -> Pi dispatch; no live hardware/cloud."""

import contextlib
import importlib.util
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from app import main


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "favorite_music_integration_player", ROOT / "Pauseable.edge/actions/favorite-music/player.py",
)
player = importlib.util.module_from_spec(spec)
spec.loader.exec_module(player)


class ApiResponse:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size):
        return self.response.content[:size]


class ApiOpener:
    def __init__(self, client):
        self.client = client

    def open(self, request, timeout):
        response = self.client.get(urlsplit(request.full_url).path, headers=dict(request.header_items()))
        if response.status_code != 200:
            raise HTTPError(request.full_url, response.status_code, "", {}, None)
        return ApiResponse(response)


class FavoriteMusicIntegrationTest(unittest.TestCase):
    def test_saved_list_random_dispatch_then_delete_without_safety_side_effects(self):
        with TemporaryDirectory() as temporary, patch.object(main, "STORAGE_BACKEND", "local"), patch(
            "app.favorite_songs.SONGS_DIR", Path(temporary) / "songs",
        ), patch.dict(os.environ, {"PAUSEABLE_APP_TOKEN": "app-test", "PAUSEABLE_DEVICE_TOKEN": "device-test"}):
            client = TestClient(main.app)
            url = "/api/patients/byunwoojin/favorite-songs"
            guardian = {"Authorization": "Bearer app-test"}
            songs = [{"title": "first", "url": "https://youtu.be/dQw4w9WgXcQ"},
                     {"title": "second", "url": "https://youtu.be/9bZkp7q19f0"}]
            self.assertEqual(client.put(url, json={"songs": songs}, headers=guardian).status_code, 200)
            opener = ApiOpener(client)
            env = {"PATIENT_ID": "byunwoojin", "PAUSEABLE_DEVICE_TOKEN": "device-test",
                   "PAUSEABLE_MUSIC_COOLDOWN_SECONDS": "0"}
            state = Path(temporary) / "state"
            state.mkdir()
            dispatched = []
            with patch("app.favorite_songs.secrets.choice", side_effect=lambda values: values[-1]):
                player.request_playback(
                    env, state,
                    fetch=lambda *args: player.fetch_random_song(*args, opener=opener),
                    atlas=lambda video_id, fifo: dispatched.append(video_id),
                )
            self.assertEqual(dispatched, ["9bZkp7q19f0"])
            self.assertEqual(client.get(url, headers=guardian).json()["songs"][1]["video_id"], dispatched[0])
            self.assertEqual(client.put(url, json={"songs": []}, headers=guardian).status_code, 200)
            with contextlib.redirect_stdout(io.StringIO()) as output:
                player.request_playback(
                    env, state,
                    fetch=lambda *args: player.fetch_random_song(*args, opener=opener),
                    atlas=lambda video_id, fifo: dispatched.append(video_id),
                )
            self.assertEqual(len(dispatched), 1)
            self.assertIn("no_saved_songs_or_patient", output.getvalue())


if __name__ == "__main__":
    unittest.main()
