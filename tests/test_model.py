import unittest
from datetime import datetime, timedelta, timezone

from weather_data.errors import WeatherDataError
from weather_data.model import WeatherForecast, optional_number


class ModelTests(unittest.TestCase):
    def forecast(self, **changes):
        start = datetime(2026, 9, 23, 18, tzinfo=timezone(timedelta(hours=8)))
        values = dict(location_name=" Test ", start_time=start, end_time=start + timedelta(hours=12), min_temperature=20, max_temperature=25, rain_probability=0, weather_description=" Clear ")
        values.update(changes)
        return WeatherForecast(**values)

    def test_normalization(self):
        forecast = self.forecast()
        self.assertEqual(forecast.location_name, "Test")
        self.assertEqual(forecast.weather_description, "Clear")
        self.assertEqual(forecast.rain_probability, 0)

    def test_null_and_invalid_numbers(self):
        for value in (None, "", "--", "-99", "-999", "nan", "inf", {}, [], True, 10**1000):
            self.assertIsNone(optional_number(value, minimum=-90, maximum=60))

    def test_naive_time_rejected(self):
        with self.assertRaises(WeatherDataError): self.forecast(start_time=datetime(2026, 9, 23))

    def test_bad_location_rejected(self):
        with self.assertRaises(WeatherDataError): self.forecast(location_name="")

    def test_min_greater_than_max_rejected(self):
        with self.assertRaises(WeatherDataError): self.forecast(min_temperature=30, max_temperature=20)

    def test_description_type_rejected(self):
        with self.assertRaises(WeatherDataError): self.forecast(weather_description=123)
