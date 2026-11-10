import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from private_chef.__main__ import setup
from private_chef.config import PROJECT_ROOT, Settings, project_root
from private_chef.openclaw import configure
from private_chef.validation import ChefError


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_setup_generates_private_token_without_overwriting_existing_env(self):
        (self.root / ".env.example").write_text("OPENAI_API_KEY=\nCHEF_API_TOKEN=\n")
        with patch.dict("os.environ", {}, clear=True), patch("builtins.print"):
            setup(self.root)
            settings = Settings.load(self.root)
            self.assertGreaterEqual(len(settings.api_token), 32)
            before = (self.root / ".env").read_bytes()
            setup(self.root)
            self.assertEqual(before, (self.root / ".env").read_bytes())
            self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o600)

    def test_openclaw_config_is_private_isolated_and_never_contains_model_key(self):
        (self.root / "openclaw").mkdir()
        (self.root / "openclaw/openclaw.plugin.json").write_text("{}")
        settings = Settings(
            self.root / "chef.db",
            "a" * 40,
            "test-api-secret",
            "test-model",
            whatsapp=("+491111111111", "+492222222222"),
        )
        path = configure(settings, self.root)
        config = json.loads(path.read_text())
        self.assertNotIn(settings.openai_key, path.read_text())
        self.assertEqual(config["channels"]["whatsapp"]["groupPolicy"], "disabled")
        self.assertEqual(config["channels"]["whatsapp"]["allowFrom"], list(settings.whatsapp))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ChefError):
            configure(settings, self.root)

    def test_setup_works_without_a_checkout_template(self):
        with patch.dict("os.environ", {}, clear=True), patch("builtins.print"):
            setup(self.root)
        self.assertTrue((self.root / ".env").is_file())
        self.assertGreaterEqual(len(Settings.load(self.root).api_token), 32)

    def test_packaged_template_matches_the_public_example(self):
        self.assertEqual(
            (PROJECT_ROOT / ".env.example").read_text(),
            (PROJECT_ROOT / "src/private_chef/env.example").read_text(),
        )

    def test_installed_package_uses_the_working_directory_instead_of_site_packages(self):
        module = self.root / "venv/lib/python3.12/site-packages/private_chef/config.py"
        with (
            patch("private_chef.config.__file__", str(module)),
            patch("pathlib.Path.cwd", return_value=self.root),
        ):
            self.assertEqual(project_root(), self.root)


if __name__ == "__main__":
    unittest.main()
