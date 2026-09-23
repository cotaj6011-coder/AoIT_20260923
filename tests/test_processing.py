"""Phase 2 regression and synthetic mutations of the unchanged real snapshot."""

import contextlib
import copy
import io
import json
import os
import random
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from validate_processing import main
from weather_data.errors import WeatherDataError
from weather_data.json_data import decode_json
from weather_data.model import WeatherForecast, validate_forecasts
from weather_data.parser import parse_forecasts, parse_response

FIXTURE = Path(__file__).parent / "fixtures/cwa_weather.json"


class FixtureCase(unittest.TestCase):
    def setUp(self) -> None:
        self.data = decode_json(FIXTURE.read_bytes())
        self.location = next(loc for loc in self.data["records"]["location"] if loc["locationName"] == "嘉義縣")

    def element(self, name: str) -> dict:
        return next(e for e in self.location["weatherElement"] if e["elementName"] == name)

    def local_rows(self) -> list[WeatherForecast]:
        return [r for r in parse_forecasts(self.data) if r.location_name == self.location["locationName"].strip()]


class ProcessingRegressionTests(FixtureCase):
    def test_real_snapshot_counts_and_known_location(self) -> None:
        rows = parse_response(FIXTURE.read_bytes())
        self.assertEqual(len(rows), 66)
        self.assertEqual(len({r.location_name for r in rows}), 22)
        known = [r for r in rows if r.location_name == "嘉義縣"]
        self.assertEqual((known[0].min_temperature, known[0].max_temperature), (25, 29))
        self.assertTrue(all(isinstance(r, WeatherForecast) for r in rows))

    def test_all_record_invariants(self) -> None:
        rows = parse_forecasts(self.data)
        validate_forecasts(rows)
        keys = [(r.location_name, r.start_time, r.end_time) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))
        for row in rows:
            self.assertTrue(row.location_name.strip())
            self.assertLess(row.start_time, row.end_time)
            self.assertEqual(row.start_time.utcoffset(), timedelta(hours=8))
            self.assertEqual(row.end_time.utcoffset(), timedelta(hours=8))
            self.assertIsInstance(row.min_temperature, float)
            self.assertIsInstance(row.max_temperature, float)
            self.assertLessEqual(row.min_temperature, row.max_temperature)

    def test_fixture_all_element_intervals_match(self) -> None:
        for location in self.data["records"]["location"]:
            periods = {
                e["elementName"]: {(t["startTime"], t["endTime"]) for t in e["time"]}
                for e in location["weatherElement"]
            }
            for intervals in periods.values():
                self.assertEqual(intervals, periods["MinT"])

    def test_no_fixed_location_count(self) -> None:
        self.data["records"]["location"] = [self.location]
        self.location["locationName"] = "另一個測試地區"
        rows = parse_forecasts(self.data)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r.location_name for r in rows}, {"另一個測試地區"})

    def test_original_location_order_and_sorted_intervals(self) -> None:
        self.data["records"]["location"].reverse()
        expected = [loc["locationName"] for loc in self.data["records"]["location"]]
        rows = parse_forecasts(self.data)
        self.assertEqual(list(dict.fromkeys(r.location_name for r in rows)), expected)
        for name in expected:
            keys = [(r.start_time, r.end_time) for r in rows if r.location_name == name]
            self.assertEqual(keys, sorted(keys))


class ProcessingAlignmentTests(FixtureCase):
    def test_element_order_independent(self) -> None:
        expected = parse_forecasts(self.data)
        random.Random(17).shuffle(self.location["weatherElement"])
        self.assertEqual(parse_forecasts(self.data), expected)

    def test_independent_time_shuffles(self) -> None:
        expected = parse_forecasts(self.data)
        rng = random.Random(42)
        for loc in self.data["records"]["location"]:
            for element in loc["weatherElement"]:
                rng.shuffle(element["time"])
        self.assertEqual(parse_forecasts(self.data), expected)

    def test_missing_min_period(self) -> None:
        self.element("MinT")["time"].pop(0)
        rows = self.local_rows()
        self.assertIsNone(rows[0].min_temperature)
        self.assertEqual(rows[0].max_temperature, 29)
        self.assertEqual(rows[1].min_temperature, 25)

    def test_missing_max_period(self) -> None:
        self.element("MaxT")["time"].pop(1)
        rows = self.local_rows()
        self.assertIsNone(rows[1].max_temperature)
        self.assertEqual(rows[2].max_temperature, 29)

    def test_disjoint_intervals_are_not_paired(self) -> None:
        mint = copy.deepcopy(self.element("MinT"))
        maxt = copy.deepcopy(self.element("MaxT"))
        mint["time"] = mint["time"][:1]
        maxt["time"] = maxt["time"][1:2]
        self.location["weatherElement"] = [maxt, mint]
        rows = self.local_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual((rows[0].min_temperature, rows[0].max_temperature), (25, None))
        self.assertEqual((rows[1].min_temperature, rows[1].max_temperature), (None, 33))

    def test_same_start_different_end_are_separate(self) -> None:
        self.element("MinT")["time"][0]["endTime"] = "2026-09-24 05:00:00"
        rows = self.local_rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual((rows[0].min_temperature, rows[0].max_temperature), (25, None))
        self.assertEqual((rows[1].min_temperature, rows[1].max_temperature), (None, 29))

    def test_explicit_iso_timezone_preserved(self) -> None:
        period = self.element("MinT")["time"][0]
        period["startTime"] = "2026-09-23T18:00:00+08:00"
        period["endTime"] = "2026-09-24T06:00:00+08:00"
        rows = self.local_rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].start_time.isoformat(), period["startTime"])
        self.assertEqual(rows[0].end_time.isoformat(), period["endTime"])

    def test_equivalent_utc_instants_pair(self) -> None:
        period = self.element("MinT")["time"][0]
        period["startTime"] = "2026-09-23T10:00:00Z"
        period["endTime"] = "2026-09-23T22:00:00+00:00"
        rows = self.local_rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[0].min_temperature, rows[0].max_temperature), (25, 29))
        self.assertEqual(rows[0].start_time.utcoffset(), timedelta(hours=8))


class ProcessingMissingTests(FixtureCase):
    def test_missing_min_element(self) -> None:
        self.location["weatherElement"].remove(self.element("MinT"))
        self.assertTrue(all(r.min_temperature is None for r in self.local_rows()))

    def test_missing_max_element(self) -> None:
        self.location["weatherElement"].remove(self.element("MaxT"))
        self.assertTrue(all(r.max_temperature is None for r in self.local_rows()))

    def test_missing_temperature_member(self) -> None:
        del self.element("MinT")["time"][0]["parameter"]["parameterName"]
        self.assertIsNone(self.local_rows()[0].min_temperature)

    def test_missing_location_name_has_context(self) -> None:
        del self.location["locationName"]
        with self.assertRaises(WeatherDataError) as caught:
            parse_forecasts(self.data)
        self.assertIn("records.location[0]", str(caught.exception))

    def test_duplicate_trimmed_location_rejected(self) -> None:
        duplicate = copy.deepcopy(self.location)
        duplicate["locationName"] = " 嘉義縣 "
        self.data["records"]["location"].append(duplicate)
        with self.assertRaises(WeatherDataError):
            parse_forecasts(self.data)

    def test_empty_and_invalid_payload(self) -> None:
        for body in (b"", b"{}", b"[]", b"null", b"not-json"):
            with self.subTest(body=body), self.assertRaises(WeatherDataError):
                parse_response(body)
        self.data["records"]["location"] = []
        self.assertEqual(parse_forecasts(self.data), [])


class ProcessingValueTests(FixtureCase):
    def test_numeric_conversion_types_and_whitespace(self) -> None:
        for value in (24, 24.5, "24.5", " 24.5 ", "0", -5):
            with self.subTest(value=value):
                self.element("MinT")["time"][0]["parameter"]["parameterName"] = value
                self.assertEqual(self.local_rows()[0].min_temperature, float(value))

    def test_null_empty_invalid_sentinels_never_become_zero(self) -> None:
        for name in ("MinT", "MaxT"):
            for value in (None, "", " ", "ABC", "N/A", -99, -999, -9999, True, "nan", "inf"):
                with self.subTest(element=name, value=value):
                    self.element(name)["time"][0]["parameter"]["parameterName"] = value
                    row = self.local_rows()[0]
                    self.assertIsNone(getattr(row, "min_temperature" if name == "MinT" else "max_temperature"))

    def test_min_above_max_is_error_with_context(self) -> None:
        self.element("MinT")["time"][0]["parameter"]["parameterName"] = "35"
        self.element("MaxT")["time"][0]["parameter"]["parameterName"] = "20"
        with self.assertRaises(WeatherDataError) as caught:
            self.local_rows()
        self.assertEqual(caught.exception.code, "INVALID_FORECAST")
        for text in ("嘉義縣", "MinT/MaxT", "2026-09-23T18:00:00+08:00"):
            self.assertIn(text, str(caught.exception))

    def test_invalid_time_context_without_echoing_raw_secret(self) -> None:
        self.element("MinT")["time"][0]["startTime"] = "not-a-date-private-value"
        with self.assertRaises(WeatherDataError) as caught:
            self.local_rows()
        self.assertEqual(caught.exception.code, "INVALID_TIME")
        for text in ("嘉義縣", "MinT", "time[0]"):
            self.assertIn(text, str(caught.exception))
        self.assertNotIn("not-a-date-private-value", str(caught.exception))

    def test_duplicate_interval_context(self) -> None:
        self.element("MinT")["time"].append(copy.deepcopy(self.element("MinT")["time"][0]))
        with self.assertRaises(WeatherDataError) as caught:
            self.local_rows()
        self.assertEqual(caught.exception.code, "TIME_ALIGNMENT_ERROR")
        self.assertIn("嘉義縣", str(caught.exception))

    def test_invalid_iso_offset_rejected(self) -> None:
        self.element("MinT")["time"][0]["startTime"] = "2026-09-23T18:00:00+08:99"
        with self.assertRaises(WeatherDataError) as caught:
            self.local_rows()
        self.assertEqual(caught.exception.code, "INVALID_TIME")


class ProcessingInvariantTests(FixtureCase):
    def test_duplicate_dto_key(self) -> None:
        row = self.local_rows()[0]
        with self.assertRaises(WeatherDataError) as caught:
            validate_forecasts([row, replace(row)])
        self.assertEqual(caught.exception.code, "DUPLICATE_FORECAST")

    def test_none_temperatures_allowed(self) -> None:
        validate_forecasts([replace(self.local_rows()[0], min_temperature=None, max_temperature=None)])

    def test_raw_dictionary_rejected(self) -> None:
        with self.assertRaises(WeatherDataError):
            validate_forecasts([{}])

    def test_invalid_normalized_types_rejected(self) -> None:
        # Bypass frozen model solely to prove the collection guard detects corruption.
        for value in ("25", True, float("nan"), float("inf"), 100):
            row = self.local_rows()[0]
            object.__setattr__(row, "min_temperature", value)
            with self.assertRaises(WeatherDataError):
                validate_forecasts([row])


class ProcessingCliTests(FixtureCase):
    def run_cli(self, body: bytes | None = None) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.json"
            path.write_bytes(FIXTURE.read_bytes() if body is None else body)
            output = io.StringIO()
            with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
                with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stdout(output):
                    code = main(["--fixture", str(path)])
            return code, output.getvalue()

    def test_offline_success_no_key(self) -> None:
        code, output = self.run_cli()
        self.assertEqual(code, 0)
        for text in ("Locations: 22", "Forecast Records: 66", "MinT Range: 22–27 C", "MaxT Range: 26–33 C", "Result: PASS"):
            self.assertIn(text, output)
        self.assertEqual(output.count("[PASS]"), 6)

    def test_missing_fixture(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--fixture", "does-not-exist.json"])
        self.assertEqual(code, 1)
        self.assertIn("FIXTURE_IO", output.getvalue())

    def test_invalid_json_failure(self) -> None:
        code, output = self.run_cli(b"not JSON")
        self.assertEqual(code, 1)
        self.assertIn("Result: FAIL", output)
        self.assertNotIn("[PASS]", output)

    def test_empty_records_failure(self) -> None:
        self.data["records"]["location"] = []
        code, output = self.run_cli(json.dumps(self.data).encode())
        self.assertEqual(code, 1)
        self.assertIn("EMPTY_DATASET", output)

    def test_incomplete_temperature_coverage_failure(self) -> None:
        self.element("MinT")["time"].pop(0)
        code, output = self.run_cli(json.dumps(self.data).encode())
        self.assertEqual(code, 1)
        self.assertIn("INCOMPLETE_TEMPERATURES", output)
        self.assertNotIn("[PASS] Time aligned", output)

    def test_default_fixture_independent_of_working_directory(self) -> None:
        output = io.StringIO()
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main([]), 0)
            finally:
                os.chdir(previous)
