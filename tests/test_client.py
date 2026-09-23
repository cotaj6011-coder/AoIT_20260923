import io
import socket
import ssl
import unittest
from http.client import IncompleteRead
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from weather_data.client import CwaClient, CwaResponse, _NoRedirect
from weather_data.config import DATASET_ID, MAX_RESPONSE_BYTES, TIMEOUT_SECONDS, CwaConfig
from weather_data.errors import WeatherDataError


class HttpClientTests(unittest.TestCase):
    def setUp(self):
        self.context_patch = patch("weather_data.client.truststore.SSLContext")
        self.context = self.context_patch.start().return_value
        self.addCleanup(self.context_patch.stop)
        self.opener_patch = patch("weather_data.client.request.build_opener")
        self.opener = self.opener_patch.start().return_value
        self.addCleanup(self.opener_patch.stop)
        self.response = self.opener.open.return_value.__enter__.return_value
        self.response.status = 200
        self.response.read.return_value = b'{"synthetic":true}'
        self.secret = "unit-test-secret"
        self.client = CwaClient(CwaConfig(self.secret))

    def check_error(self, exception, code, status=None):
        self.opener.open.side_effect = exception
        with self.assertRaises(WeatherDataError) as caught:
            self.client.fetch()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.http_status, status)
        self.assertNotIn(self.secret, str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def http(self, status):
        self.check_error(HTTPError(f"https://example.invalid/?Authorization={self.secret}", status, self.secret, {}, io.BytesIO()), "HTTP_ERROR", status)

    def test_200_request_and_timeout(self):
        self.assertEqual(self.client.fetch(), CwaResponse(200, b'{"synthetic":true}'))
        req = self.opener.open.call_args.args[0]
        self.assertEqual(urlsplit(req.full_url).path, f"/api/v1/rest/datastore/{DATASET_ID}")
        self.assertEqual(parse_qs(urlsplit(req.full_url).query), {"Authorization": [self.secret], "format": ["JSON"]})
        self.assertEqual(self.opener.open.call_args.kwargs["timeout"], TIMEOUT_SECONDS)
        self.assertEqual(req.get_header("Accept"), "application/json")
        self.response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)

    def test_400(self): self.http(400)
    def test_401(self): self.http(401)
    def test_403(self): self.http(403)
    def test_404(self): self.http(404)
    def test_429(self): self.http(429)
    def test_500(self): self.http(500)
    def test_503(self): self.http(503)
    def test_redirect_error(self): self.http(302)

    def test_timeout(self):
        self.check_error(socket.timeout(self.secret), "TIMEOUT")

    def test_wrapped_timeout(self):
        self.check_error(URLError(TimeoutError(self.secret)), "TIMEOUT")

    def test_connection_error(self):
        self.check_error(URLError(OSError(self.secret)), "CONNECTION_ERROR")

    def test_tls_error(self):
        self.check_error(URLError(ssl.SSLCertVerificationError(self.secret)), "TLS_ERROR")

    def test_direct_tls_error(self):
        self.check_error(ssl.SSLError(self.secret), "TLS_ERROR")

    def test_partial_body_failure(self):
        self.response.read.side_effect = IncompleteRead(b"partial")
        with self.assertRaisesRegex(WeatherDataError, "connection failed"):
            self.client.fetch()

    def test_oversized_body(self):
        self.response.read.return_value = b"x" * (MAX_RESPONSE_BYTES + 1)
        with self.assertRaises(WeatherDataError) as caught:
            self.client.fetch()
        self.assertEqual(caught.exception.code, "RESPONSE_TOO_LARGE")

    def test_non_200_response(self):
        self.response.status = 204
        with self.assertRaises(WeatherDataError) as caught:
            self.client.fetch()
        self.assertEqual(caught.exception.http_status, 204)

    def test_no_redirect_forwarding(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.invalid"))

    def test_explicit_ca_bundle(self):
        CwaClient(CwaConfig(self.secret, "trusted.pem")).fetch()
        self.context.load_verify_locations.assert_called_once_with(cafile="trusted.pem")

    def test_invalid_ca_bundle(self):
        self.context.load_verify_locations.side_effect = OSError(self.secret)
        with self.assertRaises(WeatherDataError) as caught:
            CwaClient(CwaConfig(self.secret, "missing.pem")).fetch()
        self.assertEqual(caught.exception.code, "TLS_CONFIG")
        self.assertNotIn(self.secret, str(caught.exception))

    def test_response_repr_hides_body(self):
        self.assertNotIn(self.secret, repr(CwaResponse(200, self.secret.encode())))
