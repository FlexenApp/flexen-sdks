import {
  APIConnectionError,
  APIError,
  FlexenError,
  InvalidInputError,
  RequestTimeoutError,
  UserAbortError,
  errorClassFor,
} from './errors.js'
import { OPERATIONS, type OperationId } from './generated/contract.js'

export const VERSION = '0.1.1'
export const DEFAULT_BASE_URL = 'https://api.flexen.co'
export const DEFAULT_TIMEOUT_MS = 60_000
export const DEFAULT_MAX_RETRIES = 3

/** Statuses that are retried automatically. Everything else (every other 4xx, 500, 504) is never retried. */
export const RETRY_STATUSES: ReadonlySet<number> = new Set([429, 503])

export interface RetryOptions {
  /** Retries after the first attempt, only for 429 and 503. Default 3. 0 turns retries off. */
  maxRetries?: number
  /** First backoff step without Retry-After, in ms. Default 500. */
  baseDelayMs?: number
  /** Upper bound of one backoff step without Retry-After, in ms. Default 8000. */
  maxDelayMs?: number
  /** If the server asks (Retry-After) for a longer wait than this, the SDK does not wait and throws. Default 60000. */
  maxRetryAfterMs?: number
}

export interface ClientOptions {
  /** API key. Default: the environment variable FLEXEN_API_KEY (Node). Never logged. */
  apiKey?: string
  /** Default https://api.flexen.co */
  baseUrl?: string
  /** Total time for one call including retries, in ms. Default 60000. */
  timeoutMs?: number
  /** Retries for 429 and 503. Default 3. */
  maxRetries?: number
  retry?: Omit<RetryOptions, 'maxRetries'>
  /** Custom fetch, for example for a proxy or tests. Default globalThis.fetch. */
  fetch?: typeof fetch
  /** Extra headers sent with every request. */
  defaultHeaders?: Record<string, string>
}

export interface RequestOptions {
  /** Cancels the call (and any retry wait). A call cancelled before the response arrives costs nothing. */
  signal?: AbortSignal
  /** Overrides the client's total timeout for this call, in ms. */
  timeoutMs?: number
  /** Overrides the client's maxRetries for this call. */
  maxRetries?: number
  /** Sent as Idempotency-Key header, the same on every retry. The API keeps the answer for 24 hours; a repeat is marked idempotentReplayed and costs nothing. */
  idempotencyKey?: string
  /** Extra headers for this call. */
  headers?: Record<string, string>
}

/** Result of every call: the parsed body and the metadata from the response headers. */
export interface FlexenResponse<T> {
  data: T
  status: number
  /** X-Request-Id */
  requestId: string | null
  /** X-Credits-Charged: credits this call cost (0 with a test key and on free endpoints). */
  creditsCharged: number | null
  /** X-Credits-Remaining: balance after the call; credits reserved for running calls are not yet deducted. */
  creditsRemaining: number | null
  /** Idempotent-Replayed: true if the API answered from an earlier call with the same Idempotency-Key (nothing was deducted again). */
  idempotentReplayed: boolean
  headers: Headers
}

export function intHeader(headers: Headers, name: string): number | null {
  const v = headers.get(name)
  if (v === null || !/^-?\d+$/.test(v.trim())) return null
  return Number.parseInt(v, 10)
}

/** Retry-After in seconds (delta seconds or HTTP date); null if missing or unreadable. */
export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (value === null) return null
  const v = value.trim()
  if (/^\d+(\.\d+)?$/.test(v)) return Number(v)
  const t = Date.parse(v)
  if (Number.isNaN(t)) return null
  return Math.max(0, (t - now) / 1000)
}

/**
 * Wait before retry number `attempt` (0 = first retry), in ms.
 * With Retry-After: at least that long, plus up to 250 ms jitter. Without: exponential backoff
 * base * 2^attempt (capped), with jitter between 50 % and 100 % of the step.
 * Returns null if Retry-After asks for longer than maxRetryAfterMs (then the SDK does not retry).
 */
export function computeRetryDelay(
  attempt: number,
  retryAfterSeconds: number | null,
  opts: Required<Omit<RetryOptions, 'maxRetries'>>,
  random: () => number = Math.random,
): number | null {
  if (retryAfterSeconds !== null) {
    const ms = retryAfterSeconds * 1000
    if (ms > opts.maxRetryAfterMs) return null
    return Math.round(ms + random() * 250)
  }
  const step = Math.min(opts.maxDelayMs, opts.baseDelayMs * 2 ** attempt)
  return Math.round(step * (0.5 + random() * 0.5))
}

type EnvLike = { process?: { env?: Record<string, string | undefined>; versions?: { node?: string } } }

function envApiKey(): string | undefined {
  const v = (globalThis as EnvLike).process?.env?.FLEXEN_API_KEY
  return v && v.trim() !== '' ? v.trim() : undefined
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason)
    const t = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    const onAbort = (): void => {
      clearTimeout(t)
      reject(signal.reason)
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

const TIMEOUT_REASON = Symbol('flexen-timeout')

export interface CallArgs {
  params?: Record<string, unknown> | undefined
  body?: unknown
  options?: RequestOptions | undefined
}

/** Transport shared by all resources. Holds the key in a private field, so it never shows up in logs, JSON or inspect. */
export class Transport {
  readonly #apiKey: string
  readonly baseUrl: string
  readonly timeoutMs: number
  readonly maxRetries: number
  readonly retry: Required<Omit<RetryOptions, 'maxRetries'>>
  readonly #fetch: typeof fetch
  readonly #defaultHeaders: Record<string, string>

  constructor(opts: ClientOptions = {}) {
    const key = opts.apiKey ?? envApiKey()
    if (!key) {
      throw new FlexenError('No API key: pass apiKey to the client or set the environment variable FLEXEN_API_KEY.')
    }
    this.#apiKey = key
    this.baseUrl = (opts.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, '')
    this.timeoutMs = opts.timeoutMs ?? DEFAULT_TIMEOUT_MS
    this.maxRetries = opts.maxRetries ?? DEFAULT_MAX_RETRIES
    this.retry = {
      baseDelayMs: opts.retry?.baseDelayMs ?? 500,
      maxDelayMs: opts.retry?.maxDelayMs ?? 8000,
      maxRetryAfterMs: opts.retry?.maxRetryAfterMs ?? 60_000,
    }
    const f = opts.fetch ?? globalThis.fetch
    if (typeof f !== 'function') throw new FlexenError('No fetch available: pass fetch to the client.')
    this.#fetch = f.bind(globalThis)
    this.#defaultHeaders = { ...(opts.defaultHeaders ?? {}) }
  }

  /** Key prefix only (for example "flx_live_AbC"), for debugging. */
  get apiKeyPrefix(): string {
    return this.#apiKey.length >= 20 ? this.#apiKey.slice(0, 12) : '***'
  }

  buildUrl(op: OperationId, params: Record<string, unknown> = {}): string {
    const def = OPERATIONS[op]
    let path: string = def.path
    for (const name of def.pathParams as readonly string[]) {
      const v = params[name]
      if (typeof v !== 'string' || v === '') throw new InvalidInputError(`${name} is required and must be a non-empty string`)
      path = path.replace(`{${name}}`, encodeURIComponent(v))
    }
    const q = new URLSearchParams()
    for (const name of def.queryParams as readonly string[]) {
      const v = params[name]
      /* Lists go comma-separated (form style without explode), as the contract says: sources=customer_catalog,usda_fdc */
      if (v !== undefined && v !== null) q.set(name, Array.isArray(v) ? v.join(',') : String(v))
    }
    const qs = q.toString()
    return `${this.baseUrl}${path}${qs ? `?${qs}` : ''}`
  }

  async call<T>(op: OperationId, args: CallArgs = {}): Promise<FlexenResponse<T>> {
    const def = OPERATIONS[op]
    const options = args.options ?? {}
    const url = this.buildUrl(op, args.params)
    const headers: Record<string, string> = {
      Accept: 'application/json',
      ...this.#defaultHeaders,
      ...(options.headers ?? {}),
      Authorization: `Bearer ${this.#apiKey}`,
    }
    const node = (globalThis as EnvLike).process?.versions?.node
    if (node && !('User-Agent' in headers)) headers['User-Agent'] = `flexen-ts/${VERSION} node/${node}`
    let body: string | undefined
    if (def.hasBody) {
      body = JSON.stringify(args.body ?? {})
      headers['Content-Type'] = 'application/json'
    }
    if (options.idempotencyKey !== undefined) headers['Idempotency-Key'] = options.idempotencyKey

    const maxRetries = options.maxRetries ?? this.maxRetries
    const timeoutMs = options.timeoutMs ?? this.timeoutMs
    const controller = new AbortController()
    const user = options.signal
    const onUserAbort = (): void => controller.abort(user?.reason)
    if (user) {
      if (user.aborted) throw new UserAbortError('The call was cancelled before it was sent.', { cause: user.reason })
      user.addEventListener('abort', onUserAbort, { once: true })
    }
    const deadline = Date.now() + timeoutMs
    const timer = setTimeout(() => controller.abort(TIMEOUT_REASON), timeoutMs)
    const cancelled = (cause: unknown): FlexenError =>
      controller.signal.reason === TIMEOUT_REASON
        ? new RequestTimeoutError(`No response within ${timeoutMs} ms; the call was cancelled.`)
        : new UserAbortError('The call was cancelled.', { cause })

    try {
      for (let attempt = 0; ; attempt++) {
        let res: Response
        try {
          res = await this.#fetch(url, { method: def.method, headers, body, signal: controller.signal })
        } catch (e) {
          if (controller.signal.aborted) throw cancelled(e)
          throw new APIConnectionError(`Could not reach ${this.baseUrl}: ${e instanceof Error ? e.message : String(e)}`, { cause: e })
        }
        let text: string
        try {
          text = await res.text()
        } catch (e) {
          if (controller.signal.aborted) throw cancelled(e)
          throw new APIConnectionError(`The response of ${this.baseUrl} broke off: ${e instanceof Error ? e.message : String(e)}`, { cause: e })
        }
        if (res.ok) {
          let data: T
          try {
            data = (text === '' ? null : JSON.parse(text)) as T
          } catch {
            throw this.#error(res, text, 'The response body is not valid JSON.')
          }
          return {
            data,
            status: res.status,
            requestId: res.headers.get('X-Request-Id'),
            creditsCharged: intHeader(res.headers, 'X-Credits-Charged'),
            creditsRemaining: intHeader(res.headers, 'X-Credits-Remaining'),
            idempotentReplayed: res.headers.get('Idempotent-Replayed') === 'true',
            headers: res.headers,
          }
        }
        const err = this.#error(res, text)
        if (!RETRY_STATUSES.has(res.status) || attempt >= maxRetries) throw err
        const delay = computeRetryDelay(attempt, err.retryAfterSeconds, this.retry)
        if (delay === null) throw err
        if (Date.now() + delay >= deadline) {
          throw new RequestTimeoutError(`No usable response within ${timeoutMs} ms; the last one was ${err.message}.`, { cause: err })
        }
        try {
          await sleep(delay, controller.signal)
        } catch (e) {
          throw cancelled(e)
        }
      }
    } finally {
      clearTimeout(timer)
      user?.removeEventListener('abort', onUserAbort)
    }
  }

  #error(res: Response, text: string, fallbackMessage?: string): APIError {
    let body: unknown = text
    try {
      body = text === '' ? null : JSON.parse(text)
    } catch {
      /* keep raw text */
    }
    const e = (body as { error?: { code?: unknown; message?: unknown; request_id?: unknown } } | null)?.error
    const code = typeof e?.code === 'string' ? e.code : null
    const message = fallbackMessage ?? (typeof e?.message === 'string' ? e.message : `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ''}`)
    const requestId = (typeof e?.request_id === 'string' ? e.request_id : null) ?? res.headers.get('X-Request-Id')
    const Cls = fallbackMessage ? APIError : errorClassFor(res.status, code)
    return new Cls({
      status: res.status,
      code,
      message,
      requestId,
      creditsCharged: intHeader(res.headers, 'X-Credits-Charged'),
      creditsRemaining: intHeader(res.headers, 'X-Credits-Remaining'),
      retryAfterSeconds: parseRetryAfter(res.headers.get('Retry-After')),
      headers: res.headers,
      body,
    })
  }

  /** Never print the key: inspect, JSON and String show the prefix only. */
  toJSON(): Record<string, unknown> {
    return { baseUrl: this.baseUrl, apiKey: `${this.apiKeyPrefix}…`, timeoutMs: this.timeoutMs, maxRetries: this.maxRetries }
  }
}
