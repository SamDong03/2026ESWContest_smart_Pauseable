import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class HomeEnvironmentApiTest(unittest.TestCase):
    def test_region_is_isolated_and_saved_with_canonical_grid(self):
        with TemporaryDirectory() as directory, patch(
            'app.home_environment.HOME_SETTINGS_DIR', Path(directory)
        ):
            client = TestClient(app)
            url = '/api/patients/byunwoojin/home-environment'
            initial = client.get(url)
            self.assertEqual(initial.status_code, 200)
            self.assertIsNone(initial.json()['region'])
            self.assertEqual(
                client.get('/api/patients/patient-001/home-environment').status_code,
                404,
            )

            saved = client.put(url, json={
                'region_code': '1111051500',
                'auto_lighting_enabled': False,
            })
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()['region']['code'], '1111051500')
            self.assertEqual((saved.json()['region']['nx'], saved.json()['region']['ny']), (60, 127))
            self.assertFalse(saved.json()['auto_lighting_enabled'])
            self.assertEqual(client.get(url).json(), saved.json())


if __name__ == '__main__':
    unittest.main()
