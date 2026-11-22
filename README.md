# Flexen API SDKs

Official clients for the Flexen API.

| Package | Directory | Docs |
| --- | --- | --- |
| `@flexen/api` (TypeScript, Node 22+ and browsers) | `packages/ts` | [English](packages/ts/README.md), [Deutsch](packages/ts/README.de.md) |
| `flexen` (Python 3.10+, sync and async) | `packages/python` | [English](packages/python/README.md), [Deutsch](packages/python/README.de.md) |

## Contract

The source of truth is the public contract on the website: `src/content/developers/api.ts` and `openapi.ts`. This repo keeps a structural snapshot of it and generates the SDK types from that snapshot.

| File | Role |
| --- | --- |
| `contract/snapshot.json` | endpoints, schemas, error codes, headers, limits (German texts and examples stripped) |
| `contract/examples.json` | request and response examples of the contract, used as test fixtures |
| `scripts/pull-contract.ts` | `npm run contract:pull -- <website checkout>` refreshes both files |
| `scripts/generate.mjs` | `npm run generate` writes `packages/ts/src/generated/contract.ts` and `packages/python/src/flexen/_generated.py` |
| `scripts/check-contract.mjs` | `npm run check:contract` fails on drift (see below) |

### Drift check

`npm run check:contract -- [--contract <website checkout>] [--offline]` checks four things and names its scope in the output:

1. contract: the website's contract against `contract/snapshot.json` (operations, parameters, fields, required, enums, limits, error codes, headers, not-available endpoints). Wording changes in descriptions only warn.
2. codegen: the generated files are what the snapshot generates.
3. ts: `tsc` over the SDK and its tests. A new operation or error code in the generated types breaks the build until it has an SDK binding and a test.
4. python: every operation is bound in `Flexen` and `AsyncFlexen` with exactly the contract's field names; every error code has a class.

Without a website checkout (default path `$FLEXEN_CONTRACT_SRC`, else `/Volumes/BuildSSD/worktrees/web-relaunch-2`; the live contract is the branch that is deployed, on 2026-11-22 `leonard/web-qa-fix`) step 1 is skipped and the output says so. `npm run test:scripts` runs positive controls: each kind of contract change must be reported.

After a contract change: `npm run contract:pull`, `npm run generate`, adapt the SDKs, `npm run check:contract`.

## Development

```bash
npm install                      # TypeScript tooling (exact versions, package-lock.json)
npm run test:ts                  # vitest, local fake server, no network
cd packages/python && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.lock && cd ../..
npm run test:python              # pytest, local fake server, no network
npm run test:scripts             # positive controls of the drift check
npm run check:contract
```

## Status

Version 0.1.0 of both packages is prepared against the live contract (website `2b02040`). Nothing is published to npm or PyPI yet, so `npm install @flexen/api` and `pip install flexen` do not work yet. How a release happens: [RELEASING.md](RELEASING.md). License: MIT ([LICENSE](LICENSE)).

Examples: [`packages/ts/examples`](packages/ts/examples), [`packages/python/examples`](packages/python/examples).
