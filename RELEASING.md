# Releasing

Status: version 0.1.0 of both packages is prepared. Nothing is published. Publishing is a decision of the account owner.

| Package | Registry | Tag | Job in `.github/workflows/publish.yml` |
| --- | --- | --- | --- |
| `@flexen/api` (`packages/ts`) | npm | `ts-v<version>` | `npm` (environment `npm`) |
| `flexen` (`packages/python`) | PyPI | `py-v<version>` | `pypi` (environment `pypi`) |

Both jobs use trusted publishing (OIDC). The repository holds no registry token. npm adds a provenance statement, PyPI adds attestations.

## One-time setup (account owner)

1. GitHub: create the repository `FlexenApp/flexen-sdks` and push `main`. Trusted publishing with provenance needs a public repository. Under Settings, Environments create `npm` and `pypi`, each with a required reviewer.
2. npm: the scope `@flexen` must belong to you. On 2026-11-22 the registry answered for the scope `flexen` (it exists, as a user or an organisation, with no public packages) and had no package `@flexen/api`. If the scope is not yours, pick another name before the first release (free on that day: scope `flexenapp`, unscoped `flexen` and `flexen-api`) and change `name` in `packages/ts/package.json`, the READMEs and the import in `packages/ts/tsconfig.json` and `examples/`.
3. npm: a trusted publisher is configured on an existing package. Publish 0.1.0 once by hand (see below), then open the package settings, Trusted Publisher, GitHub Actions: organisation or user `FlexenApp`, repository `flexen-sdks`, workflow `publish.yml`, environment `npm`. After that, set publishing access to "require two-factor authentication and disallow tokens".
4. PyPI: Account, Publishing, add a pending publisher: project name `flexen`, owner `FlexenApp`, repository `flexen-sdks`, workflow `publish.yml`, environment `pypi`. A pending publisher creates the project on the first release; the name is only reserved once that release exists.

## Each release

1. `CHANGELOG.md` of the package: move the entries under the new version with the date.
2. Version in both places of the package: `packages/ts/package.json` and `VERSION` in `packages/ts/src/core.ts`; `packages/python/pyproject.toml` and `packages/python/src/flexen/_version.py`. `node scripts/release-version.mjs` checks that they agree.
3. `npm run check:contract`, `npm run test:ts`, `npm run test:python`, `npm run test:scripts`.
4. Commit, then tag and push the tag: `git tag ts-v0.1.0 && git push origin ts-v0.1.0` (and `py-v0.1.0`). The workflow checks that the tag matches the version, runs all tests and publishes after the environment is approved.

Running the workflow by hand (workflow_dispatch) runs the checks and publishes nothing.

## First npm release by hand

```bash
npm login                     # the account that owns the scope, with 2FA
npm run build:ts
npm publish -w @flexen/api --access public --dry-run   # look at the file list
npm publish -w @flexen/api --access public
```

`prepublishOnly` runs type check, tests and build first. A release published by hand has no provenance; every later one from the workflow has.

## Checking the artifacts without publishing

```bash
npm run build:ts && npm pack --dry-run -w @flexen/api
uv build packages/python --out-dir /tmp/flexen-dist && uvx twine check /tmp/flexen-dist/*
```

## License

MIT (`LICENSE`). The API terms say nothing about client libraries, so MIT was chosen as the usual license for SDKs; this choice is open until confirmed.
