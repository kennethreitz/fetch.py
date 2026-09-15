"""Streaming uses bounded reads and explicit ownership, tested on real sockets."""

import gzip
import json
import logging
import threading
import tracemalloc
import unittest
import urllib.parse
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import fetch

LARGE_SIZE = 8_000_000
LARGE_GZIP = gzip.compress(b"a" * LARGE_SIZE)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def handle(self):
        try:
            super().handle()
        except ConnectionResetError:
            # Early exits deliberately close sockets with unread response data.
            pass

    def setup(self):
        super().setup()
        self.server.accepted += 1
        self.connection_id = self.server.accepted
        self.finished = threading.Event()
        self.server.finished[self.connection_id] = self.finished

    def finish(self):
        try:
            super().finish()
        finally:
            self.finished.set()

    def log_message(self, *args):
        pass

    def respond(self):
        path = urllib.parse.urlsplit(self.path).path
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        content = json.dumps(
            {
                "connection": self.connection_id,
                "method": self.command,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": body.decode(),
                "path": self.path,
            }
        ).encode()
        gated = path in {"/gated", "/gated-gzip", "/redirect", "/error"}
        if gated or path == "/bytes":
            content = b"abcdef"
        split = 3
        compressed = "gzip" in path
        if path == "/gated-gzip":
            compressor = zlib.compressobj(wbits=31)
            first = compressor.compress(b"abc") + compressor.flush(zlib.Z_SYNC_FLUSH)
            content = first + compressor.compress(b"def") + compressor.flush()
            split = len(first)
        elif path == "/large-gzip":
            content = LARGE_GZIP
        elif compressed:
            content = gzip.compress(b"hello") + gzip.compress(b"world") + b"\0\0"
            if path == "/truncated-gzip":
                content = content[:-6]
            elif path == "/bad-gzip":
                content = b"invalid gzip"
            elif path == "/crc-gzip":
                content = gzip.compress(b"hello")[:-8] + b"\0" * 8
        status = 302 if path == "/redirect" else 404 if path == "/error" else 200
        if path == "/empty-gzip":
            content = b""
        if path in {"/204-gzip", "/304-gzip"}:
            status, content = int(path[1:4]), b""
        self.send_response(status)
        self.send_header("X-Connection", self.connection_id)
        if status == 302:
            self.send_header("Location", query.get("to", ["/"])[0])
            self.send_header("Set-Cookie", "visited=yes; Path=/")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        chunked = path in {"/chunked", "/bad-chunk"}
        self.send_header("Transfer-Encoding", "chunked") if chunked else self.send_header(
            "Content-Length", len(content) + (10 if path == "/truncated" else 0)
        )
        if path in {"/truncated", "/bad-chunk"}:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            if gated:
                self.wfile.write(content[:split])
                self.wfile.flush()
                self.server.first.set()
                if not self.server.release.wait(5):
                    return
                self.wfile.write(content[split:])
            elif chunked:
                self.wfile.write(
                    b"3\r\nabc\r\n3\r\ndef\r\n0\r\nX-Trailer: yes\r\n\r\n"
                    if path == "/chunked"
                    else b"5\r\nab"
                )
            else:
                self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = do_POST = do_HEAD = respond


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.accepted = 0
        self.server.finished = {}
        self.server.first = threading.Event()
        self.server.release = threading.Event()
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_no_request_until_context_entry(self):
        with patch("socket.create_connection", side_effect=AssertionError("early network")):
            context = fetch.stream("GET", self.url)
        self.assertEqual(self.server.accepted, 0)
        with context as response:
            self.assertIsInstance(response, fetch.StreamResponse)
            self.assertEqual(response.status, 200)
            self.assertTrue(response.ok)
            self.assertEqual(response.url, self.url + "/")
            self.assertEqual(response.reason, "OK")
            self.assertEqual(repr(response), "<StreamResponse [200]>")
        self.assertTrue(response.closed)
        self.assertFalse(response.consumed)

    def test_first_bytes_arrive_before_remaining_body(self):
        for path in ("/gated", "/gated-gzip"):
            with self.subTest(path=path):
                self.server.release.clear()
                with fetch.stream("GET", self.url + path, timeout=0.2) as response:
                    chunks = response.iter_bytes()
                    self.assertEqual(next(chunks), b"abc")
                    self.assertFalse(self.server.release.is_set())
                    self.server.release.set()
                    self.assertEqual(b"".join(chunks), b"def")
                    self.assertTrue(response.consumed)

    def test_exhaustion_reuses_connection(self):
        with fetch.Session() as session:
            with session.stream("GET", self.url + "/bytes") as response:
                self.assertEqual(b"".join(response.iter_bytes(2)), b"abcdef")
                self.assertTrue(response.closed)
                self.assertTrue(response.consumed)
            self.assertEqual(session.get(self.url).json()["connection"], 1)
            self.assertEqual(self.server.accepted, 1)

    def test_early_exit_discards_connection_without_draining(self):
        with fetch.Session() as session:
            with session.stream("GET", self.url + "/gated", timeout=0.1) as response:
                self.assertEqual(next(response.iter_bytes()), b"abc")
            self.assertTrue(response.closed)
            self.assertFalse(response.consumed)
            self.assertFalse(self.server.release.is_set())
            self.assertEqual(session.get(self.url).json()["connection"], 2)

    def test_partial_close_preserves_other_cached_origins(self):
        # Different authorities give the session two distinct cache entries.
        other = self.url.replace("127.0.0.1", "localhost")
        with fetch.Session() as session:
            first = session.get(other).json()["connection"]
            with session.stream("GET", self.url + "/gated"):
                pass
            self.assertEqual(session.get(other).json()["connection"], first)

    def test_buffer_explicitly_and_parse_after_close(self):
        with fetch.stream("GET", self.url) as stream:
            response = stream.read()
            self.assertIs(stream.read(), response)
        self.assertIsInstance(response, fetch.Response)
        self.assertEqual(response.json()["method"], "GET")
        self.assertEqual(response.parse(json.loads), response.json())
        self.assertIs(stream.read(), response)
        with self.assertRaises(RuntimeError):
            stream.iter_bytes()

    def test_application_error_preserves_other_cached_connections(self):
        other = self.url.replace("127.0.0.1", "localhost")
        with fetch.Session() as session:
            first = session.get(other).json()["connection"]
            with self.assertRaises(OSError), session.stream("GET", self.url + "/bytes"):
                raise OSError("output file failed")
            self.assertEqual(session.get(other).json()["connection"], first)

    def test_logging_keeps_body_failure_when_caller_also_raises(self):
        error = OSError("output cleanup failed")
        with self.assertLogs("fetch", logging.DEBUG) as logs:
            with (
                self.assertRaises(OSError) as caught,
                fetch.stream("GET", self.url + "/bad-gzip") as response,
            ):
                with self.assertRaises(fetch.DecodeError):
                    response.read()
                raise error
        self.assertIs(caught.exception, error)
        self.assertEqual(
            [r.fetch_event for r in logs.records], ["request.started", "request.failed"]
        )
        self.assertEqual(logs.records[-1].fetch_error, "DecodeError")

    def test_body_can_only_be_claimed_once(self):
        with fetch.stream("GET", self.url + "/bytes") as response:
            chunks = response.iter_bytes(2)
            self.assertEqual(next(chunks), b"ab")
            with self.assertRaises(RuntimeError):
                response.iter_bytes()
            with self.assertRaises(RuntimeError):
                response.read()
            self.assertEqual(b"".join(chunks), b"cdef")

    def test_invalid_chunk_sizes_leave_body_available(self):
        with fetch.stream("GET", self.url + "/bytes") as response:
            for size in (0, -1, True, 1.5, None):
                with self.subTest(size=size), self.assertRaises(ValueError):
                    response.iter_bytes(size)
            self.assertEqual(b"".join(response.iter_bytes(1)), b"abcdef")

    def test_close_invalidates_pending_iterators(self):
        with fetch.stream("GET", self.url + "/gzip") as response:
            chunks = response.iter_bytes(1)
            self.assertEqual(next(chunks), b"h")
            response.close()
            response.close()
            with self.assertRaises(RuntimeError):
                next(chunks)
        with fetch.stream("GET", self.url) as response:
            unstarted = response.iter_bytes()
        with self.assertRaises(RuntimeError):
            next(unstarted)

    def test_exit_context_before_next_session_request(self):
        with fetch.Session() as session:
            with session.stream("GET", self.url + "/bytes") as response:
                with self.assertRaisesRegex(RuntimeError, "active stream"):
                    session.get(self.url)
                with self.assertRaises(RuntimeError), session.stream("GET", self.url):
                    pass
                response.read()
                with self.assertRaises(RuntimeError):
                    session.get(self.url)
            self.assertEqual(session.get(self.url).status, 200)

    def test_session_close_closes_live_stream(self):
        session = fetch.Session()
        with session.stream("GET", self.url + "/bytes") as response:
            session.close()
            self.assertTrue(response.closed)
            with self.assertRaises(RuntimeError):
                response.read()
        self.assertTrue(session.closed)
        self.assertTrue(self.server.finished[1].wait(1))

    def test_http_error_raises_without_reading_error_body(self):
        with (
            self.assertRaises(fetch.HTTPError) as caught,
            fetch.stream("GET", self.url + "/error", timeout=0.1),
        ):
            self.fail("HTTP status must be checked on entry")
        response = caught.exception.response
        self.assertIsInstance(response, fetch.StreamResponse)
        self.assertEqual(response.status, 404)
        self.assertTrue(response.closed)
        self.assertFalse(response.consumed)
        self.assertFalse(self.server.release.is_set())

    def test_check_status_false_allows_error_body_streaming(self):
        with fetch.stream("GET", self.url + "/error", check_status=False) as response:
            chunks = response.iter_bytes()
            self.assertEqual(next(chunks), b"abc")
            self.assertFalse(response.ok)
            with self.assertRaises(fetch.HTTPError):
                response.raise_for_status()
            self.server.release.set()
            self.assertEqual(b"".join(chunks), b"def")

    def test_redirect_drops_body_and_keeps_cookies_and_method_rules(self):
        with (
            fetch.Session(headers={"X-Shared": "yes"}) as session,
            session.stream("POST", self.url + "/redirect", json={"a": 1}, timeout=0.1) as response,
        ):
            data = response.read().json()
            self.assertEqual(data["method"], "GET")
            self.assertEqual(data["body"], "")
            self.assertEqual(data["headers"]["cookie"], "visited=yes")
            self.assertEqual(data["headers"]["x-shared"], "yes")
            self.assertEqual(data["connection"], 2)
            self.assertFalse(self.server.release.is_set())

    def test_streaming_redirect_errors_release_socket(self):
        with (
            self.assertRaises(fetch.RedirectError) as caught,
            fetch.stream("GET", self.url + "/redirect", max_redirects=0),
        ):
            pass
        self.assertTrue(caught.exception.response.closed)
        self.assertEqual(caught.exception.response.status, 302)

    def test_redirect_headers_are_stripped_on_origin_change(self):
        target = self.url.replace("127.0.0.1", "localhost")
        with (
            fetch.Session(headers={"Authorization": "secret", "Cookie": "secret=yes"}) as session,
            session.stream(
                "GET", self.url + "/redirect?" + urllib.parse.urlencode({"to": target})
            ) as response,
        ):
            headers = response.read().json()["headers"]
            self.assertNotIn("authorization", headers)
            self.assertNotIn("cookie", headers)

    def test_chunked_body_and_trailers_allow_reuse(self):
        with fetch.Session() as session:
            with session.stream("GET", self.url + "/chunked") as response:
                self.assertEqual(b"".join(response.iter_bytes(2)), b"abcdef")
            self.assertEqual(session.get(self.url).json()["connection"], 1)

    def test_truncated_and_invalid_gzip_bodies_fail_and_recover(self):
        for path, error in (
            ("/truncated", fetch.RequestError),
            ("/bad-chunk", fetch.RequestError),
            ("/bad-gzip", fetch.DecodeError),
            ("/truncated-gzip", fetch.DecodeError),
            ("/crc-gzip", fetch.DecodeError),
        ):
            with self.subTest(path=path), fetch.Session() as session:
                before = self.server.accepted
                with self.assertRaises(error), session.stream("GET", self.url + path) as response:
                    list(response.iter_bytes(2))
                self.assertTrue(response.closed)
                self.assertFalse(response.consumed)
                self.assertEqual(session.get(self.url).json()["connection"], before + 2)

    def test_timeout_during_iteration_releases_connection(self):
        with fetch.Session(timeout=0.05) as session:
            with session.stream("GET", self.url + "/gated") as response:
                chunks = response.iter_bytes()
                self.assertEqual(next(chunks), b"abc")
                with self.assertRaises(fetch.Timeout):
                    next(chunks)
            self.assertEqual(session.get(self.url).json()["connection"], 2)

    def test_gzip_members_and_empty_bodies(self):
        for method, path, expected in (
            ("GET", "/gzip", b"helloworld"),
            ("HEAD", "/gzip", b""),
            ("GET", "/204-gzip", b""),
            ("GET", "/304-gzip", b""),
            ("GET", "/empty-gzip", b""),
        ):
            with (
                self.subTest(method=method, path=path),
                fetch.stream(method, self.url + path) as response,
            ):
                self.assertEqual(b"".join(response.iter_bytes(3)), expected)
                self.assertTrue(response.consumed)

    def test_gzip_download_does_not_buffer_expanded_body(self):
        with fetch.stream("GET", self.url + "/large-gzip") as response:
            tracemalloc.start()
            try:
                total = 0
                for chunk in response.iter_bytes(4096):
                    self.assertLessEqual(len(chunk), 4096)
                    total += len(chunk)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
        self.assertEqual(total, LARGE_SIZE)
        self.assertLess(peak, 1_000_000)

    def test_proxy_streams_without_buffering(self):
        with (
            patch("urllib.request.getproxies", return_value={"http": self.url}),
            patch("urllib.request.proxy_bypass", return_value=False),
            fetch.stream(
                "GET", "http://example.invalid/gated", trust_env=True, timeout=0.1
            ) as response,
        ):
            self.assertEqual(next(response.iter_bytes()), b"abc")

    def test_application_exception_is_preserved(self):
        error = OSError("application output failed")
        with self.assertRaises(OSError) as caught, fetch.stream("GET", self.url + "/bytes"):
            raise error
        self.assertIs(caught.exception, error)
        self.assertTrue(self.server.finished[1].wait(1))

    def test_logging_terminal_events_follow_body_lifecycle(self):
        cases = (
            ("/bytes", "read", "completed"),
            ("/bytes", "close", "closed"),
            ("/bad-gzip", "catch", "failed"),
        )
        for path, operation, terminal in cases:
            with (
                self.subTest(path=path, operation=operation),
                self.assertLogs("fetch", logging.DEBUG) as logs,
            ):
                with fetch.stream("GET", self.url + path) as response:
                    self.assertEqual([r.fetch_event for r in logs.records], ["request.started"])
                    if operation == "read":
                        response.read()
                    elif operation == "catch":
                        with self.assertRaises(fetch.DecodeError):
                            response.read()
                self.assertEqual(
                    [r.fetch_event for r in logs.records],
                    ["request.started", "request." + terminal],
                )
                self.assertEqual(logs.records[-1].fetch_status, 200)


if __name__ == "__main__":
    unittest.main()
