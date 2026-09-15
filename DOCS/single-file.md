# Single file

**Status:** implemented contract with release checks. The runtime remains one
standard-library-only source file in both copied and installed forms.

## The point

Someone should be able to take `fetch.py`, put it beside their code, and own
that copy. The file is the product. The repository supplies its documentation,
tests, and release machinery.

## The experience

This layout works with the current module:

```text
my-project/
    app.py
    fetch.py
```

```python
import fetch

response = fetch.get("https://example.com", timeout=5)
print(response.status)
```

For a larger application, the same source file can live in an ordinary package:

```text
myapp/
    __init__.py
    vendor/
        __init__.py
        fetch.py
```

```python
from myapp.vendor import fetch

response = fetch.get("https://example.com", timeout=5)
```

The HTTP API should work the same way in both layouts. A vendored copy should
not depend on its import name being exactly `fetch`.

## What travels with the file

- All runtime implementation and standard-library imports.
- Inline annotations and a visible `__version__`.
- The full license notice; preserve it when copying or modifying the file.
- Useful docstrings, including timeout and error behavior.

No adjacent runtime data files, generated code, package metadata lookups, or
mandatory configuration. Importing the module should not make network requests
or configure the application's logging.

Zero dependencies means zero **third-party Python runtime packages**. The client
still relies on Python, its SSL support, and the certificate trust available to
that Python installation. A private CA can be supplied explicitly:

```python
import ssl
import fetch

response = fetch.get(
    "https://service.example.com",
    context=ssl.create_default_context(cafile="company-ca.pem"),
)
```

Copying the file does not bundle Python or certificate roots. The current TLS
behavior follows Python's [default SSL context](https://docs.python.org/3/library/ssl.html#ssl.create_default_context).

## What this means for the API

Prefer ordinary values and explicit arguments. A new feature should remain
understandable when someone encounters its implementation in this file.

Optional integrations can live in application code. The [Pydantic note](pydantic.md)
starts with a model consuming response bytes. The [logging note](logging.md)
uses standard-library logging. Neither makes third-party packages a
condition of importing fetch.py.

Smallness is a maintenance constraint, not a line-count contest. Clear names,
docstrings, and careful HTTP behavior earn their space. A feature that needs a
second subsystem should prompt a scope discussion before implementation.

## Distribution and types

Today, `pyproject.toml` configures the `fetch.py` distribution. The import name
is `fetch`. The distribution name and import name are different things.
Installing both this project and an unrelated distribution that supplies a
`fetch` module can create an import collision; a package-qualified vendored
copy makes ownership explicit.

Inline annotations travel with copied source. Discovering those annotations in
an installed distribution is a separate problem: the typing specification's
`py.typed` mechanism supports packages, not module-only distributions.
[Typing distribution specification](https://typing.python.org/en/latest/spec/distributing.html#packaging-type-information).

The small [`setup.py`](../setup.py) build command places the exact source bytes
at `fetch/__init__.py` in the wheel, alongside `fetch/py.typed`. The marker in
the repository is build input; it is not required when copying the source.
There is no second implementation or generated runtime wrapper.

Normal installs expose the package to mypy and Pyright. Editable installs point
at the original source so edits take effect without rebuilding. When checking
development code, run the checkers from this checkout; package type discovery
is verified against a normal installed wheel.

## Owning updates

A copied file stays at the version you copied. Replacing it is an explicit
application change. Keep a note of the upstream version or commit and any local
edits so fixes can be reviewed and incorporated later.

The release process should publish the canonical file alongside the installable
package, with matching behavior and version. No separate implementation for
people who vendor it.

## Checks that keep the promise

The local suite includes [`tests/test_portability.py`](../tests/test_portability.py), which
copies the file into temporary directories and launches Python with site
packages disabled. Runtime checks cover both plain and qualified imports.
The [CI workflow](../.github/workflows/ci.yml) covers Python 3.11–3.14 on Linux,
macOS, and Windows, using the development tools pinned in `uv.lock`.
[`tests/check_distribution.py`](../tests/check_distribution.py) verifies matching
source bytes in the wheel and sdist, then tests an installed wheel in a clean
environment without third-party runtime packages. It also runs mypy and Pyright
against that installation, outside the checkout, to verify type discovery.

The broader release checks are:

- Copy only the file into a clean directory and make a request to a local server.
- Repeat from a package-qualified import with no third-party packages installed.
- Confirm importing it performs no network I/O and leaves application logging alone.
- Exercise JSON, error responses, timeouts, redirects, and connection cleanup
  through both copied and installed forms.
- Verify installed type discovery and the oldest supported Python version.

**Recommendation:** treat copying the file as a primary distribution path.
Judge each feature by what the person owning that copy would have to understand.

[Back to design notes](README.md)
