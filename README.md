# fetch.py

**HTTP you can keep in your pocket.**

A small, humane HTTP client. One readable Python file. Zero runtime dependencies.
Copy it into your project, understand the whole thing, and make it yours.

```python
import fetch

data = fetch.get("https://httpbin.org/get", params={"q": "punk"}).json()
```

Typed responses. Finite timeouts. Verified TLS.\
Python 3.11+ · HTTP/1.1 · synchronous.

> **Under active development.** The API is still taking shape. Follow the
> ideas and design decisions in [`DOCS/`](DOCS/README.md).

## Why

Use **fetch.py** when the *dependency* is the problem:

- **Vendoring** — one MIT file and the standard library. Useful for scripts,
  embedded tools, and installations where adding packages is difficult.
- **Defaults with teeth** — a finite socket timeout (30s); verified TLS;
  HTTP 4xx/5xx raise unless you opt out.
- **Readability as product** — read and audit the whole client in one sitting.
  Understand the implementation as easily as the call site.
- **Control** — teach HTTP, change behavior, and keep the pieces you need.

The current scope is synchronous HTTP/1.1 with buffered responses.
[Requests](https://requests.readthedocs.io/) provides sessions and connection
pooling. [HTTPX](https://www.python-httpx.org/) also supports async, with
[optional HTTP/2](https://www.python-httpx.org/http2/).

## Install

Copy [`fetch.py`](fetch.py) next to your code and `import fetch`.

Or install from this checkout:

```sh
python -m pip install .
```

The configured distribution name is **`fetch.py`**; the import is `fetch`.
Plain [`fetch`](https://pypi.org/project/fetch/) is an unrelated legacy package.

## Quickstart

```python
import fetch

r = fetch.get("https://httpbin.org/get", params={"q": "punk"})
print(r.status, r.url)
print(r.json())

r = fetch.post(
    "https://httpbin.org/post",
    json={"hello": "world"},
    timeout=10,
)
print(r.status, r.text[:80])
```

Inspect without raising on error statuses:

```python
r = fetch.get("https://httpbin.org/status/404", check_status=False)
print(r.status, r.ok)
r.raise_for_status()  # -> fetch.HTTPError
```

Verbs: `get`, `post`, `put`, `patch`, `delete`, `head`, `options`, plus
`request(method, url, ...)`.

## Response

`Response` is fully buffered — no open socket, no `close()`.

| Attribute / method | Meaning |
| --- | --- |
| `status` | HTTP status code |
| `reason` | reason phrase |
| `headers` | case-insensitive mapping (`get_all` for repeats) |
| `content` | body `bytes`, after gzip decoding when declared |
| `text` | decoded text (charset from Content-Type, else UTF-8) |
| `json()` | parsed JSON |
| `parse(decoder)` | call a bytes decoder; preserve its result type and exceptions |
| `url` | final URL after redirects |
| `ok` | `True` if 2xx |
| `raise_for_status()` | raise `HTTPError` if status ≥ 400 |

### Typed parsing

Use a decoder your application already owns. With Pydantic v2 installed:

```python
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str

user = fetch.get("https://api.example.com/users/42").parse(User.model_validate_json)
```

`user` is a `User`. `parse()` passes the body bytes to your decoder once and
lets its exceptions propagate. Pydantic stays an application dependency; fetch
never imports it. See [Pydantic](DOCS/pydantic.md) for arrays and outbound models.

### Logging

The client emits `DEBUG` records through standard-library logging:

```python
import logging

logging.basicConfig(level=logging.DEBUG)  # application configuration
fetch.get("https://example.com")
```

The logger is named `fetch`, or the qualified module name when vendored.
Records include method, host, status, elapsed time, and redirect count. They
omit headers, bodies, full URLs, and exception text. The client installs no
output handlers. See [Logging](DOCS/logging.md) for fields and configuration.

## Errors

| Type | When |
| --- | --- |
| `HTTPError` | 4xx/5xx when `check_status=True` (default); `.response` is set |
| `Timeout` | socket operation exceeded `timeout` |
| `RequestError` | connection / TLS / protocol failure |
| `RedirectError` | too many redirects, bad Location, or HTTPS→HTTP |
| `DecodeError` | body/gzip/text/JSON decode failure |
| `ValueError` / `TypeError` | bad arguments (invalid URL, headers, timeout, …) |

Invalid arguments fail fast. Network and HTTP failures use the hierarchy above.

## Defaults

- **Timeout:** `30.0` seconds — per socket operation, not a total deadline.
  Must be a finite positive number.
- **TLS:** verified (pass `context=` for a custom `ssl.SSLContext`).
- **Status:** `check_status=True` → 4xx/5xx raise `HTTPError`.
- **Redirects:** followed (`follow_redirects=True`, `max_redirects=10`).
  POST on 301/302 and non-HEAD on 303 become GET; credentials stripped on
  origin change; HTTPS→HTTP refused.
- **Proxies / env:** off unless `trust_env=True`.
- **Body:** `json=` and `data=` are mutually exclusive; `Content-Length` is
  calculated for you.
- **No retries.** No streaming API yet. No `Session` yet.

## Request signature (abridged)

```python
def request(
    method: str,
    url: str,
    *,
    params=None,
    headers=None,
    json=...,          # any JSON value, including None
    data=None,         # bytes | str | mapping (form)
    timeout=30.0,
    follow_redirects=True,
    max_redirects=10,
    check_status=True,
    trust_env=False,
    context=None,      # ssl.SSLContext
) -> fetch.Response:
    ...
```

URLs must be absolute `http://` or `https://`. Credentials in the URL are
rejected — put them in headers.

## Roadmap

Implemented in the current prototype:

- [x] Single-module stdlib client
- [x] GET/POST/… + JSON + form/`data`
- [x] Finite timeout + TLS verify
- [x] Redirects with safe credential handling
- [x] MIT license + `pyproject.toml`
- [x] Generic typed parsing and structured debug logging
- [x] Local HTTP tests, copied-file checks, and optional Pydantic integration
- [x] Typed wheel built from the canonical source file

Next:

- [ ] Decide public story for PyPI vs copy-in
- [ ] Optional `Session` (connection reuse) — only if it stays small
- [ ] Streaming / async — only with a coherent design, not a bolt-on

## Design notes

API ideas live in [`DOCS/`](DOCS/README.md) before they become features:

- [Pydantic](DOCS/pydantic.md) — validating responses and sending models.
- [Logging](DOCS/logging.md) — useful diagnostics through standard logging.
- [Single file](DOCS/single-file.md) — the copy-in contract and its tradeoffs.

The notes distinguish current behavior from proposals and open questions.

## Development

The test suite lives in `tests/` and uses local HTTP servers. Run it with pytest
and Pydantic v2 in an isolated environment, using uv:

```sh
uv run --no-project --with pytest --with 'pydantic>=2,<3' python -m pytest
```

The standard-library runner also works. Pydantic tests skip when Pydantic v2
is not installed:

```sh
python -m unittest discover -s tests -v
```

`tests/check_types.py` contains static assertions for type checkers; pytest does
not collect it. Run the type checks and build with:

```sh
uv run --no-project --with 'pydantic>=2,<3' --with mypy mypy tests/check_types.py
uv run --no-project --with 'pydantic>=2,<3' --with pyright pyright tests/check_types.py
uv build
```

The build installs the exact contents of `fetch.py` as `fetch/__init__.py`,
with a `py.typed` marker for type checkers. Editable installs use the original
source. The standalone file remains the only runtime implementation.

## License

MIT — see [LICENSE](LICENSE).

## Credits

Inspired by the spirit of Requests (Kenneth Reitz): human defaults, readable
code, respect for the person at the keyboard.

**Punk ≠ rude. Punk = no bloat, no apology for wanting simple tools.**
# fetch.py
