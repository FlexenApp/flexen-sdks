/** Prints the contract snapshot of a website checkout as JSON on stdout (used by check-contract.mjs). */
import { resolve } from 'node:path'
import { extractContract } from './extract.ts'

const path = process.argv[2]
if (!path) {
  console.error('usage: tsx scripts/lib/extract-cli.ts <website checkout>')
  process.exit(2)
}
const { snapshot, examples } = await extractContract(resolve(path))
process.stdout.write(JSON.stringify({ snapshot, examples }))
