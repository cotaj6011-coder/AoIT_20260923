"""F-C0032-001 mapping verified against the live response on 2026-09-23."""

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import DATASET_ID
from .errors import WeatherDataError
from .json_data import decode_json, sanitize
from .model import WeatherForecast, validate_forecasts

TAIWAN_TIME = timezone(timedelta(hours=8), name="Asia/Taipei")
ELEMENT_FIELDS = {
    "MinT": "min_temperature",
    "MaxT": "max_temperature",
    "PoP": "rain_probability",
    "Wx": "weather_description",
}


def _schema(message: str) -> WeatherDataError:
    return WeatherDataError("INVALID_SCHEMA", message)


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _schema(f"{path} must be a JSON object.")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _schema(f"{path} must be a JSON array.")
    return value


def _time(value: Any) -> datetime:
    pattern = (
        r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
        r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)?"
    )
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise WeatherDataError("INVALID_TIME", "Expected a full timestamp with optional ISO timezone.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=TAIWAN_TIME)
        return parsed.astimezone(TAIWAN_TIME)
    except (ValueError, OverflowError):
        raise WeatherDataError("INVALID_TIME", "Forecast timestamp is invalid.") from None


def _context_error(
    exc: WeatherDataError, location: str, element: str, period: str
) -> WeatherDataError:
    # Never echo arbitrary raw values or credential-shaped strings in errors.
    safe_location = str(sanitize(location, ""))[:100]
    return WeatherDataError(
        exc.code,
        f"Location={safe_location!r}; Element={element}; Time={period}: {exc}",
    )


def _index_elements(elements: list[Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for element in elements:
        element = _object(element, "weatherElement[]")
        name = element.get("elementName")
        if not isinstance(name, str):
            raise _schema("elementName must be text.")
        if name not in ELEMENT_FIELDS:
            continue  # CI is in the fixture but outside this DTO.
        if name in indexed:
            raise _schema(f"Duplicate weather element {name}.")
        indexed[name] = element
    return indexed


def _period_value(period: dict[str, Any], element: str) -> Any:
    parameter = period.get("parameter")
    parameter = {} if parameter is None else _object(parameter, "time[].parameter")
    unit = parameter.get("parameterUnit")
    if element in {"MinT", "MaxT"} and unit not in (None, "", "C"):
        raise _schema("Temperature parameterUnit must be C.")
    if element == "PoP" and unit not in (None, "", "百分比"):
        raise _schema("PoP parameterUnit must be 百分比.")
    return parameter.get("parameterName")


def _index_periods(
    element: dict[str, Any], name: str, location: str
) -> dict[tuple[datetime, datetime], Any]:
    indexed: dict[tuple[datetime, datetime], Any] = {}
    try:
        periods = _list(element.get("time"), "weatherElement[].time")
    except WeatherDataError as exc:
        raise _context_error(exc, location, name, "time[]") from None
    for index, raw_period in enumerate(periods):
        context = f"time[{index}] (startTime/endTime)"
        try:
            period = _object(raw_period, "weatherElement[].time[]")
            start, end = _time(period.get("startTime")), _time(period.get("endTime"))
            context = f"{start.isoformat()} / {end.isoformat()}"
            if end <= start:
                raise WeatherDataError("TIME_ALIGNMENT_ERROR", "endTime must be after startTime.")
            interval = (start, end)
            if interval in indexed:
                raise WeatherDataError("TIME_ALIGNMENT_ERROR", "Duplicate element interval.")
            indexed[interval] = _period_value(period, name)
        except WeatherDataError as exc:
            raise _context_error(exc, location, name, context) from None
    return indexed


def _parse_location(location: dict[str, Any], name: str) -> list[WeatherForecast]:
    try:
        elements = _index_elements(_list(location.get("weatherElement"), "weatherElement"))
    except WeatherDataError as exc:
        raise _context_error(exc, name, "weatherElement[]", "N/A") from None
    periods: dict[tuple[datetime, datetime], dict[str, Any]] = {}
    for element_name, element in elements.items():
        for interval, value in _index_periods(element, element_name, name).items():
            periods.setdefault(interval, {})[ELEMENT_FIELDS[element_name]] = value
    forecasts = []
    # Full outer join: unmatched values stay None; never zip, swap, or interpolate.
    for (start, end), values in sorted(periods.items()):
        try:
            forecasts.append(WeatherForecast(
                location_name=name,
                start_time=start,
                end_time=end,
                **{field: values.get(field) for field in ELEMENT_FIELDS.values()},
            ))
        except WeatherDataError as exc:
            raise _context_error(
                exc, name, "MinT/MaxT/PoP/Wx", f"{start.isoformat()} / {end.isoformat()}"
            ) from None
    return forecasts


def parse_forecasts(data: dict[str, Any]) -> list[WeatherForecast]:
    root = _object(data, "Root")
    if "success" not in root:
        raise _schema("CWA response is missing success.")
    if root["success"] is not True and root["success"] != "true":
        raise WeatherDataError("CWA_FAILURE", "CWA reported unsuccessful data retrieval.")
    result = _object(root.get("result"), "result")
    if result.get("resource_id") != DATASET_ID:
        raise _schema("CWA resource_id does not match the configured dataset.")
    records = _object(root.get("records"), "records")
    locations = _list(records.get("location"), "records.location")
    forecasts: list[WeatherForecast] = []
    location_names: set[str] = set()
    for index, raw_location in enumerate(locations):
        location = _object(raw_location, f"records.location[{index}]")
        name = location.get("locationName")
        if not isinstance(name, str) or not name.strip():
            raise _context_error(
                _schema("locationName must be non-empty text."),
                f"records.location[{index}]", "N/A", "N/A",
            )
        name = name.strip()
        if name in location_names:
            raise _context_error(_schema("Duplicate locationName."), name, "N/A", "N/A")
        location_names.add(name)
        forecasts.extend(_parse_location(location, name))
    validate_forecasts(forecasts)
    return forecasts


def parse_response(body: bytes) -> list[WeatherForecast]:
    return parse_forecasts(decode_json(body))
