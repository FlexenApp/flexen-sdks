/**
 * Pulls the public Flexen API contract out of a website checkout and writes
 *   contract/snapshot.json  (structure: operations, schemas, error codes, headers, limits)
 *   contract/examples.json  (request/response examples, used as test fixtures only)
 *
 * The website is the source of truth (src/content/developers/api.ts and openapi.ts); it is never modified.
 *
 * Usage: npm run contract:pull -- [path to website checkout]
 * Default path: $FLEXEN_CONTRACT_SRC, else /Volumes/BuildSSD/worktrees/web-relaunch-2
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { extractContract } from './lib/extract.ts'

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const json = (v: unknown): string => JSON.stringify(v, null, 2) + '\n'

const websitePath = resolve(process.argv[2] ?? process.env.FLEXEN_CONTRACT_SRC ?? '/Volumes/BuildSSD/worktrees/web-relaunch-2')
const { snapshot, examples } = await extractContract(websitePath)
mkdirSync(join(repoRoot, 'contract'), { recursive: true })
writeFileSync(join(repoRoot, 'contract', 'snapshot.json'), json(snapshot))
writeFileSync(join(repoRoot, 'contract', 'examples.json'), json(examples))
const s = snapshot as { source: { commit: string; dirty: boolean }; operations: unknown[]; unavailable: unknown[] }
console.log(
  `contract/ written from ${websitePath} @ ${s.source.commit.slice(0, 9)}${s.source.dirty ? ' (uncommitted changes in src/content/developers)' : ''}: ` +
    `${s.operations.length} operations, ${s.unavailable.length} not available`,
)
