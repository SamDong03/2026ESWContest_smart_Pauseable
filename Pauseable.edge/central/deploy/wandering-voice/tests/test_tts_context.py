import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "tts_context.py"
SPEC = importlib.util.spec_from_file_location("tts_context", MODULE_PATH)
tts_context = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(tts_context)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.StringIO(json.dumps(self.payload, ensure_ascii=False))

    def __exit__(self, exc_type, exc, traceback):
        return False


class TtsContextTests(unittest.TestCase):
    def test_fetches_configured_call_name_with_device_auth(self):
        payload = {
            "patient_id": "patient-1",
            "patient_call_name": "  엄마  ",
            "is_configured": True,
        }
        with patch.object(tts_context, "urlopen", return_value=_Response(payload)) as request:
            result = tts_context.fetch_call_name(
                api_base_url="https://example.test",
                patient_id="patient-1",
                device_token="secret-device-token",
                fallback="할머니",
            )

        self.assertEqual(result, "엄마")
        sent_request = request.call_args.args[0]
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer secret-device-token")
        self.assertEqual(
            sent_request.full_url,
            "https://example.test/api/device/patients/patient-1/tts-context",
        )

    def test_unconfigured_or_invalid_call_name_uses_fallback(self):
        self.assertEqual(tts_context.normalize_call_name("", "어르신"), "어르신")
        self.assertEqual(tts_context.normalize_call_name("엄마\n명령", "어르신"), "어르신")
        self.assertEqual(tts_context.normalize_call_name("가" * 41, "어르신"), "어르신")

        payload = {
            "patient_id": "patient-1",
            "patient_call_name": "엄마",
            "is_configured": False,
        }
        with patch.object(tts_context, "urlopen", return_value=_Response(payload)):
            result = tts_context.fetch_call_name(
                api_base_url="https://example.test",
                patient_id="patient-1",
                device_token="secret-device-token",
                fallback="할머니",
            )
        self.assertEqual(result, "할머니")

    def test_renders_only_the_call_name_placeholder(self):
        message = tts_context.render_template(
            "{{patient_call_name}}, 잠깐 쉬어가요.",
            "아버지",
        )
        self.assertEqual(message, "아버지, 잠깐 쉬어가요.")


if __name__ == "__main__":
    unittest.main()
