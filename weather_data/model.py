"""Normalized application DTO and collection invariants; no CWA traversal."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from .errors import WeatherDataError


def optional_number(value: object, *, minimum: float, maximum: float) -> float | None:
    """Application-range policy, NOT a claim about CWA missing-value codes."""
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and minimum <= number <= maximum else None


@dataclass(frozen=True)
class WeatherForecast:
    location_name: str
    start_time: datetime
    end_time: datetime
    min_temperature: float | None
    max_temperature: float | None
    rain_probability: float | None
    weather_description: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.location_name, str) or not self.location_name.strip():
            raise WeatherDataError("INVALID_FORECAST", "Forecast location_name must be non-empty.")
        if any(not isinstance(t, datetime) or t.utcoffset() is None for t in (self.start_time, self.end_time)):
            raise WeatherDataError("INVALID_FORECAST", "Forecast times must be timezone-aware datetimes.")
        if self.end_time <= self.start_time:
            raise WeatherDataError("INVALID_FORECAST", "Forecast end_time must be after start_time.")
        for field, lower, upper in (("min_temperature", -90, 60), ("max_temperature", -90, 60), ("rain_probability", 0, 100)):
            object.__setattr__(self, field, optional_number(getattr(self, field), minimum=lower, maximum=upper))
        if self.min_temperature is not None and self.max_temperature is not None and self.min_temperature > self.max_temperature:
            raise WeatherDataError("INVALID_FORECAST", "Forecast minimum temperature exceeds maximum temperature.")
        description = self.weather_description
        if description is not None and not isinstance(description, str):
            raise WeatherDataError("INVALID_FORECAST", "Weather description must be text or null.")
        object.__setattr__(self, "location_name", self.location_name.strip())
        normalized_description = (description.strip() or None) if description is not None else None
        object.__setattr__(self, "weather_description", normalized_description)

    @property
    def forecast_date(self) -> date:
        return self.start_time.date()


def validate_forecasts(forecasts: Sequence[WeatherForecast]) -> None:
    """Validate downstream DTOs without consulting or coercing raw JSON."""
    keys: set[tuple[str, datetime, datetime]] = set()
    for index, forecast in enumerate(forecasts):
        prefix = f"Forecast[{index}]"
        if not isinstance(forecast, WeatherForecast):
            raise WeatherDataError("INVALID_FORECAST", f"{prefix} must be a WeatherForecast DTO.")
        if not isinstance(forecast.location_name, str) or not forecast.location_name.strip():
            raise WeatherDataError("INVALID_FORECAST", f"{prefix} has no location_name.")
        times = (forecast.start_time, forecast.end_time)
        if any(not isinstance(t, datetime) or t.utcoffset() is None for t in times):
            raise WeatherDataError("INVALID_TIME", f"{prefix} needs aware start_time and end_time.")
        if forecast.start_time >= forecast.end_time:
            raise WeatherDataError("TIME_ALIGNMENT_ERROR", f"{prefix} has a reversed or empty interval.")
        for field, lower, upper in (
            ("min_temperature", -90, 60), ("max_temperature", -90, 60), ("rain_probability", 0, 100)
        ):
            value = getattr(forecast, field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float))
                or not lower <= value <= upper or not math.isfinite(value)
            ):
                raise WeatherDataError("INVALID_FORECAST", f"{prefix} has invalid normalized {field}.")
        if (forecast.min_temperature is not None and forecast.max_temperature is not None
                and forecast.min_temperature > forecast.max_temperature):
            raise WeatherDataError("INVALID_FORECAST", f"{prefix} has MinT greater than MaxT.")
        key = (forecast.location_name, forecast.start_time, forecast.end_time)
        if key in keys:
            raise WeatherDataError("DUPLICATE_FORECAST", f"{prefix} repeats a location/start/end key.")
        keys.add(key)
