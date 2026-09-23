"""Manual live validation; never runs as part of the default unit tests."""

import argparse
from pathlib import Path

from weather_data.client import CwaClient
from weather_data.config import DATASET_ID, CwaConfig
from weather_data.errors import WeatherDataError
from weather_data.json_data import decode_json, sanitize, save_capture
from weather_data.parser import parse_forecasts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Read a local env file; process environment takes precedence")
    parser.add_argument("--output", type=Path, default=Path(".local/cwa_weather.json"))
    args = parser.parse_args(argv)
    print("CWA API Validation")
    print(f"Dataset: {DATASET_ID}")
    status = None
    failure = None
    forecasts = []
    sample = None
    try:
        config = CwaConfig.from_environment(env_file=args.env_file)
        response = CwaClient(config).fetch()
        status = response.status
        data = decode_json(response.body)
        # Redact any echoed credentials before mapping or displaying values.
        safe_data = sanitize(data, config.api_key)
        try:
            forecasts = parse_forecasts(safe_data)
            if not forecasts:
                raise WeatherDataError("EMPTY_DATASET", "CWA returned no forecast periods.")
            if len({f.location_name for f in forecasts}) != len(safe_data["records"]["location"]):
                raise WeatherDataError("MISSING_PERIODS", "At least one CWA location has no forecast periods.")
            sample = next((f for f in forecasts if all(
                getattr(f, field) is not None for field in
                ("min_temperature", "max_temperature", "rain_probability", "weather_description")
            )), None)
            if sample is None:
                raise WeatherDataError("MISSING_FIELDS", "No forecast period contains all Phase 1 weather fields.")
        except WeatherDataError:
            save_capture(data, args.output.with_suffix(".unverified.json"), api_key=config.api_key, status=status)
            raise
        save_capture(data, args.output, api_key=config.api_key, status=status, verified=True)
    except WeatherDataError as exc:
        failure = exc
        status = exc.http_status or status
    print(f"HTTP Status: {status if status is not None else 'N/A (no HTTP response)'}")
    print(f"Record Count: {len(forecasts) if failure is None else 'N/A (validation failed)'}")
    print(f"Location Count: {len({f.location_name for f in forecasts}) if failure is None else 'N/A (validation failed)'}")
    print("\nSample:")
    if failure is None:
        print(f"Location: {sample.location_name}")
        print(f"Start Time: {sample.start_time.isoformat()}")
        print(f"End Time: {sample.end_time.isoformat()}")
        print(f"MinT: {sample.min_temperature:g} C")
        print(f"MaxT: {sample.max_temperature:g} C")
        print(f"PoP: {sample.rain_probability:g}%")
        print(f"Weather: {sample.weather_description}")
        print("\nResult: PASS")
        return 0
    for name in ("Location", "Start Time", "End Time", "MinT", "MaxT", "PoP", "Weather"):
        print(f"{name}: N/A (not validated)")
    print("\nResult: FAIL")
    print("Phase 1 Status: INCOMPLETE")
    print(f"Reason: [{failure.code}] {failure}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
