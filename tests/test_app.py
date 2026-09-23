import base64
import json
import os
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
from streamlit.testing.v1 import AppTest

from weather_data.gis import load_coordinates
from weather_data.parser import parse_response
from weather_data.storage import WeatherForecastRepository

ROOT = Path(__file__).resolve().parents[1]


class AppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / 'ui.sqlite3'
        env = patch.dict(os.environ, {'WEATHER_DATABASE': str(self.database)})
        env.start()
        self.addCleanup(env.stop)
        self.rows = parse_response((ROOT / 'tests/fixtures/cwa_weather.json').read_bytes())

    def seed(self, rows: list | None = None) -> None:
        with WeatherForecastRepository(self.database) as repository:
            repository.initialize_database()
            repository.save_forecasts(self.rows if rows is None else rows)

    def app(self) -> AppTest:
        at = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=20).run()
        self.assertFalse(at.exception)
        return at

    def assert_chart_matches_table(self, at: AppTest) -> None:
        chart = pa.ipc.open_stream(at.get('vega_lite_chart')[0].proto.datasets[0].data.data).read_all().to_pandas()
        table = at.dataframe[0].value
        self.assertEqual(set(chart.start_time), set(table.start_time))
        values = chart['value -- streamlit-generated'].dropna().sort_values().tolist()
        self.assertEqual(values, pd.concat([table.min_temperature, table.max_temperature]).dropna().sort_values().tolist())

    def assert_map_matches_table(self, at: AppTest, count: int = 22) -> None:
        args = json.loads(at.get('component_instance')[0].proto.json_args)
        self.assertEqual(args['script'].count('L.marker('), count)
        encoded = re.findall(r'data:text/html;charset=utf-8;base64,([A-Za-z0-9+/=]+)', args['script'])
        popups = [base64.b64decode(x).decode('utf-8') for x in encoded]
        self.assertEqual(len(popups), count)
        row = at.dataframe[0].value.iloc[0]
        selected = [p for p in popups if f'<b>{row.location_name}</b>' in p]
        self.assertEqual(len(selected), 1)
        for popup in popups:
            self.assertEqual(popup.count('Forecast:'), 1)
            self.assertIn(row.start_time.isoformat(), popup)
            self.assertIn(row.end_time.isoformat(), popup)
        self.assertIn('weather-pin', args['script'])
        for field, label in [('min_temperature', 'MinT'), ('max_temperature', 'MaxT')]:
            value = getattr(row, field)
            expected = 'N/A' if pd.isna(value) else f'{value} °C'
            self.assertIn(f'{label}: {expected}', selected[0])

    def test_initial_nationwide_map_and_collapsed_detail(self) -> None:
        self.seed()
        at = self.app()
        self.assertEqual(at.title[0].value, '臺灣天氣地圖')
        self.assertEqual(len(at.selectbox), 2)
        self.assertFalse(at.expander[0].proto.expanded)
        self.assertEqual(len(at.dataframe[0].value), 1)
        self.assert_map_matches_table(at)
        self.assert_chart_matches_table(at)

    def test_location_dropdown_preserves_nationwide_map(self) -> None:
        self.seed()
        at = self.app()
        component_id = at.get('component_instance')[0].proto.id
        at.selectbox(key='location').select('臺中市').run()
        self.assertEqual(component_id, at.get('component_instance')[0].proto.id)
        self.assertFalse(at.exception)
        self.assertEqual(at.metric[0].value, '臺中市')
        self.assertEqual(at.dataframe[0].value.iloc[0].location_name, '臺中市')
        self.assert_map_matches_table(at)
        self.assert_chart_matches_table(at)

    def test_period_change_synchronizes_all_views(self) -> None:
        self.seed()
        at = self.app()
        for period in sorted({(r.start_time.isoformat(), r.end_time.isoformat()) for r in self.rows}):
            at.selectbox(key='interval').select(period).run()
            self.assertFalse(at.exception)
            self.assert_map_matches_table(at)
            self.assert_chart_matches_table(at)

    def test_map_click_updates_selector_summary_and_table(self) -> None:
        self.seed()
        point = load_coordinates()['臺中市']
        event = {'last_object_clicked': {'lat': point['latitude'], 'lng': point['longitude']},
                 'last_object_clicked_count': 1}
        with patch('streamlit_folium.st_folium', return_value=event):
            at = self.app()
            self.assertEqual(at.selectbox(key='location').value, '臺中市')
            self.assertEqual(at.metric[0].value, '臺中市')
            self.assertEqual(at.dataframe[0].value.iloc[0].location_name, '臺中市')
            # A stale click must not override a subsequent dropdown change.
            at.selectbox(key='location').select('臺北市').run()
            self.assertFalse(at.exception)
            self.assertEqual(at.metric[0].value, '臺北市')

    def test_second_click_on_same_marker_is_new_event(self) -> None:
        self.seed()
        point = load_coordinates()['臺中市']
        event = {'last_object_clicked': {'lat': point['latitude'], 'lng': point['longitude']},
                 'last_object_clicked_count': 1}
        with patch('streamlit_folium.st_folium', return_value=event):
            at = self.app()
            at.selectbox(key='location').select('臺北市').run()
            event['last_object_clicked_count'] = 2
            at.run()
            self.assertFalse(at.exception)
            self.assertEqual(at.metric[0].value, '臺中市')

    def test_missing_database(self) -> None:
        with self.assertLogs(level='ERROR'):
            at = self.app()
        self.assertTrue(at.error)
        self.assertFalse(self.database.exists())

    def test_empty_database(self) -> None:
        self.seed([])
        at = self.app()
        self.assertIn('沒有預報資料', at.info[0].value)
        self.assertFalse(at.dataframe)

    def test_corrupt_database(self) -> None:
        self.database.write_bytes(b'not sqlite')
        with self.assertLogs(level='ERROR'):
            at = self.app()
        self.assertTrue(at.error)

    def test_null_temperatures(self) -> None:
        self.seed([replace(self.rows[0], min_temperature=None, max_temperature=None, rain_probability=None)])
        at = self.app()
        self.assertEqual(at.metric[1].value, '—')
        self.assertEqual(at.metric[3].value, '—')
        self.assertFalse(at.get('vega_lite_chart'))
        self.assertTrue(at.dataframe[0].value.min_temperature.isna().all())
        self.assert_map_matches_table(at, 1)

    def test_partial_null_temperature(self) -> None:
        self.seed([replace(self.rows[0], min_temperature=None)])
        at = self.app()
        self.assert_chart_matches_table(at)
        self.assert_map_matches_table(at, 1)

    def test_unknown_location_keeps_detail(self) -> None:
        self.seed([replace(self.rows[0], location_name='Unknown')])
        with self.assertLogs('weather_data.gis', level='WARNING'):
            at = self.app()
        self.assertTrue(at.warning)
        self.assertFalse(at.get('component_instance'))
        self.assertEqual(len(at.dataframe[0].value), 1)

    def test_map_failure_keeps_detail(self) -> None:
        self.seed()
        with patch('weather_data.gis.create_map', side_effect=ValueError('test')), self.assertLogs(level='ERROR'):
            at = self.app()
        self.assertTrue(at.error)
        self.assertEqual(len(at.dataframe[0].value), 1)
        self.assert_chart_matches_table(at)

    def test_period_change_resets_unavailable_location(self) -> None:
        self.seed([replace(self.rows[0], location_name='臺北市'), replace(self.rows[1], location_name='臺中市')])
        at = self.app()
        for r in self.rows[:2]:
            at.selectbox(key='interval').select((r.start_time.isoformat(), r.end_time.isoformat())).run()
            self.assertFalse(at.exception)
            self.assertEqual(len(at.dataframe[0].value), 1)

    def test_empty_filtered_state(self) -> None:
        from weather_data.dashboard import to_dataframe
        self.seed()
        with patch('weather_data.dashboard.filter_forecasts', return_value=to_dataframe([])):
            at = self.app()
        self.assertTrue(at.info)
        self.assertFalse(at.dataframe)
