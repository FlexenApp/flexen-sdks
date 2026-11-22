# Changelog

All notable changes to `flexen`. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - not published yet

### Added

- `Flexen` (sync) and `AsyncFlexen` (async) clients for Python 3.10+, on httpx and Pydantic v2.
- Methods for every endpoint of the contract that is not marked "later": nutrition text, photo (beta) and correct; food search and barcode; goal calculator; catalog foods and recipes (upsert, list, iterate, get, delete), delete all and export; account balance and usage.
- Pydantic models generated from the contract (website `src/content/developers/api.ts` and `openapi.ts` @ 2b02040) in `flexen.types`, plus `OPERATIONS`, `NOT_AVAILABLE`, `LIMITS`, `ERROR_CODES`.
- Error classes per contract error code with `request_id`, `message`, credit headers and `retry_after_seconds`.
- `FlexenResponse` with `credits_charged`, `credits_remaining`, `request_id`.
- Retries for 429 and 503 only (max 3, exponential backoff with jitter, honours `Retry-After`), timeout budget per call, task cancellation (async), `idempotency_key` (`Idempotency-Key` header).
- Photo input from a path, bytes, a binary file object or Base64, with the contract's 8 MiB limit checked before sending.
- Per-call settings of the contract on text, photo, correct, search, barcode and goals: `lang` (12 languages), `energy_unit`, `mass_unit`, `volume_unit`, `nutrients`, `provenance`, `hint`, `known_grams`, `country`, `meal`, `venue`, `review_threshold`, `sources`, `exclude_sources`, `model` (also `false` for text), `instructions`, `chain_version`, `tier`, `profile`. Lists in query parameters are sent comma-separated.
- Tiers `light` (default) and `max`. `max` is in the contract but not available yet: with a live key the API answers `422 tier_unavailable`. `TIERS` and `TIER_IDS` list the state per endpoint.
- Error classes for `monthly_budget_reached`, `key_budget_reached`, `key_expired`, `key_scope_denied`, `ip_not_allowed` and `idempotency_in_progress`.
- `idempotent_replayed` on every result (`Idempotent-Replayed` header).
