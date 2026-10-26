import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.alert_history_store import AlertHistoryConflict, AlertHistoryStore


class FakeR2Storage:
    def __init__(self):
        self.objects = {}

    def get_json(self, key):
        return self.objects.get(key)

    def put_json_if_absent(self, key, payload):
        if key in self.objects:
            return None
        self.objects[key] = payload
        return "etag"

    def list_keys(self, prefix):
        return [key for key in self.objects if key.startswith(prefix)]


class AlertHistoryStoreTest(unittest.TestCase):
    def test_r2_history_is_idempotent_patient_scoped_and_readable(self):
        r2 = FakeR2Storage()
        with TemporaryDirectory() as directory:
            store = AlertHistoryStore(local_dir=Path(directory), r2_storage=r2)
            alert = {
                "alert_id": "ha-event-001",
                "patient_id": "byunwoojin",
                "occurred_at": "2026-10-04T10:11:12Z",
                "title": "냉장고 문 열림",
            }
            self.assertTrue(store.create(alert))
            self.assertFalse(store.create(alert))
            with self.assertRaises(AlertHistoryConflict):
                store.create({**alert, "title": "다른 사건"})
            self.assertEqual(store.list_recent("other-patient"), [])

            restarted = AlertHistoryStore(local_dir=Path(directory), r2_storage=r2)
            self.assertFalse(restarted.list_recent("byunwoojin")[0]["is_read"])
            self.assertTrue(restarted.mark_read("byunwoojin", "ha-event-001"))
            self.assertTrue(restarted.list_recent("byunwoojin")[0]["is_read"])
            self.assertFalse(restarted.mark_read("other-patient", "ha-event-001"))


if __name__ == "__main__":
    unittest.main()
