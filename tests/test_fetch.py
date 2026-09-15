"""Contract tests using local HTTP servers; no internet or extra dependencies."""

from __future__ import annotations

import gzip
import http.client
import json
import logging
import ssl
import threading
import time
import unittest
import urllib.error
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import fetch


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def handle_request(self):
        parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parts.query)
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        status = 200
        headers = [("Content-Type", "application/json")]
        content = json.dumps(
            {
                "method": self.command,
                "path": self.path,
                "body": body.decode("utf-8"),
                "headers": {name.lower(): value for name, value in self.headers.items()},
            }
        ).encode()
        if parts.path.startswith("/redirect/"):
            status = int(parts.path.rsplit("/", 1)[1])
            headers.append(("Location", query.get("to", ["/echo"])[0]))
            content = b"redirect"
        elif parts.path == "/loop":
            status = 302
            headers.append(("Location", "/loop"))
            content = b"redirect"
        elif parts.path.startswith("/status/"):
            status = int(parts.path.rsplit("/", 1)[1])
            content = b"" if status == 204 else b'{"error":"missing"}'
        elif parts.path == "/gzip":
            content = gzip.compress(b'{"greeting":"hello"}')
            headers.append(("Content-Encoding", "gzip"))
        elif parts.path == "/bad-gzip":
            content = b"this is not gzip"
            headers.append(("Content-Encoding", "gzip"))
        elif parts.path == "/latin1":
            content = "caf\u00e9".encode("latin-1")
            headers = [("Content-Type", "text/plain; charset=iso-8859-1")]
        elif parts.path == "/headers":
            headers.extend([("X-Mixed-Case", "yes"), ("Set-Cookie", "a=1"), ("Set-Cookie", "b=2")])
        elif parts.path == "/slow-headers":
            time.sleep(0.2)

        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header(
            "Content-Length", str(len(content) + (10 if parts.path == "/truncated" else 0))
        )
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if parts.path == "/slow-body":
            self.wfile.flush()
            time.sleep(0.2)
        if self.command != "HEAD":
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = handle_request


class Records(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@contextmanager
def capture_logs():
    logger = logging.getLogger("fetch")
    handler = Records()
    old_level, old_propagate, old_disabled = logger.level, logger.propagate, logger.disabled
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.disabled = False
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = old_propagate
        logger.disabled = old_disabled


class FetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
        cls.threads = []
        for server in cls.servers:
            thread = threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
            )
            thread.start()
            cls.threads.append(thread)
        cls.base, cls.other = [f"http://127.0.0.1:{server.server_port}" for server in cls.servers]

    @classmethod
    def tearDownClass(cls):
        for server, thread in zip(cls.servers, cls.threads):
            server.shutdown()
            server.server_close()
            thread.join()

    def redirect(self, status, target="/echo"):
        return f"{self.base}/redirect/{status}?{urllib.parse.urlencode({'to': target})}"

    def assert_events(self, records, events):
        self.assertEqual([record.fetch_event for record in records], events)
        elapsed = []
        for record in records:
            self.assertEqual(record.levelno, logging.DEBUG)
            self.assertEqual(record.name, "fetch")
            self.assertIn(record.fetch_method, {"GET", "POST", "HEAD"})
            self.assertEqual(record.fetch_host, "127.0.0.1")
            self.assertIsInstance(record.fetch_redirects, int)
            self.assertGreaterEqual(record.fetch_redirects, 0)
            self.assertGreaterEqual(record.fetch_elapsed, 0)
            self.assertGreater(record.fetch_timeout, 0)
            self.assertTrue(record.fetch_status is None or isinstance(record.fetch_status, int))
            self.assertTrue(record.fetch_error is None or isinstance(record.fetch_error, str))
            self.assertIsNone(record.exc_info)
            self.assertIsNone(record.stack_info)
            elapsed.append(record.fetch_elapsed)
        self.assertEqual(elapsed, sorted(elapsed))
        self.assertEqual(records[0].fetch_elapsed, 0.0)
        self.assertEqual(records[0].fetch_redirects, 0)
        self.assertIsNone(records[0].fetch_status)
        self.assertIsNone(records[0].fetch_error)

    def test_get_response_and_helpers(self):
        response = fetch.get(self.base)
        self.assertEqual(response.status, 200)
        self.assertEqual(response.reason, "OK")
        self.assertEqual(response.url, self.base + "/")
        self.assertTrue(response.ok)
        self.assertEqual(repr(response), "<Response [200]>")
        self.assertIs(response.raise_for_status(), response)
        self.assertEqual(json.loads(response.text), response.json())
        for method in ("get", "post", "put", "patch", "delete", "options"):
            with self.subTest(method=method):
                self.assertEqual(getattr(fetch, method)(self.base).json()["method"], method.upper())

    def test_json_body_including_null(self):
        for value in ({"hello": "caf\u00e9"}, [1, True, None], None):
            with self.subTest(value=value):
                data = fetch.post(self.base, json=value).json()
                self.assertEqual(json.loads(data["body"]), value)
                self.assertEqual(data["headers"]["content-type"], "application/json")
                self.assertEqual(int(data["headers"]["content-length"]), len(data["body"].encode()))

    def test_text_bytes_and_form_bodies(self):
        for value, expected, content_type in (
            ("caf\u00e9", "caf\u00e9", "text/plain; charset=utf-8"),
            (b"binary", "binary", "application/octet-stream"),
            (
                {"q": "caf\u00e9", "tag": ["a", "b"]},
                "q=caf%C3%A9&tag=a&tag=b",
                "application/x-www-form-urlencoded",
            ),
        ):
            with self.subTest(value=value):
                data = fetch.post(self.base, data=value).json()
                self.assertEqual(data["body"], expected)
                self.assertEqual(data["headers"]["content-type"], content_type)
        custom = fetch.post(self.base, data=b"x", headers={"Content-Type": "custom/type"}).json()
        self.assertEqual(custom["headers"]["content-type"], "custom/type")

    def test_unicode_urls_and_query_parameters(self):
        response = fetch.get(
            self.base + "/caf\u00e9?existing=yes#discard",
            params=[("q", "hello world"), ("tag", ["a", "b"])],
        )
        path = response.json()["path"]
        self.assertEqual(urllib.parse.urlsplit(path).path, "/caf%C3%A9")
        self.assertEqual(
            urllib.parse.parse_qs(urllib.parse.urlsplit(path).query),
            {"existing": ["yes"], "q": ["hello world"], "tag": ["a", "b"]},
        )
        self.assertNotIn("#", response.url)

    def test_case_insensitive_and_repeated_headers(self):
        headers = fetch.get(self.base + "/headers").headers
        self.assertEqual(headers["x-mixed-case"], "yes")
        self.assertEqual(headers["X-MIXED-CASE"], "yes")
        self.assertEqual(headers.get_all("SET-cookie"), ["a=1", "b=2"])
        self.assertEqual(headers.get_all("missing"), [])
        self.assertEqual(headers["set-cookie"], "a=1")
        self.assertEqual(len(headers), len({name.lower() for name in headers}))
        with self.assertRaises(KeyError):
            _ = headers["missing"]
        with self.assertRaises(TypeError):
            headers["new"] = "value"

    def test_status_errors_and_opt_out(self):
        for status in (404, 503):
            with self.subTest(status=status):
                with self.assertRaises(fetch.HTTPError) as caught:
                    fetch.get(f"{self.base}/status/{status}")
                self.assertEqual(caught.exception.response.status, status)
                self.assertEqual(caught.exception.response.json(), {"error": "missing"})
                response = fetch.get(f"{self.base}/status/{status}", check_status=False)
                self.assertFalse(response.ok)
                with self.assertRaises(fetch.HTTPError) as checked:
                    response.raise_for_status()
                self.assertIs(checked.exception.response, response)

    def test_gzip_charset_and_empty_responses(self):
        self.assertEqual(fetch.get(self.base + "/gzip").json(), {"greeting": "hello"})
        self.assertEqual(fetch.get(self.base + "/latin1").text, "caf\u00e9")
        response = fetch.get(self.base + "/status/204")
        self.assertEqual(response.content, b"")
        self.assertTrue(response.ok)
        with self.assertRaises(fetch.DecodeError):
            response.json()
        for path in ("/gzip", "/bad-gzip"):
            with self.subTest(path=path):
                self.assertEqual(fetch.head(self.base + path).content, b"")

    def test_decode_errors_keep_original_cause(self):
        with self.assertRaises(fetch.DecodeError) as caught:
            fetch.get(self.base + "/bad-gzip")
        self.assertIsNotNone(caught.exception.__cause__)
        for content, headers, operation in (
            (b"not json", [], "json"),
            (b"\xff", [], "text"),
            (b"hello", [("Content-Type", "text/plain; charset=not-an-encoding")], "text"),
        ):
            with self.subTest(operation=operation, content=content):
                response = fetch.Response(200, fetch.Headers(headers), content, self.base)
                with self.assertRaises(fetch.DecodeError) as caught:
                    response.json() if operation == "json" else response.text
                self.assertIsNotNone(caught.exception.__cause__)

    def test_redirect_method_and_body_rules(self):
        for status, method, expected in (
            (301, "POST", "GET"),
            (302, "POST", "GET"),
            (303, "PUT", "GET"),
            (301, "PUT", "PUT"),
            (302, "PATCH", "PATCH"),
            (307, "POST", "POST"),
            (308, "POST", "POST"),
        ):
            with self.subTest(status=status, method=method):
                response = fetch.request(method, self.redirect(status), data="payload")
                data = response.json()
                self.assertEqual(response.url, self.base + "/echo")
                self.assertEqual(data["method"], expected)
                self.assertEqual(data["body"], "" if expected == "GET" else "payload")
                if expected == "GET":
                    self.assertNotIn("content-type", data["headers"])
        response = fetch.head(self.redirect(303))
        self.assertEqual(response.status, 200)
        self.assertEqual(response.content, b"")

    def test_redirect_credentials_stay_on_origin(self):
        headers = {
            "Authorization": "Bearer private",
            "Cookie": "session=private",
            "Proxy-Authorization": "private",
        }
        same = fetch.get(self.redirect(302), headers=headers).json()["headers"]
        changed = fetch.get(self.redirect(302, self.other + "/echo"), headers=headers).json()[
            "headers"
        ]
        for name, value in headers.items():
            self.assertEqual(same[name.lower()], value)
            self.assertNotIn(name.lower(), changed)

    def test_redirect_opt_out_limit_and_unsafe_destinations(self):
        response = fetch.get(self.redirect(302), follow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertFalse(response.ok)
        self.assertEqual(response.content, b"redirect")
        for target in (
            "/redirect/302?to=/redirect/302",
            "file:///etc/passwd",
            "http://user:pass@example.test/",
        ):
            with self.subTest(target=target):
                with self.assertRaises(fetch.RedirectError) as caught:
                    fetch.get(self.redirect(302, target), max_redirects=1)
                self.assertEqual(caught.exception.response.status, 302)
        with self.assertRaises(fetch.RedirectError):
            fetch.get(self.redirect(302), max_redirects=0)

    def test_https_downgrade_is_refused(self):
        raw = MagicMock()
        raw.__enter__.return_value = raw
        raw.headers = Message()
        raw.headers["Location"] = self.base
        raw.status, raw.reason = 302, "Found"
        raw.read.return_value = b""
        opener = MagicMock()
        opener.open.return_value = raw
        with (
            patch("fetch.urllib.request.build_opener", return_value=opener),
            self.assertRaises(fetch.RedirectError) as caught,
        ):
            fetch.get("https://example.test/secret")
        self.assertEqual(caught.exception.response.status, 302)
        opener.open.assert_called_once()

    def test_timeouts_while_opening_and_reading_body(self):
        for path in ("/slow-headers", "/slow-body"):
            with self.subTest(path=path):
                with self.assertRaises(fetch.Timeout) as caught:
                    fetch.get(self.base + path, timeout=0.03)
                self.assertIsInstance(caught.exception, fetch.RequestError)
                self.assertIsNotNone(caught.exception.__cause__)

    def test_truncated_body_is_a_request_error(self):
        with self.assertRaises(fetch.RequestError) as caught:
            fetch.get(self.base + "/truncated")
        self.assertIsInstance(caught.exception.__cause__, http.client.IncompleteRead)

    def test_tls_failure_is_a_request_error(self):
        error = urllib.error.URLError(ssl.SSLCertVerificationError("certificate rejected"))
        opener = MagicMock()
        opener.open.side_effect = error
        with (
            patch("fetch.urllib.request.build_opener", return_value=opener),
            self.assertRaises(fetch.RequestError) as caught,
        ):
            fetch.get("https://example.test/")
        self.assertIs(caught.exception.__cause__, error)
        opener.open.assert_called_once()

    def test_parse_calls_decoder_once_and_preserves_result(self):
        @dataclass
        class User:
            id: int

        response = fetch.Response(200, fetch.Headers(), b'{"id":42}', self.base)
        calls = []

        def decode(body: bytes) -> User:
            calls.append(body)
            return User(**json.loads(body))

        result = response.parse(decode)
        self.assertIsInstance(result, User)
        self.assertEqual(result.id, 42)
        self.assertEqual(calls, [response.content])
        self.assertIsNot(response.parse(decode), result)
        self.assertEqual(calls, [response.content, response.content])
        sentinel = object()
        self.assertIs(response.parse(lambda body: sentinel), sentinel)

    def test_parse_preserves_exception_identity_and_does_not_check_status(self):
        response = fetch.Response(404, fetch.Headers(), b"", self.base)
        self.assertEqual(response.parse(bytes), b"")
        failure = ValueError("validator's own error")

        def fail(body):
            raise failure

        with self.assertRaises(ValueError) as caught:
            response.parse(fail)
        self.assertIs(caught.exception, failure)

    def test_logging_success_and_no_records_from_response_operations(self):
        with capture_logs() as records:
            response = fetch.get(self.base, timeout=3)
            response.json()
            _ = response.text
            response.parse(json.loads)
            response.raise_for_status()
        self.assert_events(records, ["request.started", "request.completed"])
        self.assertEqual(records[-1].fetch_status, 200)
        self.assertIsNone(records[-1].fetch_error)
        self.assertEqual([record.fetch_timeout for record in records], [3, 3])

    def test_logging_redirect_describes_previous_hop(self):
        with capture_logs() as records:
            fetch.post(self.redirect(303), data="body")
        self.assert_events(records, ["request.started", "request.redirect", "request.completed"])
        self.assertEqual([record.fetch_method for record in records], ["POST", "POST", "GET"])
        self.assertEqual([record.fetch_status for record in records], [None, 303, 200])
        self.assertEqual([record.fetch_redirects for record in records], [0, 0, 1])

    def test_redirect_loop_logs_only_redirects_actually_followed(self):
        with capture_logs() as records, self.assertRaises(fetch.RedirectError):
            fetch.get(self.base + "/loop", max_redirects=2)
        self.assert_events(
            records, ["request.started", "request.redirect", "request.redirect", "request.failed"]
        )
        self.assertEqual([record.fetch_redirects for record in records], [0, 0, 1, 2])
        self.assertEqual(records[-1].fetch_status, 302)
        self.assertEqual(records[-1].fetch_error, "RedirectError")

    def test_response_decoder_failures_do_not_log_again(self):
        def fail(body):
            raise ValueError("decoder failure")

        with capture_logs() as records:
            response = fetch.get(self.base + "/status/204")
            with self.assertRaises(fetch.DecodeError):
                response.json()
            with self.assertRaises(ValueError):
                response.parse(fail)
        self.assert_events(records, ["request.started", "request.completed"])
        self.assertEqual(records[-1].fetch_status, 204)

    def test_logging_failures_keep_status_when_headers_arrived(self):
        for path, error, status, options in (
            ("/status/404", fetch.HTTPError, 404, {}),
            ("/bad-gzip", fetch.DecodeError, 200, {}),
            ("/slow-headers", fetch.Timeout, None, {"timeout": 0.03}),
            ("/slow-body", fetch.Timeout, 200, {"timeout": 0.03}),
            ("/truncated", fetch.RequestError, 200, {}),
            ("/redirect/302", fetch.RedirectError, 302, {"max_redirects": 0}),
        ):
            with self.subTest(path=path), capture_logs() as records:
                with self.assertRaises(error):
                    fetch.get(self.base + path, **options)
                self.assert_events(records, ["request.started", "request.failed"])
                self.assertEqual(records[-1].fetch_status, status)
                self.assertEqual(records[-1].fetch_error, error.__name__)

    def test_logging_opt_out_means_completed_and_later_errors_are_silent(self):
        with capture_logs() as records:
            response = fetch.get(self.base + "/status/404", check_status=False)
            with self.assertRaises(fetch.HTTPError):
                response.raise_for_status()
        self.assert_events(records, ["request.started", "request.completed"])
        self.assertEqual(records[-1].fetch_status, 404)
        self.assertIsNone(records[-1].fetch_error)
        with capture_logs() as records:
            fetch.get(self.redirect(302), follow_redirects=False)
        self.assert_events(records, ["request.started", "request.completed"])
        self.assertEqual(records[-1].fetch_status, 302)

    def test_logging_does_not_contain_secrets_or_full_urls(self):
        secret = "private-value-do-not-log"
        url = self.base + "/secret-path?token=" + secret
        with capture_logs() as records:
            fetch.post(
                url, data=secret, headers={"Authorization": "Bearer " + secret, "Cookie": secret}
            )
            with self.assertRaises(fetch.HTTPError):
                fetch.get(self.base + "/status/404?token=" + secret)
            fetch.get(self.redirect(302, "/secret-location?token=" + secret))
        self.assertTrue(records)
        for record in records:
            serialized = repr(vars(record)) + record.getMessage()
            for forbidden in (secret, "/secret-path", "/secret-location", self.base, "/status/404"):
                self.assertNotIn(forbidden, serialized)
            self.assertIsNone(record.exc_info)

    def test_invalid_inputs_fail_before_request_logs(self):
        cases = [
            (("GET", "relative/path"), {}),
            (("GET", "http://example.test%0a/"), {}),
            (("GET", "http://example.test%20/"), {}),
            (("GET", "http://example.test%5c/"), {}),
            (("GET", "http://example.test%2f/"), {}),
            (("GET", "http://example.test%3a80/"), {}),
            (("GET", "http://user:password@example.test/"), {}),
            (("GET", self.base + "/\n"), {}),
            (("BAD METHOD", self.base), {}),
            (("GET", self.base), {"timeout": 0}),
            (("GET", self.base), {"timeout": float("inf")}),
            (("GET", self.base), {"timeout": float("nan")}),
            (("GET", self.base), {"timeout": True}),
            (("GET", self.base), {"max_redirects": -1}),
            (("GET", self.base), {"max_redirects": True}),
            (("POST", self.base), {"json": {}, "data": "x"}),
            (("POST", self.base), {"json": {"bad": object()}}),
            (("POST", self.base), {"json": float("nan")}),
            (("POST", self.base), {"data": ["unsupported"]}),
            (("GET", self.base), {"headers": {"Invalid Header": "x"}}),
            (("GET", self.base), {"headers": {"X-Test": "\r\ninjected"}}),
            (("GET", self.base), {"headers": {"Content-Length": "99"}}),
            (("GET", self.base), {"headers": {"Transfer-Encoding": "chunked"}}),
        ]
        for args, kwargs in cases:
            with self.subTest(args=args, kwargs=kwargs), capture_logs() as records:
                with self.assertRaises((ValueError, TypeError)):
                    fetch.request(*args, **kwargs)
                self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
