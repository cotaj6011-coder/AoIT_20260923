"""All production SQL is static; all data values are bound parameters."""

BEGIN = "BEGIN"

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS weather_forecasts (
    id INTEGER PRIMARY KEY,
    location_name TEXT NOT NULL CHECK(length(trim(location_name)) > 0),
    start_time TEXT NOT NULL CHECK(
        length(start_time) = 32 AND substr(start_time, 27) = '+08:00'
        AND julianday(start_time) IS NOT NULL),
    end_time TEXT NOT NULL CHECK(
        length(end_time) = 32 AND substr(end_time, 27) = '+08:00'
        AND julianday(end_time) IS NOT NULL),
    min_temperature REAL CHECK(min_temperature IS NULL OR
        (typeof(min_temperature) IN ('real', 'integer') AND min_temperature BETWEEN -90 AND 60)),
    max_temperature REAL CHECK(max_temperature IS NULL OR
        (typeof(max_temperature) IN ('real', 'integer') AND max_temperature BETWEEN -90 AND 60)),
    rain_probability REAL CHECK(rain_probability IS NULL OR
        (typeof(rain_probability) IN ('real', 'integer') AND rain_probability BETWEEN 0 AND 100)),
    weather_description TEXT,
    created_at TEXT NOT NULL CHECK(julianday(created_at) IS NOT NULL),
    updated_at TEXT NOT NULL CHECK(julianday(updated_at) IS NOT NULL),
    UNIQUE(location_name, start_time, end_time),
    CHECK(start_time < end_time),
    CHECK(min_temperature IS NULL OR max_temperature IS NULL OR min_temperature <= max_temperature)
)
"""

CREATE_TIME_INDEX = """
CREATE INDEX IF NOT EXISTS weather_forecasts_time ON weather_forecasts(start_time, end_time)
"""

UPSERT = """
INSERT INTO weather_forecasts (
    location_name, start_time, end_time, min_temperature, max_temperature,
    rain_probability, weather_description, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(location_name, start_time, end_time) DO UPDATE SET
    min_temperature = excluded.min_temperature,
    max_temperature = excluded.max_temperature,
    rain_probability = excluded.rain_probability,
    weather_description = excluded.weather_description,
    updated_at = excluded.updated_at
"""

GET_ALL = """
SELECT * FROM weather_forecasts ORDER BY location_name, start_time, end_time
"""
GET_BY_LOCATION = """
SELECT * FROM weather_forecasts WHERE location_name = ?
ORDER BY location_name, start_time, end_time
"""
GET_BY_TIME_RANGE = """
SELECT * FROM weather_forecasts WHERE start_time < ? AND end_time > ?
ORDER BY location_name, start_time, end_time
"""
GET_BY_KEY = """
SELECT * FROM weather_forecasts WHERE location_name = ? AND start_time = ? AND end_time = ?
ORDER BY location_name, start_time, end_time
"""
GET_LOCATIONS = "SELECT DISTINCT location_name FROM weather_forecasts ORDER BY location_name"
COUNT = "SELECT COUNT(*) FROM weather_forecasts"
LAST_UPDATED = "SELECT MAX(updated_at) FROM weather_forecasts"
COUNT_DUPLICATES = """
SELECT COUNT(*) FROM (
    SELECT location_name, start_time, end_time FROM weather_forecasts
    GROUP BY location_name, start_time, end_time HAVING COUNT(*) > 1
)
"""
INTEGRITY_CHECK = "PRAGMA integrity_check"
