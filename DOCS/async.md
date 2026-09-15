# Native async

**Status:** deferred design, not an implemented API. The current decision is
to ship [synchronous streaming](streaming.md) while preserving one copyable file
and zero runtime dependencies. There is no `AsyncSession` or thread-backed
adapter in fetch.py.

## What should stay the same

Async should change where execution yields, while retaining the request and
body contracts:

- A buffered call returns the existing `Response`. Its parsing methods do no I/O.
- A streamed call has an explicit context and a one-shot body.
- Metadata is immediately usable once response headers arrive.
- Bytes are pulled by the caller, with bounded buffering and incremental decoding.
- A fully consumed response can release its connection for reuse. Early exit or
  cancellation discards an unfinished response's connection.
- Status errors, redirects, cookies, finite timeouts, and no automatic retries
  have the same meaning across both execution models.

Illustrative syntax only; these classes do not exist:

```python
async with fetch.AsyncSession(timeout=5) as s:
    response = await s.get(url)
    data = response.json()  # already buffered; no await

    async with s.stream("GET", download_url) as r:
        async for chunk in r.iter_bytes():
            await consume(chunk)
```

The stream's explicit buffering operation would be `await r.read()`, returning
the same `Response`. There should be no automatic sync/async mode detection or
properties that sometimes require an await. This is a target shape to assess
an engine against, not a promise to ship a second copy of every implementation.

## The engine decision remains open

The present transport uses blocking `urllib` and `http.client`. Moving those
calls to a worker thread can keep an event loop responsive, but it does not
turn their socket operations into cancellable async I/O. Python documents
[`asyncio.to_thread()`](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread)
as a way to run blocking work separately. That is not the native async contract
we are choosing here.

Native async would require either an async-capable HTTP engine dependency or
substantial new connection/protocol handling in this file. Neither tradeoff is
accepted by the current zero-dependency, small-core decision. Do not slip one
in behind a convenient method name.

Before selecting an engine, work through:

1. **Cancellation:** DNS, connect, TLS, response headers, body reads, and waiting
   for a connection. Cleanup must not swallow cancellation or make an unfinished
   connection available to another task. Cancellation cannot undo server actions.
2. **Concurrency:** a bound on active connections and queued work, with a stated
   timeout policy while waiting. The synchronous session's cache size is not a
   concurrency limit and its sequential guard is not an async pool.
3. **Shared state:** cookie updates and session defaults across concurrent
   requests, plus the lifetime of sessions relative to the event loop.
4. **Protocol parity:** redirects, proxy tunnels, TLS verification, framing,
   truncated bodies, and bounded gzip decoding.
5. **Common implementation:** share pure request/response policy and types;
   keep the transport and scheduling differences explicit. Test the same HTTP
   contracts for each engine, with extra cancellation and concurrency tests.

**Recommendation:** use streaming's ownership rules as the foundation. Revisit
native async when we are ready to make the engine tradeoff explicitly. Until
then, fetch.py's supported execution model remains synchronous.

[Back to design notes](README.md)
