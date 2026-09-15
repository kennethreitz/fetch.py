# [name TBD]

> A punk-rock HTTP client for Python — how you'd build Requests today if you
> were starting fresh.

**One readable Python file. Install it, copy it into your project, make it yours.**

**Status:** README-driven design. These examples describe the API we want to
build. The name, engine, and concurrency model are still open.

**Working titles:** `fetchy` · `wire` · `ask`. These are naming directions;
all three already have PyPI projects. See [Name](#name).

## Why

[Requests](https://requests.readthedocs.io/) taught a generation that HTTP could
feel human. The world moved on: HTTP/2, HTTP/3, async everywhere, typing as a
default. That deserves a fresh look at what an HTTP client should be.

A spiritual successor with a different spine:

- **Humane** — one obvious way to GET/POST and read a body.
- **Punk** — tiny core, ruthless defaults, no cathedral.
- **Modern** — typed from day one; streaming and concurrency considered before
  the API hardens.
- **Honest** — clear limits, visible dependencies, optional pieces that compose
  without taking over your application.

## Priorities (non-negotiable)

1. Clarity over cleverness.
2. Small, copyable core over kitchen sink.
3. A finite timeout by default, with an explicit override.
4. Types that help, not ceremony.
5. Docs a stranger can use in under a minute.

## Quickstart (target API)

`fetchy` is a placeholder import name throughout these examples.

```python
from fetchy import get, post

r = get("https://httpbin.org/get", params={"q": "punk"})
r.raise_for_status()
print(r.json())

r = post(
    "https://httpbin.org/post",
    json={"hello": "world"},
    timeout=10,
)
r.raise_for_status()
print(r.status_code, r.text[:80])
```

One response type, with `status_code`, case-insensitive `headers`, `content`
(bytes), `text`, and `json()`.

This sketch uses **explicit status checking**: an HTTP response is returned
even for 4xx or 5xx; `raise_for_status()` turns those statuses into exceptions.
Connection failures and timeouts raise when the request cannot complete.

### Session-shaped reuse

```python
from fetchy import Session

with Session(headers={"User-Agent": "punk/0.1"}) as s:
    print(s.get("https://example.com").status_code)
```

A session gives repeated calls an explicit home for shared configuration and
connection reuse. The context manager owns cleanup. The same request options
should mean the same thing inside and outside a session.

## Design notes

### One file

Copying the core into a project is a supported use case, not a build trick.
Package metadata, tests, and docs can live around it; the implementation should
remain one readable source file.

One file and zero dependencies are separate promises. Dependency-free is
appealing, but the engine decision must make clear what copying the file
requires. Packaging and typing support should serve this shape.

### Sync / async

Pick one coherent story and document it with examples before scaffolding.
The examples above sketch synchronous usage; they do not settle the execution
model.

Streaming, concurrency, cancellation, and resource ownership belong in that
design conversation. Decide what happens when a caller stops reading or cancels
a request before committing to the API.

### Engine

Use the standard library where it fits. If an HTTP engine earns a dependency,
explain why in one paragraph: what it provides, what it costs, and how it affects
the single-file experience.

HTTP/2 and HTTP/3 are part of the design context, not promises of v0 support.
Document the supported protocols when choosing the engine.

### Defaults

- Every request has a finite timeout. Define the default duration and whether
  the limit applies to individual operations or the whole request.
- HTTPS verifies certificates by default.
- Redirect behavior and credential handling are documented.
- Retries are explicit, especially when a request can change server state.
- Proxy and environment behavior are visible choices.
- Error responses remain inspectable when status checking raises.

### Extensions

Keep integrations optional and ordinary. An extension should solve a specific
problem, declare its dependencies, and compose with the core through a small,
documented boundary. Add boundaries when real use cases justify them.

### What this is not

- A drop-in Requests clone.
- HTTPX with different branding.
- A microservice framework.
- A place to hide magic globals.

## Roadmap (v0)

- [ ] Agree on the examples and response/error contract.
- [ ] Choose the sync/async story, engine, and supported Python versions.
- [ ] Design streaming and cancellation behavior; define what ships in v0.
- [ ] Choose distribution and import names; verify PyPI availability.
- [ ] Package the single module with `pyproject.toml` and discoverable inline types.
- [ ] GET/POST, JSON, and finite timeouts.
- [ ] Session with explicit configuration, reuse, and cleanup.
- [ ] Small local tests: a 200, JSON, an HTTP error, a timeout, and cleanup.
- [ ] Settle the license: MIT or Apache-2.0.
- [ ] Publish a usable first release with real install and copy-in instructions.

## Name

The public package and import names are **TBD**. PyPI already has projects named
[`fetch`](https://pypi.org/project/fetch/),
[`fetchy`](https://pypi.org/project/fetchy/),
[`wire`](https://pypi.org/project/wire/), and
[`ask`](https://pypi.org/project/ask/) (checked September 14, 2026).

The local file can still feel like `fetch.py`; the published name needs its own
identity. Examples use `fetchy` only as a placeholder, not as an installation
instruction.

## License

TBD: MIT or Apache-2.0.

## Credits

Inspired by the spirit of Requests (Kenneth Reitz): human defaults, readable
code, respect for the person at the keyboard.

**Punk ≠ rude. Punk = no bloat, no apology for wanting simple tools.**
