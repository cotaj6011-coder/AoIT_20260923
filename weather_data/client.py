"""Bounded HTTPS acquisition of the documented CWA datastore endpoint."""

import socket
import ssl
from http.client import HTTPException
from dataclasses import dataclass, field
from urllib import error, parse, request

import truststore

from .config import BASE_URL, DATASET_ID, MAX_RESPONSE_BYTES, TIMEOUT_SECONDS, CwaConfig
from .errors import WeatherDataError


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Authorization is a documented query parameter. Never forward it.
        return None


@dataclass(frozen=True)
class CwaResponse:
    status: int
    body: bytes = field(repr=False)


def _http_error(status: int) -> WeatherDataError:
    messages = {
        400: "CWA rejected the request parameters (HTTP 400).",
        401: "CWA authentication failed (HTTP 401). Check CWA_API_KEY.",
        403: "CWA access denied (HTTP 403). Check API key permissions.",
        404: "CWA dataset endpoint was not found (HTTP 404).",
        429: "CWA rate limit reached (HTTP 429). Wait before retrying.",
    }
    message = messages.get(status)
    if message is None:
        message = (
            f"CWA service failed (HTTP {status}). Retry later."
            if 500 <= status <= 599
            else f"Unexpected CWA HTTP status {status}; redirects are not followed."
        )
    return WeatherDataError("HTTP_ERROR", message, http_status=status)


class CwaClient:
    def __init__(self, config: CwaConfig):
        self._config = config

    def fetch(self) -> CwaResponse:
        try:
            context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            if self._config.ca_file:
                context.load_verify_locations(cafile=self._config.ca_file)
        except (OSError, ssl.SSLError):
            raise WeatherDataError(
                "TLS_CONFIG", "Cannot load TLS trust. Check SSL_CERT_FILE and its trusted PEM certificates."
            ) from None
        # No logging of this URL, Request, HTTPError or underlying exception.
        url = f"{BASE_URL}/{DATASET_ID}?" + parse.urlencode(
            {"Authorization": self._config.api_key, "format": "JSON"}
        )
        req = request.Request(url, headers={"Accept": "application/json"})
        opener = request.build_opener(_NoRedirect(), request.HTTPSHandler(context=context))
        try:
            with opener.open(req, timeout=TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    raise _http_error(response.status)
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise WeatherDataError("RESPONSE_TOO_LARGE", "CWA response exceeds the 5 MiB limit.")
                return CwaResponse(response.status, body)
        except error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise _http_error(status) from None
        except (TimeoutError, socket.timeout):
            raise WeatherDataError("TIMEOUT", "CWA request timed out after a 15-second socket timeout.") from None
        except ssl.SSLError:
            raise WeatherDataError(
                "TLS_ERROR", "CWA TLS verification failed. Configure a trusted SSL_CERT_FILE; do not disable verification."
            ) from None
        except error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise WeatherDataError("TIMEOUT", "CWA request timed out after a 15-second socket timeout.") from None
            if isinstance(exc.reason, ssl.SSLError):
                raise WeatherDataError(
                    "TLS_ERROR", "CWA TLS verification failed. Configure a trusted SSL_CERT_FILE; do not disable verification."
                ) from None
            raise WeatherDataError(
                "CONNECTION_ERROR", "Cannot connect to CWA. Check DNS, network and proxy settings."
            ) from None
        except (OSError, HTTPException):
            raise WeatherDataError("CONNECTION_ERROR", "CWA connection failed while receiving data.") from None
