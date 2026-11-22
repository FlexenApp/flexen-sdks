/**
 * Positive controls for the drift check: each kind of contract change must be reported.
 * Run: npm run test:scripts
 */
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { diffPythonSurface, diffSnapshots } from './lib/drift.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const base = JSON.parse(readFileSync(join(root, 'contract', 'snapshot.json'), 'utf8'))
const copy = () => structuredClone(base)

test('identical snapshots: no drift', () => {
  assert.deepEqual(diffSnapshots(base, copy()), [])
})

test('description-only change is not structural drift', () => {
  const b = copy()
  b.schemas.NutritionItem.properties.needs_review.description = 'reworded'
  assert.deepEqual(diffSnapshots(base, b), [])
})

test('reports removed, added and retyped fields, enums and required', () => {
  const b = copy()
  delete b.schemas.NutritionItem.properties.needs_review
  b.schemas.GoalsRequest.properties.body_fat_pct = { type: 'number' }
  b.schemas.GoalsRequest.properties.goal.enum = [...b.schemas.GoalsRequest.properties.goal.enum, 'recomp']
  b.schemas.AccountBalance.properties.credits_remaining.type = 'string'
  b.schemas.NutritionTextRequest.required = ['text', 'lang']
  const d = diffSnapshots(base, b).join('\n')
  assert.match(d, /NutritionItem: field "needs_review" removed/)
  assert.match(d, /GoalsRequest: field "body_fat_pct" added/)
  assert.match(d, /GoalsRequest: field "goal" changed/)
  assert.match(d, /AccountBalance: field "credits_remaining" changed/)
  assert.match(d, /NutritionTextRequest: field "lang" became required/)
})

test('reports nested inline fields (AccountUsage.days[])', () => {
  const b = copy()
  b.schemas.AccountUsage.properties.days.items.properties.tier = { type: 'string' }
  assert.match(diffSnapshots(base, b).join('\n'), /AccountUsage\.days\[\]: field "tier" added/)
})

test('reports operations, parameters, states, error codes, headers and limits', () => {
  const b = copy()
  b.operations.push({ ...b.operations[0], operationId: 'pantryPhoto', id: 'pantry-photo', path: '/v1/pantry/photo' })
  b.operations.find((o) => o.operationId === 'foodsSearch').parameters.push({ name: 'limit', in: 'query', required: false, schema: { type: 'integer' } })
  b.operations.find((o) => o.operationId === 'nutritionPhoto').state = 'planned'
  b.errorCodes.push({ status: 409, code: 'idempotency_conflict', message: 'x' })
  b.responseHeaders.push({ name: 'X-Idempotent-Replay', type: 'string', alsoWithoutKey: false })
  b.limits.imageMaxMiB = 10
  const d = diffSnapshots(base, b).join('\n')
  assert.match(d, /operation pantryPhoto .* added/)
  assert.match(d, /foodsSearch: parameter "limit" added/)
  assert.match(d, /nutritionPhoto: state "[a-z-]+" -> "planned"/)
  assert.match(d, /error code idempotency_conflict \(409\) added/)
  assert.match(d, /responseHeaders changed/)
  assert.match(d, /limits changed/)
})

test('python surface: missing method, missing field, unknown field, error classes', () => {
  const surface = { operations: {}, errorCodes: base.errorCodes.map((c) => c.code) }
  for (const o of base.operations) {
    const fields = o.requestSchema ? Object.keys(base.schemas[o.requestSchema].properties) : o.parameters.map((p) => p.name)
    for (const f of ['sync', 'async']) (surface.operations[o.operationId] ??= {})[f] = { method: o.operationId, params: fields, extra: [] }
  }
  assert.deepEqual(diffPythonSurface(base, surface), [])
  delete surface.operations.accountBalance.async
  surface.operations.nutritionText.sync.params = ['text', 'lang', 'tier', 'model', 'extra_field']
  surface.errorCodes = surface.errorCodes.slice(1)
  const d = diffPythonSurface(base, surface).join('\n')
  assert.match(d, /python async: no method for accountBalance/)
  assert.match(d, /nutritionText lacks contract field\(s\) .*custom_foods/)
  assert.match(d, /takes field\(s\) not in the contract: extra_field/)
  assert.match(d, /python: error classes/)
})

test('end to end: a changed snapshot makes check-contract exit 1 and name the field', () => {
  const dir = mkdtempSync(join(tmpdir(), 'flexen-drift-'))
  try {
    const b = copy()
    b.schemas.NutritionTextRequest.properties.portion_hint = { type: 'string' }
    const file = join(dir, 'snapshot.json')
    writeFileSync(file, JSON.stringify(b))
    const r = spawnSync(process.execPath, [join(root, 'scripts', 'check-contract.mjs'), '--snapshot', file, '--offline', '--skip-ts'], { encoding: 'utf8' })
    assert.equal(r.status, 1, r.stdout + r.stderr)
    assert.match(r.stdout, /codegen: .*contract\.ts is not what/)
    assert.match(r.stdout, /Flexen\.nutrition\.text lacks contract field\(s\) portion_hint/)
    assert.match(r.stdout, /AsyncFlexen\.nutrition\.text lacks contract field\(s\) portion_hint/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
