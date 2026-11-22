import { Transport, type ClientOptions, type FlexenResponse, type RequestOptions } from './core.js'
import type {
  AccountBalance,
  AccountUsage,
  AccountUsageParams,
  CatalogCleared,
  CatalogDeleted,
  CatalogExport,
  CatalogFood,
  CatalogFoodList,
  CatalogFoodsListParams,
  CatalogFoodsRequest,
  CatalogRecipe,
  CatalogRecipeList,
  CatalogRecipesListParams,
  CatalogRecipesRequest,
  CatalogSaveResponse,
  FoodsBarcodeParams,
  FoodSearchResponse,
  FoodsSearchParams,
  GoalsRequest,
  GoalsResponse,
  NutritionCorrectRequest,
  NutritionCorrectResponse,
  NutritionPhotoRequest,
  NutritionPhotoResponse,
  NutritionTextRequest,
  NutritionTextResponse,
  OperationId,
  ProductResponse,
} from './generated/contract.js'
import { toImageBase64, type PhotoSource } from './photo.js'

/** Parameters of nutrition.photo: the fields of NutritionPhotoRequest, with the photo as Base64, bytes or file path. */
export type NutritionPhotoParams = Omit<NutritionPhotoRequest, 'image_base64'> & PhotoSource

type R<T> = Promise<FlexenResponse<T>>

class Nutrition {
  constructor(private readonly t: Transport) {}

  /**
   * POST /v1/nutrition/text: free text to amount, calories and macros.
   * tier: 'light' is the default. 'max' is not available yet: a live key gets TierUnavailableError (422 tier_unavailable).
   */
  text(body: NutritionTextRequest, options?: RequestOptions): R<NutritionTextResponse> {
    return this.t.call('nutritionText', { body, options })
  }

  /**
   * POST /v1/nutrition/photo (beta): photo of a dish to dish, amount and nutrition.
   * Pass image_base64, image (bytes or Blob) or file (path, Node only). The photo may have at most
   * LIMITS.imageMaxMiB MiB before Base64 encoding; larger photos throw InvalidInputError without a request.
   */
  async photo(params: NutritionPhotoParams, options?: RequestOptions): R<NutritionPhotoResponse> {
    const { image_base64: _b, image: _i, file: _f, ...rest } = params as NutritionPhotoParams & { image_base64?: string; image?: unknown; file?: string }
    const image_base64 = await toImageBase64(params)
    const body: NutritionPhotoRequest = { ...rest, image_base64 }
    return this.t.call('nutritionPhoto', { body, options })
  }

  /** POST /v1/nutrition/correct: recalculate items with corrected amounts. No model runs, 0 credits. */
  correct(body: NutritionCorrectRequest, options?: RequestOptions): R<NutritionCorrectResponse> {
    return this.t.call('nutritionCorrect', { body, options })
  }
}

class Foods {
  constructor(private readonly t: Transport) {}

  /** GET /v1/foods/search: your catalog first, then open sources. sources and exclude_sources are sent comma-separated. */
  search(params: FoodsSearchParams, options?: RequestOptions): R<FoodSearchResponse> {
    return this.t.call('foodsSearch', { params: { ...params }, options })
  }

  /** GET /v1/foods/barcode/{code}: 8, 12, 13 or 14 digits. 404 NotFoundError if no product is known. */
  barcode(params: FoodsBarcodeParams, options?: RequestOptions): R<ProductResponse> {
    return this.t.call('foodsBarcode', { params: { ...params }, options })
  }
}

class Goals {
  constructor(private readonly t: Transport) {}

  /** POST /v1/goals/calculate: calories, macros and water from body data and goal (Mifflin-St Jeor). */
  calculate(body: GoalsRequest, options?: RequestOptions): R<GoalsResponse> {
    return this.t.call('goalsCalculate', { body, options })
  }
}

interface PageOf<T> {
  items: T[]
  next_cursor?: string | null
}

class CatalogEntries<Entry, List extends PageOf<Entry>, Upload, ListParams extends { q?: string; cursor?: string }> {
  constructor(
    private readonly t: Transport,
    private readonly ops: { put: OperationId; list: OperationId; get: OperationId; delete: OperationId },
  ) {}

  /** Create or replace entries (the same id replaces). At most LIMITS.catalogUploadMax per call. */
  upsert(body: Upload, options?: RequestOptions): R<CatalogSaveResponse> {
    return this.t.call(this.ops.put, { body, options })
  }

  /** One page of entries; pass next_cursor as cursor for the next page. */
  list(params: ListParams = {} as ListParams, options?: RequestOptions): R<List> {
    return this.t.call(this.ops.list, { params: { ...params }, options })
  }

  /** All entries, page by page (one request per page). */
  async *iterate(params: Omit<ListParams, 'cursor'> = {} as Omit<ListParams, 'cursor'>, options?: RequestOptions): AsyncGenerator<Entry, void, undefined> {
    let cursor: string | undefined
    do {
      const page = await this.list({ ...params, ...(cursor !== undefined ? { cursor } : {}) } as ListParams, options)
      for (const item of page.data.items) yield item
      cursor = page.data.next_cursor ?? undefined
    } while (cursor !== undefined && cursor !== '')
  }

  /** One entry by your id. 404 NotFoundError if it does not exist. */
  get(id: string, options?: RequestOptions): R<Entry> {
    return this.t.call(this.ops.get, { params: { id }, options })
  }

  /** Delete one entry by your id. 404 NotFoundError if it does not exist. */
  delete(id: string, options?: RequestOptions): R<CatalogDeleted> {
    return this.t.call(this.ops.delete, { params: { id }, options })
  }
}

class Catalog {
  /** Your foods (private per account). */
  readonly foods: CatalogEntries<CatalogFood, CatalogFoodList, CatalogFoodsRequest, CatalogFoodsListParams>
  /** Your recipes (fields preliminary in the contract). */
  readonly recipes: CatalogEntries<CatalogRecipe, CatalogRecipeList, CatalogRecipesRequest, CatalogRecipesListParams>

  constructor(private readonly t: Transport) {
    this.foods = new CatalogEntries(t, { put: 'catalogFoodsPut', list: 'catalogFoodsList', get: 'catalogFoodsGet', delete: 'catalogFoodsDelete' })
    this.recipes = new CatalogEntries(t, { put: 'catalogRecipesPut', list: 'catalogRecipesList', get: 'catalogRecipesGet', delete: 'catalogRecipesDelete' })
  }

  /** DELETE /v1/catalog: deletes the whole catalog, foods and recipes. */
  deleteAll(options?: RequestOptions): R<CatalogCleared> {
    return this.t.call('catalogDelete', { options })
  }

  /** GET /v1/catalog/export: all foods and recipes as JSON. */
  export(options?: RequestOptions): R<CatalogExport> {
    return this.t.call('catalogExport', { options })
  }
}

class Account {
  constructor(private readonly t: Transport) {}

  /** GET /v1/account/balance: current balance in credits. Free. */
  balance(options?: RequestOptions): R<AccountBalance> {
    return this.t.call('accountBalance', { options })
  }

  /** GET /v1/account/usage: calls and credits per day and endpoint, at most LIMITS.usageMaxDays days. Free. */
  usage(params: AccountUsageParams, options?: RequestOptions): R<AccountUsage> {
    return this.t.call('accountUsage', { params: { ...params }, options })
  }
}

/**
 * Client of the Flexen API.
 *
 * ```ts
 * const flexen = new Flexen() // reads FLEXEN_API_KEY
 * const { data, creditsRemaining } = await flexen.nutrition.text({ text: '2 eggs and a toast' })
 * ```
 */
export class Flexen {
  readonly nutrition: Nutrition
  readonly foods: Foods
  readonly goals: Goals
  readonly catalog: Catalog
  readonly account: Account
  /** Low-level transport (base URL, timeouts, retries). The key is not readable from it. */
  readonly transport: Transport

  constructor(options: ClientOptions = {}) {
    this.transport = new Transport(options)
    this.nutrition = new Nutrition(this.transport)
    this.foods = new Foods(this.transport)
    this.goals = new Goals(this.transport)
    this.catalog = new Catalog(this.transport)
    this.account = new Account(this.transport)
  }

  toJSON(): Record<string, unknown> {
    return this.transport.toJSON()
  }
}
