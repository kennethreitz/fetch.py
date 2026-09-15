# Logging

**Status: implemented.** The client emits standard-library `DEBUG` records.
Output is silent unless the application configures logging to receive them.

## Direction

Use Python's `logging` module. One named logger, small records, no extra
dependency. The application decides where logs go and how they look.

Library setup:

```python
import logging

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())
```

The library leaves levels and propagation alone. It never calls
`basicConfig()`, install an output handler, or configure the root logger.
`NullHandler` keeps an unconfigured application quiet while allowing its
logging configuration to work normally. This follows Python's
[guidance for library logging](https://docs.python.org/3.11/howto/logging.html#configuring-logging-for-a-library).

## Using it

Configure once, at application startup:

```python
import logging
import fetch

console = logging.StreamHandler()
console.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))

log = logging.getLogger("fetch")
log.addHandler(console)
log.setLevel(logging.DEBUG)
log.propagate = False  # this application handles fetch records here

fetch.get("https://example.com", timeout=10)
```

Example output (elapsed time varies):

```text
DEBUG fetch GET example.com started
DEBUG fetch GET example.com completed -> 200 (0.143s)
```

All records use `DEBUG`. A handled 404 or timeout should not
become a second application error report merely because logging is enabled.
Exceptions remain the API for failures.

## Records

Use ordinary `LogRecord` fields through `extra=`, so applications can choose
text or JSON formatting without a fetch-specific adapter. Prefix custom fields
to avoid collisions with logging's reserved attributes.
[Python documents `extra` and its formatting requirements](https://docs.python.org/3.11/library/logging.html#logging.Logger.debug).

| Field | Meaning |
| --- | --- |
| `fetch_event` | `request.started`, `request.redirect`, `request.completed`, `request.closed`, or `request.failed` |
| `fetch_method` | Method for the current hop; terminal records use the final attempted method |
| `fetch_host` | Current destination hostname, without credentials, path, query, or fragment |
| `fetch_status` | Status for this hop, or `None` if no response was received |
| `fetch_elapsed` | Seconds since the logical request started; `0.0` on start |
| `fetch_timeout` | Configured socket-operation timeout, in seconds |
| `fetch_redirects` | Number of redirects already followed |
| `fetch_error` | Exception class name on failure, otherwise `None` |

Every record contains all fields, including `None` for unavailable values.
One start and one terminal record per request, with a record for each redirect
actually followed. Start after argument validation and request serialization;
invalid local inputs raise without generating request records.

For `request.redirect`, method, host, and status describe the response that
triggered the redirect. The next hop may use a different method or host.

## Success, failure, and time

- A buffered response returned to the caller produces `request.completed`.
  This includes a 404 when `check_status=False`, or a redirect when following
  is disabled. Completion means the call returned a response.
- A streaming request produces its terminal record on context exit:
  `request.completed` after full consumption, `request.closed` after early
  closure, or `request.failed` after a transport/body failure. A read failure
  still produces `request.failed` if the application caught it inside the
  context. An application exception is preserved; without a fetch failure,
  the event describes whether the body was consumed or closed early.
  If both body reading and application cleanup fail, the record keeps the body
  failure's type; the application's exception still propagates unchanged.
- An exception raised during the request produces `request.failed`, including
  HTTP status errors, transport failures, timeouts, invalid gzip, and refused
  or exhausted redirects. Keep the status when one was received.
- Calling `response.raise_for_status()`, `.json()`, or `.text` later would not
  create another request record. Those operations happen after the HTTP call.
- Elapsed time covers all hops, reading, and decompression, ending just before
  return or raise. Measure differences with
  [`time.perf_counter()`](https://docs.python.org/3.11/library/time.html#time.perf_counter).
  A request can take longer than `timeout`: the current timeout applies to
  individual socket operations, not the whole request.
  For streams it also includes time the application spends inside the context.

## Keep the record small

No headers, cookies, bodies, full URLs, redirect locations, exception messages,
or tracebacks in these records, even at `DEBUG`. Paths and queries can
contain secrets; existing exception messages can contain URLs. Log the error
type and bounded metadata instead. Hostnames are included; applications can
remove them with their logging filters if needed.

No callbacks, event bus, tracing client, or `fetch.configure_logging()` needed.

## Vendored copies

The logger follows `__name__`: `import fetch` uses `fetch`, while
`from myapp.vendor import fetch` uses `myapp.vendor.fetch`. Configure that name
to keep separately vendored copies independent. Importing fetch only adds a
`NullHandler` to its own logger; it leaves root handlers and levels alone.

## Open questions

- Is a small per-request correlation ID worth adding before concurrency?
- Are terminal records useful enough at `INFO`, or should all remain opt-in
  diagnostics at `DEBUG`?

Related: [single-file contract](single-file.md).

[Back to design notes](README.md)
