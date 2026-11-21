import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import {
  Flexen,
  InsufficientCreditsError,
  InternalServerError,
  InvalidRequestError,
  RateLimitError,
  ServerTimeoutError,
  ServiceUnavailableError,
  computeRetryDelay,
  parseRetryAfter,
  type APIError,
} from '../src/index.js'
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
  client = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url, retry: { baseDelayMs: 1, maxDelayMs: 4 } })
})

const ok = { status: 200, headers: OK_HEADERS, json: { credits_remaining: 7 } }
const err = (status: number, code: string, headers: Record<string, string> = {}) => ({ status, headers, json: errorBody(code) })

describe('automatic retries', () => {
  it('retries 503 and returns the later success', async () => {
    fake.queue(err(503, 'service_unavailable'), err(503, 'service_unavailable'), ok)
    const res = await client.account.balance()
    expect(res.data).toEqual({ credits_remaining: 7 })
    expect(fake.requests).toHaveLength(3)
  })

  it('retries 429 and honours Retry-After', async () => {
    fake.queue(err(429, 'rate_limited', { 'Retry-After': '1' }), ok)
    const t0 = Date.now()
    await client.account.balance()
    expect(Date.now() - t0).toBeGreaterThanOrEqual(1000)
    expect(fake.requests).toHaveLength(2)
  })

  it('stops after 3 retries (4 attempts) and throws the last error', async () => {
    fake.handle(() => err(503, 'service_unavailable'))
    const e = await client.account.balance().catch((x: unknown) => x)
    expect(e).toBeInstanceOf(ServiceUnavailableError)
    expect(fake.requests).toHaveLength(4)
  })

  it('maxRetries 0 turns retries off', async () => {
    fake.handle(() => err(429, 'rate_limited'))
    const e = await client.account.balance({ maxRetries: 0 }).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(RateLimitError)
    expect(fake.requests).toHaveLength(1)
  })

  it('does not wait when Retry-After is longer than maxRetryAfterMs', async () => {
    const c = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url, retry: { maxRetryAfterMs: 500 } })
    fake.handle(() => err(429, 'rate_limited', { 'Retry-After': '30' }))
    const e = (await c.account.balance().catch((x: unknown) => x)) as APIError
    expect(e).toBeInstanceOf(RateLimitError)
    expect(e.retryAfterSeconds).toBe(30)
    expect(fake.requests).toHaveLength(1)
  })

  for (const [status, code, Cls] of [
    [402, 'insufficient_credits', InsufficientCreditsError],
    [422, 'invalid_request', InvalidRequestError],
    [500, 'internal_error', InternalServerError],
    [504, 'timeout', ServerTimeoutError],
  ] as const) {
    it(`never retries ${status} ${code}`, async () => {
      fake.handle(() => err(status, code))
      const e = await client.nutrition.text({ text: 'x' }).catch((x: unknown) => x)
      expect(e).toBeInstanceOf(Cls)
      expect(fake.requests).toHaveLength(1)
    })
  }

  it('sends the same Idempotency-Key on every attempt', async () => {
    fake.queue(err(503, 'service_unavailable'), err(429, 'rate_limited'), ok)
    await client.nutrition.text({ text: 'Apfel' }, { idempotencyKey: 'idem-123' })
    expect(fake.requests.map((r) => r.headers['idempotency-key'])).toEqual(['idem-123', 'idem-123', 'idem-123'])
  })

  it('sends no Idempotency-Key when none is given', async () => {
    fake.queue(ok)
    await client.nutrition.text({ text: 'Apfel' })
    expect(fake.requests[0]!.headers['idempotency-key']).toBeUndefined()
  })
})

describe('computeRetryDelay', () => {
  const opts = { baseDelayMs: 500, maxDelayMs: 8000, maxRetryAfterMs: 60_000 }

  it('grows exponentially with jitter between 50 and 100 %', () => {
    expect(computeRetryDelay(0, null, opts, () => 0)).toBe(250)
    expect(computeRetryDelay(0, null, opts, () => 1)).toBe(500)
    expect(computeRetryDelay(1, null, opts, () => 1)).toBe(1000)
    expect(computeRetryDelay(2, null, opts, () => 1)).toBe(2000)
    expect(computeRetryDelay(10, null, opts, () => 1)).toBe(8000)
  })

  it('waits at least Retry-After', () => {
    expect(computeRetryDelay(0, 2, opts, () => 0)).toBe(2000)
    expect(computeRetryDelay(0, 2, opts, () => 1)).toBe(2250)
    expect(computeRetryDelay(0, 61, opts, () => 0)).toBeNull()
  })

  it('parses Retry-After as seconds or HTTP date', () => {
    expect(parseRetryAfter('3')).toBe(3)
    expect(parseRetryAfter(null)).toBeNull()
    expect(parseRetryAfter('soon')).toBeNull()
    const now = Date.parse('2026-11-21T12:00:00Z')
    expect(parseRetryAfter('Sat, 21 Nov 2026 12:00:05 GMT', now)).toBe(5)
  })
})
