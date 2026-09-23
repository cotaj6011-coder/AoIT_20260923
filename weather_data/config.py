"""Single source of request settings; no API credentials in source or repr."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .errors import WeatherDataError

BASE_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
DATASET_ID = "F-C0032-001"
TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


def read_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=value settings without executing or expanding content."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeError):
        raise WeatherDataError("CONFIG_FILE", "Cannot read the specified UTF-8 env file.") from None
    values = {}
    for number, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise WeatherDataError("CONFIG_FILE", f"Expected KEY=value on env file line {number}.")
        name, value = (part.strip() for part in line.split("=", 1))
        if name not in {"CWA_API_KEY", "SSL_CERT_FILE"}:
            continue
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise WeatherDataError("CONFIG_FILE", f"Unclosed quote on env file line {number}.")
            value = value[1:-1]
        values[name] = value
    return values


@dataclass(frozen=True)
class CwaConfig:
    api_key: str = field(repr=False)
    ca_file: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise WeatherDataError(
                "MISSING_API_KEY",
                "CWA_API_KEY is missing. Set the environment variable or use --env-file .env.local.",
            )
        object.__setattr__(self, "api_key", self.api_key.strip())

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None, *, env_file: Path | None = None
    ) -> "CwaConfig":
        values = read_env_file(env_file) if env_file is not None else {}
        # An explicitly empty environment variable must not silently fall back.
        values.update(os.environ if environ is None else environ)
        return cls(values.get("CWA_API_KEY", ""), values.get("SSL_CERT_FILE") or None)
