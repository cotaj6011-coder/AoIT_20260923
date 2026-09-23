"""Offline Phase 3 acceptance; the temporary SQLite file is always removed."""

import argparse
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from weather_data.errors import WeatherDataError
from weather_data.model import WeatherForecast
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "tests/fixtures/cwa_weather.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WeatherDataError("STORAGE_VALIDATION", message)


def _verify_rollback(repository: WeatherForecastRepository, sample: WeatherForecast) -> None:
    before = repository.get_forecasts()

    def failing_batch() -> Iterator[WeatherForecast]:
        yield replace(sample, min_temperature=None, max_temperature=None)
        yield replace(sample, location_name=f"rollback-probe-{uuid4().hex}")
        raise WeatherDataError("ROLLBACK_PROBE", "Intentional validation interruption after a write.")

    try:
        repository.save_forecasts(failing_batch())
    except WeatherDataError as exc:
        if exc.code != "ROLLBACK_PROBE":
            raise
    else:
        raise WeatherDataError("STORAGE_VALIDATION", "Rollback probe did not fail as expected.")
    _require(repository.get_forecasts() == before, "Failed transaction changed stored data.")


def validate(repository: WeatherForecastRepository, forecasts: list[WeatherForecast]) -> None:
    repository.initialize_database()
    _require(bool(forecasts), "Fixture produced no forecasts.")
    repository.save_forecasts(forecasts)
    stored = repository.count_forecasts()
    queried = repository.get_forecasts()
    expected = sorted(forecasts, key=lambda row: (row.location_name, row.start_time, row.end_time))
    _require(len(forecasts) == stored == len(queried), "Parsed, stored and queried counts differ.")
    _require(queried == expected, "Round-trip values or timestamps differ from Phase 2 DTOs.")
    sample = queried[0]
    _require(repository.get_forecast(sample.location_name, sample.start_time, sample.end_time) == sample,
             "Natural-key query did not return the expected forecast.")
    _require(repository.get_forecasts_by_location(sample.location_name) ==
             [row for row in expected if row.location_name == sample.location_name], "Location query differs.")
    _require(repository.get_forecasts_by_time_range(sample.start_time, sample.end_time) ==
             [row for row in expected if row.start_time < sample.end_time and row.end_time > sample.start_time],
             "Time-range query differs.")
    # Repeat the entire import: UNIQUE + UPSERT must keep all keys singular.
    repository.save_forecasts(forecasts)
    _require(repository.count_forecasts() == stored, "Repeated import created duplicates.")
    duplicates = repository.count_duplicate_keys()
    _require(duplicates == 0, "Duplicate natural keys found.")
    _verify_rollback(repository, sample)
    repository.check_integrity()
    print(f"Parsed Records: {len(forecasts)}\nStored Records: {stored}\nQueried Records: {len(queried)}")
    print(f"Locations: {len(repository.get_locations())}\nDuplicate Keys: {duplicates}")
    print(f"\nSample:\nLocation: {sample.location_name}")
    print(f"Start: {sample.start_time.isoformat()}\nEnd: {sample.end_time.isoformat()}")
    print(f"MinT: {sample.min_temperature}\nMaxT: {sample.max_temperature}")
    print("\nChecks:")
    for check in ("Database initialized", "Records inserted", "Counts matched", "Unique constraint",
                  "Query works", "Transaction works", "Data integrity"):
        print(f"[PASS] {check}")


def main(argv: list[str] | None = None) -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = arguments.parse_args(argv)
    print("Phase 3 Data Storage Validation")
    try:
        try:
            forecasts = parse_response(args.fixture.read_bytes())
        except OSError:
            raise WeatherDataError("FIXTURE_IO", "Cannot read fixture; check path and permissions.") from None
        with TemporaryDirectory(prefix="cwa-storage-") as directory:
            with WeatherForecastRepository(Path(directory) / "validation.sqlite3") as repository:
                validate(repository, forecasts)
        print("\nResult: PASS")
        return 0
    except WeatherDataError as exc:
        print(f"\n[FAIL] {exc.code}: {exc}\nResult: FAIL")
        return 1
    except OSError:
        print("\n[FAIL] TEMP_DATABASE_IO: Cannot create or clean temporary storage.\nResult: FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
