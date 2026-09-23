import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validate_cwa import main
from weather_data.client import CwaResponse
from weather_data.errors import WeatherDataError

FIXTURE = Path(__file__).parent / "fixtures" / "cwa_weather.json"


class ValidationTests(unittest.TestCase):
    def run_cli(self, *, body=None, error=None, env=None):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "capture.json"
            with patch.dict(os.environ, {"CWA_API_KEY": "test-only-secret"} if env is None else env, clear=True):
                with patch("validate_cwa.CwaClient.fetch") as fetch:
                    fetch.side_effect = error
                    fetch.return_value = CwaResponse(200, FIXTURE.read_bytes() if body is None else body)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        code = main(["--output", str(destination)])
            files = {p.name: p.read_text(encoding="utf-8") for p in Path(directory).iterdir()}
            return code, output.getvalue(), files, fetch.call_count

    def test_success_using_real_fixture_mock_http(self):
        code, output, files, calls = self.run_cli()
        self.assertEqual(code, 0)
        for text in ("HTTP Status: 200", "Record Count: 66", "Location Count: 22", "Location: 嘉義縣", "MinT: 25 C", "MaxT: 29 C", "PoP: 10%", "Result: PASS"):
            self.assertIn(text, output)
        self.assertIn("capture.json", files)
        self.assertEqual(calls, 1)

    def test_missing_key_no_request(self):
        code, output, files, calls = self.run_cli(env={})
        self.assertEqual((code, calls), (1, 0))
        self.assertIn("MISSING_API_KEY", output)
        self.assertEqual(files, {})

    def test_http_failure(self):
        code, output, files, _ = self.run_cli(error=WeatherDataError("HTTP_ERROR", "Authentication failed.", http_status=401))
        self.assertEqual(code, 1)
        self.assertIn("HTTP Status: 401", output)
        self.assertNotIn("test-only-secret", output)
        self.assertEqual(files, {})

    def test_invalid_json(self):
        code, output, files, _ = self.run_cli(body=b"invalid test-only-secret")
        self.assertEqual(code, 1)
        self.assertIn("INVALID_JSON", output)
        self.assertNotIn("test-only-secret", output)
        self.assertEqual(files, {})

    def test_failed_cwa_status_preserves_unverified_capture(self):
        code, output, files, _ = self.run_cli(body=b'{"success":"false", "token":"test-only-secret"}')
        self.assertEqual(code, 1)
        self.assertIn("CWA_FAILURE", output)
        self.assertIn("capture.unverified.json", files)
        self.assertNotIn("test-only-secret", str(files))
        self.assertFalse(json.loads(files["capture.unverified.metadata.json"])["forecast_schema_verified"])

    def test_empty_dataset_is_not_pass(self):
        data = json.loads(FIXTURE.read_bytes())
        data["records"]["location"] = []
        code, output, _, _ = self.run_cli(body=json.dumps(data).encode())
        self.assertEqual(code, 1)
        self.assertIn("EMPTY_DATASET", output)

    def test_location_without_periods_is_not_pass(self):
        data = json.loads(FIXTURE.read_bytes())
        data["records"]["location"][0]["weatherElement"] = []
        code, output, _, _ = self.run_cli(body=json.dumps(data).encode())
        self.assertEqual(code, 1)
        self.assertIn("MISSING_PERIODS", output)

    def test_echoed_secret_never_logged_or_saved(self):
        data = json.loads(FIXTURE.read_bytes())
        data["records"]["location"][0]["locationName"] = "test-only-secret"
        code, output, files, _ = self.run_cli(body=json.dumps(data).encode())
        self.assertEqual(code, 0)
        self.assertNotIn("test-only-secret", output + str(files))
