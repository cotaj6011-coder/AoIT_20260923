"""Storage tests use only isolated in-memory databases and synthetic DTOs."""

import sqlite3
import unittest
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from weather_data.errors import WeatherDataError
from weather_data.model import WeatherForecast
from weather_data.storage import WeatherForecastRepository


def sample_forecast() -> WeatherForecast:
    start = datetime(2026, 9, 23, 18, tzinfo=timezone(timedelta(hours=8)))
    return WeatherForecast("測試縣", start, start + timedelta(hours=12), 20, 30, 10, "晴")


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = WeatherForecastRepository(":memory:")
        self.addCleanup(self.repository.close)
        self.repository.initialize_database()
        self.sample = sample_forecast()

    def raw_rows(self) -> list[tuple]:
        return [tuple(row) for row in self.repository._connection.execute(
            "SELECT * FROM weather_forecasts ORDER BY id"
        )]

    def test_initialization_idempotent_and_schema(self) -> None:
        self.repository.initialize_database()
        self.assertEqual(self.repository.count_forecasts(), 0)
        columns = self.repository._connection.execute("PRAGMA table_info(weather_forecasts)").fetchall()
        self.assertEqual({row[1] for row in columns}, {
            "id", "location_name", "start_time", "end_time", "min_temperature", "max_temperature",
            "rain_probability", "weather_description", "created_at", "updated_at",
        })
        self.assertEqual(next(row[5] for row in columns if row[1] == "id"), 1)

    def test_insert_single_and_round_trip(self) -> None:
        self.repository.save_forecast(self.sample)
        self.assertEqual(self.repository.count_forecasts(), 1)
        self.assertEqual(self.repository.get_forecasts(), [self.sample])

    def test_batch_insert_one_connection_one_transaction(self) -> None:
        trace: list[str] = []
        self.repository._connection.set_trace_callback(trace.append)
        records = [replace(self.sample, location_name=str(n)) for n in range(5)]
        with patch("weather_data.storage.sqlite3.connect", side_effect=AssertionError("Extra connection")):
            self.assertEqual(self.repository.save_forecasts(records), 5)
        self.assertEqual(trace.count("BEGIN"), 1)
        self.assertEqual(trace.count("COMMIT"), 1)
        self.assertEqual(self.repository.count_forecasts(), 5)

    def test_upsert_values_preserve_id_and_created_at(self) -> None:
        stamps = ["2026-09-23T10:00:00.000000+00:00", "2026-09-23T11:00:00.000000+00:00"]
        with patch("weather_data.storage._now", side_effect=stamps):
            self.repository.save_forecast(self.sample)
            before = self.raw_rows()[0]
            updated = replace(self.sample, min_temperature=21, max_temperature=31,
                              rain_probability=40, weather_description="雨")
            self.repository.save_forecast(updated)
        after = self.raw_rows()[0]
        self.assertEqual(self.repository.count_forecasts(), 1)
        self.assertEqual(self.repository.get_forecasts(), [updated])
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[8], before[8])
        self.assertEqual(after[9], stamps[1])

    def test_duplicate_batch_last_value_wins(self) -> None:
        updated = replace(self.sample, min_temperature=21)
        self.assertEqual(self.repository.save_forecasts([self.sample, updated]), 2)
        self.assertEqual(self.repository.get_forecasts(), [updated])
        self.assertEqual(self.repository.count_duplicate_keys(), 0)

    def test_database_unique_constraint_enforced_without_upsert(self) -> None:
        self.repository.save_forecast(self.sample)
        with self.assertRaises(sqlite3.IntegrityError):
            self.repository._connection.execute("""
                INSERT INTO weather_forecasts (
                    location_name, start_time, end_time, min_temperature, max_temperature,
                    rain_probability, weather_description, created_at, updated_at
                ) SELECT location_name, start_time, end_time, min_temperature, max_temperature,
                         rain_probability, weather_description, created_at, updated_at
                  FROM weather_forecasts
            """)
        self.assertEqual(self.repository.count_forecasts(), 1)

    def test_null_preserved_including_upsert(self) -> None:
        self.repository.save_forecast(self.sample)
        empty = replace(self.sample, min_temperature=None, max_temperature=None,
                        rain_probability=None, weather_description=None)
        self.repository.save_forecast(empty)
        self.assertEqual(self.repository.get_forecasts(), [empty])
        types = self.repository._connection.execute(
            "SELECT typeof(min_temperature), typeof(max_temperature) FROM weather_forecasts"
        ).fetchone()
        self.assertEqual(tuple(types), ("null", "null"))

    def test_numeric_storage_not_display_strings(self) -> None:
        self.repository.save_forecast(replace(self.sample, min_temperature=0, max_temperature=0))
        row = self.repository._connection.execute(
            "SELECT min_temperature, typeof(min_temperature) FROM weather_forecasts"
        ).fetchone()
        self.assertEqual(tuple(row), (0.0, "real"))

    def test_timezone_and_microseconds_preserved(self) -> None:
        record = replace(self.sample, start_time=self.sample.start_time.replace(microsecond=123456))
        self.repository.save_forecast(record)
        raw = self.repository._connection.execute("SELECT start_time FROM weather_forecasts").fetchone()[0]
        self.assertEqual(raw, "2026-09-23T18:00:00.123456+08:00")
        self.assertEqual(self.repository.get_forecasts(), [record])

    def test_equivalent_offset_uses_same_natural_key(self) -> None:
        self.repository.save_forecast(self.sample)
        utc = replace(self.sample, start_time=self.sample.start_time.astimezone(timezone.utc),
                      end_time=self.sample.end_time.astimezone(timezone.utc), min_temperature=21)
        self.repository.save_forecast(utc)
        self.assertEqual(self.repository.count_forecasts(), 1)
        self.assertEqual(self.repository.get_forecasts()[0].start_time.utcoffset(), timedelta(hours=8))

    def test_query_by_location_and_distinct_locations(self) -> None:
        self.repository.save_forecasts([self.sample, replace(self.sample, location_name="A"),
                                       replace(self.sample, start_time=self.sample.start_time + timedelta(hours=1))])
        self.assertEqual(len(self.repository.get_forecasts_by_location("測試縣")), 2)
        self.assertEqual(self.repository.get_forecasts_by_location("unknown"), [])
        self.assertEqual(self.repository.get_locations(), ["A", "測試縣"])

    def test_exact_natural_key_query(self) -> None:
        self.repository.save_forecast(self.sample)
        self.assertEqual(self.repository.get_forecast(
            self.sample.location_name, self.sample.start_time, self.sample.end_time), self.sample)
        self.assertIsNone(self.repository.get_forecast("unknown", self.sample.start_time, self.sample.end_time))

    def test_time_range_overlap_and_endpoints(self) -> None:
        self.repository.save_forecast(self.sample)
        start, end = self.sample.start_time, self.sample.end_time
        self.assertEqual(self.repository.get_forecasts_by_time_range(start, end), [self.sample])
        self.assertEqual(self.repository.get_forecasts_by_time_range(start + timedelta(hours=1), end), [self.sample])
        self.assertEqual(self.repository.get_forecasts_by_time_range(start - timedelta(hours=1), start), [])
        self.assertEqual(self.repository.get_forecasts_by_time_range(end, end + timedelta(hours=1)), [])
        self.assertEqual(self.repository.get_forecasts_by_time_range(
            start.astimezone(timezone.utc), end.astimezone(timezone.utc)), [self.sample])

    def test_invalid_query_range(self) -> None:
        for start, end in ((self.sample.end_time, self.sample.start_time),
                           (self.sample.start_time, self.sample.start_time),
                           (datetime(2026, 9, 23), self.sample.end_time)):
            with self.subTest(start=start), self.assertRaises(WeatherDataError):
                self.repository.get_forecasts_by_time_range(start, end)

    def test_deterministic_sorting(self) -> None:
        later = replace(self.sample, start_time=self.sample.start_time + timedelta(hours=1))
        earlier_end = replace(self.sample, end_time=self.sample.end_time - timedelta(hours=1))
        first_location = replace(self.sample, location_name="A")
        self.repository.save_forecasts([later, self.sample, first_location, earlier_end])
        self.assertEqual(self.repository.get_forecasts(), [first_location, earlier_end, self.sample, later])

    def test_empty_batch(self) -> None:
        self.assertEqual(self.repository.save_forecasts([]), 0)
        self.assertEqual(self.repository.count_forecasts(), 0)

    def test_sql_injection_is_literal_data(self) -> None:
        text = "x'; DROP TABLE weather_forecasts; --"
        record = replace(self.sample, location_name=text, weather_description=text)
        self.repository.save_forecast(record)
        self.assertEqual(self.repository.get_forecasts_by_location(text), [record])
        self.assertEqual(self.repository.get_forecasts_by_location("' OR 1=1 --"), [])
        self.assertEqual(self.repository.get_forecast(text, record.start_time, record.end_time), record)
        self.assertEqual(self.repository.count_forecasts(), 1)

    def test_generator_failure_rolls_back_updates_and_insertions(self) -> None:
        self.repository.save_forecast(self.sample)
        before = self.raw_rows()

        def broken() -> Iterator[WeatherForecast]:
            yield replace(self.sample, min_temperature=21)
            yield replace(self.sample, location_name="new")
            raise RuntimeError("synthetic interrupted input")

        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            self.repository.save_forecasts(broken())
        self.assertEqual(self.raw_rows(), before)
        self.repository.save_forecast(replace(self.sample, min_temperature=22))
        self.assertEqual(self.repository.get_forecasts()[0].min_temperature, 22)

    def test_late_sql_failure_rolls_back_everything(self) -> None:
        self.repository.save_forecast(self.sample)
        before = self.raw_rows()
        self.repository._connection.execute("""
            CREATE TEMP TRIGGER fail_insert BEFORE INSERT ON weather_forecasts
            WHEN NEW.location_name = 'blocked'
            BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END
        """)
        with self.assertRaises(WeatherDataError) as caught:
            self.repository.save_forecasts([
                replace(self.sample, min_temperature=21),
                replace(self.sample, location_name="new"),
                replace(self.sample, location_name="blocked"),
            ])
        self.assertEqual(caught.exception.code, "DATABASE_ERROR")
        self.assertEqual(self.raw_rows(), before)
        self.assertFalse(self.repository._connection.in_transaction)

    def test_late_dto_validation_error_rolls_back(self) -> None:
        with self.assertRaises(WeatherDataError):
            self.repository.save_forecasts([self.sample, {}])
        self.assertEqual(self.repository.count_forecasts(), 0)

    def test_database_check_constraints(self) -> None:
        self.repository.save_forecast(self.sample)
        statements = (
            ("UPDATE weather_forecasts SET location_name = ?", ("",)),
            ("UPDATE weather_forecasts SET min_temperature = ?", (35,)),
            ("UPDATE weather_forecasts SET min_temperature = ?", ("24C",)),
            ("UPDATE weather_forecasts SET start_time = ?", ("not-time",)),
            ("UPDATE weather_forecasts SET start_time = end_time", ()),
        )
        for statement, parameters in statements:
            with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                self.repository._connection.execute(statement, parameters)
        self.assertEqual(self.repository.get_forecasts(), [self.sample])

    def test_integrity_check(self) -> None:
        self.repository.save_forecast(self.sample)
        self.repository.check_integrity()

    def test_closed_connection_reports_application_error(self) -> None:
        self.repository.close()
        with self.assertRaises(WeatherDataError) as caught:
            self.repository.get_forecasts()
        self.assertEqual(caught.exception.code, "DATABASE_ERROR")
