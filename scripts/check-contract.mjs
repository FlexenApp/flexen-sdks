/**
 * Drift check: fails (exit 1) if the SDKs no longer match the public contract.
 *
 *   1. contract  : the website's api.ts/openapi.ts vs contract/snapshot.json (endpoints, fields, enums, limits, codes, headers)
 *   2. codegen   : generated TS types and Pydantic models vs what the snapshot generates today
 *   3. ts        : tsc over src and tests; every OperationId needs an SDK call (typed Record in the tests)
 *   4. python    : every operation bound in Flexen and AsyncFlexen with exactly the contract's field names; error classes per code
 *
 * Usage: npm run check:contract -- [--contract <website checkout>] [--offline] [--snapshot <file>] [--skip-ts] [--skip-python]
 * Default contract path: $FLEXEN_CONTRACT_SRC, else /Volumes/BuildSSD/worktrees/web-relaunch-2.
 * --offline (or a missing default path) skips step 1 and says so; an explicit --contract path must exist.
 */
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { GENERATED, generatePython, generateTs } from './lib/codegen.mjs'
import { diffDescriptions, diffPythonSurface, diffSnapshots } from './lib/drift.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
const flag = (n) => args.includes(n)
const opt = (n) => {
  const i = args.indexOf(n)
  return i >= 0 ? args[i + 1] : undefined
}

const snapshotPath = resolve(opt('--snapshot') ?? join(root, 'contract', 'snapshot.json'))
const snapshot = JSON.parse(readFileSync(snapshotPath, 'utf8'))
const failures = []
const lines = []
const ok = (m) => lines.push(`[ok]   ${m}`)
const skip = (m) => lines.push(`[skip] ${m}`)
const warn = (m) => lines.push(`[warn] ${m}`)
const fail = (step, items) => {
  for (const i of items) failures.push(`${step}: ${i}`)
  lines.push(`[FAIL] ${step}: ${items.length} difference(s)`)
}

// 1. contract
const explicit = opt('--contract')
const contractPath = resolve(explicit ?? process.env.FLEXEN_CONTRACT_SRC ?? '/Volumes/BuildSSD/worktrees/web-relaunch-2')
if (flag('--offline')) {
  skip(`contract: --offline, compared against ${snapshotPath} only (website not read)`)
} else if (!existsSync(join(contractPath, 'src', 'content', 'developers', 'api.ts'))) {
  if (explicit) {
    failures.push(`contract: ${contractPath} has no src/content/developers/api.ts`)
    lines.push(`[FAIL] contract: website checkout not found at ${contractPath}`)
  } else {
    skip(`contract: no website checkout at ${contractPath}; compared against the committed snapshot only`)
  }
} else {
  const r = spawnSync(join(root, 'node_modules', '.bin', 'tsx'), [join(root, 'scripts', 'lib', 'extract-cli.ts'), contractPath], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
  if (r.status !== 0) {
    failures.push(`contract: reading ${contractPath} failed: ${r.stderr.trim().split('\n').slice(-3).join(' | ')}`)
    lines.push('[FAIL] contract: website contract could not be read')
  } else {
    const fresh = JSON.parse(r.stdout).snapshot
    const d = diffSnapshots(snapshot, fresh)
    const at = `${fresh.source.repo} @ ${fresh.source.commit.slice(0, 9)}${fresh.source.dirty ? ' (uncommitted changes)' : ''}`
    if (d.length) fail(`contract (${at})`, d)
    else ok(`contract ${at}: ${fresh.operations.length} operations, ${fresh.unavailable.length} not available, ${Object.keys(fresh.schemas).length} schemas, ${fresh.errorCodes.length} error codes, ${fresh.responseHeaders.length} headers match the snapshot`)
    for (const w of diffDescriptions(snapshot, fresh)) warn(`contract: ${w}`)
    if (fresh.source.commit !== snapshot.source.commit && d.length === 0) warn(`contract: website moved ${snapshot.source.commit.slice(0, 9)} -> ${fresh.source.commit.slice(0, 9)} without structural change`)
  }
}

// 2. codegen
{
  const stale = []
  for (const [lang, gen] of [['ts', generateTs], ['python', generatePython]]) {
    const file = join(root, GENERATED[lang])
    const want = gen(snapshot)
    const have = existsSync(file) ? readFileSync(file, 'utf8') : ''
    if (want !== have) stale.push(`${GENERATED[lang]} is not what ${snapshotPath.replace(root + '/', '')} generates (run npm run generate)`)
  }
  if (stale.length) fail('codegen', stale)
  else ok(`codegen: ${GENERATED.ts} and ${GENERATED.python} are current`)
}

// 3. TypeScript
if (flag('--skip-ts')) {
  skip('ts: --skip-ts')
} else {
  const r = spawnSync(join(root, 'node_modules', '.bin', 'tsc'), ['--noEmit', '-p', join(root, 'packages', 'ts', 'tsconfig.json')], { encoding: 'utf8' })
  if (r.status !== 0) fail('ts (tsc over src and tests)', (r.stdout + r.stderr).trim().split('\n').slice(0, 20))
  else ok(`ts: src and tests compile against the generated types (${snapshot.operations.length} operations need a call in test/endpoints.test.ts)`)
}

// 4. Python
if (flag('--skip-python')) {
  skip('python: --skip-python')
} else {
  const py = join(root, 'packages', 'python', '.venv', 'bin', 'python')
  if (!existsSync(py)) {
    failures.push('python: no venv at packages/python/.venv (see packages/python/README.md) or pass --skip-python')
    lines.push('[FAIL] python: venv missing')
  } else {
    const r = spawnSync(py, [join(root, 'scripts', 'python_surface.py')], { encoding: 'utf8' })
    if (r.status !== 0) {
      fail('python', [`surface dump failed: ${r.stderr.trim().split('\n').slice(-3).join(' | ')}`])
    } else {
      const d = diffPythonSurface(snapshot, JSON.parse(r.stdout))
      if (d.length) fail('python', d)
      else ok(`python: ${snapshot.operations.length} operations bound in Flexen and AsyncFlexen with the contract's field names, ${snapshot.errorCodes.length} error codes mapped`)
    }
  }
}

console.log(lines.join('\n'))
if (failures.length) {
  console.log('\nDRIFT:')
  for (const f of failures) console.log(`  - ${f}`)
  process.exit(1)
}
console.log('\nno drift')
