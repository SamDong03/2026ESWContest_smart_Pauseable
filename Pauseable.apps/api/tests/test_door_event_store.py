import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
from unittest.mock import patch

from app.door_event_store import (
    EVENT_PREFIX, DoorEventConflict, DoorEventStore,
)


def event(event_id, second=1):
    return {
        "id": event_id, "device_id": "test-camera", "patient_id": "test-patient",
        "occurred_at": f"2026-10-10T00:00:{second:02d}Z", "decision": "EXIT",
        "motion_statistics": {"pre": {"movement": True}},
    }


class FakeR2:
    def __init__(self):
        self.objects = {}
        self.reads = Counter()
        self.lock = Lock()
        self.list_calls = 0

    def list_keys(self, prefix):
        with self.lock:
            self.list_calls += 1
            return sorted(key for key in self.objects if key.startswith(prefix))

    def get_json(self, key):
        with self.lock:
            self.reads[key] += 1
            return deepcopy(self.objects.get(key))

    def put_json_if_absent(self, key, payload):
        with self.lock:
            if key in self.objects:
                return None
            self.objects[key] = deepcopy(payload)
            return "etag"

    def put_bytes(self, key, data, **kwargs):
        self.objects[key] = data

    def get_bytes(self, key):
        return self.objects.get(key)

    def add(self, payload):
        self.objects[f"{EVENT_PREFIX}{payload['id']}.json"] = deepcopy(payload)


class DoorEventStoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.r2 = FakeR2()
        self.store = DoorEventStore(local_dir=Path(self.directory.name), r2_storage=self.r2)

    def test_warm_list_fetches_only_new_metadata_and_keeps_order(self):
        self.r2.add(event("first", 1))
        self.r2.add(event("second", 2))
        self.assertEqual([e["id"] for e in self.store.list_events()], ["second", "first"])
        self.store.list_events()
        self.r2.add(event("third", 3))
        self.assertEqual([e["id"] for e in self.store.list_events()], ["third", "second", "first"])
        self.assertEqual(list(self.r2.reads.values()), [1, 1, 1])
        self.assertEqual(self.r2.list_calls, 3)

    def test_new_upload_is_cached_only_after_success_and_remains_idempotent(self):
        payload = event("uploaded")
        stored, duplicate = self.store.create_event(payload, b"jpeg")
        self.assertFalse(duplicate)
        reads = self.r2.reads.copy()
        self.assertEqual(self.store.list_events(), [stored])
        self.assertEqual(self.r2.reads, reads)
        _, duplicate = self.store.create_event(payload, b"jpeg")
        self.assertTrue(duplicate)
        with self.assertRaises(DoorEventConflict):
            self.store.create_event({**payload, "decision": "RETURN"}, b"jpeg")

    def test_callers_cannot_mutate_cached_nested_metadata(self):
        self.r2.add(event("one"))
        result = self.store.list_events()
        result[0]["motion_statistics"]["pre"]["movement"] = False
        result[0]["id"] = "changed"
        self.assertEqual(self.store.list_events(), [event("one")])
        stored, _ = self.store.create_event(event("two", 2), b"jpeg")
        stored["motion_statistics"]["pre"]["movement"] = False
        self.assertTrue(self.store.list_events()[0]["motion_statistics"]["pre"]["movement"])

    def test_deleted_key_is_removed_and_recreated_key_is_refetched(self):
        self.r2.add(event("one"))
        self.store.list_events()
        del self.r2.objects[f"{EVENT_PREFIX}one.json"]
        self.assertEqual(self.store.list_events(), [])
        self.r2.add(event("one", 2))
        self.assertEqual(self.store.list_events(), [event("one", 2)])
        self.assertEqual(self.r2.reads[f"{EVENT_PREFIX}one.json"], 2)

    def test_cached_point_reads_do_not_list_or_download_other_events(self):
        self.r2.add(event("one"))
        self.r2.add(event("two", 2))
        self.store.list_events()
        reads = self.r2.reads.copy()
        lists = self.r2.list_calls
        result = self.store.get_event("one", use_cache=True)
        self.assertEqual(result, event("one"))
        result["motion_statistics"]["pre"]["movement"] = False
        self.assertEqual(self.store.get_event("one", use_cache=True), event("one"))
        self.assertEqual(self.r2.reads, reads)
        self.assertEqual(self.r2.list_calls, lists)

        self.r2.add(event("one", 3))
        self.assertEqual(self.store.get_event("one"), event("one", 3))

    def test_cold_point_read_caches_only_the_requested_record(self):
        self.r2.add(event("one"))
        self.r2.add(event("two", 2))
        self.assertEqual(self.store.get_event("two", use_cache=True), event("two", 2))
        self.assertEqual(self.store.get_event("two", use_cache=True), event("two", 2))
        self.assertEqual(self.r2.list_calls, 0)
        self.assertEqual(self.r2.reads, {f"{EVENT_PREFIX}two.json": 1})

    def test_missing_metadata_is_not_negatively_cached(self):
        key = f"{EVENT_PREFIX}late.json"
        self.r2.objects[key] = None
        self.assertEqual(self.store.list_events(), [])
        self.r2.add(event("late"))
        self.assertEqual(self.store.list_events(), [event("late")])
        self.assertEqual(self.r2.reads[key], 2)

    def test_storage_errors_propagate_instead_of_returning_incomplete_history(self):
        self.r2.add(event("one"))
        with patch.object(self.r2, "get_json", side_effect=OSError("storage unavailable")):
            with self.assertRaises(OSError):
                self.store.list_events()
        self.assertEqual(self.store.list_events(), [event("one")])

    def test_cold_reads_are_parallel_bounded_and_shared_by_concurrent_requests(self):
        for i in range(8):
            self.r2.add(event(f"item-{i}", i))
        barrier = Barrier(4)
        original = self.r2.get_json
        active = 0
        peak = 0
        counter_lock = Lock()

        def coordinated_read(key):
            nonlocal active, peak
            with counter_lock:
                active += 1
                peak = max(peak, active)
            try:
                barrier.wait(timeout=5)
                return original(key)
            finally:
                with counter_lock:
                    active -= 1

        with patch.object(self.r2, "get_json", side_effect=coordinated_read):
            with ThreadPoolExecutor(max_workers=2) as callers:
                results = list(callers.map(lambda _: self.store.list_events(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(results[0]), 8)
        self.assertEqual(peak, 4)
        self.assertTrue(all(count == 1 for count in self.r2.reads.values()))

    def test_cache_is_bounded_without_truncating_returned_history(self):
        for i in range(4):
            self.r2.add(event(f"item-{i}", i))
        with patch("app.door_event_store.METADATA_CACHE_SIZE", 2):
            self.assertEqual(len(self.store.list_events()), 4)
            self.assertEqual(len(self.store._metadata_cache), 2)
            self.assertEqual(len(self.store.list_events()), 4)
            self.assertEqual(len(self.store._metadata_cache), 2)

    def test_local_storage_and_restart_preserve_events_and_images(self):
        local = DoorEventStore(local_dir=Path(self.directory.name))
        stored, duplicate = local.create_event(event("local"), b"jpeg")
        self.assertFalse(duplicate)
        restarted = DoorEventStore(local_dir=Path(self.directory.name))
        self.assertEqual(restarted.list_events(), [stored])
        self.assertEqual(restarted.get_image(stored), b"jpeg")
        self.assertTrue(restarted.create_event(event("local"), b"jpeg")[1])
        cold_r2 = DoorEventStore(local_dir=Path(self.directory.name), r2_storage=self.r2)
        self.r2.add(event("remote"))
        self.assertEqual(cold_r2.list_events(), [event("remote")])


if __name__ == "__main__":
    unittest.main()
