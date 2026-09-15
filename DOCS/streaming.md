# Streaming

**Status:** implemented for response bodies. Synchronous HTTP/1.1, one file,
zero runtime dependencies. Native async is [a separate design](async.md).

## The call site

```python
import fetch

with fetch.stream("GET", "https://example.com/archive.tar", timeout=10) as r:
    print(r.status, r.headers.get("content-type"))
    with open("archive.tar", "wb") as output:
        for chunk in r.iter_bytes():
            output.write(chunk)
```

Use `with session.stream(method, url, ...)` to share a session's headers,
cookies, and connections. Both forms accept the same request options as their
buffered counterparts. Request bodies (`json` and `data`) remain buffered.

The context starts I/O on entry and owns cleanup. There is no `stream=True`
flag changing the return type of `get()`: a normal request always returns a
complete `Response`; a stream context yields a `StreamResponse`.

## One body, one reader

| Operation | Behavior |
| --- | --- |
| `status`, `reason`, `url`, `headers`, `ok` | Inspect metadata without reading the body |
| `iter_bytes(chunk_size=65536)` | Claim the body and yield up to that many decoded bytes per chunk |
| `read()` | Buffer an unclaimed body into an ordinary `Response` |
| `raise_for_status()` | Check status without reading the body |
| `close()` | Close immediately; discard an incompletely consumed connection |
| `closed` | Whether body access has ended |
| `consumed` | Whether iteration reached and validated the end of the body |

`iter_bytes()` claims the body when called, even before the first `next()`.
A second iterator or `read()` afterward raises `RuntimeError`. Chunks are bytes,
not text lines, HTTP chunks, or application messages. They can be smaller than
`chunk_size`, which must be a positive integer. The client does not wait for a
full chunk before returning available body data; decoding may need more input.

If buffering becomes useful, make it explicit:

```python
with fetch.stream("GET", "https://api.example.com/me") as r:
    response = r.read()

print(response.json())
```

`read()` allocates the full decoded body and returns a `Response`. Repeating it
returns the same object, including after context exit. Streaming itself has no
`.content`, `.text`, `.json()`, or `.parse()` that could hide network reads.
Use those methods on the buffered response instead.

## Connection ownership

An open context reserves its session, including after the body is consumed.
Exit it before sending another request through that session. Overlap raises
`RuntimeError`; the existing session remains sequential and is not thread-safe.

- Reaching the validated end of the body closes the stream and permits reuse
  of a compatible direct connection after context exit.
- Breaking out early, calling `close()`, or leaving because application code
  raised closes the unread body without downloading the remainder. That
  connection is discarded. Do not depend on an abandoned iterator's garbage
  collection for cleanup; keep the context.
- `Session.close()` closes its active stream too. An iterator cannot keep
  reading buffered decoder data after the stream closes.
- Module-level `stream()` also closes its temporary session on exit. Proxy
  connections remain uncached, as with buffered requests.

Consumption means exhausting the iterator, not merely receiving what appears
to be the final data chunk. A final read can still validate a gzip checksum or
HTTP chunk terminator. Closing before that point conservatively discards the
connection. Closing repeatedly is harmless; a closed, unbuffered body cannot
be reopened.

## Redirects, errors, and deadlines

Redirect decisions and cookie updates happen before the context yields. The
streaming path closes intermediate redirect bodies without draining them, then
opens the next hop. It therefore does not validate or retain skipped bodies.
Method rewriting, credential stripping, limits, and HTTPS downgrade refusal
match buffered requests.

With `check_status=True`, 4xx/5xx raise on entry, before downloading the error
body. `HTTPError.response` is a closed `StreamResponse` containing the metadata.
Streaming `RedirectError` follows the same rule. Buffered errors still carry
the complete `Response`; the error attribute's type now admits both forms.
To inspect an error body:

```python
with fetch.stream("GET", url, check_status=False) as r:
    if not r.ok:
        print(r.status)
    for chunk in r.iter_bytes():
        consume(chunk)
```

Network and framing failures raise `RequestError`, socket timeouts raise
`Timeout`, and malformed gzip raises `DecodeError`. These can occur after some
bytes have already been delivered. Output already written is not rolled back;
use an application-owned temporary file if a download must be atomic.

Timeouts still bound individual socket operations, not overall download time
or time spent processing chunks. There are no retries or background readers.
Reads advance only as the caller advances the iterator. Errors and early exits
always release the body. Application exceptions inside `with` propagate intact.

## Engine and checks

Buffered and streaming calls share request preparation, redirects, cookies,
status rules, and the session transport. Incremental reads use `http.client`'s
`read1()`; a small reader also detects premature EOF for fixed-length bodies.
Gzip decoding uses the standard library with bounded output and supports
concatenated members and checksum validation. Headers retain their received
values, so `Content-Length` can describe compressed bytes rather than the bytes
yielded. Other content encodings are passed through, as with buffered requests.

The relevant standard-library contracts are [HTTP response reads and reuse](https://docs.python.org/3/library/http.client.html#httpresponse-objects)
and [gzip file reads](https://docs.python.org/3/library/gzip.html#gzip.GzipFile).

Local-server tests cover gated first-byte delivery, HTTP/HTTPS reuse, early
close, chunked framing, truncated bodies, gzip corruption, redirects, proxy
streaming, socket timeouts, and context cleanup. A compressed 8 MB response
checks that iteration does not allocate the expanded body. Copied-file and
installed-package checks preserve the distribution contract.

**Recommendation:** keep this surface small. Text/line decoding, streaming
uploads, and download helpers need their own contracts before adding methods.

[Back to design notes](README.md)
