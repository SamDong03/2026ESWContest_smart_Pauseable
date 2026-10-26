import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class FavoriteSongsApiTest(unittest.TestCase):
    def test_guardian_save_device_random_and_delete(self):
        with TemporaryDirectory() as directory, patch.object(
            main, "STORAGE_BACKEND", "local"
        ), patch("app.favorite_songs.SONGS_DIR", Path(directory)), patch.dict(
            "os.environ",
            {"PAUSEABLE_APP_TOKEN": "app-test", "PAUSEABLE_DEVICE_TOKEN": "device-test"},
        ):
            client = TestClient(main.app)
            url = "/api/patients/byunwoojin/favorite-songs"
            guardian = {"Authorization": "Bearer app-test"}
            device = {"Authorization": "Bearer device-test"}
            songs = [
                {"title": "첫 번째 곡", "url": "https://youtu.be/dQw4w9WgXcQ?t=10"},
                {"title": "두 번째 곡", "url": "https://www.youtube.com/watch?v=9bZkp7q19f0"},
            ]

            self.assertEqual(client.get(url).status_code, 401)
            self.assertEqual(client.get(url, headers=guardian).json()["songs"], [])
            self.assertEqual(client.put(url, json={"songs": songs}, headers=guardian).status_code, 200)
            stored = client.get(url, headers=guardian).json()["songs"]
            self.assertEqual(len(stored), 2)
            self.assertEqual(stored[0]["url"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            self.assertEqual(client.get(url, headers=device).status_code, 403)

            pick_url = "/api/device/patients/byunwoojin/favorite-songs/random"
            self.assertEqual(client.get(pick_url, headers=guardian).status_code, 403)
            for _ in range(12):
                self.assertIn(client.get(pick_url, headers=device).json(), stored)

            self.assertEqual(
                client.put(url, json={"songs": songs + [songs[0]]}, headers=guardian).status_code,
                422,
            )
            self.assertEqual(
                client.put(url, json={"songs": [{"title": "bad", "url": "https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ"}]}, headers=guardian).status_code,
                422,
            )
            self.assertEqual(
                client.put(url, json={"songs": [{"title": "bad", "url": "https://[invalid/watch?v=dQw4w9WgXcQ"}]}, headers=guardian).status_code,
                422,
            )
            self.assertEqual(client.put(url, json={"songs": []}, headers=guardian).status_code, 200)
            self.assertEqual(client.get(pick_url, headers=device).status_code, 404)


if __name__ == "__main__":
    unittest.main()
