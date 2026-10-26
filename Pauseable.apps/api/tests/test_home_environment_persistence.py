import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import home_environment as home, main


class HomePersistenceTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        change = patch.object(home, 'HOME_SETTINGS_DIR', Path(self.directory.name))
        change.start()
        self.addCleanup(change.stop)
        self.objects = {}
        objects = self.objects

        class FakeStorage:
            def get_json(self, key):
                return objects.get(key)

            def put_json(self, key, payload):
                objects[key] = dict(payload)

            def put_json_if_absent(self, key, payload):
                if key in objects:
                    return None
                objects[key] = dict(payload)
                return 'created'

        self.storage = FakeStorage()
        change = patch.object(home.R2Storage, 'from_environment', return_value=self.storage)
        change.start()
        self.addCleanup(change.stop)

    def test_region_survives_empty_new_deployment_directory(self):
        saved = home.save_home_environment('byunwoojin', '1111051500', False, 'r2')
        self.assertEqual(saved['storage_backend'], 'r2')
        self.assertTrue(saved['is_persistent'])
        self.assertIn('patients/byunwoojin/home-environment.json', self.objects)
        with TemporaryDirectory() as fresh_directory, patch.object(
            home, 'HOME_SETTINGS_DIR', Path(fresh_directory),
        ):
            self.assertEqual(home.load_home_environment('byunwoojin', 'r2'), saved)
        self.assertIsNone(home.load_home_environment('another-patient', 'r2')['region'])

    def test_legacy_local_selection_is_migrated_without_deleting_it(self):
        legacy = Path(self.directory.name) / 'byunwoojin.json'
        legacy.write_text(json.dumps({
            'region_code': '1111051500', 'auto_lighting_enabled': False,
        }), encoding='utf-8')
        loaded = home.load_home_environment('byunwoojin', 'r2')
        self.assertEqual(loaded['region']['code'], '1111051500')
        self.assertTrue(legacy.is_file())
        self.assertIn('patients/byunwoojin/home-environment.json', self.objects)

    def test_r2_selection_wins_over_a_stale_local_file(self):
        home.save_home_environment('byunwoojin', '1111051500', False, 'local')
        self.objects['patients/byunwoojin/home-environment.json'] = {
            'region_code': 'removed-region', 'auto_lighting_enabled': False,
        }
        self.assertIsNone(home.load_home_environment('byunwoojin', 'r2')['region'])
        self.assertEqual(self.objects['patients/byunwoojin/home-environment.json']['region_code'], 'removed-region')

    def test_storage_failure_does_not_report_local_success(self):
        home.save_home_environment('byunwoojin', '1111051500', False, 'local')
        with patch.object(self.storage, 'get_json', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                home.load_home_environment('byunwoojin', 'r2')
        with patch.object(self.storage, 'put_json', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                home.save_home_environment('byunwoojin', '1111051500', False, 'r2')

    def test_api_uses_configured_r2_storage_and_keeps_authentication(self):
        with patch.object(main, 'STORAGE_BACKEND', 'r2'), patch.dict('os.environ', {
            'PAUSEABLE_ENV': 'production', 'PAUSEABLE_APP_TOKEN': 'home-test-app',
        }):
            client = TestClient(main.app)
            url = '/api/patients/byunwoojin/home-environment'
            self.assertEqual(client.get(url).status_code, 401)
            headers = {'Authorization': 'Bearer home-test-app'}
            saved = client.put(url, headers=headers, json={
                'region_code': '1111051500', 'auto_lighting_enabled': False,
            })
            self.assertEqual(saved.status_code, 200)
            self.assertTrue(saved.json()['is_persistent'])
            self.assertEqual(TestClient(main.app).get(url, headers=headers).json(), saved.json())
            self.assertEqual(client.get(
                '/api/patients/another-patient/home-environment', headers=headers,
            ).status_code, 404)


if __name__ == '__main__':
    unittest.main()
