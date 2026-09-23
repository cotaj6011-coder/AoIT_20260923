"""SQLite repository for normalized forecasts; owns exactly one connection."""

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any

from . import storage_sql as sql
from .errors import WeatherDataError
from .model import WeatherForecast, validate_forecasts

STORAGE_TIMEZONE = timezone(timedelta(hours=8))


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise WeatherDataError("INVALID_TIME", "Storage requires timezone-aware datetime values.")
    try:
        return value.astimezone(STORAGE_TIMEZONE).isoformat(timespec="microseconds")
    except (ValueError, OverflowError):
        raise WeatherDataError("INVALID_TIME", "Timestamp cannot be represented in storage timezone.") from None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _database_error(operation: str, exc: sqlite3.Error) -> WeatherDataError:
    # Exception messages can include data/paths; expose only SQLite's error name.
    name = getattr(exc, "sqlite_errorname", type(exc).__name__)
    return WeatherDataError("DATABASE_ERROR", f"SQLite {operation} failed ({name}).")


def _parameters(forecast: WeatherForecast, stamp: str) -> tuple[Any, ...]:
    validate_forecasts([forecast])
    return (
        forecast.location_name, _timestamp(forecast.start_time), _timestamp(forecast.end_time),
        forecast.min_temperature, forecast.max_temperature, forecast.rain_probability,
        forecast.weather_description, stamp, stamp,
    )


def _forecast(row: sqlite3.Row) -> WeatherForecast:
    try:
        return WeatherForecast(
            location_name=row["location_name"],
            start_time=datetime.fromisoformat(row["start_time"]),
            end_time=datetime.fromisoformat(row["end_time"]),
            min_temperature=row["min_temperature"], max_temperature=row["max_temperature"],
            rain_probability=row["rain_probability"], weather_description=row["weather_description"],
        )
    except (ValueError, TypeError, IndexError, WeatherDataError):
        raise WeatherDataError("DATABASE_DATA", "Stored forecast violates the WeatherForecast contract.") from None


class WeatherForecastRepository:
    """Use as a context manager; methods commit independently, queries return DTOs."""

    def __init__(self, database: str | Path = ":memory:", *, read_only: bool = False) -> None:
        try:
            target = Path(database).resolve().as_uri() + "?mode=ro" if read_only else str(database)
            self._connection = sqlite3.connect(target, uri=read_only, timeout=5, isolation_level=None)
            self._connection.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise _database_error("open", exc) from None

    def __enter__(self) -> "WeatherForecastRepository":
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def initialize_database(self) -> None:
        try:
            with self._connection:
                self._connection.execute(sql.BEGIN)
                self._connection.execute(sql.CREATE_TABLE)
                self._connection.execute(sql.CREATE_TIME_INDEX)
        except sqlite3.Error as exc:
            raise _database_error("initialize", exc) from None

    def save_forecast(self, forecast: WeatherForecast) -> None:
        self.save_forecasts([forecast])

    def save_forecasts(self, forecasts: Iterable[WeatherForecast]) -> int:
        """One atomic batch; duplicate keys use last supplied values, including NULL."""
        count = 0
        stamp = _now()
        try:
            # Explicit BEGIN also makes empty batches and iterator failures atomic.
            # Connection context rolls back on ANY exception, not only SQL errors.
            with self._connection:
                self._connection.execute(sql.BEGIN)
                for forecast in forecasts:
                    self._connection.execute(sql.UPSERT, _parameters(forecast, stamp))
                    count += 1
        except sqlite3.Error as exc:
            raise _database_error("save batch", exc) from None
        return count

    def _query(self, statement: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        try:
            return self._connection.execute(statement, parameters).fetchall()
        except sqlite3.Error as exc:
            raise _database_error("query", exc) from None

    def _read(self, statement: str, parameters: tuple[Any, ...] = ()) -> list[WeatherForecast]:
        forecasts = [_forecast(row) for row in self._query(statement, parameters)]
        validate_forecasts(forecasts)
        return forecasts

    def get_forecasts(self) -> list[WeatherForecast]:
        return self._read(sql.GET_ALL)

    def get_forecasts_by_location(self, location_name: str) -> list[WeatherForecast]:
        return self._read(sql.GET_BY_LOCATION, (location_name,))

    def get_forecasts_by_time_range(self, start: datetime, end: datetime) -> list[WeatherForecast]:
        """Return forecast intervals overlapping [start, end), excluding touching endpoints."""
        start_text, end_text = _timestamp(start), _timestamp(end)
        if start_text >= end_text:
            raise WeatherDataError("INVALID_TIME_RANGE", "Query range must have start before end.")
        return self._read(sql.GET_BY_TIME_RANGE, (end_text, start_text))

    def get_forecast(
        self, location_name: str, start_time: datetime, end_time: datetime
    ) -> WeatherForecast | None:
        rows = self._read(sql.GET_BY_KEY, (location_name, _timestamp(start_time), _timestamp(end_time)))
        return rows[0] if rows else None

    def get_locations(self) -> list[str]:
        return [row[0] for row in self._query(sql.GET_LOCATIONS)]

    def count_forecasts(self) -> int:
        return int(self._query(sql.COUNT)[0][0])

    def get_last_updated(self) -> datetime | None:
        value = self._query(sql.LAST_UPDATED)[0][0]
        return datetime.fromisoformat(value) if value is not None else None

    def count_duplicate_keys(self) -> int:
        return int(self._query(sql.COUNT_DUPLICATES)[0][0])

    def check_integrity(self) -> None:
        if [row[0] for row in self._query(sql.INTEGRITY_CHECK)] != ["ok"]:
            raise WeatherDataError("DATABASE_INTEGRITY", "SQLite integrity_check did not return ok.")
        validate_forecasts(self.get_forecasts())
