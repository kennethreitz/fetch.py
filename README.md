# fetch.py

> HTTP you can keep in your pocket — one readable Python file, no dependencies.

How you'd build a tiny humane HTTP client today if vendoring was the goal,
not a dependency tree.

```python
import fetch

data = fetch.get("https://httpbin.org/get", params={"q": "punk"}).json()
```

Copy `fetch.py` into your project, or install the package. Timeouts and TLS
verification are on. HTTP/1.1, synchronous, Python 3.11+.

## Why

[Requests](https://requests.readthedocs.io/) taught a generation that HTTP
could feel human. This is a spiritual cousin with a different spine:

- **One file** — the implementation is a single module you can read and own.
- **Zero dependencies** — stdlib only (`urllib`, `ssl`, `json`, …).
- **Humane** — `get` / `post` / … and a small `Response`.
- **Honest defaults** — finite timeout (30s), cert verification, HTTP 4xx/5xx
  raise unless you opt out.

Not Requests 2. Not HTTPX with different branding. Not a framework.

## Install

```bash
pip install -e /path/to/fetch.py   # local editable, for now
# or: copy fetch.py next to your code and `import fetch`
```

PyPI distribution name is **`fetch.py`** (the import is still `fetch`).
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

| attr / method | meaning |
|---|---|
| `status` | HTTP status code |
| `reason` | reason phrase |
| `headers` | case-insensitive mapping (`get_all` for repeats) |
| `content` | raw body `bytes` (gzip decoded when declared) |
| `text` | decoded text (charset from Content-Type, else UTF-8) |
| `json()` | parsed JSON |
| `url` | final URL after redirects |
| `ok` | `True` if 2xx |
| `raise_for_status()` | raise `HTTPError` if status ≥ 400 |

## Errors

| type | when |
|---|---|
| `HTTPError` | 4xx/5xx when `check_status=True` (default); `.response` is set |
| `Timeout` | socket operation exceeded `timeout` |
| `RequestError` | connection / TLS / protocol failure |
| `RedirectError` | too many redirects, bad Location, or HTTPS→HTTP |
| `DecodeError` | body/gzip/text/JSON decode failure |
| `ValueError` / `TypeError` | bad arguments (invalid URL, headers, timeout, …) |

Invalid arguments fail fast. Network and HTTP failures use the hierarchy above.

## Defaults (what the code actually does)

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

## API sketch

```python
fetch.request(
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
) -> Response
```

URLs must be absolute `http://` or `https://`. Credentials in the URL are
rejected — put them in headers.

## Roadmap

Done in-tree today:

- [x] Single-module stdlib client
- [x] GET/POST/… + JSON + form/`data`
- [x] Finite timeout + TLS verify
- [x] Redirects with safe credential handling
- [x] MIT license + `pyproject.toml`

Next:

- [ ] Tests (200, JSON, HTTP error, timeout)
- [ ] Decide public story for PyPI vs copy-in
- [ ] Optional `Session` (connection reuse) — only if it stays small
- [ ] Streaming / async — only with a coherent design, not a bolt-on

## License

MIT — see `LICENSE`.

## Credits

Inspired by the spirit of Requests (Kenneth Reitz): human defaults, readable
code, respect for the person at the keyboard.

**Punk ≠ rude. Punk = no bloat, no apology for wanting simple tools.**
