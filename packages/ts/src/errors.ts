import type { ErrorCode } from './generated/contract.js'

/** Base class of every error this SDK throws. */
export class FlexenError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = new.target.name
  }
}

/** The SDK rejected the input before sending anything (for example a photo above the size limit). No credits are used. */
export class InvalidInputError extends FlexenError {}

/** The request could not be sent or no response arrived (DNS, refused connection, reset). Not retried automatically. */
export class APIConnectionError extends FlexenError {}

/** The client-side timeout ran out before a response arrived. The call was cancelled; per the contract, a cancelled call costs nothing. */
export class RequestTimeoutError extends FlexenError {}

/** The call was cancelled through the AbortSignal you passed. Per the contract, a cancelled call costs nothing. */
export class UserAbortError extends FlexenError {}

/** Details shared by every error response of the API. */
export interface APIErrorDetails {
  status: number
  code: ErrorCode | (string & {}) | null
  message: string
  requestId: string | null
  creditsCharged: number | null
  creditsRemaining: number | null
  retryAfterSeconds: number | null
  headers: Headers
  body: unknown
}

/** The API answered with an error status. Subclasses per error code of the contract. */
export class APIError extends FlexenError {
  readonly status: number
  /** Error code from the response body ({"error": {"code", ...}}); null if the body was not the contract's error format. */
  readonly code: ErrorCode | (string & {}) | null
  /** request_id from the body, else the X-Request-Id header. Include it when you contact Flexen. */
  readonly requestId: string | null
  /** X-Credits-Charged of the error response (0 for errors; null without a valid key). */
  readonly creditsCharged: number | null
  /** X-Credits-Remaining of the error response (null without a valid key). */
  readonly creditsRemaining: number | null
  /** Retry-After in seconds, if the response carried it. */
  readonly retryAfterSeconds: number | null
  readonly headers: Headers
  /** Parsed response body (JSON) or the raw text if it was not JSON. */
  readonly body: unknown
  /** The server's message, without status and code. */
  readonly apiMessage: string

  constructor(d: APIErrorDetails) {
    super(`${d.status}${d.code ? ` ${d.code}` : ''}: ${d.message}${d.requestId ? ` (request_id ${d.requestId})` : ''}`)
    this.status = d.status
    this.code = d.code
    this.apiMessage = d.message
    this.requestId = d.requestId
    this.creditsCharged = d.creditsCharged
    this.creditsRemaining = d.creditsRemaining
    this.retryAfterSeconds = d.retryAfterSeconds
    this.headers = d.headers
    this.body = d.body
  }
}

/** 400 invalid_json */
export class BadRequestError extends APIError {}
/** 401 invalid_key: key missing, unknown or blocked. */
export class AuthenticationError extends APIError {}
/** 402 insufficient_credits: not enough credits for this call. Top up in the console. */
export class InsufficientCreditsError extends APIError {}
/** 402 daily_limit_reached: the daily spending limit of the account has been reached. */
export class DailyLimitReachedError extends APIError {}
/** 403 account_suspended */
export class AccountSuspendedError extends APIError {}
/** 404 not_found */
export class NotFoundError extends APIError {}
/** 422 invalid_request: the message names the fields concerned. */
export class InvalidRequestError extends APIError {}
/** 422 tier_unavailable: the chosen tier is not available yet or not enabled for live keys. */
export class TierUnavailableError extends APIError {}
/** 429 rate_limited. Retried automatically (see maxRetries). */
export class RateLimitError extends APIError {}
/** 500 internal_error. Not retried. */
export class InternalServerError extends APIError {}
/** 503 service_unavailable. Retried automatically (see maxRetries). */
export class ServiceUnavailableError extends APIError {}
/** 504 timeout: the server-side time limit ran out before a usable estimate was ready (AI endpoints). Not retried. */
export class ServerTimeoutError extends APIError {}

type APIErrorClass = new (d: APIErrorDetails) => APIError

/** Error class per contract error code. Typed against ErrorCode: a new code in the contract fails the type check. */
export const ERROR_CLASS_BY_CODE: Record<ErrorCode, APIErrorClass> = {
  invalid_json: BadRequestError,
  invalid_key: AuthenticationError,
  insufficient_credits: InsufficientCreditsError,
  daily_limit_reached: DailyLimitReachedError,
  account_suspended: AccountSuspendedError,
  not_found: NotFoundError,
  invalid_request: InvalidRequestError,
  tier_unavailable: TierUnavailableError,
  rate_limited: RateLimitError,
  internal_error: InternalServerError,
  service_unavailable: ServiceUnavailableError,
  timeout: ServerTimeoutError,
}

/** Fallback by status when the body carries no known code (for example an HTML page of a proxy). */
const ERROR_CLASS_BY_STATUS: Record<number, APIErrorClass> = {
  400: BadRequestError,
  401: AuthenticationError,
  402: InsufficientCreditsError,
  403: AccountSuspendedError,
  404: NotFoundError,
  422: InvalidRequestError,
  429: RateLimitError,
  500: InternalServerError,
  503: ServiceUnavailableError,
  504: ServerTimeoutError,
}

export function errorClassFor(status: number, code: string | null): APIErrorClass {
  if (code && Object.prototype.hasOwnProperty.call(ERROR_CLASS_BY_CODE, code)) return ERROR_CLASS_BY_CODE[code as ErrorCode]
  return ERROR_CLASS_BY_STATUS[status] ?? APIError
}
