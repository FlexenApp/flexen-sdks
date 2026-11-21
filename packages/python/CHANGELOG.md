# Changelog

All notable changes to `flexen`. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-21

### Added

- `Flexen` (sync) and `AsyncFlexen` (async) clients for Python 3.10+, on httpx and Pydantic v2.
- Methods for every endpoint of the contract that is not marked "later": nutrition text, photo (beta) and correct; food search and barcode; goal calculator; catalog foods and recipes (upsert, list, iterate, get, delete), delete all and export; account balance and usage.
- Pydantic models generated from the contract (website `src/content/developers/api.ts` and `openapi.ts` @ 2892864) in `flexen.types`, plus `OPERATIONS`, `NOT_AVAILABLE`, `LIMITS`, `ERROR_CODES`.
- Error classes per contract error code with `request_id`, `message`, credit headers and `retry_after_seconds`.
- `FlexenResponse` with `credits_charged`, `credits_remaining`, `request_id`.
- Retries for 429 and 503 only (max 3, exponential backoff with jitter, honours `Retry-After`), timeout budget per call, task cancellation (async), `idempotency_key` (`Idempotency-Key` header).
- Photo input from a path, bytes, a binary file object or Base64, with the contract's 8 MiB limit checked before sending.
