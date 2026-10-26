from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DEPLOY = ROOT / "deploy"

spec = importlib.util.spec_from_file_location("repetitive_tts_context", SCRIPTS / "tts_context.py")
assert spec and spec.loader
tts_context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tts_context)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class TtsContextTests(unittest.TestCase):
    def test_fetches_configured_call_name_with_device_token(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return FakeResponse(
                {
                    "patient_id": "patient 1",
                    "is_configured": True,
                    "patient_call_name": "어머니",
                }
            )

        with patch.object(tts_context, "urlopen", fake_urlopen):
            result = tts_context.fetch_call_name(
                api_base_url="https://example.test/",
                patient_id="patient 1",
                device_token="secret-token",
                fallback="할머니",
            )

        self.assertEqual(result, "어머니")
        self.assertEqual(
            captured["url"],
            "https://example.test/api/device/patients/patient%201/tts-context",
        )
        self.assertEqual(captured["authorization"], "Bearer secret-token")
        self.assertEqual(captured["timeout"], 15)

    def test_unconfigured_or_invalid_call_name_uses_fallback(self) -> None:
        self.assertEqual(tts_context.normalize_call_name("", "할머니"), "할머니")
        self.assertEqual(tts_context.normalize_call_name("이름\n주입", "할머니"), "할머니")
        self.assertEqual(tts_context.normalize_call_name("어머니", "할머니"), "어머니")

    def test_templates_use_runtime_placeholder(self) -> None:
        for name in ("air-purifier-message.txt", "washer-youtube-message.txt"):
            template = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn(tts_context.PLACEHOLDER, template)
            self.assertNotIn("할머니", template)
            self.assertIn("어머니", tts_context.render_template(template, "어머니"))

    def test_services_generate_before_playback_and_keep_actions(self) -> None:
        cases = (
            (
                "pauseable-air-purifier-tts.service",
                "generate-air-purifier-tts.sh",
                "turn_on_air_purifier.py",
            ),
            (
                "pauseable-washer-youtube-tts.service",
                "generate-washer-youtube-tts.sh",
                "play_lg_tv_youtube.py",
            ),
        )
        for unit_name, generator, action in cases:
            unit = (DEPLOY / unit_name).read_text(encoding="utf-8")
            self.assertIn(f"ExecStartPre=+/bin/sh /data/ha_ai_fullcycle_20260911/scripts/{generator}", unit)
            self.assertLess(unit.index("ExecStartPre="), unit.index("ExecStart="))
            self.assertIn(action, unit)

    def test_generators_do_not_embed_the_guidance_call_name(self) -> None:
        for name in ("generate-air-purifier-tts.sh", "generate-washer-youtube-tts.sh"):
            script = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("tts_context.py", script)
            self.assertNotIn("TEXT='할머니", script)


if __name__ == "__main__":
    unittest.main()
