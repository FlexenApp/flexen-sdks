import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { Flexen, IMAGE_MAX_BYTES, InvalidInputError, LIMITS, decodedBase64Bytes } from '../src/index.js'
import { EXAMPLES, OK_HEADERS, TEST_KEY, startFake, type Fake } from './fake-server.js'

let fake: Fake
let client: Flexen
let dir: string

beforeAll(async () => {
  fake = await startFake()
  dir = mkdtempSync(join(tmpdir(), 'flexen-ts-photo-'))
})
afterAll(async () => {
  await fake.close()
  rmSync(dir, { recursive: true, force: true })
})
beforeEach(() => {
  fake.reset()
  fake.handle(() => ({ status: 200, headers: { ...OK_HEADERS, 'X-Credits-Charged': '2' }, json: EXAMPLES.nutritionPhoto!.response }))
  client = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url, maxRetries: 0 })
})

/** Tiny JPEG header bytes; the fake does not decode images. */
const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00, 0x01])

describe('photo upload', () => {
  it('limit comes from the contract (8 MiB decoded)', () => {
    expect(LIMITS.imageMaxMiB).toBe(8)
    expect(IMAGE_MAX_BYTES).toBe(8 * 1024 * 1024)
  })

  it('sends bytes as image_base64 with the other fields', async () => {
    const res = await client.nutrition.photo({ image: JPEG, lang: 'de', tier: 'economy' })
    const body = fake.requests[0]!.json as Record<string, unknown>
    expect(body).toEqual({ image_base64: Buffer.from(JPEG).toString('base64'), lang: 'de', tier: 'economy' })
    expect(res.creditsCharged).toBe(2)
    expect(res.data.beta).toBe(true)
  })

  it('reads a file (Node)', async () => {
    const p = join(dir, 'meal.jpg')
    writeFileSync(p, JPEG)
    await client.nutrition.photo({ file: p })
    expect((fake.requests[0]!.json as { image_base64: string }).image_base64).toBe(Buffer.from(JPEG).toString('base64'))
  })

  it('accepts an ArrayBuffer and a Blob', async () => {
    await client.nutrition.photo({ image: JPEG.slice().buffer })
    await client.nutrition.photo({ image: new Blob([JPEG], { type: 'image/jpeg' }) })
    const sent = fake.requests.map((r) => (r.json as { image_base64: string }).image_base64)
    expect(sent).toEqual([Buffer.from(JPEG).toString('base64'), Buffer.from(JPEG).toString('base64')])
  })

  it('passes Base64 with a data URL prefix through unchanged', async () => {
    const b64 = `data:image/jpeg;base64,${Buffer.from(JPEG).toString('base64')}`
    await client.nutrition.photo({ image_base64: b64 })
    expect((fake.requests[0]!.json as { image_base64: string }).image_base64).toBe(b64)
  })

  it('accepts exactly the limit', async () => {
    await client.nutrition.photo({ image: new Uint8Array(IMAGE_MAX_BYTES) })
    expect(fake.requests).toHaveLength(1)
    expect(decodedBase64Bytes((fake.requests[0]!.json as { image_base64: string }).image_base64)).toBe(IMAGE_MAX_BYTES)
  })

  it('rejects one byte over the limit without a request (bytes)', async () => {
    const e = await client.nutrition.photo({ image: new Uint8Array(IMAGE_MAX_BYTES + 1) }).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(InvalidInputError)
    expect(String(e)).toMatch(/8 MiB/)
    expect(fake.requests).toHaveLength(0)
  })

  it('rejects over the limit without a request (Base64 and file)', async () => {
    const big = Buffer.alloc(IMAGE_MAX_BYTES + 3).toString('base64')
    await expect(client.nutrition.photo({ image_base64: big })).rejects.toBeInstanceOf(InvalidInputError)
    const p = join(dir, 'big.jpg')
    writeFileSync(p, Buffer.alloc(IMAGE_MAX_BYTES + 1))
    await expect(client.nutrition.photo({ file: p })).rejects.toBeInstanceOf(InvalidInputError)
    expect(fake.requests).toHaveLength(0)
  })

  it('needs exactly one source', async () => {
    await expect(client.nutrition.photo({} as never)).rejects.toBeInstanceOf(InvalidInputError)
    await expect(client.nutrition.photo({ image: JPEG, image_base64: 'x' } as never)).rejects.toBeInstanceOf(InvalidInputError)
    expect(fake.requests).toHaveLength(0)
  })
})

describe('browser safety', () => {
  it('src has no static import of Node modules (fetch only)', () => {
    const srcDir = fileURLToPath(new URL('../src', import.meta.url))
    const files = readdirSync(srcDir, { recursive: true }).map(String).filter((f) => f.endsWith('.ts'))
    expect(files.length).toBeGreaterThan(3)
    for (const f of files) {
      const text = readFileSync(join(srcDir, f), 'utf8')
      expect(text, f).not.toMatch(/^\s*import[^\n]*from\s+['"](node:|fs|path|http|https|crypto)/m)
    }
  })
})
