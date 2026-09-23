"""Explicit local snapshot import, separate from the read-only web app."""

import argparse
from pathlib import Path

from weather_data.dashboard import DEFAULT_DATABASE
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository


def main() -> None:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    arguments.add_argument("--fixture", type=Path, default=Path(__file__).resolve().parent / "tests/fixtures/cwa_weather.json")
    args = arguments.parse_args()
    forecasts = parse_response(args.fixture.read_bytes())
    args.database.parent.mkdir(parents=True, exist_ok=True)
    with WeatherForecastRepository(args.database) as repository:
        repository.initialize_database()
        repository.save_forecasts(forecasts)
        print(f"Imported snapshot records: {len(forecasts)}; stored: {repository.count_forecasts()}")
    print("Historical fixture snapshot; not a live API refresh.")


if __name__ == "__main__":
    main()
