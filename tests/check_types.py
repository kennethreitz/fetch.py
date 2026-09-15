"""Static assertions for copied and installed fetch, with optional Pydantic v2.

Run with mypy or Pyright in an environment containing Pydantic.
"""

from typing import assert_type

from pydantic import BaseModel, TypeAdapter

import fetch


class User(BaseModel):
    id: int
    name: str


def check(response: fetch.Response) -> None:
    assert_type(fetch.get("https://example.com", timeout=5), fetch.Response)
    assert_type(fetch.post("https://example.com", json={"name": "Jo"}), fetch.Response)
    assert_type(response.parse(int), int)
    assert_type(response.parse(User.model_validate_json), User)
    assert_type(response.parse(TypeAdapter(list[User]).validate_json), list[User])
    assert_type(response.parse(lambda data: User.model_validate_json(data, strict=True)), User)
    with fetch.Session(timeout=5, headers={"Accept": "application/json"}) as session:
        assert_type(session.get("https://example.com", timeout=2), fetch.Response)
        assert_type(session.post("https://example.com", json={"name": "Jo"}), fetch.Response)
        assert_type(session.request("GET", "https://example.com"), fetch.Response)
        assert_type(session.get("https://example.com").parse(User.model_validate_json), User)
