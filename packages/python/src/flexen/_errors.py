from __future__ import annotations

from typing import Any

import httpx


class FlexenError(Exception):
    """Base class of every error this SDK raises."""


class InvalidInputError(FlexenError):
    """The SDK rejected the input before sending anything (for example a photo above the size limit). No credits are used."""


class APIConnectionError(FlexenError):
    """The request could not be sent or no response arrived. Not retried automatically."""


class RequestTimeoutError(FlexenError):
    """The client-side timeout ran out before a usable response arrived. Per the contract, a cancelled call costs nothing."""


class UnexpectedResponseError(FlexenError):
    """A successful response did not match the contract's schema (or was not JSON)."""

    def __init__(self, message: str, *, status_code: int, request_id: str | None, body: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.body = body


class APIError(FlexenError):
    """The API answered with an error status. Subclasses per error code of the contract."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str | None,
        message: str,
        request_id: str | None,
        credits_charged: int | None,
        credits_remaining: int | None,
        retry_after_seconds: float | None,
        headers: httpx.Headers,
        body: Any,
    ) -> None:
        text = f"{status_code}{' ' + code if code else ''}: {message}"
        if request_id:
            text += f" (request_id {request_id})"
        super().__init__(text)
        self.status_code = status_code
        #: Error code from {"error": {"code", ...}}; None if the body was not the contract's error format.
        self.code = code
        #: The server's message, without status and code.
        self.message = message
        #: request_id from the body, else the X-Request-Id header. Include it when you contact Flexen.
        self.request_id = request_id
        self.credits_charged = credits_charged
        self.credits_remaining = credits_remaining
        self.retry_after_seconds = retry_after_seconds
        self.headers = headers
        self.body = body

    def __str__(self) -> str:
        return self.args[0]


class BadRequestError(APIError):
    """400 invalid_json"""


class AuthenticationError(APIError):
    """401 invalid_key: key missing, unknown or blocked."""


class InsufficientCreditsError(APIError):
    """402 insufficient_credits: not enough credits for this call. Top up in the console."""


class DailyLimitReachedError(APIError):
    """402 daily_limit_reached: the daily spending limit of the account has been reached."""


class AccountSuspendedError(APIError):
    """403 account_suspended"""


class MonthlyBudgetReachedError(APIError):
    """402 monthly_budget_reached: the monthly budget of the account has been reached (until the end of the calendar month, UTC)."""


class KeyBudgetReachedError(APIError):
    """402 key_budget_reached: the monthly limit of this key has been reached."""


class KeyExpiredError(APIError):
    """403 key_expired: the key has passed its expiry date."""


class KeyScopeDeniedError(APIError):
    """403 key_scope_denied: this key may not call this endpoint."""


class IpNotAllowedError(APIError):
    """403 ip_not_allowed: the call comes from an IP address that is not allowed for this key."""


class IdempotencyInProgressError(APIError):
    """409 idempotency_in_progress: a call with the same Idempotency-Key is still running. Not retried; see retry_after_seconds."""


class NotFoundError(APIError):
    """404 not_found"""


class InvalidRequestError(APIError):
    """422 invalid_request: the message names the fields concerned."""


class TierUnavailableError(APIError):
    """422 tier_unavailable: the chosen tier is not available yet or not enabled for live keys."""


class RateLimitError(APIError):
    """429 rate_limited. Retried automatically (see max_retries)."""


class InternalServerError(APIError):
    """500 internal_error. Not retried."""


class ServiceUnavailableError(APIError):
    """503 service_unavailable. Retried automatically (see max_retries)."""


class ServerTimeoutError(APIError):
    """504 timeout: the server-side time limit ran out before a usable estimate was ready (AI endpoints). Not retried."""


#: Error class per contract error code. The drift check compares the keys with the contract's error codes.
ERROR_CLASS_BY_CODE: dict[str, type[APIError]] = {
    "invalid_json": BadRequestError,
    "invalid_key": AuthenticationError,
    "insufficient_credits": InsufficientCreditsError,
    "daily_limit_reached": DailyLimitReachedError,
    "account_suspended": AccountSuspendedError,
    "monthly_budget_reached": MonthlyBudgetReachedError,
    "key_budget_reached": KeyBudgetReachedError,
    "key_expired": KeyExpiredError,
    "key_scope_denied": KeyScopeDeniedError,
    "ip_not_allowed": IpNotAllowedError,
    "idempotency_in_progress": IdempotencyInProgressError,
    "not_found": NotFoundError,
    "invalid_request": InvalidRequestError,
    "tier_unavailable": TierUnavailableError,
    "rate_limited": RateLimitError,
    "internal_error": InternalServerError,
    "service_unavailable": ServiceUnavailableError,
    "timeout": ServerTimeoutError,
}

_ERROR_CLASS_BY_STATUS: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    402: InsufficientCreditsError,
    403: AccountSuspendedError,
    404: NotFoundError,
    409: IdempotencyInProgressError,
    422: InvalidRequestError,
    429: RateLimitError,
    500: InternalServerError,
    503: ServiceUnavailableError,
    504: ServerTimeoutError,
}


def error_class_for(status_code: int, code: str | None) -> type[APIError]:
    if code is not None and code in ERROR_CLASS_BY_CODE:
        return ERROR_CLASS_BY_CODE[code]
    return _ERROR_CLASS_BY_STATUS.get(status_code, APIError)
