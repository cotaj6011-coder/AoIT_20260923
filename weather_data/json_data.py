"""Schema-neutral JSON checks and safe capture; no unverified CWA paths."""

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

from .config import DATASET_ID
from .errors import WeatherDataError


def _reject_constant(value: str) -> None:
    raise ValueError("Non-standard JSON numeric constant")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def decode_json(body: bytes) -> dict[str, Any]:
    if not body.strip():
        raise WeatherDataError("EMPTY_RESPONSE", "CWA returned an empty response body.")
    try:
        data = json.loads(
            body.decode("utf-8-sig"), parse_constant=_reject_constant, object_pairs_hook=_unique_object
        )
    except (UnicodeError, ValueError, RecursionError):
        raise WeatherDataError("INVALID_JSON", "CWA response is not valid, unambiguous UTF-8 JSON.") from None
    if not isinstance(data, dict):
        raise WeatherDataError("INVALID_ROOT", "Expected a JSON root object; inspect the captured API contract.")
    if not data:
        raise WeatherDataError("EMPTY_RESPONSE", "CWA returned an empty JSON object.")
    return data


def sanitize(data: Any, api_key: str, *, _depth: int = 0) -> Any:
    """Redact credential-named members and echoed secrets, including in keys."""
    if _depth > 40:
        raise WeatherDataError("JSON_DEPTH", "JSON nesting exceeds the supported inspection depth.")
    sensitive = {"authorization", "apikey", "token", "accesstoken", "refreshtoken", "cookie", "setcookie", "password", "secret"}

    def clean(value: str) -> str:
        for secret in (api_key, quote(api_key, safe=""), quote_plus(api_key)):
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"CWA-[A-Za-z0-9-]+", "[REDACTED]", value, flags=re.IGNORECASE)

    if isinstance(data, dict):
        return {
            clean(key): "[REDACTED]" if re.sub(r"[^a-z]", "", key.lower()) in sensitive else sanitize(value, api_key, _depth=_depth + 1)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [sanitize(value, api_key, _depth=_depth + 1) for value in data]
    return clean(data) if isinstance(data, str) else data


def describe_structure(data: Any, path: str = "$", *, depth: int = 0) -> dict[str, list[str]]:
    """Describe observed paths/types only; never infer forecast field mappings."""
    if depth > 40:
        raise WeatherDataError("JSON_DEPTH", "JSON nesting exceeds the supported inspection depth.")
    kind = "null" if data is None else type(data).__name__
    result = {path: [kind]}
    children = data.items() if isinstance(data, dict) else enumerate(data) if isinstance(data, list) else []
    for key, value in children:
        child_path = f"{path}[{json.dumps(key, ensure_ascii=False)}]" if isinstance(data, dict) else f"{path}[]"
        for entry, kinds in describe_structure(value, child_path, depth=depth + 1).items():
            result[entry] = sorted(set(result.get(entry, []) + kinds))
    return result


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_capture(data: dict, destination: Path, *, api_key: str, status: int, verified: bool = False) -> None:
    """Persist a sanitized live response with explicit provenance and verification."""
    cleaned = sanitize(data, api_key)
    structure = describe_structure(cleaned)
    body = (json.dumps(cleaned, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    metadata = {
        "dataset_id": DATASET_ID,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "http_status": status,
        "source": "live CWA HTTPS response",
        "sanitization": "credential members and echoed API keys redacted; no HTTP headers saved",
        "sha256": hashlib.sha256(body).hexdigest(),
        "forecast_schema_verified": verified,
        "note": "Validated by the forecast parser." if verified else "Unverified response; not a successful forecast fixture.",
    }
    try:
        _write_atomic(destination, body)
        _write_atomic(destination.with_suffix(".metadata.json"), (json.dumps(metadata, indent=2) + "\n").encode())
        _write_atomic(destination.with_suffix(".structure.json"), (json.dumps(structure, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except OSError:
        raise WeatherDataError("CAPTURE_IO", "Cannot save capture files. Check output directory permissions.") from None
