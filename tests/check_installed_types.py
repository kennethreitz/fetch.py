"""Type discovery checks that need only an installed fetch, without Pydantic."""

from collections.abc import Iterator
from typing import assert_type

import fetch


def check(response: fetch.Response) -> None:
    assert_type(fetch.get("https://example.com"), fetch.Response)
    assert_type(response.parse(int), int)
    with fetch.Session() as session:
        assert_type(session.get("https://example.com"), fetch.Response)
        with session.stream("GET", "https://example.com") as stream:
            assert_type(stream, fetch.StreamResponse)
            assert_type(stream.iter_bytes(), Iterator[bytes])
            assert_type(stream.read(), fetch.Response)

    # Also verify that installed argument types are enforced.
    # mypy --warn-unused-ignores fails if this silently becomes Any.
    fetch.Session(timeout="forever")  # type: ignore[arg-type]
