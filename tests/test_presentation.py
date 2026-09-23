from datetime import datetime, timezone
from pathlib import Path
import unittest

from weather_data.dashboard import to_dataframe
from weather_data.gis import create_map, prepare_markers
from weather_data.parser import parse_response
from weather_data.presentation import clicked_location, default_interval, forecast_intervals, interval_label, temperature_label


class PresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        rows = parse_response((Path(__file__).parent / 'fixtures/cwa_weather.json').read_bytes())
        self.frame = to_dataframe(rows)
        self.periods = forecast_intervals(self.frame)

    def test_intervals_unique_sorted(self) -> None:
        self.assertEqual(len(self.periods), 3)
        self.assertEqual(self.periods, forecast_intervals(self.frame.iloc[::-1]))

    def test_current_interval(self) -> None:
        self.assertEqual(default_interval(self.periods, datetime.fromisoformat(self.periods[1][0])), self.periods[1])

    def test_future_interval(self) -> None:
        self.assertEqual(default_interval(self.periods, datetime(2000, 1, 1, tzinfo=timezone.utc)), self.periods[0])

    def test_historical_interval(self) -> None:
        self.assertEqual(default_interval(self.periods, datetime(2100, 1, 1, tzinfo=timezone.utc)), self.periods[-1])

    def test_readable_labels_and_null(self) -> None:
        self.assertEqual(temperature_label(None), '—')
        self.assertEqual(temperature_label(30.0), '30°')
        self.assertEqual(interval_label(self.periods[0]), '09/23 18:00 → 09/24 06:00')

    def test_marker_click_exact_match(self) -> None:
        data = prepare_markers(self.frame)
        marker = data.markers[0]
        self.assertEqual(clicked_location({'last_object_clicked': {'lat': marker.latitude, 'lng': marker.longitude}}, data), marker.location_name)

    def test_invalid_clicks_do_not_select(self) -> None:
        data = prepare_markers(self.frame)
        for event in [None, {}, {'last_clicked': {'lat': 24, 'lng': 121}},
                      {'last_object_clicked': {'lat': 0, 'lng': 0}},
                      {'last_object_clicked': {'lat': float('nan'), 'lng': 121}},
                      {'last_object_clicked': {'lat': '24', 'lng': 121}}]:
            self.assertIsNone(clicked_location(event, data))

    def test_numeric_markers_highlight_and_dark_style(self) -> None:
        data = prepare_markers(self.frame)
        rendered = create_map(data, data.markers[0].location_name).get_root().render()
        self.assertIn('weather-pin selected', rendered)
        self.assertIn('leaflet-tile-pane', rendered)
        self.assertIn('預報最高溫', rendered)
        self.assertIn('最低', rendered)
        self.assertIn('openstreetmap.org', rendered)
