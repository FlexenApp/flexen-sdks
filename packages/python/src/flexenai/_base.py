"""Shared building blocks of the sync and async clients: configuration, URLs, retries, responses, errors."""

from __future__ import annotations

import json
import os
import platform
import random
import re
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Generic, Mapping, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from ._errors import APIError, FlexenError, InvalidInputError, UnexpectedResponseError, error_class_for
from ._generated import MODELS, OPERATIONS
from ._version import __version__

T = TypeVar("T")

DEFAULT_BASE_URL = "https://api.flexen.co"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 3
#: Statuses that are retried automatically. Everything else (every other 4xx, 500, 504) is never retried.
RETRY_STATUSES = frozenset({429, 503})


@dataclass(frozen=True)
class RetryConfig:
    """Backoff for 429 and 503. The number of retries is max_retries on the client or per call."""

    #: First backoff step without Retry-After, in seconds.
    base_delay: float = 0.5
    #: Upper bound of one backoff step without Retry-After, in seconds.
    max_delay: float = 8.0
    #: If the server asks (Retry-After) for a longer wait than this, the SDK does not wait and raises.
    max_retry_after: float = 60.0


@dataclass(frozen=True)
class FlexenResponse(Generic[T]):
    """Result of every call: the parsed body and the metadata from the response headers."""

    data: T
    status_code: int
    #: X-Request-Id
    request_id: str | None
    #: X-Credits-Charged: credits this call cost (0 with a test key and on free endpoints).
    credits_charged: int | None
    #: X-Credits-Remaining: balance after the call; credits reserved for running calls are not yet deducted.
    credits_remaining: int | None
    headers: httpx.Headers = field(repr=False)
    #: Idempotent-Replayed: True if the API answered from an earlier call with the same Idempotency-Key (nothing was deducted again).
    idempotent_replayed: bool = False


def int_header(headers: httpx.Headers, name: str) -> int | None:
    v = headers.get(name)
    if v is None or not re.fullmatch(r"-?\d+", v.strip()):
        return None
    return int(v)


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Retry-After in seconds (delta seconds or HTTP date); None if missing or unreadable."""
    if value is None:
        return None
    v = value.strip()
    if re.fullmatch(r"\d+(\.\d+)?", v):
        return float(v)
    try:
        dt = parsedate_to_datetime(v)
    except (TypeError, ValueError, IndexError):
        return None
    if dt is None:
        return None
    return max(0.0, dt.timestamp() - (time.time() if now is None else now))


def compute_retry_delay(attempt: int, retry_after: float | None, cfg: RetryConfig, rnd: Callable[[], float] = random.random) -> float | None:
    """Wait before retry number `attempt` (0 = first retry), in seconds.

    With Retry-After: at least that long, plus up to 0.25 s jitter. Without: exponential backoff
    base_delay * 2**attempt (capped at max_delay) with jitter between 50 % and 100 % of the step.
    None if Retry-After asks for longer than max_retry_after (then the SDK does not retry).
    """
    if retry_after is not None:
        if retry_after > cfg.max_retry_after:
            return None
        return retry_after + rnd() * 0.25
    step = min(cfg.max_delay, cfg.base_delay * (2**attempt))
    return step * (0.5 + rnd() * 0.5)


def resolve_api_key(api_key: str | None) -> str:
    key = api_key if api_key is not None else os.environ.get("FLEXEN_API_KEY")
    if key is None or key.strip() == "":
        raise FlexenError("No API key: pass api_key to the client or set the environment variable FLEXEN_API_KEY.")
    return key.strip()


def user_agent() -> str:
    return f"flexen-python/{__version__} python/{platform.python_version()}"


def build_url(base_url: str, op: str, params: Mapping[str, Any] | None) -> str:
    d = OPERATIONS[op]
    path: str = d["path"]
    query: list[tuple[str, str]] = []
    for name, where, required in d["params"]:
        v = (params or {}).get(name)
        if where == "path":
            if not isinstance(v, str) or v == "":
                raise InvalidInputError(f"{name} is required and must be a non-empty string")
            path = path.replace("{" + name + "}", quote(v, safe=""))
        elif where != "query":
            continue  # header parameters (Idempotency-Key) are set from the call options
        elif v is not None:
            # Lists go comma-separated (form style without explode), as the contract says: sources=customer_catalog,usda_fdc
            query.append((name, v if isinstance(v, str) else ",".join(str(x) for x in v) if isinstance(v, (list, tuple)) else str(v)))
        elif required:
            raise InvalidInputError(f"{name} is required")
    url = base_url.rstrip("/") + path
    if query:
        url += "?" + str(httpx.QueryParams(query))
    return url


def build_body(op: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Validates the request fields against the generated request model and returns JSON-ready data (by contract name)."""
    name = OPERATIONS[op]["request"]
    model: type[BaseModel] = MODELS[name]
    data = {k: v for k, v in fields.items() if v is not None}
    try:
        return model.model_validate(data).model_dump(mode="json", by_alias=True, exclude_none=True)
    except ValidationError as e:
        raise InvalidInputError(f"Invalid {name}: {e}") from e


def _error_from(res: httpx.Response, text: str, body: Any) -> APIError:
    e = body.get("error") if isinstance(body, dict) else None
    e = e if isinstance(e, dict) else {}
    code = e.get("code") if isinstance(e.get("code"), str) else None
    message = e.get("message") if isinstance(e.get("message"), str) else f"HTTP {res.status_code} {res.reason_phrase}".strip()
    request_id = e.get("request_id") if isinstance(e.get("request_id"), str) else res.headers.get("X-Request-Id")
    cls = error_class_for(res.status_code, code)
    return cls(
        status_code=res.status_code,
        code=code,
        message=message,
        request_id=request_id,
        credits_charged=int_header(res.headers, "X-Credits-Charged"),
        credits_remaining=int_header(res.headers, "X-Credits-Remaining"),
        retry_after_seconds=parse_retry_after(res.headers.get("Retry-After")),
        headers=res.headers,
        body=body if body is not None else text,
    )


def error_from_response(res: httpx.Response) -> APIError:
    text = res.text
    try:
        body: Any = json.loads(text) if text else None
    except ValueError:
        body = text
    return _error_from(res, text, body)


def parse_success(op: str, res: httpx.Response) -> FlexenResponse[Any]:
    request_id = res.headers.get("X-Request-Id")
    try:
        raw = res.json()
    except ValueError as e:
        raise UnexpectedResponseError("The response body is not valid JSON.", status_code=res.status_code, request_id=request_id, body=res.text) from e
    name = OPERATIONS[op]["response"]
    data: Any = raw
    if name is not None:
        try:
            data = MODELS[name].model_validate(raw)
        except ValidationError as e:
            raise UnexpectedResponseError(f"The response does not match {name}: {e}", status_code=res.status_code, request_id=request_id, body=raw) from e
    return FlexenResponse(
        data=data,
        status_code=res.status_code,
        request_id=request_id,
        credits_charged=int_header(res.headers, "X-Credits-Charged"),
        credits_remaining=int_header(res.headers, "X-Credits-Remaining"),
        headers=res.headers,
        idempotent_replayed=res.headers.get("Idempotent-Replayed") == "true",
    )


@dataclass
class CallOptions:
    """Per-call options of every SDK method."""

    idempotency_key: str | None = None
    timeout: float | None = None
    max_retries: int | None = None
    extra_headers: Mapping[str, str] | None = None


def request_headers(api_key: str, default_headers: Mapping[str, str], op: str, opts: CallOptions) -> dict[str, str]:
    h = {"Accept": "application/json", "User-Agent": user_agent(), **default_headers, **(opts.extra_headers or {})}
    h["Authorization"] = f"Bearer {api_key}"
    if OPERATIONS[op]["request"] is not None:
        h["Content-Type"] = "application/json"
    if opts.idempotency_key is not None:
        h["Idempotency-Key"] = opts.idempotency_key
    return h


class Deadline:
    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.end = time.monotonic() + seconds

    def remaining(self) -> float:
        return self.end - time.monotonic()


def key_prefix(api_key: str) -> str:
    """First 12 characters (for example "flx_live_AbC") of a real key; short or odd keys are not shown at all."""
    return api_key[:12] + "…" if len(api_key) >= 20 else "***"


def operation(op: str, *, extra: tuple[str, ...] = ()) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Marks an SDK method as the binding of a contract operation (read by scripts/python_surface.py for the drift check)."""

    def mark(fn: Callable[..., T]) -> Callable[..., T]:
        fn.__flexen_operation__ = op  # type: ignore[attr-defined]
        fn.__flexen_extra__ = extra  # type: ignore[attr-defined]
        return fn

    return mark


#: Keyword arguments every SDK method takes besides the contract's fields.
SDK_OPTIONS = ("idempotency_key", "timeout", "max_retries", "extra_headers")

__all__ = [
    "CallOptions",
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT",
    "Deadline",
    "FlexenResponse",
    "RETRY_STATUSES",
    "RetryConfig",
    "SDK_OPTIONS",
    "build_body",
    "build_url",
    "compute_retry_delay",
    "error_from_response",
    "int_header",
    "key_prefix",
    "operation",
    "parse_retry_after",
    "parse_success",
    "request_headers",
    "resolve_api_key",
]
