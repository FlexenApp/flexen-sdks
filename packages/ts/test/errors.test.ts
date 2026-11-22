import { inspect } from 'node:util'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import {
  APIConnectionError,
  APIError,
  AccountSuspendedError,
  AuthenticationError,
  BadRequestError,
  DailyLimitReachedError,
  ERROR_CODES,
  IdempotencyInProgressError,
  IpNotAllowedError,
  KeyBudgetReachedError,
  KeyExpiredError,
  KeyScopeDeniedError,
  MonthlyBudgetReachedError,
  Flexen,
  FlexenError,
  InsufficientCreditsError,
  InternalServerError,
  InvalidRequestError,
  NotFoundError,
  RateLimitError,
  ServerTimeoutError,
  ServiceUnavailableError,
  TierUnavailableError,
  type ErrorCode,
} from '../src/index.js'
import { TEST_KEY, errorBody, startFake, type Fake } from './fake-server.js'

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
  client = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url, retry: { baseDelayMs: 1, maxDelayMs: 2 } })
})

const EXPECTED: Record<ErrorCode, new (...a: never[]) => APIError> = {
  invalid_json: BadRequestError,
  invalid_key: AuthenticationError,
  insufficient_credits: InsufficientCreditsError,
  daily_limit_reached: DailyLimitReachedError,
  monthly_budget_reached: MonthlyBudgetReachedError,
  key_budget_reached: KeyBudgetReachedError,
  account_suspended: AccountSuspendedError,
  key_expired: KeyExpiredError,
  key_scope_denied: KeyScopeDeniedError,
  ip_not_allowed: IpNotAllowedError,
  not_found: NotFoundError,
  idempotency_in_progress: IdempotencyInProgressError,
  invalid_request: InvalidRequestError,
  tier_unavailable: TierUnavailableError,
  rate_limited: RateLimitError,
  internal_error: InternalServerError,
  service_unavailable: ServiceUnavailableError,
  timeout: ServerTimeoutError,
}

describe('error mapping per contract error code', () => {
  for (const { status, code } of ERROR_CODES) {
    it(`${status} ${code} -> ${EXPECTED[code].name}`, async () => {
      const withKey = code !== 'invalid_key'
      fake.handle(() => ({
        status,
        headers: { 'X-Request-Id': 'req_abc', ...(withKey ? { 'X-Credits-Charged': '0', 'X-Credits-Remaining': '42' } : {}) },
        json: errorBody(code, `server says ${code}`, 'req_abc'),
      }))
      const err = await client.nutrition.text({ text: 'Apfel' }, { maxRetries: 0 }).catch((e: unknown) => e)
      expect(err).toBeInstanceOf(EXPECTED[code])
      expect(err).toBeInstanceOf(APIError)
      expect(err).toBeInstanceOf(FlexenError)
      const e = err as APIError
      expect(e.status).toBe(status)
      expect(e.code).toBe(code)
      expect(e.requestId).toBe('req_abc')
      expect(e.apiMessage).toBe(`server says ${code}`)
      expect(e.message).toContain(`server says ${code}`)
      expect(e.message).toContain('req_abc')
      expect(e.creditsCharged).toBe(withKey ? 0 : null)
      expect(e.creditsRemaining).toBe(withKey ? 42 : null)
      expect(fake.requests).toHaveLength(1)
    })
  }

  it('uses X-Request-Id when the body has no request_id', async () => {
    fake.handle(() => ({ status: 404, headers: { 'X-Request-Id': 'req_hdr' }, json: { error: { code: 'not_found', message: 'nope' } } }))
    const e = (await client.foods.barcode({ code: '4000000000000' }).catch((x: unknown) => x)) as NotFoundError
    expect(e).toBeInstanceOf(NotFoundError)
    expect(e.requestId).toBe('req_hdr')
  })

  it('maps a body that is not the contract format by status', async () => {
    fake.handle(() => ({ status: 502, headers: { 'Content-Type': 'text/html' }, text: '<html>Bad gateway</html>' }))
    const e = (await client.account.balance().catch((x: unknown) => x)) as APIError
    expect(e.constructor).toBe(APIError)
    expect(e.status).toBe(502)
    expect(e.code).toBeNull()
    expect(e.body).toBe('<html>Bad gateway</html>')
  })

  it('maps an unknown code by status (422 -> InvalidRequestError)', async () => {
    fake.handle(() => ({ status: 422, json: errorBody('something_new') }))
    const e = (await client.account.balance().catch((x: unknown) => x)) as APIError
    expect(e).toBeInstanceOf(InvalidRequestError)
    expect(e.code).toBe('something_new')
  })

  it('reports a 200 response that is not JSON', async () => {
    fake.handle(() => ({ status: 200, text: 'not json' }))
    const e = await client.account.balance().catch((x: unknown) => x)
    expect(e).toBeInstanceOf(APIError)
    expect((e as APIError).message).toMatch(/not valid JSON/)
  })

  it('wraps a refused connection in APIConnectionError and does not retry', async () => {
    const dead = new Flexen({ apiKey: TEST_KEY, baseUrl: 'http://127.0.0.1:1' })
    await expect(dead.account.balance()).rejects.toBeInstanceOf(APIConnectionError)
  })
})

describe('API key', () => {
  const saved = process.env.FLEXEN_API_KEY
  afterEach(() => {
    if (saved === undefined) delete process.env.FLEXEN_API_KEY
    else process.env.FLEXEN_API_KEY = saved
  })

  it('is read from FLEXEN_API_KEY by default', async () => {
    process.env.FLEXEN_API_KEY = 'flx_test_fromenv'
    const c = new Flexen({ baseUrl: fake.url })
    fake.handle(() => ({ status: 200, json: { credits_remaining: 1 } }))
    await c.account.balance()
    expect(fake.requests[0]!.headers.authorization).toBe('Bearer flx_test_fromenv')
  })

  it('an explicit key wins over the environment', async () => {
    process.env.FLEXEN_API_KEY = 'flx_test_fromenv'
    const c = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url })
    fake.handle(() => ({ status: 200, json: { credits_remaining: 1 } }))
    await c.account.balance()
    expect(fake.requests[0]!.headers.authorization).toBe(`Bearer ${TEST_KEY}`)
  })

  it('missing key throws without a request', () => {
    delete process.env.FLEXEN_API_KEY
    expect(() => new Flexen({ baseUrl: fake.url })).toThrow(/FLEXEN_API_KEY/)
    expect(fake.requests).toHaveLength(0)
  })

  it('never shows up in inspect, JSON, String or errors', async () => {
    const c = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url, maxRetries: 0 })
    fake.handle(() => ({ status: 401, json: errorBody('invalid_key') }))
    const err = await c.account.balance().catch((e: unknown) => e)
    const secret = TEST_KEY.slice(12)
    for (const text of [inspect(c, { depth: 10, showHidden: true }), JSON.stringify(c), String(c), inspect(err, { depth: 10 }), JSON.stringify(err), String(err)]) {
      expect(text).not.toContain(secret)
    }
  })

  it('shows no part of a short or odd key', () => {
    const c = new Flexen({ apiKey: 'short-secret', baseUrl: fake.url })
    expect(JSON.stringify(c)).not.toContain('short')
    expect(c.transport.apiKeyPrefix).toBe('***')
  })

  it('uses the default base URL https://api.flexen.co', () => {
    const c = new Flexen({ apiKey: TEST_KEY })
    expect(c.transport.baseUrl).toBe('https://api.flexen.co')
  })
})
