import copy
import unittest
from datetime import timedelta
from pathlib import Path

from weather_data.errors import WeatherDataError
from weather_data.json_data import decode_json
from weather_data.parser import parse_forecasts, parse_response

FIXTURE = Path(__file__).parent / "fixtures" / "cwa_weather.json"


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.data = decode_json(FIXTURE.read_bytes())
        self.location = self.data["records"]["location"][0]

    def element(self, name):
        return next(e for e in self.location["weatherElement"] if e["elementName"] == name)

    def test_real_fixture_record_count(self):
        forecasts = parse_response(FIXTURE.read_bytes())
        self.assertEqual(len(forecasts), 66)
        self.assertEqual(len({f.location_name for f in forecasts}), 22)

    def test_location_name(self):
        self.assertEqual(parse_forecasts(self.data)[0].location_name, "嘉義縣")

    def test_min_temperature(self):
        self.assertEqual(parse_forecasts(self.data)[0].min_temperature, 25)

    def test_max_temperature(self):
        self.assertEqual(parse_forecasts(self.data)[0].max_temperature, 29)

    def test_rain_probability(self):
        self.assertEqual(parse_forecasts(self.data)[0].rain_probability, 10)

    def test_weather_description(self):
        self.assertEqual(parse_forecasts(self.data)[0].weather_description, "晴時多雲")

    def test_forecast_time_and_date(self):
        forecast = parse_forecasts(self.data)[0]
        self.assertEqual(forecast.start_time.isoformat(), "2026-09-23T18:00:00+08:00")
        self.assertEqual(forecast.end_time.isoformat(), "2026-09-24T06:00:00+08:00")
        self.assertEqual(forecast.forecast_date.isoformat(), "2026-09-23")
        self.assertEqual(forecast.start_time.utcoffset(), timedelta(hours=8))

    def test_no_mutation(self):
        before = copy.deepcopy(self.data)
        parse_forecasts(self.data)
        self.assertEqual(self.data, before)

    def test_empty_locations(self):
        self.data["records"]["location"] = []
        self.assertEqual(parse_forecasts(self.data), [])

    def test_missing_element_is_nullable(self):
        self.location["weatherElement"].remove(self.element("MinT"))
        self.assertIsNone(parse_forecasts(self.data)[0].min_temperature)

    def test_null_temperature(self):
        self.element("MinT")["time"][0]["parameter"]["parameterName"] = None
        self.assertIsNone(parse_forecasts(self.data)[0].min_temperature)

    def test_invalid_numbers(self):
        for value in ("", "not-a-number", "-99", "-999", "-9999", "NaN", "Infinity", True, {}, []):
            with self.subTest(value=value):
                self.element("MinT")["time"][0]["parameter"]["parameterName"] = value
                self.assertIsNone(parse_forecasts(self.data)[0].min_temperature)

    def test_zero_and_negative_values_preserved(self):
        self.element("MinT")["time"][0]["parameter"]["parameterName"] = "-5"
        self.element("PoP")["time"][0]["parameter"]["parameterName"] = "0"
        first = parse_forecasts(self.data)[0]
        self.assertEqual(first.min_temperature, -5)
        self.assertEqual(first.rain_probability, 0)

    def test_probability_range(self):
        for value in ("-1", "101"):
            self.element("PoP")["time"][0]["parameter"]["parameterName"] = value
            self.assertIsNone(parse_forecasts(self.data)[0].rain_probability)

    def test_missing_parameter(self):
        del self.element("MinT")["time"][0]["parameter"]
        self.assertIsNone(parse_forecasts(self.data)[0].min_temperature)

    def test_missing_weather_description(self):
        self.element("Wx")["time"][0]["parameter"]["parameterName"] = ""
        self.assertIsNone(parse_forecasts(self.data)[0].weather_description)

    def test_reordered_elements_and_periods(self):
        expected = parse_forecasts(self.data)
        self.location["weatherElement"].reverse()
        for element in self.location["weatherElement"]:
            element["time"].reverse()
        self.assertEqual(parse_forecasts(self.data), expected)

    def test_missing_period_does_not_shift_values(self):
        self.element("MaxT")["time"].pop(0)
        forecasts = parse_forecasts(self.data)
        self.assertIsNone(forecasts[0].max_temperature)
        self.assertEqual(forecasts[1].max_temperature, 33)

    def test_empty_elements(self):
        self.location["weatherElement"] = []
        self.assertEqual(len(parse_forecasts(self.data)), 63)

    def test_failed_success(self):
        for value in (False, "false", None, 1):
            self.data["success"] = value
            with self.assertRaises(WeatherDataError) as caught:
                parse_forecasts(self.data)
            self.assertEqual(caught.exception.code, "CWA_FAILURE")

    def test_wrong_resource_id(self):
        self.data["result"]["resource_id"] = "wrong"
        with self.assertRaises(WeatherDataError): parse_forecasts(self.data)

    def test_missing_records_or_location(self):
        for data in ({"success": "true"}, {**self.data, "records": {}}, {**self.data, "records": {"location": None}}):
            with self.assertRaises(WeatherDataError): parse_forecasts(data)

    def test_blank_location(self):
        self.location["locationName"] = " "
        with self.assertRaises(WeatherDataError): parse_forecasts(self.data)

    def test_duplicate_location(self):
        self.data["records"]["location"].append(copy.deepcopy(self.location))
        with self.assertRaises(WeatherDataError): parse_forecasts(self.data)

    def test_duplicate_element(self):
        self.location["weatherElement"].append(copy.deepcopy(self.element("MinT")))
        with self.assertRaises(WeatherDataError): parse_forecasts(self.data)

    def test_duplicate_interval(self):
        self.element("MinT")["time"].append(copy.deepcopy(self.element("MinT")["time"][0]))
        with self.assertRaises(WeatherDataError): parse_forecasts(self.data)

    def test_invalid_timestamp(self):
        for value in (None, "2026-09-23", "2026-02-30 00:00:00", "2026-9-23 18:00:00"):
            self.element("MinT")["time"][0]["startTime"] = value
            with self.assertRaises(WeatherDataError): parse_forecasts(self.data)

    def test_reversed_interval(self):
        period = self.element("MinT")["time"][0]
        period["endTime"] = period["startTime"]
        with self.assertRaises(WeatherDataError): parse_forecasts(self.data)

    def test_wrong_temperature_unit(self):
        self.element("MinT")["time"][0]["parameter"]["parameterUnit"] = "F"
        with self.assertRaises(WeatherDataError): parse_forecasts(self.data)

    def test_unexpected_container_type(self):
        self.location["weatherElement"] = {}
        with self.assertRaises(WeatherDataError): parse_forecasts(self.data)
