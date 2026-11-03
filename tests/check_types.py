"""Static assertions for copied and installed fetch, with optional Pydantic v2.

Run with mypy or Pyright in an environment containing Pydantic.
"""

from collections.abc import Iterator
from typing import assert_type

from pydantic import BaseModel, TypeAdapter

import fetch


class User(BaseModel):
    id: int
    name: str


def check(response: fetch.Response) -> None:
    assert_type(fetch.get("https://example.com", timeout=5), fetch.Response)
    assert_type(fetch.post("https://example.com", json={"name": "Jo"}), fetch.Response)
    assert_type(fetch.get("https://example.com", auth=("user", "pw")), fetch.Response)
    assert_type(response.elapsed, float)
    assert_type(response.history, tuple[fetch.Response, ...])
    assert_type(response.encoding, str | None)
    assert_type(response.parse(int), int)
    assert_type(response.parse(User.model_validate_json), User)
    assert_type(response.parse(TypeAdapter(list[User]).validate_json), list[User])
    assert_type(response.parse(lambda data: User.model_validate_json(data, strict=True)), User)
    with fetch.Session(timeout=5, headers={"Accept": "application/json"}) as session:
        assert_type(session.get("https://example.com", timeout=2), fetch.Response)
        assert_type(session.post("https://example.com", json={"name": "Jo"}), fetch.Response)
        assert_type(session.request("GET", "https://example.com"), fetch.Response)
        assert_type(session.get("https://example.com").parse(User.model_validate_json), User)
        with session.stream("GET", "https://example.com", timeout=2) as stream:
            assert_type(stream, fetch.StreamResponse)
            assert_type(stream.iter_bytes(), Iterator[bytes])
            assert_type(stream.elapsed, float)
            assert_type(stream.history, tuple[fetch.Response, ...])
            assert_type(stream.encoding, str | None)
    with fetch.stream("GET", "https://example.com", auth=("user", "pw")) as stream:
        assert_type(stream.read(), fetch.Response)
        assert_type(stream.read().parse(User.model_validate_json), User)
        assert_type(stream.read().history, tuple[fetch.Response, ...])
