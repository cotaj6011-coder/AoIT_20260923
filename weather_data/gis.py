"""Filtered dashboard data → county markers; no API, SQL or raw CWA parsing."""

import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from pathlib import Path

import folium
import pandas as pd

LOGGER = logging.getLogger(__name__)
COORDINATE_FILE = Path(__file__).with_name("location_coordinates.json")
TAIWAN_CENTER = (23.7, 120.9)
# Include offshore counties when initially viewing Taiwan.
TAIWAN_BOUNDS = ((21.8, 118.1), (26.4, 122.1))
TEMPERATURE_BANDS = ((20, "blue"), (25, "green"), (30, "orange"))
MISSING_COLOR = "gray"
MAP_COLORS = {"blue": "#60a5fa", "green": "#34d399", "orange": "#fbbf24", "red": "#fb7185", "gray": "#94a3b8"}


def load_coordinates() -> dict[str, dict[str, object]]:
    return json.loads(COORDINATE_FILE.read_text(encoding="utf-8"))["locations"]


def coordinate_status(value: object) -> str:
    if value is None:
        return "missing"
    if not isinstance(value, Mapping):
        return "invalid"
    lat, lon = value.get("latitude"), value.get("longitude")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
           for v in (lat, lon)):
        return "invalid"
    # This project's display anchors must be in Taiwan or its offshore counties.
    return "valid" if 21 <= lat <= 27 and 118 <= lon <= 123 else "invalid"


def marker_color(max_temperature: float | None) -> str:
    if pd.isna(max_temperature):
        return MISSING_COLOR
    for upper, color in TEMPERATURE_BANDS:
        if max_temperature < upper:
            return color
    return "red"


def _display(value: object, unit: str = "") -> str:
    return "N/A" if pd.isna(value) else escape(f"{value}{unit}", quote=True)


def popup_content(location: str, forecasts: pd.DataFrame) -> str:
    parts = [f"<b>{escape(location)}</b><p style='color:#94a3b8'>縣市預報 · 非測站觀測</p>"]
    for row in forecasts.sort_values(["start_time", "end_time"]).itertuples():
        parts.append(
            f"<p>預報時段 Forecast: <time datetime='{escape(row.start_time.isoformat())}'>{row.start_time:%m/%d %H:%M}</time><br>"
            f"→ <time datetime='{escape(row.end_time.isoformat())}'>{row.end_time:%m/%d %H:%M}</time> (+08:00)<br>"
            f"最低溫 MinT: {_display(row.min_temperature, ' °C')}<br>"
            f"最高溫 MaxT: {_display(row.max_temperature, ' °C')}<br>"
            f"降雨機率: {_display(row.rain_probability, ' %')}<br>"
            f"天氣: {_display(row.weather_description)}</p>"
        )
    return "".join(parts)


@dataclass(frozen=True)
class WeatherMarker:
    location_name: str
    latitude: float
    longitude: float
    forecast_count: int
    min_temperature: float | None
    max_temperature: float | None
    popup: str


@dataclass(frozen=True)
class MarkerData:
    markers: tuple[WeatherMarker, ...]
    missing_locations: tuple[str, ...]
    invalid_locations: tuple[str, ...]


def prepare_markers(
    filtered: pd.DataFrame, coordinates: Mapping[str, object] | None = None,
) -> MarkerData:
    coordinates = load_coordinates() if coordinates is None else coordinates
    markers, missing, invalid = [], [], []
    for location, group in filtered.groupby("location_name", sort=True):
        coordinate = coordinates.get(location)
        status = coordinate_status(coordinate)
        if status != "valid":
            (missing if status == "missing" else invalid).append(location)
            LOGGER.warning("Skipping map marker: location=%s coordinate=%s", location, status)
            continue
        low, high = group.min_temperature.min(), group.max_temperature.max()
        markers.append(WeatherMarker(
            location, float(coordinate["latitude"]), float(coordinate["longitude"]), len(group),
            None if pd.isna(low) else float(low), None if pd.isna(high) else float(high),
            popup_content(location, group),
        ))
    return MarkerData(tuple(markers), tuple(missing), tuple(invalid))


def create_map(data: MarkerData, selected_location: str | None = None) -> folium.Map:
    result = folium.Map(location=TAIWAN_CENTER, zoom_start=7, tiles="OpenStreetMap", control_scale=True)
    result.fit_bounds(TAIWAN_BOUNDS)
    result.get_root().header.add_child(folium.Element('''<style>
      .leaflet-container {background:#0b1120;font-family:system-ui,sans-serif;}
      html, body, #parent, #map_div {height:100dvh !important;margin:0;}
      .leaflet-container {height:100dvh !important;}
      .leaflet-top.leaflet-left {top:45%;}
      .leaflet-tile-pane {filter:invert(1) hue-rotate(180deg) brightness(.75) saturate(.45);}
      .leaflet-popup-content-wrapper,.leaflet-popup-tip {background:#111827;color:#e5e7eb;}
      .weather-pin {background:rgba(17,24,39,.94);border:1px solid var(--tone);
        border-radius:12px;padding:5px 8px;min-width:62px;text-align:center;
        box-shadow:0 4px 15px #0008;color:#e5e7eb;line-height:1.2;}
      .weather-pin.selected {outline:2px solid #f8fafc;box-shadow:0 0 20px #38bdf888;}
      .weather-pin b {display:block;font-size:20px;color:var(--tone);}
      .weather-pin small {font-size:10px;color:#cbd5e1;}
      .map-note {position:absolute;z-index:999;pointer-events:none;background:rgba(17,24,39,.9);
        color:#e5e7eb;border:1px solid #334155;border-radius:12px;padding:12px 16px;
        font:12px system-ui,sans-serif;box-shadow:0 8px 24px #0005;backdrop-filter:blur(8px);}
      .map-summary {display:none;} .map-legend {bottom:26px;right:12px;}
      @media(max-width:600px){.map-note{padding:8px;font-size:10px;}.map-summary{left:48px;}}
      </style>'''))
    result.get_root().html.add_child(folium.Element(
        f'<div class="map-note map-summary"><b>TAIWAN / 縣市預報</b><br>{len(data.markers)} 個地區 · 點選溫度標記查看明細</div>'
        '<div class="map-note map-legend"><b>預報最高溫 °C</b><br>'
        '<span style="color:#60a5fa">● &lt;20</span>　<span style="color:#34d399">● 20–&lt;25</span>　'
        '<span style="color:#fbbf24">● 25–&lt;30</span>　<span style="color:#fb7185">● ≥30</span>'
        '<br><span style="color:#94a3b8">● 缺值</span> · 小字為預報最低溫</div>'
    ))
    for marker in data.markers:
        # IFrame isolates popup text from Folium's JavaScript template literals.
        popup_html = '<body style="background:#111827;color:#e5e7eb;font:13px system-ui">' + marker.popup + '</body>'
        popup = folium.Popup(folium.IFrame(html=popup_html, width=300, height=230), max_width=320)
        safe_name = escape(marker.location_name).replace("`", "&#96;").replace("$", "&#36;")
        tooltip = f"{safe_name} · 點選查看縣市預報"
        high = "—" if marker.max_temperature is None else f"{marker.max_temperature:g}°"
        low = "—" if marker.min_temperature is None else f"{marker.min_temperature:g}°"
        selected = " selected" if marker.location_name == selected_location else ""
        icon = folium.DivIcon(icon_size=(78, 63), icon_anchor=(39, 32), html=(
            f'<div class="weather-pin{selected}" style="--tone:{MAP_COLORS[marker_color(marker.max_temperature)]}">'
            f'<small>{safe_name}</small><b>{high}</b><small>最低 {low}</small></div>'
        ))
        folium.Marker(
            [marker.latitude, marker.longitude], popup=popup, tooltip=tooltip,
            icon=icon,
        ).add_to(result)
    return result
