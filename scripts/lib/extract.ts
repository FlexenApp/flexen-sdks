/**
 * Reads the contract modules of the website (api.ts, openapi.ts) and turns them into a stable,
 * language-neutral snapshot. Needs tsx (the website modules are TypeScript with JSON imports).
 */
import { execFileSync } from 'node:child_process'
import { basename, join } from 'node:path'
import { pathToFileURL } from 'node:url'

type Json = null | boolean | number | string | Json[] | { [k: string]: Json }
type Obj = Record<string, any>

const STRIP = new Set(['x-description-de', 'example', 'examples', 'x-example-de'])

/** Removes German descriptions and examples (examples go to examples.json, not into the structure). */
export function strip(v: unknown): Json {
  if (Array.isArray(v)) return v.map(strip)
  if (v === null || typeof v !== 'object') return v as Json
  const out: Record<string, Json> = {}
  for (const [k, val] of Object.entries(v as Obj)) {
    if (STRIP.has(k)) continue
    out[k] = strip(val)
  }
  return out
}

const refName = (s: unknown): string | null => {
  const r = (s as Obj | undefined)?.$ref
  return typeof r === 'string' ? r.replace('#/components/schemas/', '') : null
}

function git(path: string, args: string[]): string {
  return execFileSync('git', ['-C', path, ...args], { encoding: 'utf8' }).trim()
}

export interface Extracted {
  snapshot: Obj
  examples: Obj
}

export async function extractContract(websitePath: string): Promise<Extracted> {
  const content = join(websitePath, 'src', 'content', 'developers')
  const api = (await import(pathToFileURL(join(content, 'api.ts')).href)) as Obj
  const { OPENAPI } = (await import(pathToFileURL(join(content, 'openapi.ts')).href)) as Obj

  let commit = 'unknown'
  let dirty = false
  try {
    commit = git(websitePath, ['rev-parse', 'HEAD'])
    dirty = git(websitePath, ['status', '--porcelain', '--', 'src/content/developers']) !== ''
  } catch {
    /* not a git checkout: commit stays unknown */
  }

  const operations: Obj[] = []
  const examples: Obj = {}
  const methods = ['get', 'post', 'delete'] as const
  for (const [p, item] of Object.entries(OPENAPI.paths as Obj).sort(([a], [b]) => a.localeCompare(b))) {
    for (const m of methods) {
      const op = (item as Obj)[m]
      if (!op) continue
      const body = op.requestBody?.content?.['application/json']
      const ok = op.responses?.['200']?.content?.['application/json']
      const tiers = op['x-flexen-tiers'] as Obj[] | undefined
      operations.push({
        operationId: op.operationId,
        id: op['x-flexen-id'],
        method: m.toUpperCase(),
        path: `/v1${p}`,
        state: op['x-flexen-state'],
        credits: op['x-flexen-credits'],
        tag: op.tags?.[0] ?? null,
        summary: op.summary,
        parameters: (op.parameters ?? []).map((x: Obj) => ({ name: x.name, in: x.in, required: x.required, description: x.description, schema: strip(x.schema) })),
        requestSchema: body ? refName(body.schema) : null,
        responseSchema: ok ? refName(ok.schema) : null,
        errorStatuses: Object.keys(op.responses ?? {}).filter((s) => s !== '200').sort(),
        ...(tiers ? { tiers: tiers.map((t) => ({ id: t.id, state: t.state, modelId: t.modelId, credits: t.credits })) } : {}),
      })
      examples[op.operationId] = {
        params: Object.fromEntries((op.parameters ?? []).filter((x: Obj) => x.example !== undefined).map((x: Obj) => [x.name, x.example])),
        request: body?.example ?? null,
        requestExamples: Object.fromEntries(Object.entries(body?.examples ?? {}).map(([k, v]) => [k, (v as Obj).value])),
        response: ok?.example ?? null,
        responseExamples: Object.fromEntries(Object.entries(ok?.examples ?? {}).map(([k, v]) => [k, (v as Obj).value])),
      }
    }
  }

  /* Every endpoint the contract lists that is not 'later' must be an operation; 'later' ones are not available. */
  const all: Obj[] = [...api.ENDPOINTS, ...api.CATALOG_ENDPOINTS, ...(api.ACCOUNT_ENDPOINTS ?? [])]
  const byId = new Map(operations.map((o) => [o.id, o]))
  const unavailable: Obj[] = []
  for (const e of all) {
    if (e.state === 'later') {
      unavailable.push({ id: e.id, method: e.method, path: e.path, state: e.state })
      continue
    }
    const o = byId.get(e.id)
    if (!o || o.method !== e.method || o.path !== e.path) {
      throw new Error(`contract inconsistent: ${e.id} (${e.method} ${e.path}) is in api.ts but not in openapi.ts`)
    }
  }
  for (const o of operations) {
    if (!all.some((e) => e.id === o.id)) throw new Error(`contract inconsistent: ${o.operationId} (${o.id}) is in openapi.ts but not in api.ts`)
  }

  const snapshot = {
    source: { repo: basename(websitePath), files: ['src/content/developers/api.ts', 'src/content/developers/openapi.ts'], commit, dirty },
    info: { title: OPENAPI.info.title, version: OPENAPI.info.version },
    operations,
    unavailable,
    schemas: strip(OPENAPI.components.schemas),
    errorCodes: (api.ERROR_CODES as Obj[]).map((c) => ({ status: Number(c.status), code: c.code, message: c.meaning.en })),
    responseHeaders: (api.RESPONSE_HEADERS as Obj[]).map((h) => ({ name: h.name, type: h.type, alsoWithoutKey: h.alsoWithoutKey })),
    limits: api.LIMITS,
    sourceIds: api.SOURCE_IDS,
    tierIds: api.TIER_IDS,
    defaultTier: api.DEFAULT_TIER,
    promptVersion: api.PROMPT_VERSION,
  }
  return { snapshot: JSON.parse(JSON.stringify(snapshot)), examples }
}
