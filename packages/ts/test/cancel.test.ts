import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { Flexen, RequestTimeoutError, UserAbortError } from '../src/index.js'
import { OK_HEADERS, TEST_KEY, errorBody, startFake, type Fake } from './fake-server.js'

let fake: Fake
let client: Flexen

beforeAll(async () => {
  fake = await startFake()
})
afterAll(async () => {
  await fake.close()
})
beforeEach(() => {
  fake.reset()
  client = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url })
})

describe('cancellation', () => {
  it('AbortSignal cancels a running call with UserAbortError', async () => {
    fake.handle(() => ({ status: 200, headers: OK_HEADERS, json: {}, delayMs: 2000 }))
    const ac = new AbortController()
    setTimeout(() => ac.abort(), 50)
    const t0 = Date.now()
    await expect(client.nutrition.text({ text: 'x' }, { signal: ac.signal })).rejects.toBeInstanceOf(UserAbortError)
    expect(Date.now() - t0).toBeLessThan(1500)
  })

  it('an already aborted signal sends nothing', async () => {
    const ac = new AbortController()
    ac.abort()
    await expect(client.account.balance({ signal: ac.signal })).rejects.toBeInstanceOf(UserAbortError)
    expect(fake.requests).toHaveLength(0)
  })

  it('timeoutMs cancels with RequestTimeoutError', async () => {
    fake.handle(() => ({ status: 200, headers: OK_HEADERS, json: {}, delayMs: 2000 }))
    const e = await client.nutrition.text({ text: 'x' }, { timeoutMs: 100 }).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(RequestTimeoutError)
  })

  it('the client timeout covers retry waits too', async () => {
    const c = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url, timeoutMs: 300 })
    fake.handle(() => ({ status: 429, headers: { 'Retry-After': '5' }, json: errorBody('rate_limited') }))
    const t0 = Date.now()
    const e = await c.account.balance().catch((x: unknown) => x)
    expect(e).toBeInstanceOf(RequestTimeoutError)
    expect(Date.now() - t0).toBeLessThan(2000)
    expect(fake.requests).toHaveLength(1)
  })

  it('aborting during a retry wait stops further attempts', async () => {
    fake.handle(() => ({ status: 503, headers: { 'Retry-After': '5' }, json: errorBody('service_unavailable') }))
    const ac = new AbortController()
    setTimeout(() => ac.abort(), 100)
    await expect(client.account.balance({ signal: ac.signal })).rejects.toBeInstanceOf(UserAbortError)
    await new Promise((r) => setTimeout(r, 50))
    expect(fake.requests).toHaveLength(1)
  })
})
