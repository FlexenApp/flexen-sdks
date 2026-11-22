/**
 * Checks that a release tag matches the version of the package it publishes.
 *   node scripts/release-version.mjs ts-v0.1.0   -> packages/ts/package.json and src/core.ts (VERSION)
 *   node scripts/release-version.mjs py-v0.1.0   -> packages/python/pyproject.toml and src/flexen/_version.py
 * Without an argument it only checks that the two places per package agree.
 */
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const read = (p) => readFileSync(join(root, p), 'utf8')
const pick = (text, re, where) => {
  const m = re.exec(text)
  if (!m) throw new Error(`no version found in ${where}`)
  return m[1]
}

export function versions() {
  return {
    ts: [JSON.parse(read('packages/ts/package.json')).version, pick(read('packages/ts/src/core.ts'), /export const VERSION = '([^']+)'/, 'packages/ts/src/core.ts')],
    py: [pick(read('packages/python/pyproject.toml'), /^version = "([^"]+)"/m, 'pyproject.toml'), pick(read('packages/python/src/flexen/_version.py'), /__version__ = "([^"]+)"/, '_version.py')],
  }
}

export function check(tag) {
  const v = versions()
  const problems = []
  for (const [k, [a, b]] of Object.entries(v)) if (a !== b) problems.push(`${k}: ${a} in the package file, ${b} in the source`)
  if (tag !== undefined) {
    const m = /^(ts|py)-v(\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?)$/.exec(tag)
    if (!m) problems.push(`tag ${tag} is not ts-v<version> or py-v<version>`)
    else if (v[m[1]][0] !== m[2]) problems.push(`tag ${tag} does not match version ${v[m[1]][0]} of the ${m[1]} package`)
  }
  return problems
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const problems = check(process.argv[2])
  if (problems.length) {
    for (const p of problems) console.error(p)
    process.exit(1)
  }
  const v = versions()
  console.log(`versions agree: @flexen/api ${v.ts[0]}, flexen ${v.py[0]}`)
}
