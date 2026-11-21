# Changelog

All notable changes to `@flexen/api`. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-21

### Added

- `Flexen` client for Node 22+ and browsers (fetch, ESM, no runtime dependencies).
- Methods for every endpoint of the contract that is not marked "later": nutrition text, photo (beta) and correct; food search and barcode; goal calculator; catalog foods and recipes (upsert, list, iterate, get, delete), delete all and export; account balance and usage.
- Types generated from the contract (website `src/content/developers/api.ts` and `openapi.ts` @ 2892864), including `OPERATIONS`, `NOT_AVAILABLE`, `LIMITS`, `ERROR_CODES`.
- Error classes per contract error code with `requestId`, `apiMessage`, credit headers and `retryAfterSeconds`.
- `FlexenResponse` with `creditsCharged`, `creditsRemaining`, `requestId`.
- Retries for 429 and 503 only (max 3, exponential backoff with jitter, honours `Retry-After`), total timeout, `AbortSignal`, `idempotencyKey` (`Idempotency-Key` header).
- Photo input from Base64, bytes, Blob or file path, with the contract's 8 MiB limit checked before sending.
