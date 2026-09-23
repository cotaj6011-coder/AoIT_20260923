"""Phase 4 validation: real fixture via temporary SQLite by default; no network."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from weather_data.dashboard import chart_data, filter_forecasts, load_dashboard, table_data
from weather_data.errors import WeatherDataError
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository
from weather_data.presentation import default_interval, forecast_intervals


def validate(database: Path) -> None:
    frame, _ = load_dashboard(database)
    if frame.empty:
        raise WeatherDataError("EMPTY_DATASET", "No forecast records available.")
    location = sorted(frame["location_name"].unique())[0]
    period = default_interval(forecast_intervals(frame), datetime.now(timezone.utc))
    nationwide = filter_forecasts(frame, interval=period)
    location = sorted(nationwide["location_name"].unique())[0]
    filtered = filter_forecasts(nationwide, location)
    chart, table = chart_data(filtered), table_data(filtered)
    paired = filtered.dropna(subset=["min_temperature", "max_temperature"])
    sample = filtered.iloc[0]
    exact = filter_forecasts(frame, location, sample.start_time.date(),
                             (sample.start_time.isoformat(), sample.end_time.isoformat()))
    checks = {
        "Database read": len(frame) > 0,
        "DataFrame created": frame["location_name"].nunique() > 0,
        "Location filter": not filtered.empty and filtered["location_name"].eq(location).all() and len(exact) == 1,
        "Time sorting": filtered["start_time"].is_monotonic_increasing,
        "Chart data": not chart.empty and not paired.empty and paired["min_temperature"].le(paired["max_temperature"]).all(),
        "Table data": not table.empty and len(table) == len(chart),
    }
    print(f"Records: {len(frame)}\nLocations: {frame['location_name'].nunique()}")
    print(f"Selected Location: {location}\nFiltered Records: {len(filtered)}\n\nChecks:")
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise WeatherDataError("WEBAPP_VALIDATION", "One or more dashboard checks failed.")


def main(argv: list[str] | None = None) -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--database", type=Path, help="Read an existing DB without modifying it")
    args = arguments.parse_args(argv)
    print("Phase 4 Web App Validation")
    try:
        if args.database is not None:
            validate(args.database)
        else:
            fixture = Path(__file__).resolve().parent / "tests/fixtures/cwa_weather.json"
            with TemporaryDirectory(prefix="cwa-webapp-") as directory:
                database = Path(directory) / "test.sqlite3"
                with WeatherForecastRepository(database) as repository:
                    repository.initialize_database()
                    repository.save_forecasts(parse_response(fixture.read_bytes()))
                validate(database)
        print("\nResult: PASS")
        return 0
    except (WeatherDataError, OSError) as exc:
        print(f"\nResult: FAIL\nReason: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
