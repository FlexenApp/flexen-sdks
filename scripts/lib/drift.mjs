/**
 * Structural comparison of two contract snapshots and of an SDK surface against a snapshot.
 * Descriptions are compared separately (they change wording, not shape) and only warn.
 */

const IGNORED = new Set(['description', 'summary'])

/** Copy without descriptions (deep). */
export function shape(v) {
  if (Array.isArray(v)) return v.map(shape)
  if (v === null || typeof v !== 'object') return v
  const out = {}
  for (const k of Object.keys(v).sort()) if (!IGNORED.has(k)) out[k] = shape(v[k])
  return out
}

const eq = (a, b) => JSON.stringify(shape(a)) === JSON.stringify(shape(b))
const byKey = (list, key) => new Map(list.map((x) => [x[key], x]))

function compareSchema(name, a, b, out, path = name) {
  if (!a || !b) return
  const pa = a.properties ?? {}
  const pb = b.properties ?? {}
  for (const k of Object.keys(pb)) if (!(k in pa)) out.push(`schema ${path}: field "${k}" added in the contract`)
  for (const k of Object.keys(pa)) if (!(k in pb)) out.push(`schema ${path}: field "${k}" removed from the contract`)
  const ra = new Set(a.required ?? [])
  const rb = new Set(b.required ?? [])
  for (const k of rb) if (!ra.has(k) && k in pa) out.push(`schema ${path}: field "${k}" became required`)
  for (const k of ra) if (!rb.has(k) && k in pb) out.push(`schema ${path}: field "${k}" became optional`)
  for (const k of Object.keys(pa)) {
    if (!(k in pb)) continue
    const x = pa[k]
    const y = pb[k]
    if (x?.properties || y?.properties) compareSchema(name, x, y, out, `${path}.${k}`)
    else if (x?.items?.properties || y?.items?.properties) compareSchema(name, x.items, y.items, out, `${path}.${k}[]`)
    else if (!eq(x, y)) out.push(`schema ${path}: field "${k}" changed (${JSON.stringify(shape(x))} -> ${JSON.stringify(shape(y))})`)
  }
  const restA = { ...a, properties: undefined, required: undefined }
  const restB = { ...b, properties: undefined, required: undefined }
  if (!eq(restA, restB)) out.push(`schema ${path}: changed (${JSON.stringify(shape(restA))} -> ${JSON.stringify(shape(restB))})`)
}

/**
 * Differences from the committed snapshot `a` to the contract `b`, as human-readable lines.
 * Empty = no drift in structure (endpoints, fields, enums, limits, error codes, headers).
 */
export function diffSnapshots(a, b) {
  const out = []
  const oa = byKey(a.operations, 'operationId')
  const ob = byKey(b.operations, 'operationId')
  for (const [id, o] of ob) if (!oa.has(id)) out.push(`operation ${id} (${o.method} ${o.path}, state ${o.state}) added in the contract`)
  for (const [id, o] of oa) if (!ob.has(id)) out.push(`operation ${id} (${o.method} ${o.path}) removed from the contract`)
  for (const [id, x] of oa) {
    const y = ob.get(id)
    if (!y) continue
    for (const k of ['method', 'path', 'state', 'credits', 'requestSchema', 'responseSchema', 'id']) {
      if (!eq(x[k], y[k])) out.push(`operation ${id}: ${k} ${JSON.stringify(x[k])} -> ${JSON.stringify(y[k])}`)
    }
    const pa = byKey(x.parameters, 'name')
    const pb = byKey(y.parameters, 'name')
    for (const n of pb.keys()) if (!pa.has(n)) out.push(`operation ${id}: parameter "${n}" added`)
    for (const n of pa.keys()) if (!pb.has(n)) out.push(`operation ${id}: parameter "${n}" removed`)
    for (const [n, p] of pa) if (pb.has(n) && !eq(p, pb.get(n))) out.push(`operation ${id}: parameter "${n}" changed`)
    if (!eq(x.errorStatuses, y.errorStatuses)) out.push(`operation ${id}: error statuses ${x.errorStatuses} -> ${y.errorStatuses}`)
    if (!eq(x.tiers, y.tiers)) out.push(`operation ${id}: tiers changed`)
  }
  const ua = byKey(a.unavailable, 'id')
  const ub = byKey(b.unavailable, 'id')
  for (const [id, e] of ub) if (!ua.has(id)) out.push(`not-available endpoint ${id} (${e.path}) added`)
  for (const [id, e] of ua) if (!ub.has(id)) out.push(`not-available endpoint ${id} (${e.path}) is no longer 'later'`)
  for (const n of Object.keys(b.schemas)) if (!(n in a.schemas)) out.push(`schema ${n} added in the contract`)
  for (const n of Object.keys(a.schemas)) if (!(n in b.schemas)) out.push(`schema ${n} removed from the contract`)
  for (const n of Object.keys(a.schemas)) if (n in b.schemas) compareSchema(n, a.schemas[n], b.schemas[n], out)
  const ea = byKey(a.errorCodes, 'code')
  const eb = byKey(b.errorCodes, 'code')
  for (const [c, e] of eb) if (!ea.has(c)) out.push(`error code ${c} (${e.status}) added in the contract`)
  for (const [c] of ea) if (!eb.has(c)) out.push(`error code ${c} removed from the contract`)
  for (const [c, e] of ea) if (eb.has(c) && eb.get(c).status !== e.status) out.push(`error code ${c}: status ${e.status} -> ${eb.get(c).status}`)
  for (const k of ['responseHeaders', 'limits', 'sourceIds', 'tierIds', 'defaultTier', 'promptVersion']) {
    if (!eq(a[k], b[k])) out.push(`${k} changed: ${JSON.stringify(a[k])} -> ${JSON.stringify(b[k])}`)
  }
  return out
}

/** Description-only changes (warnings). */
export function diffDescriptions(a, b) {
  const strip = (s) => JSON.stringify({ ...s, source: undefined })
  return strip(a) !== strip(b) && diffSnapshots(a, b).length === 0 ? ['descriptions or summaries changed (run npm run contract:pull to refresh the doc comments)'] : []
}

/** Contract field names a method of an operation must take: body fields, else path and query parameters. */
export function contractFields(snapshot, op) {
  if (op.requestSchema) return Object.keys(snapshot.schemas[op.requestSchema]?.properties ?? {}).sort()
  return op.parameters.map((p) => p.name).sort()
}

/** Compares the Python surface (scripts/python_surface.py) with the snapshot. */
export function diffPythonSurface(snapshot, surface) {
  const out = []
  const ops = new Map(snapshot.operations.map((o) => [o.operationId, o]))
  for (const [id, op] of ops) {
    for (const flavour of ['sync', 'async']) {
      const m = surface.operations[id]?.[flavour]
      if (!m) {
        out.push(`python ${flavour}: no method for ${id} (${op.method} ${op.path})`)
        continue
      }
      const extra = new Set(m.extra)
      const have = m.params.filter((p) => !extra.has(p)).map((p) => p.replace(/_$/, '')).sort()
      const want = contractFields(snapshot, op)
      const missing = want.filter((f) => !have.includes(f))
      const unknown = have.filter((f) => !want.includes(f))
      if (missing.length) out.push(`python ${flavour}: ${m.method} lacks contract field(s) ${missing.join(', ')}`)
      if (unknown.length) out.push(`python ${flavour}: ${m.method} takes field(s) not in the contract: ${unknown.join(', ')}`)
    }
  }
  for (const id of Object.keys(surface.operations)) if (!ops.has(id)) out.push(`python: methods bind ${id}, which is not in the contract`)
  const want = snapshot.errorCodes.map((c) => c.code).sort()
  const have = [...surface.errorCodes].sort()
  if (JSON.stringify(want) !== JSON.stringify(have)) out.push(`python: error classes ${have.join(',')} vs contract codes ${want.join(',')}`)
  return out
}
