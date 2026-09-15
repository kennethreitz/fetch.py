# Pydantic

**Status: implemented.** Direct composition and `Response.parse(decoder)` work
with the current client. Pydantic v2 remains an optional application dependency.

## Direction

fetch brings back bytes. Your model gives those bytes meaning.

Pydantic belongs to the application: install it there if you want validation.
fetch.py keeps zero runtime dependencies and never imports Pydantic, discovers
models, or changes behavior because a package happens to be installed.

## What already works

Assume an API that returns `{"id": 42, "name": "Jo"}`:

```python
import fetch
from pydantic import BaseModel


class User(BaseModel):
    id: int
    name: str


user_response = fetch.get("https://api.example.com/users/42")
user = User.model_validate_json(user_response.content)
print(user.name)
```

`model_validate_json()` accepts JSON bytes and returns a `User`. There is no
need to call `response.json()` first. JSON validation and Python-object
validation can have different behavior, so choose deliberately.
[Pydantic: validating data](https://docs.pydantic.dev/latest/concepts/models/#validating-data).

For a JSON array, keep and reuse an adapter:

```python
from pydantic import TypeAdapter

users_adapter = TypeAdapter(list[User])
users_response = fetch.get("https://api.example.com/users")
users = users_adapter.validate_json(users_response.content)  # list[User]
```

An adapter validates types such as lists without inventing a wrapper model.
[Pydantic: TypeAdapter](https://docs.pydantic.dev/latest/concepts/type_adapter/).

## Sending a model

```python
user = User(id=42, name="Jo")
response = fetch.post(
    "https://api.example.com/users",
    json=user.model_dump(mode="json"),
)
```

JSON mode produces JSON-compatible values, including conversions for fields
such as dates and UUIDs. The application chooses aliases and excluded fields.
[Pydantic: serialization](https://docs.pydantic.dev/latest/concepts/serialization/).

Pass that value to `json=`, which handles encoding and the content type.
Passing `model_dump_json()` to `json=` would encode the JSON string again.

## A typed convenience

`parse()` gives a decoder the response body and preserves its return type:

```python
user = user_response.parse(User.model_validate_json)  # User
users = users_response.parse(users_adapter.validate_json)  # list[User]
```

The contract is `parse(decoder: Callable[[bytes], T]) -> T`: call the decoder
once with `content` and return its result. Each call runs the decoder again.
There is no intermediate JSON object, registry, model detection, or cache.

Application options remain ordinary Python:

```python
# Reuse the response from the first example.
user = user_response.parse(
    lambda body: User.model_validate_json(body, strict=True),
)
```

Direct calls and `parse()` have the same validation semantics. The generic
decoder also supports other libraries without importing their dependencies.

## Errors and HTTP behavior

- Current requests raise `fetch.HTTPError` for 4xx/5xx by default, before
  validation. Transport failures remain fetch errors.
- With `check_status=False`, inspect `response.status` and deliberately select
  a success or error schema. Parsing never performs another status check.
- Malformed JSON or a failed schema validation raises Pydantic's
  `ValidationError`; `parse()` preserves decoder exceptions.
  Calling fetch's existing `json()` instead uses `fetch.DecodeError` for bad JSON.
- Empty bodies, including a 204 response, are not silently converted to `None`.
  Decide whether to validate them at the call site.
- Validation strictness, coercion, and extra-field handling belong to the
  model or validator call. fetch does not set a validation policy.
  [Pydantic: models and validation](https://docs.pydantic.dev/latest/concepts/models/).

## Validation and future questions

- Runtime checks cover model methods, list adapters, strict validation, and
  invalid/empty JSON. Static assertions in [`tests/check_types.py`](../tests/check_types.py)
  cover inferred return types.
- The decoder owns content-type and encoding decisions; fetch passes its
  already buffered body. Streaming validation needs its own design if added.

Related: [single-file boundary](single-file.md).

[Back to design notes](README.md)
