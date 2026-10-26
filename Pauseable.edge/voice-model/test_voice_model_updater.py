from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from voice_model_updater import (
    CONFIG_TARGET_NAME,
    ONNX_TARGET_NAME,
    Settings,
    make_release_runtime_readable,
    point_models_at,
    repair_active_release_permissions,
    remove_duplicate_bootstrap,
    restore_models,
    validate_wav_file,
)


class AtomicModelSwitchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.piper_root = root / "piper"
        self.piper_root.mkdir()
        self.release_root = self.piper_root / "model-releases"
        (self.release_root / "releases").mkdir(parents=True)
        self.settings = Settings(
            api_url="https://example.invalid",
            device_token="test",
            patient_id="byunwoojin",
            device_id="pi5-home-01",
            piper_root=self.piper_root,
            release_root=self.release_root,
            validation_text="test",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_first_switch_preserves_existing_models_as_bootstrap(self) -> None:
        old_models = self.piper_root / "models"
        old_models.mkdir()
        (old_models / "old.onnx").write_bytes(b"old")
        release = self.release_root / "releases" / "voice-model-0123456789ab"
        release.mkdir()

        previous = point_models_at(self.settings, release)

        self.assertTrue((self.piper_root / "models").is_symlink())
        self.assertEqual((self.piper_root / "models").resolve(), release)
        self.assertEqual(previous.name, "bootstrap")
        self.assertEqual((previous / "old.onnx").read_bytes(), b"old")

    def test_rollback_restores_previous_release(self) -> None:
        previous = self.release_root / "releases" / "voice-model-aaaaaaaaaaaa"
        current = self.release_root / "releases" / "voice-model-bbbbbbbbbbbb"
        previous.mkdir()
        current.mkdir()
        (self.piper_root / "models").symlink_to(previous, target_is_directory=True)

        previous_target = point_models_at(self.settings, current)
        restore_models(self.settings, previous_target)

        self.assertEqual((self.piper_root / "models").resolve(), previous)

    def test_matching_bootstrap_is_removed(self) -> None:
        bootstrap = self.release_root / "releases" / "bootstrap"
        bootstrap.mkdir()
        onnx = b"same model"
        config = b'{"same": true}'
        (bootstrap / ONNX_TARGET_NAME).write_bytes(onnx)
        (bootstrap / CONFIG_TARGET_NAME).write_bytes(config)
        release = {
            "onnx_sha256": hashlib.sha256(onnx).hexdigest(),
            "config_sha256": hashlib.sha256(config).hexdigest(),
        }

        removed = remove_duplicate_bootstrap(self.settings, bootstrap, release)

        self.assertTrue(removed)
        self.assertFalse(bootstrap.exists())

    def test_nonmatching_bootstrap_is_preserved(self) -> None:
        bootstrap = self.release_root / "releases" / "bootstrap"
        bootstrap.mkdir()
        (bootstrap / ONNX_TARGET_NAME).write_bytes(b"old model")
        (bootstrap / CONFIG_TARGET_NAME).write_bytes(b"old config")
        release = {
            "onnx_sha256": hashlib.sha256(b"new model").hexdigest(),
            "config_sha256": hashlib.sha256(b"new config").hexdigest(),
        }

        removed = remove_duplicate_bootstrap(self.settings, bootstrap, release)

        self.assertFalse(removed)
        self.assertTrue(bootstrap.is_dir())

    def test_release_permissions_are_readable_by_central(self) -> None:
        release = self.release_root / "releases" / "voice-model-permissions"
        release.mkdir(mode=0o700)
        model = release / ONNX_TARGET_NAME
        config = release / CONFIG_TARGET_NAME
        validation = release / "validation.wav"
        model.write_bytes(b"model")
        config.write_text("{}", encoding="utf-8")
        validation.write_bytes(b"wav")

        make_release_runtime_readable(release)

        self.assertEqual(release.stat().st_mode & 0o777, 0o755)
        self.assertEqual(model.stat().st_mode & 0o777, 0o644)
        self.assertEqual(config.stat().st_mode & 0o777, 0o644)
        self.assertEqual(validation.stat().st_mode & 0o777, 0o644)

    def test_existing_active_release_permissions_are_repaired(self) -> None:
        release = self.release_root / "releases" / "voice-model-active"
        release.mkdir(mode=0o700)
        (release / ONNX_TARGET_NAME).write_bytes(b"model")
        (release / CONFIG_TARGET_NAME).write_text("{}", encoding="utf-8")
        (self.piper_root / "models").symlink_to(release, target_is_directory=True)

        repair_active_release_permissions(self.settings)

        self.assertEqual(release.stat().st_mode & 0o777, 0o755)


class WavValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_wav(self, format_tag: int, data: bytes, *, streaming: bool = False) -> Path:
        fmt = (
            format_tag.to_bytes(2, "little")
            + (1).to_bytes(2, "little")
            + (22050).to_bytes(4, "little")
            + (88200).to_bytes(4, "little")
            + (4).to_bytes(2, "little")
            + (32).to_bytes(2, "little")
        )
        body = b"fmt " + len(fmt).to_bytes(4, "little") + fmt
        data_size = 0x7FFFF000 if streaming else len(data)
        body += b"data" + data_size.to_bytes(4, "little") + data
        path = self.root / "validation.wav"
        riff_size = 0x7FFFF024 if streaming else len(body) + 4
        path.write_bytes(b"RIFF" + riff_size.to_bytes(4, "little") + b"WAVE" + body)
        return path

    def test_ieee_float_wav_is_accepted(self) -> None:
        validate_wav_file(self.write_wav(3, b"\x00" * 16))

    def test_streaming_ieee_float_wav_is_accepted(self) -> None:
        validate_wav_file(self.write_wav(3, b"\x00" * 16, streaming=True))

    def test_empty_wav_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no audio frames"):
            validate_wav_file(self.write_wav(3, b""))

    def test_non_wav_file_is_rejected(self) -> None:
        path = self.root / "not.wav"
        path.write_bytes(b"not a wave file")
        with self.assertRaisesRegex(RuntimeError, "not a RIFF/WAVE"):
            validate_wav_file(path)


if __name__ == "__main__":
    unittest.main()
