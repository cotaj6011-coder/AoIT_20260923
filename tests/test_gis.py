import contextlib
import hashlib
import io
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

import folium
import pandas as pd

from validate_gis import main
from weather_data.dashboard import filter_forecasts, load_dashboard, to_dataframe
from weather_data.gis import coordinate_status, create_map, load_coordinates, marker_color, prepare_markers
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository

FIXTURE = Path(__file__).parent / "fixtures/cwa_weather.json"


class GisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = parse_response(FIXTURE.read_bytes())
        self.frame = to_dataframe(self.rows)

    def test_all_fixture_locations_have_valid_coordinates(self) -> None:
        coordinates = load_coordinates()
        self.assertEqual(set(coordinates), set(self.frame.location_name))
        self.assertTrue(all(coordinate_status(c) == "valid" for c in coordinates.values()))
        self.assertEqual(len({c['station_id'] for c in coordinates.values()}), 22)

    def test_known_taipei_and_offshore_coordinates(self) -> None:
        coordinates = load_coordinates()
        self.assertEqual(coordinates['臺北市']['latitude'], 25.037658)
        self.assertEqual(coordinates['臺北市']['longitude'], 121.514853)
        self.assertEqual(coordinates['金門縣']['longitude'], 118.289281)
        self.assertEqual(coordinates['連江縣']['latitude'], 26.169467)
        self.assertNotEqual(coordinates['新竹市'], coordinates['新竹縣'])

    def test_unknown_location_skipped_with_warning(self) -> None:
        frame = to_dataframe([replace(self.rows[0], location_name='Unknown')])
        with self.assertLogs('weather_data.gis', level='WARNING'):
            data = prepare_markers(frame)
        self.assertEqual(data.markers, ())
        self.assertEqual(data.missing_locations, ('Unknown',))
        self.assertEqual(data.invalid_locations, ())

    def test_invalid_coordinate_values(self) -> None:
        for value in [{}, {'latitude': 0, 'longitude': 0}, {'latitude': 121, 'longitude': 24},
                      {'latitude': float('nan'), 'longitude': 121},
                      {'latitude': 24, 'longitude': float('inf')},
                      {'latitude': '24', 'longitude': 121}, {'latitude': True, 'longitude': 121}]:
            with self.subTest(value=value):
                self.assertEqual(coordinate_status(value), 'invalid')

    def test_invalid_coordinates_counted_separately(self) -> None:
        frame = filter_forecasts(self.frame, '臺北市')
        with self.assertLogs('weather_data.gis', level='WARNING'):
            data = prepare_markers(frame, {'臺北市': {'latitude': 0, 'longitude': 0}})
        self.assertEqual(data.invalid_locations, ('臺北市',))
        self.assertFalse(data.markers)
        self.assertFalse(data.missing_locations)

    def test_marker_data_preserves_all_intervals_without_mutation(self) -> None:
        before = self.frame.copy(deep=True)
        data = prepare_markers(self.frame)
        self.assertEqual(len(data.markers), 22)
        self.assertEqual(sum(m.forecast_count for m in data.markers), 66)
        for marker in data.markers:
            rows = filter_forecasts(self.frame, marker.location_name)
            self.assertEqual(marker.min_temperature, rows.min_temperature.min())
            self.assertEqual(marker.max_temperature, rows.max_temperature.max())
            for row in rows.itertuples():
                self.assertIn(row.start_time.isoformat(), marker.popup)
                self.assertIn(row.end_time.isoformat(), marker.popup)
                self.assertIn(f'MinT: {row.min_temperature} °C', marker.popup)
                self.assertIn(f'MaxT: {row.max_temperature} °C', marker.popup)
        pd.testing.assert_frame_equal(before, self.frame)

    def test_null_temperatures_remain_missing(self) -> None:
        data = prepare_markers(to_dataframe([replace(self.rows[0], min_temperature=None, max_temperature=None)]))
        self.assertIsNone(data.markers[0].min_temperature)
        self.assertIsNone(data.markers[0].max_temperature)
        self.assertIn('MinT: N/A', data.markers[0].popup)
        self.assertEqual(marker_color(data.markers[0].max_temperature), 'gray')

    def test_style_boundaries(self) -> None:
        for value, color in [(None, 'gray'), (float('nan'), 'gray'), (19.9, 'blue'),
                             (20, 'green'), (24.9, 'green'), (25, 'orange'), (29.9, 'orange'),
                             (30, 'red'), (35, 'red')]:
            self.assertEqual(marker_color(value), color)

    def test_location_filter(self) -> None:
        data = prepare_markers(filter_forecasts(self.frame, '臺中市'))
        self.assertEqual([m.location_name for m in data.markers], ['臺中市'])
        self.assertEqual(data.markers[0].forecast_count, 3)

    def test_date_and_interval_filter(self) -> None:
        filtered = filter_forecasts(self.frame, '臺中市', date(2026, 9, 24))
        self.assertEqual(prepare_markers(filtered).markers[0].forecast_count, 2)
        row = filtered.iloc[0]
        exact = filter_forecasts(filtered, interval=(row.start_time.isoformat(), row.end_time.isoformat()))
        marker = prepare_markers(exact).markers[0]
        self.assertEqual(marker.forecast_count, 1)
        self.assertEqual(marker.min_temperature, row.min_temperature)
        self.assertEqual(marker.max_temperature, row.max_temperature)

    def test_empty_input_creates_empty_map(self) -> None:
        data = prepare_markers(to_dataframe([]))
        self.assertFalse(data.markers)
        self.assertIn('L.map(', create_map(data).get_root().render())

    def test_map_marker_popup_objects_and_tiles(self) -> None:
        data = prepare_markers(self.frame)
        result = create_map(data)
        markers = [c for c in result._children.values() if isinstance(c, folium.Marker)]
        self.assertEqual(len(markers), 22)
        self.assertEqual(markers[0].location, [data.markers[0].latitude, data.markers[0].longitude])
        self.assertTrue(any(isinstance(c, folium.Popup) for c in markers[0]._children.values()))
        html = result.get_root().render()
        self.assertIn('openstreetmap.org', html)
        self.assertEqual(html.count('L.marker('), 22)
        self.assertEqual(html.count('.bindPopup('), 22)

    def test_popup_escapes_untrusted_weather(self) -> None:
        row = replace(self.rows[0], weather_description='<script>alert(1)</script>')
        marker = prepare_markers(to_dataframe([row])).markers[0]
        self.assertNotIn('<script>', marker.popup)
        self.assertIn('&lt;script&gt;', marker.popup)

    def test_shuffled_input_is_deterministic(self) -> None:
        self.assertEqual(prepare_markers(self.frame), prepare_markers(self.frame.sample(frac=1, random_state=1)))


class GisIntegrationTests(unittest.TestCase):
    def test_repository_dataframe_map_roundtrip_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'test.sqlite3'
            with WeatherForecastRepository(database) as repository:
                repository.initialize_database()
                repository.save_forecasts(parse_response(FIXTURE.read_bytes()))
            digest = hashlib.sha256(database.read_bytes()).digest()
            frame, _ = load_dashboard(database)
            data = prepare_markers(frame)
            self.assertEqual(len(data.markers), 22)
            self.assertEqual(sum(m.forecast_count for m in data.markers), len(frame))
            self.assertIn('L.map(', create_map(data).get_root().render())
            self.assertEqual(digest, hashlib.sha256(database.read_bytes()).digest())

    def test_validation_default(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main([]), 0)
        self.assertIn('Weather Records: 66', output.getvalue())
        self.assertIn('Markers: 22', output.getvalue())
        self.assertIn('Missing Coordinates: 0', output.getvalue())
        self.assertIn('Invalid Coordinates: 0', output.getvalue())
        self.assertEqual(output.getvalue().count('[PASS]'), 5)

    def test_validation_missing_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--database', str(Path(directory) / 'missing.sqlite3')]), 1)
