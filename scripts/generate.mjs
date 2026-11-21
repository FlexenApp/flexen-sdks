/**
 * Writes the generated contract types of both SDKs from contract/snapshot.json.
 * Usage: npm run generate
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { GENERATED, generatePython, generateTs } from './lib/codegen.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const snapshot = JSON.parse(readFileSync(join(root, 'contract', 'snapshot.json'), 'utf8'))
writeFileSync(join(root, GENERATED.ts), generateTs(snapshot))
writeFileSync(join(root, GENERATED.python), generatePython(snapshot))
console.log(`generated ${GENERATED.ts} and ${GENERATED.python} from contract @ ${snapshot.source.commit.slice(0, 9)}`)
