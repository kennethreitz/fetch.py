"""Optional integration checks; Pydantic belongs to the application."""

import unittest
from datetime import date

import fetch

try:
    import pydantic
except ImportError:
    pydantic = None


@unittest.skipIf(pydantic is None, "optional Pydantic v2 integration")
class PydanticTests(unittest.TestCase):
    def test_models_and_list_adapters_preserve_types(self):
        class User(pydantic.BaseModel):
            id: int
            name: str

        user = fetch.Response(200, fetch.Headers(), b'{"id":42,"name":"Jo"}', "http://example.test")
        self.assertIsInstance(user.parse(User.model_validate_json), User)
        self.assertEqual(user.parse(User.model_validate_json).name, "Jo")
        users = fetch.Response(200, fetch.Headers(), b'[{"id":42,"name":"Jo"}]', user.url)
        parsed = users.parse(pydantic.TypeAdapter(list[User]).validate_json)
        self.assertEqual(len(parsed), 1)
        self.assertIsInstance(parsed[0], User)

    def test_validation_errors_remain_pydantic_errors(self):
        class User(pydantic.BaseModel):
            id: int

        for body in (b"not json", b"{}", b""):
            with self.subTest(body=body):
                response = fetch.Response(200, fetch.Headers(), body, "http://example.test")
                with self.assertRaises(pydantic.ValidationError):
                    response.parse(User.model_validate_json)

    def test_caller_controls_strictness_and_serialization(self):
        class Event(pydantic.BaseModel):
            id: int
            when: date

        response = fetch.Response(
            200, fetch.Headers(), b'{"id":"42","when":"2026-09-14"}', "http://example.test"
        )
        event = response.parse(Event.model_validate_json)
        self.assertEqual(event.model_dump(mode="json"), {"id": 42, "when": "2026-09-14"})
        with self.assertRaises(pydantic.ValidationError):
            response.parse(lambda body: Event.model_validate_json(body, strict=True))


if __name__ == "__main__":
    unittest.main()
