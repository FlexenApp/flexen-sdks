# Changelog

All notable changes to `@flexen/api`. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - not published yet

### Added

- `Flexen` client for Node 22+ and browsers (fetch, ESM, no runtime dependencies).
- Methods for every endpoint of the contract that is not marked "later": nutrition text, photo (beta) and correct; food search and barcode; goal calculator; catalog foods and recipes (upsert, list, iterate, get, delete), delete all and export; account balance and usage.
- Types generated from the contract (website `src/content/developers/api.ts` and `openapi.ts` @ 2b02040), including `OPERATIONS`, `NOT_AVAILABLE`, `LIMITS`, `ERROR_CODES`.
- Error classes per contract error code with `requestId`, `apiMessage`, credit headers and `retryAfterSeconds`.
- `FlexenResponse` with `creditsCharged`, `creditsRemaining`, `requestId`.
- Retries for 429 and 503 only (max 3, exponential backoff with jitter, honours `Retry-After`), total timeout, `AbortSignal`, `idempotencyKey` (`Idempotency-Key` header).
- Photo input from Base64, bytes, Blob or file path, with the contract's 8 MiB limit checked before sending.
- Per-call settings of the contract on text, photo, correct, search, barcode and goals: `lang` (12 languages), `energy_unit`, `mass_unit`, `volume_unit`, `nutrients`, `provenance`, `hint`, `known_grams`, `country`, `meal`, `venue`, `review_threshold`, `sources`, `exclude_sources`, `model` (also `false` for text), `instructions`, `chain_version`, `tier`, `profile`. Lists in query parameters are sent comma-separated.
- Tiers `light` (default) and `max`. `max` is in the contract but not available yet: with a live key the API answers `422 tier_unavailable`. `TIERS` and `TIER_IDS` list the state per endpoint.
- Error classes for `monthly_budget_reached`, `key_budget_reached`, `key_expired`, `key_scope_denied`, `ip_not_allowed` and `idempotency_in_progress`.
- `idempotentReplayed` on every result (`Idempotent-Replayed` header).
