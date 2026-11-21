import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { Flexen, NOT_AVAILABLE, OPERATIONS, type FlexenResponse, type OperationId } from '../src/index.js'
import { EXAMPLES, OK_HEADERS, TEST_KEY, startFake, type Fake } from './fake-server.js'

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
  client = new Flexen({ apiKey: TEST_KEY, baseUrl: fake.url, maxRetries: 0 })
})

const ex = (op: OperationId) => EXAMPLES[op]!
const body = <T>(op: OperationId) => ex(op).request as T
const params = <T>(op: OperationId) => ex(op).params as T

/**
 * One call per operation of the contract. Typed as Record<OperationId, ...>: a new operation in the
 * contract (regenerated types) fails the type check until it has an SDK method and a test here.
 */
const CALLS: Record<OperationId, (c: Flexen) => Promise<FlexenResponse<unknown>>> = {
  nutritionText: (c) => c.nutrition.text(body('nutritionText')),
  nutritionPhoto: (c) => c.nutrition.photo({ ...(body('nutritionPhoto') as object), image_base64: 'aGVsbG8=' } as never),
  nutritionCorrect: (c) => c.nutrition.correct(body('nutritionCorrect')),
  foodsSearch: (c) => c.foods.search(params('foodsSearch')),
  foodsBarcode: (c) => c.foods.barcode(params('foodsBarcode')),
  goalsCalculate: (c) => c.goals.calculate(body('goalsCalculate')),
  catalogFoodsPut: (c) => c.catalog.foods.upsert(body('catalogFoodsPut')),
  catalogFoodsList: (c) => c.catalog.foods.list(params('catalogFoodsList')),
  catalogFoodsGet: (c) => c.catalog.foods.get('rezept-linsensuppe'),
  catalogFoodsDelete: (c) => c.catalog.foods.delete('sku-10482'),
  catalogRecipesPut: (c) => c.catalog.recipes.upsert({ recipes: [{ id: 'r1', name: 'Linsensuppe', per_100g: { kcal: 92, protein_g: 5.4, carbs_g: 11.8, fat_g: 2 } }] }),
  catalogRecipesList: (c) => c.catalog.recipes.list(),
  catalogRecipesGet: (c) => c.catalog.recipes.get('r1'),
  catalogRecipesDelete: (c) => c.catalog.recipes.delete('r1'),
  catalogDelete: (c) => c.catalog.deleteAll(),
  catalogExport: (c) => c.catalog.export(),
  accountBalance: (c) => c.account.balance(),
  accountUsage: (c) => c.account.usage(params('accountUsage')),
}

describe('every operation of the contract', () => {
  for (const op of Object.keys(OPERATIONS) as OperationId[]) {
    it(`${op}: ${OPERATIONS[op].method} ${OPERATIONS[op].path}`, async () => {
      const response = ex(op).response ?? { ok: true }
      fake.queue({ status: 200, headers: OK_HEADERS, json: response })
      const res = await CALLS[op](client)
      expect(fake.requests).toHaveLength(1)
      const req = fake.requests[0]!
      expect(req.method).toBe(OPERATIONS[op].method)
      expect(req.headers.authorization).toBe(`Bearer ${TEST_KEY}`)
      const expectedPath = OPERATIONS[op].path.replace(/\{(\w+)\}/g, (_, name: string) => {
        if (name === 'id') return op.startsWith('catalogFoods') ? (op === 'catalogFoodsGet' ? 'rezept-linsensuppe' : 'sku-10482') : 'r1'
        return String(ex(op).params[name])
      })
      expect(req.path).toBe(expectedPath)
      for (const q of OPERATIONS[op].queryParams as readonly string[]) {
        const want = ex(op).params[q]
        if (want !== undefined) expect(req.query[q]).toBe(String(want))
      }
      if (OPERATIONS[op].hasBody) {
        expect(req.headers['content-type']).toBe('application/json')
        if (op !== 'nutritionPhoto' && op !== 'catalogRecipesPut') expect(req.json).toEqual(ex(op).request)
      } else {
        expect(req.body).toBe('')
      }
      expect(res.data).toEqual(response)
      expect(res.status).toBe(200)
      expect(res.requestId).toBe('req_test_1')
      expect(res.creditsCharged).toBe(1)
      expect(res.creditsRemaining).toBe(18341)
    })
  }
})

describe('response headers', () => {
  it('are null when missing or not an integer', async () => {
    fake.queue({ status: 200, headers: { 'X-Credits-Charged': 'abc' }, json: { credits_remaining: 5 } })
    const res = await client.account.balance()
    expect(res.creditsCharged).toBeNull()
    expect(res.creditsRemaining).toBeNull()
    expect(res.requestId).toBeNull()
  })

  it('reads 0 credits on free endpoints', async () => {
    fake.queue({ status: 200, headers: { 'X-Request-Id': 'req_9', 'X-Credits-Charged': '0', 'X-Credits-Remaining': '0' }, json: { credits_remaining: 0 } })
    const res = await client.account.balance()
    expect(res.creditsCharged).toBe(0)
    expect(res.creditsRemaining).toBe(0)
    expect(res.headers.get('x-request-id')).toBe('req_9')
  })
})

describe('parameters', () => {
  it('encodes path parameters', async () => {
    fake.queue({ status: 200, headers: OK_HEADERS, json: { id: 'a/b c', deleted: true } })
    await client.catalog.foods.delete('a/b c')
    expect(fake.requests[0]!.url).toBe('/v1/catalog/foods/a%2Fb%20c')
  })

  it('leaves out query parameters that are not set', async () => {
    fake.queue({ status: 200, headers: OK_HEADERS, json: { items: [] } })
    await client.catalog.foods.list({})
    expect(fake.requests[0]!.url).toBe('/v1/catalog/foods')
  })

  it('rejects an empty id before sending', async () => {
    await expect(client.catalog.foods.get('')).rejects.toThrow(/id is required/)
    expect(fake.requests).toHaveLength(0)
  })

  it('sends text with custom_foods as in the contract example', async () => {
    fake.queue({ status: 200, headers: OK_HEADERS, json: ex('nutritionText').responseExamples.custom_foods })
    const req = ex('nutritionText').requestExamples.custom_foods as Parameters<Flexen['nutrition']['text']>[0]
    const res = await client.nutrition.text(req)
    expect(fake.requests[0]!.json).toEqual(req)
    expect(res.data.items[0]!.source).toBe('customer_inline')
  })
})

describe('catalog iteration', () => {
  it('follows next_cursor until the last page', async () => {
    const food = (id: string) => ({ id, name: id, per_100g: { kcal: 1, protein_g: 0, carbs_g: 0, fat_g: 0 } })
    fake.queue(
      { status: 200, headers: OK_HEADERS, json: { items: [food('a'), food('b')], next_cursor: 'c1' } },
      { status: 200, headers: OK_HEADERS, json: { items: [food('c')] } },
    )
    const ids: string[] = []
    for await (const f of client.catalog.foods.iterate({ q: 'x' })) ids.push(f.id)
    expect(ids).toEqual(['a', 'b', 'c'])
    expect(fake.requests.map((r) => r.url)).toEqual(['/v1/catalog/foods?q=x', '/v1/catalog/foods?q=x&cursor=c1'])
  })
})

describe('not available endpoints', () => {
  it("are the contract's 'later' endpoints and have no operation", () => {
    expect(NOT_AVAILABLE.length).toBeGreaterThan(0)
    const paths = new Set(Object.values(OPERATIONS).map((o) => o.path as string))
    for (const e of NOT_AVAILABLE) {
      expect(e.state).toBe('later')
      expect(paths.has(e.path)).toBe(false)
    }
  })
})
