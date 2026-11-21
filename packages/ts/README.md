# @flexen/api

Official TypeScript client for the Flexen API: nutrition from text and photos, food search, barcode lookup, goal calculator, your own food catalog and your account balance.

- Node 22+ and modern browsers (uses `fetch`), ESM only, zero runtime dependencies
- Types generated from the public API contract (`contract/snapshot.json` in this repo)
- Typed errors per error code, automatic retries for 429 and 503, cancellation, credit headers on every result

Deutsch: [README.de.md](./README.de.md)

## Quick start

1. Install: `npm install @flexen/api`
2. Set your key: `export FLEXEN_API_KEY=flx_live_…` (create keys in the Flexen console; `flx_test_…` keys return fixed examples and cost nothing)
3. Call the API:

```ts
import { Flexen } from '@flexen/api'

const flexen = new Flexen() // reads FLEXEN_API_KEY
const { data, creditsCharged, creditsRemaining } = await flexen.nutrition.text({ text: '2 slices of wholemeal bread with gouda and an apple' })
console.log(data.total.kcal.value, data.items[0].needs_review, creditsCharged, creditsRemaining)
```

## Examples

### Photo from a file

```ts
const res = await flexen.nutrition.photo({ file: './lunch.jpg', lang: 'en' }) // Node only
console.log(res.data.dish, res.data.kcal, res.data.confidence)

// Browser: pass a File/Blob, or bytes, or Base64
await flexen.nutrition.photo({ image: fileInput.files[0] })
await flexen.nutrition.photo({ image_base64: 'data:image/jpeg;base64,/9j/…' })
```

The photo may have at most 8 MiB before Base64 encoding (`LIMITS.imageMaxMiB`). Larger photos throw `InvalidInputError` before anything is sent. JPEG, PNG and WebP are accepted.

### Food search and barcode

```ts
const { data } = await flexen.foods.search({ q: 'apple', lang: 'en' })
for (const r of data.results) console.log(r.name, r.per_100g.kcal, r.source, r.license)

const product = await flexen.foods.barcode({ code: '4000000000000' })
```

Names come as the source lists them (USDA only in English). Every result names its source and, for open sources, the license and attribution you must show.

### Handling insufficient credits

```ts
import { InsufficientCreditsError, DailyLimitReachedError, APIError } from '@flexen/api'

try {
  await flexen.nutrition.text({ text: 'porridge with blueberries' })
} catch (e) {
  if (e instanceof InsufficientCreditsError) {
    console.log(`Top up in the console. Balance: ${e.creditsRemaining}, request ${e.requestId}`)
  } else if (e instanceof DailyLimitReachedError) {
    console.log('Daily spending limit reached')
  } else if (e instanceof APIError) {
    console.log(e.status, e.code, e.apiMessage, e.requestId)
  } else {
    throw e
  }
}
```

## Endpoints

| Method | Endpoint | Price (preliminary, credits) |
| --- | --- | --- |
| `nutrition.text(body)` | POST /v1/nutrition/text | 1 |
| `nutrition.photo(params)` | POST /v1/nutrition/photo (beta) | 2 |
| `nutrition.correct(body)` | POST /v1/nutrition/correct | open, see below |
| `foods.search(params)` | GET /v1/foods/search | 1 |
| `foods.barcode(params)` | GET /v1/foods/barcode/{code} | 1 |
| `goals.calculate(body)` | POST /v1/goals/calculate | 1 |
| `catalog.foods.upsert / list / iterate / get / delete` | /v1/catalog/foods | free |
| `catalog.recipes.upsert / list / iterate / get / delete` | /v1/catalog/recipes | free |
| `catalog.deleteAll()` / `catalog.export()` | DELETE /v1/catalog, GET /v1/catalog/export | free |
| `account.balance()` / `account.usage({ from, to })` | /v1/account/… | free |

1 credit = 0.1 cent net. Prices and response field names are preliminary in the contract. `OPERATIONS` exports method, path, state and price of every endpoint.

- The price of `nutrition/correct` is still open in the contract; live keys may get `503 service_unavailable` until it is set.
- Tier `max` is not available yet: the API answers `422 tier_unavailable` (`TierUnavailableError`). Leave out `tier` for `economy`.
- Not available (announced as "later" in the contract, no methods in this SDK): `NOT_AVAILABLE` lists them (pantry photo, recipe ideas, micronutrients, training plan).

## Results

Every method returns a `FlexenResponse<T>`:

| Field | Header / meaning |
| --- | --- |
| `data` | parsed JSON body, typed |
| `creditsCharged` | `X-Credits-Charged` (0 with test keys and on free endpoints) |
| `creditsRemaining` | `X-Credits-Remaining`; credits reserved for running calls are not yet deducted |
| `requestId` | `X-Request-Id`; include it when you contact Flexen |
| `status`, `headers` | HTTP status and all headers |

## Errors

All errors extend `FlexenError`. Responses with an error status throw an `APIError` subclass with `status`, `code`, `apiMessage`, `requestId`, `creditsCharged`, `creditsRemaining` and `retryAfterSeconds`:

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

Client-side: `InvalidInputError` (rejected before sending), `APIConnectionError`, `RequestTimeoutError`, `UserAbortError`.

## Retries, timeouts, cancellation, idempotency

- Only 429 and 503 are retried, at most 3 times (`maxRetries`), with exponential backoff and jitter. `Retry-After` is honoured; if it asks for more than `retry.maxRetryAfterMs` (60 s), the error is thrown instead. Nothing else (other 4xx, 500, 504, network errors) is retried. Per the contract, 429 and 503 deduct nothing.
- `timeoutMs` (default 60 s) is the total time of a call including retry waits. `RequestTimeoutError` when it runs out.
- Pass `{ signal }` to cancel a call; you get `UserAbortError`. A call cancelled before the response arrives costs nothing.
- `{ idempotencyKey }` is sent as `Idempotency-Key`, the same on every retry. The API honours it from Plan 05 on; before that it is ignored.

```ts
const ac = new AbortController()
const res = await flexen.nutrition.text({ text: 'banana' }, { signal: ac.signal, timeoutMs: 30_000, idempotencyKey: crypto.randomUUID() })
```

## Configuration

```ts
new Flexen({
  apiKey: 'flx_live_…',              // default: process.env.FLEXEN_API_KEY
  baseUrl: 'https://api.flexen.co',  // default
  timeoutMs: 60_000,
  maxRetries: 3,
  retry: { baseDelayMs: 500, maxDelayMs: 8000, maxRetryAfterMs: 60_000 },
  fetch: customFetch,                // optional
})
```

The key is held in a private field and never logged; `JSON.stringify(client)` shows only its prefix. Do not ship a live key in browser code that other people can open: anyone can read it there. Call the API from your server instead.

## Development

From the repository root: `npm install`, `npm run test:ts`, `npm run build:ts`, `npm run check:contract`. The types in `src/generated/contract.ts` are generated (`npm run generate`); do not edit them by hand.
