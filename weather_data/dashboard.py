"""Repository → typed DataFrame → shared filters, chart and table inputs."""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .errors import WeatherDataError
from .model import WeatherForecast, validate_forecasts
from .storage import WeatherForecastRepository

COLUMNS = ["location_name", "start_time", "end_time", "min_temperature", "max_temperature",
           "rain_probability", "weather_description"]
DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / ".local/weather.sqlite3"


def to_dataframe(forecasts: Sequence[WeatherForecast]) -> pd.DataFrame:
    validate_forecasts(forecasts)
    frame = pd.DataFrame([asdict(row) for row in forecasts], columns=COLUMNS)
    for column in ("start_time", "end_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True).dt.tz_convert("Asia/Taipei")
    for column in ("min_temperature", "max_temperature", "rain_probability"):
        frame[column] = pd.array(frame[column], dtype="Float64")
    return frame.sort_values(["location_name", "start_time", "end_time"], kind="stable").reset_index(drop=True)


def load_dashboard(database: Path) -> tuple[pd.DataFrame, datetime | None]:
    if not database.is_file():
        raise WeatherDataError("DATABASE_MISSING", "Weather database does not exist. Prepare or select a database first.")
    with WeatherForecastRepository(database, read_only=True) as repository:
        return to_dataframe(repository.get_forecasts()), repository.get_last_updated()


def filter_forecasts(
    frame: pd.DataFrame, location: str | None = None, forecast_date: date | None = None,
    interval: tuple[str, str] | None = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=frame.index)
    if location is not None:
        mask &= frame["location_name"].eq(location)
    if forecast_date is not None:
        mask &= frame["start_time"].dt.date.eq(forecast_date)
    if interval is not None:
        mask &= frame["start_time"].eq(pd.Timestamp(interval[0])) & frame["end_time"].eq(pd.Timestamp(interval[1]))
    return frame.loc[mask].sort_values(["start_time", "end_time", "location_name"], kind="stable").reset_index(drop=True).copy()


def chart_data(filtered: pd.DataFrame) -> pd.DataFrame:
    # Retain gaps: missing temperatures are never filled with zero or interpolated.
    return filtered.sort_values(["start_time", "end_time"], kind="stable")[
        ["start_time", "min_temperature", "max_temperature"]
    ].reset_index(drop=True).copy()


def table_data(filtered: pd.DataFrame) -> pd.DataFrame:
    return filtered.sort_values(["start_time", "end_time"], kind="stable")[COLUMNS].reset_index(drop=True).copy()
