"""Offline Phase 2 acceptance using the unchanged Phase 1 snapshot."""

import argparse
from pathlib import Path

from weather_data.config import DATASET_ID
from weather_data.errors import WeatherDataError
from weather_data.model import WeatherForecast, validate_forecasts
from weather_data.parser import parse_response

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "tests/fixtures/cwa_weather.json"


def _temperature_range(values: list[float]) -> str:
    return f"{min(values):g}–{max(values):g} C" if values else "N/A"


def _check_temperatures(forecasts: list[WeatherForecast]) -> None:
    # Parsing permits missing values. Acceptance must not claim complete
    # temperature coverage when any interval has only one side of the pair.
    for index, forecast in enumerate(forecasts):
        if forecast.min_temperature is None or forecast.max_temperature is None:
            raise WeatherDataError(
                "INCOMPLETE_TEMPERATURES",
                f"Forecast[{index}] has missing/invalid MinT or MaxT; no cross-interval pairing was applied.",
            )


def main(argv: list[str] | None = None) -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = arguments.parse_args(argv)
    print("Phase 2 Data Processing Validation")
    print(f"Fixture: {args.fixture.name}")
    print(f"Dataset: {DATASET_ID}")
    try:
        try:
            body = args.fixture.read_bytes()
        except OSError:
            raise WeatherDataError("FIXTURE_IO", "Cannot read fixture; check its path and permissions.") from None
        forecasts = parse_response(body)
        validate_forecasts(forecasts)
        if not forecasts:
            raise WeatherDataError("EMPTY_DATASET", "Fixture contains no forecast records.")
        _check_temperatures(forecasts)
        print(f"Locations: {len({row.location_name for row in forecasts})}")
        print(f"Forecast Records: {len(forecasts)}")
        print(f"MinT Range: {_temperature_range([row.min_temperature for row in forecasts if row.min_temperature is not None])}")
        print(f"MaxT Range: {_temperature_range([row.max_temperature for row in forecasts if row.max_temperature is not None])}")
        sample = forecasts[0]
        print(f"\nSample:\nLocation: {sample.location_name}")
        print(f"Start: {sample.start_time.isoformat()}\nEnd: {sample.end_time.isoformat()}")
        print(f"MinT: {sample.min_temperature:g} C\nMaxT: {sample.max_temperature:g} C")
        print("\nValidation:")
        for check in ("JSON parsed", "MinT parsed", "MaxT parsed", "Time aligned", "Data normalized", "No duplicate forecast key"):
            print(f"[PASS] {check}")
        print("\nResult: PASS")
        return 0
    except WeatherDataError as exc:
        print(f"\nValidation:\n[FAIL] {exc.code}: {exc}\n\nResult: FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
