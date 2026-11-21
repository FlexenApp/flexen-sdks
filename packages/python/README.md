# flexen

Official Python client for the Flexen API: nutrition from text and photos, food search, barcode lookup, goal calculator, your own food catalog and your account balance.

- Python 3.10+, built on httpx and Pydantic v2
- `Flexen` (sync) and `AsyncFlexen` (async, asyncio)
- Models generated from the public API contract (`contract/snapshot.json` in this repo)
- Typed errors per error code, automatic retries for 429 and 503, timeouts, credit headers on every result

Deutsch: [README.de.md](./README.de.md)

## Quick start

1. Install: `pip install flexen`
2. Set your key: `export FLEXEN_API_KEY=flx_live_…` (create keys in the Flexen console; `flx_test_…` keys return fixed examples and cost nothing)
3. Call the API:

```python
from flexen import Flexen

client = Flexen()  # reads FLEXEN_API_KEY
res = client.nutrition.text("2 slices of wholemeal bread with gouda and an apple")
print(res.data.total.kcal.value, res.data.items[0].needs_review, res.credits_charged, res.credits_remaining)
```

## Examples

### Photo from a file

```python
res = client.nutrition.photo(image_path="lunch.jpg", lang="en")
print(res.data.dish, res.data.kcal, res.data.confidence)

# or bytes (also a binary file object) / Base64
client.nutrition.photo(image_bytes=Path("lunch.jpg").read_bytes())  # from pathlib import Path
client.nutrition.photo(image_base64="data:image/jpeg;base64,/9j/…")
```

The photo may have at most 8 MiB before Base64 encoding (`LIMITS["imageMaxMiB"]`). Larger photos raise `InvalidInputError` before anything is sent. JPEG, PNG and WebP are accepted.

### Food search and barcode

```python
res = client.foods.search("apple", lang="en")
for r in res.data.results:
    print(r.name, r.per_100g.kcal, r.source, r.license)

product = client.foods.barcode("4000000000000")
```

Names come as the source lists them (USDA only in English). Every result names its source and, for open sources, the license and attribution you must show.

### Handling insufficient credits

```python
from flexen import APIError, DailyLimitReachedError, InsufficientCreditsError

try:
    client.nutrition.text("porridge with blueberries")
except InsufficientCreditsError as e:
    print(f"Top up in the console. Balance: {e.credits_remaining}, request {e.request_id}")
except DailyLimitReachedError:
    print("Daily spending limit reached")
except APIError as e:
    print(e.status_code, e.code, e.message, e.request_id)
```

### Async

```python
import asyncio
from flexen import AsyncFlexen

async def main() -> None:
    async with AsyncFlexen() as client:
        res = await client.nutrition.text("banana", timeout=30)
        async for food in client.catalog.foods.iterate():
            print(food.id, food.name)

asyncio.run(main())
```

Cancel an async call by cancelling its task (for example `asyncio.wait_for` or `anyio.move_on_after`). A call cancelled before the response arrives costs nothing.

## Endpoints

| Method | Endpoint | Price (preliminary, credits) |
| --- | --- | --- |
| `nutrition.text(text, ...)` | POST /v1/nutrition/text | 1 |
| `nutrition.photo(image_path= / image_bytes= / image_base64=, ...)` | POST /v1/nutrition/photo (beta) | 2 |
| `nutrition.correct(items, ...)` | POST /v1/nutrition/correct | open, see below |
| `foods.search(q, lang=)` | GET /v1/foods/search | 1 |
| `foods.barcode(code, lang=)` | GET /v1/foods/barcode/{code} | 1 |
| `goals.calculate(sex=, weight_kg=, height_cm=, age=, activity_level=, goal=)` | POST /v1/goals/calculate | 1 |
| `catalog.foods.upsert / list / iterate / get / delete` | /v1/catalog/foods | free |
| `catalog.recipes.upsert / list / iterate / get / delete` | /v1/catalog/recipes | free |
| `catalog.delete_all()` / `catalog.export()` | DELETE /v1/catalog, GET /v1/catalog/export | free |
| `account.balance()` / `account.usage(from_, to)` | /v1/account/… | free |

1 credit = 0.1 cent net. Prices and response field names are preliminary in the contract. `flexen.OPERATIONS` lists method, path, state and price of every endpoint; all contract models are in `flexen.types`.

- The price of `nutrition/correct` is still open in the contract; live keys may get `503 service_unavailable` until it is set.
- Tier `max` is not available yet: the API answers `422 tier_unavailable` (`TierUnavailableError`). Leave out `tier` for `economy`.
- Not available (announced as "later" in the contract, no methods in this SDK): `flexen.NOT_AVAILABLE` lists them (pantry photo, recipe ideas, micronutrients, training plan).

## Results

Every method returns a `FlexenResponse`:

| Attribute | Header / meaning |
| --- | --- |
| `data` | the response as a Pydantic model |
| `credits_charged` | `X-Credits-Charged` (0 with test keys and on free endpoints) |
| `credits_remaining` | `X-Credits-Remaining`; credits reserved for running calls are not yet deducted |
| `request_id` | `X-Request-Id`; include it when you contact Flexen |
| `status_code`, `headers` | HTTP status and all headers |

## Errors

All errors derive from `FlexenError`. Responses with an error status raise an `APIError` subclass with `status_code`, `code`, `message`, `request_id`, `credits_charged`, `credits_remaining` and `retry_after_seconds`:

| Status | Code | Class |
| --- | --- | --- |
| 400 | invalid_json | `BadRequestError` |
| 401 | invalid_key | `AuthenticationError` |
| 402 | insufficient_credits | `InsufficientCreditsError` |
| 402 | daily_limit_reached | `DailyLimitReachedError` |
| 403 | account_suspended | `AccountSuspendedError` |
| 404 | not_found | `NotFoundError` |
| 422 | invalid_request | `InvalidRequestError` |
| 422 | tier_unavailable | `TierUnavailableError` |
| 429 | rate_limited | `RateLimitError` |
| 500 | internal_error | `InternalServerError` |
| 503 | service_unavailable | `ServiceUnavailableError` |
| 504 | timeout | `ServerTimeoutError` |

Client-side: `InvalidInputError` (rejected before sending, including Pydantic validation of the request), `APIConnectionError`, `RequestTimeoutError`, `UnexpectedResponseError` (a 2xx body that does not match the contract).

## Retries, timeouts, idempotency

- Only 429 and 503 are retried, at most 3 times (`max_retries`), with exponential backoff and jitter. `Retry-After` is honoured; if it asks for more than `RetryConfig.max_retry_after` (60 s), the error is raised instead. Nothing else (other 4xx, 500, 504, network errors) is retried. Per the contract, 429 and 503 deduct nothing.
- `timeout` (seconds, default 60) is the time budget of a call including retry waits; `RequestTimeoutError` when it runs out.
- `idempotency_key="…"` is sent as `Idempotency-Key`, the same on every retry. The API honours it from Plan 05 on; before that it is ignored.

```python
client.nutrition.text("banana", timeout=30, max_retries=1, idempotency_key="order-4711-meal-2")
```

## Configuration

```python
from flexen import Flexen, RetryConfig

client = Flexen(
    api_key="flx_live_…",              # default: FLEXEN_API_KEY
    base_url="https://api.flexen.co",  # default
    timeout=60.0,
    max_retries=3,
    retry=RetryConfig(base_delay=0.5, max_delay=8.0, max_retry_after=60.0),
)
```

The key is never logged; `repr(client)` shows only its prefix. Use the client as a context manager (`with Flexen() as client:`) or call `close()` / `await aclose()`.

## Development

```bash
cd packages/python
uv venv --python 3.12 .venv            # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -r requirements-dev.lock
.venv/bin/python -m pytest -q
```

`src/flexen/_generated.py` is generated from the contract (`npm run generate` in the repository root); do not edit it by hand. `npm run check:contract` fails if the SDK drifts from the contract.
