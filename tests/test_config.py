import tempfile
import unittest
from pathlib import Path

from weather_data.config import CwaConfig, read_env_file
from weather_data.errors import WeatherDataError


class ConfigurationTests(unittest.TestCase):
    def test_load_environment(self):
        self.assertEqual(CwaConfig.from_environment({"CWA_API_KEY": " test-only "}).api_key, "test-only")

    def test_missing_key_clear_error(self):
        with self.assertRaisesRegex(WeatherDataError, "CWA_API_KEY is missing"):
            CwaConfig.from_environment({})

    def test_blank_key(self):
        with self.assertRaises(WeatherDataError):
            CwaConfig.from_environment({"CWA_API_KEY": "  "})

    def test_key_not_in_repr(self):
        self.assertNotIn("test-only-secret", repr(CwaConfig("test-only-secret")))

    def test_env_file_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text('# comment\nCWA_API_KEY="file-test"\nSSL_CERT_FILE=ca.pem\n', encoding="utf-8")
            self.assertEqual(CwaConfig.from_environment({}, env_file=path).api_key, "file-test")
            config = CwaConfig.from_environment({"CWA_API_KEY": "process-test"}, env_file=path)
            self.assertEqual(config.api_key, "process-test")
            self.assertEqual(config.ca_file, "ca.pem")

    def test_explicit_empty_environment_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("CWA_API_KEY=file-test", encoding="utf-8")
            with self.assertRaises(WeatherDataError):
                CwaConfig.from_environment({"CWA_API_KEY": ""}, env_file=path)

    def test_missing_env_file_safe_error(self):
        with self.assertRaisesRegex(WeatherDataError, "Cannot read"):
            read_env_file(Path("not-a-real-env-file"))

    def test_malformed_file_does_not_echo_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            for text in ('CWA_API_KEY="unclosed-secret', 'private-malformed-value'):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(WeatherDataError) as caught:
                    read_env_file(path)
                self.assertNotIn(text, str(caught.exception))
