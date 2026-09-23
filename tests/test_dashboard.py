import contextlib
import hashlib
import io
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from validate_webapp import main
from weather_data.dashboard import COLUMNS, chart_data, filter_forecasts, load_dashboard, table_data, to_dataframe
from weather_data.errors import WeatherDataError
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository

FIXTURE = Path(__file__).parent / "fixtures/cwa_weather.json"


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = parse_response(FIXTURE.read_bytes())
        self.frame = to_dataframe(self.rows)

    def test_columns_and_record_count(self) -> None:
        self.assertEqual(list(self.frame.columns), COLUMNS)
        self.assertEqual(len(self.frame), 66)
        self.assertEqual(self.frame.location_name.nunique(), 22)

    def test_datetime_timezone_and_values(self) -> None:
        local = filter_forecasts(self.frame, "嘉義縣")
        self.assertEqual(local.iloc[0].start_time.isoformat(), "2026-09-23T18:00:00+08:00")
        self.assertEqual(local.iloc[0].end_time.utcoffset(), timedelta(hours=8))
        self.assertEqual(local.iloc[0].min_temperature, 25)
        self.assertEqual(local.iloc[0].max_temperature, 29)

    def test_location_filter(self) -> None:
        result = filter_forecasts(self.frame, "臺中市")
        self.assertEqual(len(result), 3)
        self.assertEqual(result.location_name.unique().tolist(), ["臺中市"])

    def test_date_filter_uses_local_start_date(self) -> None:
        result = filter_forecasts(self.frame, "臺中市", date(2026, 9, 24))
        self.assertEqual(len(result), 2)
        self.assertTrue(result.start_time.dt.date.eq(date(2026, 9, 24)).all())

    def test_exact_interval_filter(self) -> None:
        period = self.rows[0]
        interval = (period.start_time.isoformat(), period.end_time.isoformat())
        self.assertEqual(len(filter_forecasts(self.frame, period.location_name, interval=interval)), 1)

    def test_sort_is_deterministic(self) -> None:
        pd.testing.assert_frame_equal(to_dataframe(list(reversed(self.rows))), self.frame)
        selected = filter_forecasts(self.frame.sample(frac=1, random_state=42), "臺中市")
        self.assertTrue(selected.start_time.is_monotonic_increasing)

    def test_null_temperature_not_zero(self) -> None:
        frame = to_dataframe([replace(self.rows[0], min_temperature=None)])
        self.assertTrue(pd.isna(frame.iloc[0].min_temperature))
        self.assertTrue(pd.isna(chart_data(frame).iloc[0].min_temperature))
        self.assertEqual(frame.iloc[0].max_temperature, 29)

    def test_empty_dataframe_preserves_schema(self) -> None:
        frame = to_dataframe([])
        self.assertEqual(list(frame.columns), COLUMNS)
        self.assertTrue(filter_forecasts(frame, "unknown").empty)
        self.assertTrue(chart_data(frame).empty)
        self.assertTrue(table_data(frame).empty)

    def test_empty_filter_results(self) -> None:
        self.assertTrue(filter_forecasts(self.frame, "unknown").empty)
        self.assertTrue(filter_forecasts(self.frame, forecast_date=date(2000, 1, 1)).empty)

    def test_chart_table_same_rows_and_no_mutation(self) -> None:
        before = self.frame.copy(deep=True)
        filtered = filter_forecasts(self.frame, "臺中市", date(2026, 9, 24))
        chart, table = chart_data(filtered), table_data(filtered)
        for column in chart.columns:
            pd.testing.assert_series_equal(chart[column], table[column])
        pd.testing.assert_frame_equal(self.frame, before)
        chart.loc[0, "min_temperature"] = 0
        self.assertNotEqual(filtered.iloc[0].min_temperature, 0)


class DashboardIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "weather.sqlite3"

    def seed(self, empty: bool = False) -> None:
        with WeatherForecastRepository(self.database) as repository:
            repository.initialize_database()
            if not empty:
                repository.save_forecasts(parse_response(FIXTURE.read_bytes()))

    def test_repository_to_frame_read_only_round_trip(self) -> None:
        self.seed()
        digest = hashlib.sha256(self.database.read_bytes()).hexdigest()
        frame, updated = load_dashboard(self.database)
        self.assertEqual(len(frame), 66)
        self.assertIsNotNone(updated.utcoffset())
        self.assertEqual(digest, hashlib.sha256(self.database.read_bytes()).hexdigest())
        with WeatherForecastRepository(self.database, read_only=True) as repository:
            with self.assertRaises(WeatherDataError):
                repository.save_forecast(parse_response(FIXTURE.read_bytes())[0])

    def test_missing_database_not_created(self) -> None:
        with self.assertRaises(WeatherDataError) as caught:
            load_dashboard(self.database)
        self.assertEqual(caught.exception.code, "DATABASE_MISSING")
        self.assertFalse(self.database.exists())

    def test_empty_database(self) -> None:
        self.seed(empty=True)
        frame, updated = load_dashboard(self.database)
        self.assertTrue(frame.empty)
        self.assertIsNone(updated)

    def test_corrupt_database(self) -> None:
        self.database.write_bytes(b"not a database")
        with self.assertRaises(WeatherDataError):
            load_dashboard(self.database)

    def test_validation_temporary_database(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main([]), 0)
        self.assertIn("Records: 66", output.getvalue())
        self.assertIn("Filtered Records: 1", output.getvalue())
        self.assertEqual(output.getvalue().count("[PASS]"), 6)

    def test_validation_missing_database_fails(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--database", str(self.database)]), 1)
