from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from banking_demo.config import Settings


class SettingsTests(unittest.TestCase):
    def test_settings_have_no_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"DEMO_MODE": "replay"}, clear=True
        ):
            settings = Settings.load(Path(directory))
        self.assertFalse(hasattr(settings, "mode"))
        self.assertEqual("gpt-5.4-mini", settings.model)

    def test_approval_timeout_must_be_finite_and_positive(self) -> None:
        for value in ("nan", "inf", "-inf", "0", "-1", "invalid"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"APPROVAL_TIMEOUT_SECONDS": value}, clear=True
            ):
                with self.assertRaisesRegex(ValueError, "positive number"):
                    Settings.load(Path(directory))

    def test_environment_selects_foundry_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"FOUNDRY_PROJECT_ENDPOINT": "https://example.invalid/api/projects/demo", "FOUNDRY_MODEL": "test-model"},
            clear=True,
        ):
            settings = Settings.load(Path(directory))
        self.assertEqual("https://example.invalid/api/projects/demo", settings.project_endpoint)
        self.assertEqual("test-model", settings.model)


if __name__ == "__main__":
    unittest.main()
