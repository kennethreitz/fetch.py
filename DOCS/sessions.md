# Sessions

**Status:** implemented. Synchronous sessions live in the same `fetch.py`, with
no additional runtime dependencies.

## The experience

```python
import fetch

with fetch.Session(headers={"Authorization": "Bearer ..."}, timeout=5) as s:
    user = s.get("https://api.example.com/me").json()
    s.post("https://api.example.com/events", json={"event": "hello"}, timeout=10)
```

One session owns shared request defaults, a cookie jar, and a bounded set of
direct connections. It returns the same buffered `Response` as `fetch.get()`.
Typed parsing and logging work the same way.

For a streamed response, use `with s.stream(method, url, ...) as r:` and consume
`r.iter_bytes()`. The request options are the same. See [Streaming](streaming.md).

## Defaults and overrides

The constructor accepts `headers`, `auth=None`, `timeout=30.0`,
`follow_redirects=True`, `max_redirects=10`, `check_status=True`,
`trust_env=False`, `context=None`, and `max_connections=8`.

`request(method, url, ...)` and all seven verb helpers accept `params`, `headers`,
`json`, `data`, `timeout`, `follow_redirects`, `max_redirects`, `check_status`,
and `auth`.

Per-request options override the session defaults. `None` for timeout or redirect
and status options means inherit; it never disables the finite timeout.
TLS context and proxy discovery are configured at construction.

Headers are copied at construction into a case-insensitive dictionary and merged
on every call. Assigning `X-Token` replaces an existing `x-token`. Per-request
changes leave session defaults alone:

```python
with fetch.Session(headers={"Authorization": "Bearer ..."}) as s:
    s.get("https://api.example.com/public", headers={"Authorization": None})
    s.get("https://api.example.com/private")  # session authorization still present
```

A `None` header removes a session header for that call. Built-in transport headers
may still be supplied, and the cookie jar may still add applicable cookies.
`s.headers` is a mutable dictionary. Names are stored in lowercase: item
assignment, `update()` (from a mapping or pairs), `setdefault()`, and `|` all
keep that rule. Set `s.timeout`, `s.follow_redirects`, `s.max_redirects`,
`s.check_status`, or `s.auth` to change future defaults. Assigning `s.auth`
checks the pair immediately and leaves the previous value in place when the
new one is invalid.

`auth=("username", "password")` adds `Authorization: Basic ...` when that header
is not already set. Credentials are UTF-8, and a lone surrogate is a
`ValueError` before any request is sent. Per-request `auth` replaces the
session pair for that call. An explicit `Authorization` header wins, and
`headers={"Authorization": None}` sends the call with no credentials. A
cross-origin redirect drops the header and does not put `auth` back.

Session headers apply to every URL explicitly requested through that session.
Use separate sessions for services with different credentials. Redirects strip
explicit authorization and cookie headers on an origin change, without
reapplying session defaults to the next hop. HTTPS-to-HTTP redirects are refused.

## Cookies

Responses update `s.cookies`, a standard-library `CookieJar`, including during
redirects. The jar supplies cookies to later matching requests. Domain, path,
expiry, and Secure rules apply; host-only cookies stay on their original host.
Cookies are scoped by host and path, not TCP port. This is an HTTP client jar,
not a browser's SameSite or public-suffix policy.

An explicit `Cookie` request header takes precedence over the jar for that
request. `s.cookies.clear()` forgets stored cookies. Separate sessions have
separate jars; cookies are not saved to disk.

## Connections and ownership

The session keeps one reusable connection per direct HTTP/HTTPS authority, up to
`max_connections` (a positive integer). Using another origin at capacity closes
the least recently used cached connection. Server `Connection: close`, a client
close request, and protocol upgrades prevent reuse. Proxy connections use
urllib's existing transport and are closed after each response.

Buffered bodies are fully consumed before returning a response or raising `HTTPError`.
That makes reuse safe even after a 404. A transport or body-decoding failure
discards only the failed connection; cached connections to other servers remain
available. Invalid request arguments leave existing connections alone.
Before a cached connection is reused, the session checks whether the idle socket
is already closed or has unexpected data waiting. That socket is discarded and
a new one is opened, so a server that hung up after the previous response does
not fail the next request. The check does not write the request. If the server
closes the socket after that check, or the connection fails while the request
is being written, the call raises `RequestError` and is not sent again.

The timeout applies to each socket operation, including reused sockets. It is
not an overall request deadline or a connection idle-expiry setting.

Use the context manager or explicitly call `close()`. Closing is idempotent and
permanent; requesting through or entering a closed session raises `RuntimeError`.
Responses remain usable after the session closes. There is no global session or
background cleanup thread. Do not share a session across concurrent work;
each worker should own its own session.

An open stream reserves the session until its context exits, even after the
body is consumed or closed. An overlapping request raises `RuntimeError`.
Closing a session also closes its active stream. Full consumption makes the
connection reusable; early exit discards that connection without draining the
body. Streaming redirects discard their intermediate bodies as well.

Module-level calls use a temporary session, including cookies within that call's
redirect chain. They release connections before returning and share no state
with later calls.

## Engine and cost

The urllib request pipeline handles proxy routing. Each request applies the
standard-library cookie jar before sending and inside response cleanup, so even
a failing custom cookie policy releases the affected response. A small handler
uses `http.client` for persistent direct connections, with a bounded dictionary
for eviction. This keeps the single-file contract and avoids a second request
engine. It also means proxy pooling,
concurrent sharing, streaming uploads, retries, and HTTP/2 remain outside this API.
Python documents the underlying [connection lifecycle](https://docs.python.org/3/library/http.client.html#http.client.HTTPConnection.getresponse)
and [cookie policy](https://docs.python.org/3/library/http.cookiejar.html).

**Recommendation:** keep ownership explicit. Streaming now shares this cache
through a scoped, one-shot body. [Native async](async.md) must preserve those
ownership rules before adding concurrency.

[Back to design notes](README.md)
