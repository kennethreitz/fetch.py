"""HTTP you can keep in your pocket. Python 3.11+, no dependencies.

    import fetch
    data = fetch.get("https://example.com/api").json()

Copy this file into your project. Timeouts and TLS verification are on;
HTTP errors raise by default. Responses are buffered. HTTP/1.1, synchronous.
SPDX-License-Identifier: MIT
Copyright (c) 2026 Kenneth Reitz

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from __future__ import annotations

import gzip
import http.client
import json as _json
import math
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from email.message import Message
from functools import partial
from typing import Any

__version__ = "0.1.0"
__all__ = [
    "request", "get", "post", "put", "patch", "delete", "head", "options",
    "Response", "Headers", "Error", "RequestError", "Timeout", "HTTPError",
    "RedirectError", "DecodeError",
]

_UNSET = object()
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_REDIRECTS = {301, 302, 303, 307, 308}


class Headers(Mapping[str, str]):
    """Read-only, case-insensitive headers. Use get_all() for repeated fields."""

    def __init__(self, items: Iterable[tuple[str, str]] = ()) -> None:
        self._items = tuple(items)

    def __getitem__(self, name: str) -> str:
        values = self.get_all(name)
        if not values:
            raise KeyError(name)
        return values[0]

    def __iter__(self) -> Iterator[str]:
        seen = set()
        for name, _ in self._items:
            if name.lower() not in seen:
                seen.add(name.lower())
                yield name

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def get_all(self, name: str) -> list[str]:
        return [value for key, value in self._items if key.lower() == name.lower()]


class Error(Exception):
    """Base class for fetch failures. Invalid arguments raise ValueError/TypeError."""


class RequestError(Error):
    """A connection, TLS, or HTTP protocol failure; __cause__ holds the original."""


class Timeout(RequestError):
    """A socket operation exceeded the timeout."""


class DecodeError(Error):
    """The response body could not be decoded."""


class HTTPError(Error):
    """An HTTP failure, with the complete response available as .response."""

    def __init__(self, response: Response) -> None:
        self.response = response
        super().__init__(f"{response.status} {response.reason} for {response.url}")


class RedirectError(HTTPError):
    """A redirect exceeded the limit or attempted an unsafe destination."""


@dataclass(frozen=True)
class Response:
    """A fully read response; it owns no open socket and needs no close()."""

    status: int
    headers: Headers
    content: bytes
    url: str
    reason: str = ""

    def __repr__(self) -> str:
        return f"<Response [{self.status}]>"

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def text(self) -> str:
        """Decode the declared charset, or UTF-8. Invalid input raises."""
        message = Message()
        message["content-type"] = self.headers.get("content-type", "")
        encoding = message.get_content_charset() or "utf-8"
        try:
            return self.content.decode(encoding)
        except (LookupError, UnicodeError) as exc:
            raise DecodeError(f"Cannot decode response as {encoding}") from exc

    def json(self) -> Any:
        """Parse JSON, including UTF-8/16/32 and byte-order marks."""
        try:
            return _json.loads(self.content)
        except (ValueError, UnicodeError) as exc:
            raise DecodeError("Response is not valid JSON") from exc

    def raise_for_status(self) -> Response:
        if self.status >= 400:
            raise HTTPError(self)
        return self


class _ReturnResponse(urllib.request.HTTPErrorProcessor):
    # urllib normally turns errors into exceptions and follows redirects itself.
    # Keep both decisions here so all verbs and all statuses behave consistently.
    def http_response(self, request: Any, response: Any) -> Any:
        return response

    https_response = http_response


def _url(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("url must be a string")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("url must not contain control characters")
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("url must be an absolute http:// or https:// URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("Put credentials in headers, not in the URL")
    host = parts.hostname.encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{host}]"
    if parts.port is not None:
        host += f":{parts.port}"
    path = urllib.parse.quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
    return urllib.parse.urlunsplit((parts.scheme, host, path, query, ""))


def _origin(url: str) -> tuple[str, str | None, int]:
    parts = urllib.parse.urlsplit(url)
    port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
    return parts.scheme, parts.hostname, port


def _headers(values: Mapping[str, str] | None) -> dict[str, str]:
    result = {"user-agent": f"fetch.py/{__version__}", "accept-encoding": "gzip"}
    for name, value in (values or {}).items():
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise ValueError("Header names must be HTTP tokens")
        if not isinstance(value, str) or any(ord(c) < 32 and c != "\t" or ord(c) == 127 for c in value):
            raise ValueError("Header values must be strings without control characters")
        value.encode("latin-1")
        result[name.lower()] = value
    if "transfer-encoding" in result or "content-length" in result:
        raise ValueError("fetch calculates Content-Length; do not set body framing headers")
    return result


def request(
    method: str,
    url: str,
    *,
    params: Mapping[str, Any] | Iterable[tuple[str, Any]] | None = None,
    headers: Mapping[str, str] | None = None,
    json: Any = _UNSET,
    data: bytes | str | Mapping[str, Any] | None = None,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    max_redirects: int = 10,
    check_status: bool = True,
    trust_env: bool = False,
    context: ssl.SSLContext | None = None,
) -> Response:
    """Send a request. HTTP 4xx/5xx raise HTTPError unless check_status=False.

    params appends query parameters; sequence values become repeated keys.
    json serializes any JSON value (including None). data sends bytes, UTF-8
    text, or a mapping encoded as a form. json and data are mutually exclusive.

    timeout is a positive socket-operation timeout, not a total deadline.
    trust_env opts into urllib's environment/system proxy discovery.
    context supplies a custom TLS context, e.g. for a private certificate CA.

    Redirects preserve methods/bodies except POST on 301/302 and non-HEAD
    methods on 303, which become GET. Credentials are stripped when origins
    change; HTTPS-to-HTTP redirects are refused. No retries are performed.
    """
    if not isinstance(method, str) or not _TOKEN.fullmatch(method):
        raise ValueError("method must be an HTTP token")
    method = method.upper()
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number of seconds")
    if isinstance(max_redirects, bool) or not isinstance(max_redirects, int) or max_redirects < 0:
        raise ValueError("max_redirects must be a nonnegative integer")
    if json is not _UNSET and data is not None:
        raise ValueError("Use either json or data, not both")
    url = _url(url)
    if params is not None:
        query = urllib.parse.urlencode(params if isinstance(params, Mapping) else list(params), doseq=True)
        if query:
            url += ("&" if urllib.parse.urlsplit(url).query else "?") + query
    outgoing = _headers(headers)
    body = None
    if json is not _UNSET:
        body = _json.dumps(json, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        outgoing.setdefault("content-type", "application/json")
    elif isinstance(data, Mapping):
        body = urllib.parse.urlencode(data, doseq=True).encode("ascii")
        outgoing.setdefault("content-type", "application/x-www-form-urlencoded")
    elif isinstance(data, str):
        body = data.encode("utf-8")
        outgoing.setdefault("content-type", "text/plain; charset=utf-8")
    elif isinstance(data, bytes):
        body = data
        outgoing.setdefault("content-type", "application/octet-stream")
    elif data is not None:
        raise TypeError("data must be bytes, str, or a mapping")

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(None if trust_env else {}),
        urllib.request.HTTPSHandler(context=context),
        _ReturnResponse(),
    )
    for hop in range(max_redirects + 1):
        req = urllib.request.Request(url, data=body, headers=outgoing, method=method)
        try:
            with opener.open(req, timeout=timeout) as raw:
                response_headers = Headers(raw.headers.raw_items())
                content = raw.read()
                status, reason = raw.status, raw.reason
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            cause = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            if isinstance(cause, TimeoutError):
                raise Timeout(f"Request timed out: {url}") from exc
            raise RequestError(f"Request failed: {url}") from exc
        # HEAD/204/304 have no payload even if they describe compressed content.
        if content and response_headers.get("content-encoding", "").lower().strip() == "gzip":
            try:
                content = gzip.decompress(content)
            except (OSError, EOFError, zlib.error) as exc:
                raise DecodeError("Response is not valid gzip") from exc
        response = Response(status, response_headers, content, url, reason)
        location = response.headers.get("location")
        if follow_redirects and status in _REDIRECTS and location:
            if hop == max_redirects:
                raise RedirectError(response)
            try:
                target = _url(urllib.parse.urljoin(url, location))
            except (ValueError, UnicodeError) as exc:
                raise RedirectError(response) from exc
            if url.startswith("https:") and target.startswith("http:"):
                raise RedirectError(response)
            if _origin(url) != _origin(target):
                for name in ("authorization", "cookie", "proxy-authorization"):
                    outgoing.pop(name, None)
            outgoing.pop("host", None)
            if (status in {301, 302} and method == "POST") or (status == 303 and method != "HEAD"):
                method, body = "GET", None
                for name in list(outgoing):
                    if name.startswith("content-"):
                        del outgoing[name]
            url = target
            continue
        return response.raise_for_status() if check_status else response
    raise AssertionError("unreachable")


get = partial(request, "GET")
post = partial(request, "POST")
put = partial(request, "PUT")
patch = partial(request, "PATCH")
delete = partial(request, "DELETE")
head = partial(request, "HEAD")
options = partial(request, "OPTIONS")
