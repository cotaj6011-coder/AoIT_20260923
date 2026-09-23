"""Presentation decisions shared by the dashboard and offline tests."""

from datetime import datetime
import math

import pandas as pd

from .gis import MarkerData


def forecast_intervals(frame: pd.DataFrame) -> list[tuple[str, str]]:
    return sorted({(r.start_time.isoformat(), r.end_time.isoformat()) for r in frame.itertuples()})


def default_interval(intervals: list[tuple[str, str]], now: datetime) -> tuple[str, str]:
    """Current interval, otherwise next available, otherwise latest historical period."""
    for period in intervals:
        if pd.Timestamp(period[1]) > now:
            return period
    return intervals[-1]


def interval_label(period: tuple[str, str]) -> str:
    start, end = (pd.Timestamp(t) for t in period)
    return f"{start:%m/%d %H:%M} → {end:%m/%d %H:%M}"


def temperature_label(value: float | None) -> str:
    return "—" if pd.isna(value) else f"{value:g}°"


def clicked_location(event: object, data: MarkerData) -> str | None:
    """Accept only exact mapped marker positions, never arbitrary map clicks."""
    if not isinstance(event, dict) or not isinstance(event.get("last_object_clicked"), dict):
        return None
    point = event["last_object_clicked"]
    lat, lon = point.get("lat"), point.get("lng")
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in (lat, lon)):
        return None
    for marker in data.markers:
        if abs(marker.latitude - lat) < 1e-7 and abs(marker.longitude - lon) < 1e-7:
            return marker.location_name
    return None
