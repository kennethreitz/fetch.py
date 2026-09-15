# fetch.py

## HTTP you can own.

A small, humane HTTP client in **one Python file**. Copy it into your project,
read the code, and make it yours. **Zero runtime dependencies.**

```python
import fetch

response = fetch.get("https://httpbin.org/get", params={"q": "punk"})
print(response.json())
```

**Python 3.11+ · HTTP/1.1 · Synchronous · MIT**

[Get the file](fetch.py) · [Get started](#get-started) · [Design notes](DOCS/README.md)

> **Under active development.** The API is still taking shape.

## Why a single file?

Sometimes you want HTTP without adding a package to a script, a bootstrap tool,
or a project that keeps its dependencies close. fetch.py gives you familiar
calls, finite timeouts, verified TLS, and code you can take with you.

Readability and portability are the point. Sessions and streaming belong here
because they make that same file useful beyond a quick request. Every feature
has to earn its place in a copy someone else will maintain.

## Get started

Copy [`fetch.py`](fetch.py) beside your code and `import fetch`. That's the install.

You can also install from a checkout of this repository:

```sh
python -m pip install .
```

The distribution is named `fetch.py`; the Python import is `fetch`.

### Make a request

```python
import fetch

r = fetch.get("https://httpbin.org/get", params={"q": "punk"})
print(r.status, r.url)

r = fetch.post("https://httpbin.org/post", json={"hello": "world"}, timeout=10)
print(r.json())
```

Use `params=` for query parameters, `json=` for JSON, and `data=` for bytes,
text, or a mapping of form fields. Add headers with `headers={"Accept": "application/json"}`.

All seven verbs are available: `get`, `post`, `put`, `patch`, `delete`, `head`,
and `options`. For other methods, use `request(method, url, ...)`.
URLs must be absolute HTTP or HTTPS URLs; put credentials in headers.

### Read the response

Ordinary requests return a fully buffered `Response`. It owns no socket and
needs no `close()`.

| Attribute / method | Meaning |
| --- | --- |
| `status`, `reason` | Status code and reason phrase |
| `url` | Final URL after redirects |
| `headers` | Case-insensitive mapping; `get_all()` preserves repeated fields |
| `content` | Body bytes, with gzip decoded when declared |
| `text` | Text using the declared charset, or UTF-8 |
| `json()` | Parsed JSON |
| `parse(decoder)` | Pass body bytes to a decoder and preserve its return type |
| `ok` | `True` for 2xx |
| `raise_for_status()` | Raise `HTTPError` for status ≥ 400 |

## Sessions

Share headers, cookies, and connections across requests:

```python
with fetch.Session(headers={"User-Agent": "my-app/1.0"}, timeout=5) as s:
    profile = s.get("https://api.example.com/me").json()
    s.post("https://api.example.com/events", json={"event": "hello"}, timeout=10)
```

Sessions have the same verbs as the module. Per-request options override session
defaults; headers merge case-insensitively. A header value of `None` removes a
session header for that call. Cookies live in `s.cookies`, a standard-library
`CookieJar`.

Use `with`, or call `s.close()`. Each session is for sequential use and caches
up to eight direct HTTP/HTTPS connections (`max_connections=8`). Proxy
connections are not reused. Module-level calls use temporary sessions and
share no state between calls. [Session details →](DOCS/sessions.md)

## Streaming

Read a download in bounded chunks:

```python
with fetch.stream("GET", "https://example.com/archive.tar", timeout=10) as r:
    with open("archive.tar", "wb") as output:
        for chunk in r.iter_bytes():
            output.write(chunk)
```

The request starts on context entry. `iter_bytes(chunk_size=65536)` consumes the
body once, decoding gzip incrementally. Chunks may be smaller than requested.
Call `r.read()` instead to explicitly buffer an unread body into a `Response`.

Use `s.stream(method, url, ...)` with a session. Fully consuming the body permits
connection reuse; leaving early closes the connection without draining it.
Exit the stream context before making another request through that session.
[Streaming details →](DOCS/streaming.md)

## Defaults

| Default | Behavior |
| --- | --- |
| `timeout=30.0` | Finite, positive seconds per socket operation; not a total deadline |
| Verified TLS | Pass `context=` for a custom `ssl.SSLContext` |
| `check_status=True` | HTTP 4xx/5xx raise `HTTPError` |
| `follow_redirects=True` | Follow up to `max_redirects=10`; refuse HTTPS → HTTP |
| `trust_env=False` | Ignore environment/system proxies unless enabled |
| Buffered bodies | Stream responses explicitly; request bodies remain buffered |
| No retries | Failed requests are never automatically replayed |

Redirects strip explicit credentials on an origin change. POST on 301/302 and
non-HEAD on 303 become GET. `json=` and `data=` are mutually exclusive;
fetch calculates `Content-Length` for you.

## Errors

To inspect an HTTP error response yourself:

```python
r = fetch.get("https://httpbin.org/status/404", check_status=False)
print(r.status, r.ok)
r.raise_for_status()  # raises fetch.HTTPError
```

Buffered HTTP errors carry the complete `Response` in `.response`.
**Streaming HTTP errors raise on context entry**, without downloading the body;
`.response` is a closed `StreamResponse` containing its metadata. Use
`check_status=False` to read a streamed error body yourself.

| Exception | Meaning |
| --- | --- |
| `HTTPError` | An error status; `.response` matches buffered or streaming mode |
| `Timeout` | A socket operation exceeded its timeout |
| `RequestError` | Connection, TLS, or HTTP protocol failure |
| `RedirectError` | Too many redirects, an invalid destination, or HTTPS → HTTP |
| `DecodeError` | Invalid gzip, text, or JSON |
| `ValueError` / `TypeError` | Invalid arguments |
| `RuntimeError` | A closed session, a claimed/closed body, or an overlapping session request |

## Typed parsing

Use a decoder your application already owns. With Pydantic v2 installed:

```python
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str

user = fetch.get("https://api.example.com/users/42").parse(User.model_validate_json)
```

`user` is a `User`. `parse()` passes the bytes to your decoder and preserves its
result type and exceptions. Pydantic remains an application dependency.
[More parsing examples →](DOCS/pydantic.md)

## Logging

Use standard-library logging:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
fetch.get("https://example.com")
```

The module's logger emits `DEBUG` records with method, host, status, elapsed time,
and redirect count. Headers, bodies, full URLs, and exception text are omitted.
fetch installs no output handlers. [Fields and configuration →](DOCS/logging.md)

## Scope and direction

Today: synchronous HTTP/1.1, typed responses, sessions, cookies, and response
streaming. Native async and HTTP/2 are not implemented. Async needs an explicit
engine and cancellation decision before it belongs in this file.

We work out APIs in [`DOCS/`](DOCS/README.md):

[Single file](DOCS/single-file.md) · [Sessions](DOCS/sessions.md) ·
[Streaming](DOCS/streaming.md) · [Async](DOCS/async.md) ·
[Pydantic](DOCS/pydantic.md) · [Logging](DOCS/logging.md)

## Development

Tests live in `tests/` and use local HTTP servers. Install the locked development
tools, then run the suite, including Pydantic integration:

```sh
uv sync --locked
uv run --locked pytest
```

The standard-library runner also works; Pydantic tests skip if it isn't installed:

```sh
python -m unittest discover -s tests -v
```

Lint, type checks, and packaging:

```sh
uv run --locked ruff check fetch.py setup.py tests
uv run --locked ruff format --check fetch.py setup.py tests
uv run --locked mypy fetch.py tests/check_types.py tests/check_installed_types.py
uv run --locked pyright fetch.py tests/check_types.py tests/check_installed_types.py
uv build --no-build-isolation
uv run --locked python tests/check_distribution.py
```

The wheel contains the exact source as `fetch/__init__.py`, plus `py.typed`.
Editable installs use the original file. [The copy-in contract →](DOCS/single-file.md)

[CI](.github/workflows/ci.yml) covers Python 3.11–3.14 on Linux, macOS, and Windows.
It checks copied modules with site packages disabled, builds the wheel and sdist,
and runs runtime and type checks against an isolated wheel installation. Keep
only the current build in `dist/` when running the distribution check locally.

## License and credits

[MIT](LICENSE). Inspired by the spirit of Requests: human defaults, readable
code, and respect for the person at the keyboard.

Punk means keeping the tools simple enough to make your own.
