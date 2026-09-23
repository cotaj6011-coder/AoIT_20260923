"""Real fixture → unchanged parser → temporary SQLite → DTO equality."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validate_storage import main
from weather_data.model import validate_forecasts
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository

FIXTURE = Path(__file__).parent / "fixtures/cwa_weather.json"


class StorageIntegrationTests(unittest.TestCase):
    def test_full_fixture_persist_reopen_and_query(self) -> None:
        forecasts = parse_response(FIXTURE.read_bytes())
        expected = sorted(forecasts, key=lambda row: (row.location_name, row.start_time, row.end_time))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite3"
            with WeatherForecastRepository(path) as repository:
                repository.initialize_database()
                self.assertEqual(repository.save_forecasts(forecasts), 66)
            with WeatherForecastRepository(path) as repository:
                repository.initialize_database()
                queried = repository.get_forecasts()
                self.assertEqual(len(forecasts), repository.count_forecasts())
                self.assertEqual(repository.count_forecasts(), len(queried))
                self.assertEqual(queried, expected)
                validate_forecasts(queried)
                self.assertEqual(len(repository.get_locations()), 22)
                known = repository.get_forecasts_by_location("嘉義縣")[0]
                self.assertEqual((known.min_temperature, known.max_temperature), (25, 29))
                self.assertEqual(known.start_time.isoformat(), "2026-09-23T18:00:00+08:00")
                self.assertEqual(known.end_time.isoformat(), "2026-09-24T06:00:00+08:00")
                repository.save_forecasts(forecasts)
                self.assertEqual(repository.count_forecasts(), 66)
                self.assertEqual(repository.count_duplicate_keys(), 0)
                repository.check_integrity()
        self.assertFalse(path.exists())

    def test_validation_passes_offline_and_removes_temporary_database(self) -> None:
        paths: list[Path] = []
        original = WeatherForecastRepository.__init__

        def track(repository: WeatherForecastRepository, database: str | Path = ":memory:") -> None:
            paths.append(Path(database))
            original(repository, database)

        output = io.StringIO()
        with patch("socket.socket.connect", side_effect=AssertionError("No network")):
            with patch.object(WeatherForecastRepository, "__init__", track):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main([]), 0)
        self.assertTrue(paths)
        self.assertTrue(all(not path.exists() for path in paths))
        for text in ("Parsed Records: 66", "Stored Records: 66", "Queried Records: 66",
                     "Locations: 22", "Duplicate Keys: 0", "Result: PASS"):
            self.assertIn(text, output.getvalue())
        self.assertEqual(output.getvalue().count("[PASS]"), 7)

    def test_validation_missing_fixture(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--fixture", "not-a-real-fixture.json"]), 1)
        self.assertIn("FIXTURE_IO", output.getvalue())
        self.assertNotIn("[PASS]", output.getvalue())

    def test_validation_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("not json", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--fixture", str(path)]), 1)
            self.assertIn("INVALID_JSON", output.getvalue())

    def test_initialization_failure_is_fail_and_cleanup(self) -> None:
        from weather_data.errors import WeatherDataError
        output = io.StringIO()
        with patch.object(WeatherForecastRepository, "initialize_database",
                          side_effect=WeatherDataError("DATABASE_ERROR", "synthetic DB error")):
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([]), 1)
        self.assertIn("Result: FAIL", output.getvalue())
        self.assertNotIn("[PASS]", output.getvalue())
