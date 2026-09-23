import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from weather_data.errors import WeatherDataError
from weather_data.json_data import decode_json, describe_structure, sanitize, save_capture


class JsonDataTests(unittest.TestCase):
    # Inline values in these tests are synthetic, not claimed as CWA responses.
    def test_valid_object(self):
        self.assertEqual(decode_json(b'{"example": []}'), {"example": []})

    def test_empty_response(self):
        for body in (b"", b" \n", b"{}"):
            with self.assertRaises(WeatherDataError) as caught: decode_json(body)
            self.assertEqual(caught.exception.code, "EMPTY_RESPONSE")

    def test_invalid_json(self):
        for body in (b"not JSON", b'{"x":', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1,"x":2}', b"\xff"):
            with self.assertRaises(WeatherDataError) as caught: decode_json(body)
            self.assertEqual(caught.exception.code, "INVALID_JSON")

    def test_wrong_root(self):
        for body in (b"null", b"[]", b"true", b'"text"'):
            with self.assertRaises(WeatherDataError) as caught: decode_json(body)
            self.assertEqual(caught.exception.code, "INVALID_ROOT")

    def test_utf8_bom(self):
        self.assertEqual(decode_json(b'\xef\xbb\xbf{"example":1}'), {"example": 1})

    def test_sanitization_and_no_mutation(self):
        data = {"Authorization": "private", "nested": [{"api_key": "private", "echo": "a/b c"}], "other": "a%2Fb%20c", "token": "private"}
        clean = sanitize(data, "a/b c")
        self.assertNotIn("private", json.dumps(clean))
        self.assertNotIn("a%2Fb%20c", json.dumps(clean))
        self.assertEqual(data["Authorization"], "private")

    def test_structure_has_paths_and_types_not_values(self):
        result = describe_structure({"rows": [{"n": 1}, {"n": None}]})
        self.assertEqual(result['$["rows"][]["n"]'], ["int", "null"])

    def test_capture_provenance_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            save_capture({"Authorization": "test-secret", "example": []}, path, api_key="test-secret", status=200, verified=True)
            self.assertNotIn("test-secret", path.read_text())
            metadata = json.loads(path.with_suffix(".metadata.json").read_text())
            self.assertTrue(metadata["forecast_schema_verified"])
            self.assertEqual(metadata["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(len(list(Path(directory).iterdir())), 3)

    def test_unverified_capture_is_labelled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.json"
            save_capture({"example": 1}, path, api_key="test-secret", status=200)
            self.assertFalse(json.loads(path.with_suffix(".metadata.json").read_text())["forecast_schema_verified"])

    def test_capture_io_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            path.write_text("blocking-file")
            with self.assertRaises(WeatherDataError) as caught:
                save_capture({"example": 1}, path / "capture.json", api_key="test", status=200)
            self.assertEqual(caught.exception.code, "CAPTURE_IO")

    def test_real_fixture_provenance_matches_bytes(self):
        path = Path(__file__).parent / "fixtures" / "cwa_weather.json"
        metadata = json.loads(path.with_suffix(".metadata.json").read_text())
        self.assertEqual(metadata["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(metadata["dataset_id"], "F-C0032-001")
        self.assertEqual(metadata["http_status"], 200)
        self.assertTrue(metadata["forecast_schema_verified"])

    def test_deep_structure_safe_error(self):
        data = {"example": 1}
        for _ in range(42):
            data = {"nested": data}
        for function in (lambda: sanitize(data, "test"), lambda: describe_structure(data)):
            with self.assertRaises(WeatherDataError) as caught:
                function()
            self.assertEqual(caught.exception.code, "JSON_DEPTH")
