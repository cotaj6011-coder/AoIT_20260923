"""Safe application errors: never retain request URLs or response bodies."""


class WeatherDataError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
