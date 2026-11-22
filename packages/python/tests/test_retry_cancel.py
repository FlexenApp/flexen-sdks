from __future__ import annotations

import time

import anyio
import pytest

from conftest import OK_HEADERS, TEST_KEY, Fake, Reply, error_body
from flexenai import (
    AsyncFlexen,
    Flexen,
    InsufficientCreditsError,
    InternalServerError,
    InvalidRequestError,
    RateLimitError,
    RequestTimeoutError,
    RetryConfig,
    ServerTimeoutError,
    ServiceUnavailableError,
    compute_retry_delay,
    parse_retry_after,
)

FAST = RetryConfig(base_delay=0.001, max_delay=0.004)
OK = Reply(200, {"credits_remaining": 7}, headers=OK_HEADERS)


def err(status: int, code: str, **headers: str) -> Reply:
    return Reply(status, error_body(code), headers={k.replace("_", "-"): v for k, v in headers.items()})


def client(fake: Fake, **kw) -> Flexen:
    return Flexen(TEST_KEY, base_url=fake.url, retry=kw.pop("retry", FAST), **kw)


def test_retries_503_then_succeeds(fake: Fake) -> None:
    fake.queue(err(503, "service_unavailable"), err(503, "service_unavailable"), OK)
    with client(fake) as c:
        res = c.account.balance()
    assert res.data.credits_remaining == 7
    assert len(fake.requests) == 3


def test_retries_429_honouring_retry_after(fake: Fake) -> None:
    fake.queue(err(429, "rate_limited", Retry_After="1"), OK)
    t0 = time.monotonic()
    with client(fake) as c:
        c.account.balance()
    assert time.monotonic() - t0 >= 1.0
    assert len(fake.requests) == 2


def test_stops_after_three_retries(fake: Fake) -> None:
    fake.handle(lambda r: err(503, "service_unavailable"))
    with client(fake) as c:
        with pytest.raises(ServiceUnavailableError):
            c.account.balance()
    assert len(fake.requests) == 4


def test_max_retries_zero(fake: Fake) -> None:
    fake.handle(lambda r: err(429, "rate_limited"))
    with client(fake) as c:
        with pytest.raises(RateLimitError):
            c.account.balance(max_retries=0)
    assert len(fake.requests) == 1


def test_retry_after_longer_than_allowed_is_not_waited(fake: Fake) -> None:
    fake.handle(lambda r: err(429, "rate_limited", Retry_After="30"))
    with client(fake, retry=RetryConfig(max_retry_after=0.5)) as c:
        with pytest.raises(RateLimitError) as info:
            c.account.balance()
    assert info.value.retry_after_seconds == 30
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    ("status", "code", "cls"),
    [(402, "insufficient_credits", InsufficientCreditsError), (422, "invalid_request", InvalidRequestError), (500, "internal_error", InternalServerError), (504, "timeout", ServerTimeoutError)],
)
def test_never_retried(fake: Fake, status: int, code: str, cls: type) -> None:
    fake.handle(lambda r: err(status, code))
    with client(fake) as c:
        with pytest.raises(cls):
            c.nutrition.text("x")
    assert len(fake.requests) == 1


def test_idempotency_key_on_every_attempt(fake: Fake) -> None:
    fake.queue(err(503, "service_unavailable"), err(429, "rate_limited"), OK)
    with client(fake) as c:
        c.account.balance(idempotency_key="idem-123")
    assert [r.headers.get("idempotency-key") for r in fake.requests] == ["idem-123"] * 3


def test_no_idempotency_key_by_default(fake: Fake) -> None:
    fake.queue(OK)
    with client(fake) as c:
        c.account.balance()
    assert "idempotency-key" not in fake.requests[0].headers


def test_compute_retry_delay() -> None:
    cfg = RetryConfig(base_delay=0.5, max_delay=8.0, max_retry_after=60.0)
    assert compute_retry_delay(0, None, cfg, lambda: 0.0) == 0.25
    assert compute_retry_delay(0, None, cfg, lambda: 1.0) == 0.5
    assert compute_retry_delay(2, None, cfg, lambda: 1.0) == 2.0
    assert compute_retry_delay(10, None, cfg, lambda: 1.0) == 8.0
    assert compute_retry_delay(0, 2.0, cfg, lambda: 0.0) == 2.0
    assert compute_retry_delay(0, 2.0, cfg, lambda: 1.0) == 2.25
    assert compute_retry_delay(0, 61.0, cfg, lambda: 0.0) is None


def test_parse_retry_after() -> None:
    assert parse_retry_after("3") == 3.0
    assert parse_retry_after(None) is None
    assert parse_retry_after("soon") is None
    now = 1795262400.0  # 2026-11-21T12:00:00Z
    assert parse_retry_after("Sat, 21 Nov 2026 12:00:05 GMT", now=now) == 5.0


# ------------------------------------------------------------- timeouts and cancellation


def test_sync_timeout(fake: Fake) -> None:
    fake.handle(lambda r: Reply(200, {"credits_remaining": 1}, delay=1.5))
    with client(fake) as c:
        t0 = time.monotonic()
        with pytest.raises(RequestTimeoutError):
            c.account.balance(timeout=0.2)
    assert time.monotonic() - t0 < 1.2


def test_timeout_covers_retry_waits(fake: Fake) -> None:
    fake.handle(lambda r: err(429, "rate_limited", Retry_After="5"))
    with client(fake, timeout=0.3) as c:
        t0 = time.monotonic()
        with pytest.raises(RequestTimeoutError):
            c.account.balance()
    assert time.monotonic() - t0 < 2
    assert len(fake.requests) == 1


@pytest.mark.anyio
async def test_async_timeout(fake: Fake) -> None:
    fake.handle(lambda r: Reply(200, {"credits_remaining": 1}, delay=1.5))
    async with AsyncFlexen(TEST_KEY, base_url=fake.url) as c:
        with pytest.raises(RequestTimeoutError):
            await c.account.balance(timeout=0.2)


@pytest.mark.anyio
async def test_async_cancel_by_cancelling_the_task(fake: Fake) -> None:
    fake.handle(lambda r: Reply(200, {"credits_remaining": 1}, delay=1.5))
    async with AsyncFlexen(TEST_KEY, base_url=fake.url) as c:
        t0 = time.monotonic()
        with anyio.move_on_after(0.1) as scope:
            await c.nutrition.text("Apfel")
        assert scope.cancelled_caught
        assert time.monotonic() - t0 < 1.0


@pytest.mark.anyio
async def test_async_retries(fake: Fake) -> None:
    fake.queue(err(503, "service_unavailable"), OK)
    async with AsyncFlexen(TEST_KEY, base_url=fake.url, retry=FAST) as c:
        res = await c.account.balance(idempotency_key="k")
    assert res.data.credits_remaining == 7
    assert [r.headers.get("idempotency-key") for r in fake.requests] == ["k", "k"]
