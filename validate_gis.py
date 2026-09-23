"""Offline Phase 5 validation; default fixture → temporary SQLite → dashboard → map."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import folium

from weather_data.dashboard import filter_forecasts, load_dashboard
from weather_data.errors import WeatherDataError
from weather_data.gis import create_map, prepare_markers
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository


def validate(database: Path) -> None:
    frame, _ = load_dashboard(database)
    data = prepare_markers(frame)
    print(f"Weather Records: {len(frame)}\nLocations: {frame.location_name.nunique()}")
    print(f"Markers: {len(data.markers)}\nMissing Coordinates: {len(data.missing_locations)}")
    print(f"Invalid Coordinates: {len(data.invalid_locations)}")
    if frame.empty or not data.markers:
        raise WeatherDataError("GIS_VALIDATION", "No mapped weather records available.")
    sample = data.markers[0]
    first = frame[frame.location_name.eq(sample.location_name)].iloc[0]
    filtered = filter_forecasts(frame, sample.location_name, first.start_time.date(),
                                (first.start_time.isoformat(), first.end_time.isoformat()))
    subset = prepare_markers(filtered)
    weather_map = create_map(data)
    rendered = weather_map.get_root().render()
    checks = {
        "Weather data loaded": len(frame) > 0,
        "Coordinates mapped": not data.missing_locations and not data.invalid_locations,
        "Marker data created": sum(m.forecast_count for m in data.markers) == len(frame),
        "Filter integration": len(subset.markers) == 1 and subset.markers[0].forecast_count == 1
            and subset.markers[0].location_name == sample.location_name
            and subset.markers[0].min_temperature == first.min_temperature
            and subset.markers[0].max_temperature == first.max_temperature
            and first.start_time.isoformat() in subset.markers[0].popup,
        "Map created": "L.map(" in rendered and sum(isinstance(c, folium.Marker)
            for c in weather_map._children.values()) == len(data.markers),
    }
    print(f"\nSample Marker:\nLocation: {sample.location_name}\nLatitude: {sample.latitude}")
    print(f"Longitude: {sample.longitude}\nMinT: {sample.min_temperature}\nMaxT: {sample.max_temperature}")
    print("\nChecks:")
    for name, passed in checks.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
    if not all(checks.values()):
        raise WeatherDataError("GIS_VALIDATION", "One or more GIS checks failed.")


def main(argv: list[str] | None = None) -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--database", type=Path, help="Read an existing database without modifying it")
    args = arguments.parse_args(argv)
    print("Phase 5 GIS Validation")
    try:
        if args.database is not None:
            validate(args.database)
        else:
            fixture = Path(__file__).resolve().parent / "tests/fixtures/cwa_weather.json"
            with TemporaryDirectory(prefix="cwa-gis-") as directory:
                database = Path(directory) / "gis.sqlite3"
                with WeatherForecastRepository(database) as repository:
                    repository.initialize_database()
                    repository.save_forecasts(parse_response(fixture.read_bytes()))
                validate(database)
        print("\nResult: PASS")
        return 0
    except (WeatherDataError, OSError, ValueError, TypeError) as exc:
        print(f"\nResult: FAIL\nReason: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
