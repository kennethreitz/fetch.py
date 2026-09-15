"""Session contracts, including real socket reuse and failure recovery."""

import http.cookiejar
import json
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import fetch


class Server(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.accepted = 0
        self.dropped = 0
        self.finished = {}

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

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
        parts = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parts.query)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if parts.path == "/drop":
            self.server.dropped += 1
            self.close_connection = True
            self.connection.shutdown(socket.SHUT_RDWR)
            return
        content = json.dumps(
            {
                "connection": self.connection_id,
                "method": self.command,
                "body": body.decode(),
                "headers": {name.lower(): value for name, value in self.headers.items()},
                "path": self.path,
            }
        ).encode()
        status = 302 if parts.path == "/redirect" else 404 if parts.path == "/missing" else 200
        self.send_response(status)
        if status == 302:
            self.send_header("Location", query.get("to", ["/"])[0])
        for cookie in query.get("cookie", []):
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", len(content) + (10 if parts.path == "/truncated" else 0))
        if parts.path in {"/close", "/truncated"}:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        if parts.path == "/slow":
            self.wfile.flush()
            time.sleep(0.15)
        if self.command != "HEAD":
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = respond


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.servers = [Server() for _ in range(3)]
        self.threads = []
        for server in self.servers:
            thread = threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
            )
            thread.start()
            self.threads.append(thread)
        self.server = self.servers[0]
        self.url = self.server.url

    def tearDown(self):
        for server, thread in zip(self.servers, self.threads):
            server.shutdown()
            server.server_close()
            thread.join()

    def test_reuse_and_context_cleanup(self):
        with fetch.Session() as session:
            first = session.get(self.url)
            second = session.post(self.url, json={"hello": "world"})
            self.assertEqual(first.json()["connection"], second.json()["connection"])
            self.assertEqual(json.loads(second.json()["body"]), {"hello": "world"})
            self.assertEqual(self.server.accepted, 1)
            self.assertFalse(session.closed)
        self.assertTrue(self.server.finished[1].wait(1), "Session.close() left a socket open")
        self.assertTrue(session.closed)
        self.assertEqual(first.status, 200)
        session.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            session.get(self.url)
        with self.assertRaisesRegex(RuntimeError, "closed"), session:
            pass

    def test_exception_exits_close_connections(self):
        with self.assertRaisesRegex(ValueError, "application"), fetch.Session() as session:
            session.get(self.url)
            raise ValueError("application error")
        self.assertTrue(self.server.finished[1].wait(1))

    def test_headers_merge_remove_and_do_not_mutate_defaults(self):
        defaults = {"X-Shared": "default", "Authorization": "token"}
        with fetch.Session(headers=defaults) as session:
            defaults["X-Shared"] = "changed outside"
            headers = session.get(
                self.url, headers={"x-SHARED": "override", "Authorization": None}
            ).json()["headers"]
            self.assertEqual(headers["x-shared"], "override")
            self.assertNotIn("authorization", headers)
            headers = session.get(self.url).json()["headers"]
            self.assertEqual(headers["x-shared"], "default")
            self.assertEqual(headers["authorization"], "token")
            session.headers["X-Shared"] = "updated"
            self.assertEqual(session.get(self.url).json()["headers"]["x-shared"], "updated")

    def test_request_options_override_session_defaults(self):
        with fetch.Session(check_status=False, follow_redirects=False, max_redirects=0) as session:
            self.assertEqual(session.get(self.url + "/missing").status, 404)
            with self.assertRaises(fetch.HTTPError):
                session.get(self.url + "/missing", check_status=True)
            self.assertEqual(session.get(self.url + "/redirect").status, 302)
            with self.assertRaises(fetch.RedirectError):
                session.get(self.url + "/redirect", follow_redirects=True)
            self.assertEqual(
                session.get(self.url + "/redirect", follow_redirects=True, max_redirects=1).status,
                200,
            )
            self.assertFalse(session.check_status)
            self.assertFalse(session.follow_redirects)
            self.assertEqual(session.max_redirects, 0)

    def test_all_verbs_and_http_error_keep_connection_usable(self):
        with fetch.Session() as session:
            for verb in ("get", "post", "put", "patch", "delete", "options"):
                self.assertEqual(getattr(session, verb)(self.url).json()["method"], verb.upper())
            self.assertEqual(session.head(self.url).content, b"")
            with self.assertRaises(fetch.HTTPError) as error:
                session.get(self.url + "/missing")
            self.assertEqual(error.exception.response.status, 404)
            self.assertEqual(session.request("GET", self.url).json()["connection"], 1)
            self.assertEqual(self.server.accepted, 1)

    def test_cookies_across_redirects_and_requests(self):
        query = urllib.parse.urlencode({"cookie": "flavor=punk; Path=/"})
        with fetch.Session() as session:
            response = session.get(self.url + "/redirect?" + query)
            self.assertEqual(response.json()["headers"]["cookie"], "flavor=punk")
            self.assertEqual(session.get(self.url).json()["headers"]["cookie"], "flavor=punk")
            self.assertEqual(
                session.get(self.url, headers={"Cookie": "manual=yes"}).json()["headers"]["cookie"],
                "manual=yes",
            )
            with fetch.Session() as other:
                self.assertNotIn("cookie", other.get(self.url).json()["headers"])
            session.cookies.clear()
            self.assertNotIn("cookie", session.get(self.url).json()["headers"])

    def test_cookie_path_secure_and_host_scope(self):
        cookies = [
            ("cookie", "private=yes; Path=/private"),
            ("cookie", "secret=yes; Secure; Path=/"),
            ("cookie", "host=yes; Path=/"),
        ]
        with fetch.Session() as session:
            session.get(self.url + "/?" + urllib.parse.urlencode(cookies))
            self.assertEqual(session.get(self.url).json()["headers"]["cookie"], "host=yes")
            self.assertIn(
                "private=yes", session.get(self.url + "/private/page").json()["headers"]["cookie"]
            )
            other_host = self.url.replace("127.0.0.1", "localhost")
            self.assertNotIn("cookie", session.get(other_host).json()["headers"])

    def test_redirect_strips_session_credentials_without_reapplying(self):
        target = self.servers[1].url
        with fetch.Session(
            headers={"Authorization": "secret", "Cookie": "manual=secret"}
        ) as session:
            headers = session.get(
                self.url + "/redirect?" + urllib.parse.urlencode({"to": target})
            ).json()["headers"]
            self.assertNotIn("authorization", headers)
            self.assertNotIn("cookie", headers)
            self.assertEqual(session.get(self.url).json()["headers"]["authorization"], "secret")

    def test_bounded_cache_evicts_least_recently_used_origin(self):
        first, second, third = self.servers
        with fetch.Session(max_connections=2) as session:
            session.get(first.url)
            session.get(second.url)
            session.get(first.url)
            session.get(third.url)
            self.assertTrue(second.finished[1].wait(1))
            self.assertEqual(session.get(first.url).json()["connection"], 1)
            self.assertEqual(session.get(second.url).json()["connection"], 2)

    def test_server_and_client_connection_close_are_respected(self):
        with fetch.Session() as session:
            session.get(self.url + "/close")
            self.assertEqual(session.get(self.url).json()["connection"], 2)
            session.get(self.url, headers={"Connection": "keep-alive, close"})
            self.assertTrue(self.server.finished[2].wait(1))
            self.assertEqual(session.get(self.url).json()["connection"], 3)

    def test_timeout_override_updates_reused_socket_and_recovers(self):
        with fetch.Session(timeout=1) as session:
            session.get(self.url)
            with self.assertRaises(fetch.Timeout):
                session.get(self.url + "/slow", timeout=0.02)
            self.assertEqual(self.server.accepted, 1)
            self.assertEqual(session.get(self.url + "/slow").status, 200)
            self.assertEqual(self.server.accepted, 2)

    def test_truncated_body_discards_connection(self):
        with fetch.Session() as session:
            session.get(self.url)
            with self.assertRaises(fetch.RequestError):
                session.get(self.url + "/truncated")
            self.assertEqual(session.get(self.url).json()["connection"], 2)

    def test_failed_post_is_never_replayed(self):
        with fetch.Session() as session:
            other = self.servers[1].url
            first = session.get(other).json()["connection"]
            session.get(self.url)
            with self.assertRaises(fetch.RequestError):
                session.post(self.url + "/drop", json={"charge": 1})
            self.assertEqual(self.server.dropped, 1)
            self.assertEqual(session.get(other).json()["connection"], first)
            self.assertEqual(session.get(self.url).json()["connection"], 2)

    def test_invalid_request_preserves_cached_connections(self):
        with fetch.Session() as session:
            urls = [server.url for server in self.servers]
            first = [session.get(url).json()["connection"] for url in urls]
            for options in ({"timeout": 0}, {"data": object()}, {"json": float("nan")}):
                with self.subTest(options=options):
                    with self.assertRaises((ValueError, TypeError)):
                        session.get(self.url, **options)
                    self.assertEqual([session.get(url).json()["connection"] for url in urls], first)

    def test_cookie_policy_failures_release_only_the_affected_connection(self):
        policy = http.cookiejar.DefaultCookiePolicy()
        error = RuntimeError("cookie policy failed")
        other = self.servers[1].url
        url = self.url + "/?cookie=flavor%3Dpunk"
        with fetch.Session() as session:
            session.cookies.set_policy(policy)
            first = session.get(url).json()["connection"]
            second = session.get(other).json()["connection"]
            with patch.object(policy, "return_ok", side_effect=error):
                with self.assertRaises(RuntimeError) as caught:
                    session.get(self.url)
            self.assertIs(caught.exception, error)
            self.assertEqual(session.get(self.url).json()["connection"], first)
            self.assertEqual(session.get(other).json()["connection"], second)

            with patch.object(policy, "set_ok", side_effect=error):
                with self.assertRaises(RuntimeError) as caught:
                    session.get(url)
            self.assertIs(caught.exception, error)
            self.assertTrue(self.server.finished[first].wait(1))
            self.assertEqual(session.get(other).json()["connection"], second)
            self.assertEqual(session.get(self.url).json()["connection"], first + 1)

    def test_module_calls_are_short_lived(self):
        fetch.get(self.url + "/?cookie=a%3D1")
        self.assertTrue(self.server.finished[1].wait(1))
        response = fetch.get(self.url)
        self.assertEqual(response.json()["connection"], 2)
        self.assertNotIn("cookie", response.json()["headers"])

    def test_proxy_uses_urllib_without_caching_connections(self):
        with (
            patch("urllib.request.getproxies", return_value={"http": self.url}),
            patch("urllib.request.proxy_bypass", return_value=False),
            fetch.Session(trust_env=True) as session,
        ):
            for _ in range(2):
                response = session.get("http://example.invalid/resource")
                self.assertEqual(response.json()["path"], "http://example.invalid/resource")
            self.assertEqual(self.server.accepted, 2)
            self.assertTrue(self.server.finished[1].wait(1))
            self.assertTrue(self.server.finished[2].wait(1))

    @unittest.skipUnless(shutil.which("openssl"), "openssl needed for a temporary TLS certificate")
    def test_https_reuses_verified_connection_and_closes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            cert, key = Path(tmp) / "cert.pem", Path(tmp) / "key.pem"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=IP:127.0.0.1",
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            server = Server()
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
            )
            thread.start()
            self.servers.append(server)
            self.threads.append(thread)
            url = server.url.replace("http:", "https:")
            with fetch.Session() as session, self.assertRaises(fetch.RequestError):
                session.get(url)
            trusted = ssl.create_default_context(cafile=cert)
            with fetch.Session(context=trusted) as session:
                first = session.get(url).json()["connection"]
                self.assertEqual(session.get(url).json()["connection"], first)
                with session.stream("GET", url) as stream:
                    self.assertEqual(stream.read().json()["connection"], first)
                self.assertEqual(server.accepted, 1)
            self.assertTrue(server.finished[first].wait(1))

    def test_invalid_session_defaults_fail_at_construction(self):
        for value in (0, -1, True, 1.5, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                fetch.Session(max_connections=value)
        with self.assertRaises(ValueError):
            fetch.Session(timeout=0)
        with self.assertRaises(ValueError):
            fetch.Session(max_redirects=-1)


if __name__ == "__main__":
    unittest.main()
