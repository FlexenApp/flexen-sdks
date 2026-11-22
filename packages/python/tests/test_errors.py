from __future__ import annotations

import pickle

import pytest

from conftest import TEST_KEY, Fake, Reply, error_body
from flexenai import (
    ERROR_CLASS_BY_CODE,
    ERROR_CODES,
    AccountSuspendedError,
    APIConnectionError,
    APIError,
    AsyncFlexen,
    AuthenticationError,
    BadRequestError,
    DailyLimitReachedError,
    Flexen,
    IdempotencyInProgressError,
    IpNotAllowedError,
    KeyBudgetReachedError,
    KeyExpiredError,
    KeyScopeDeniedError,
    MonthlyBudgetReachedError,
    FlexenError,
    InsufficientCreditsError,
    InternalServerError,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    ServerTimeoutError,
    ServiceUnavailableError,
    TierUnavailableError,
    UnexpectedResponseError,
)

EXPECTED: dict[str, type[APIError]] = {
    "invalid_json": BadRequestError,
    "invalid_key": AuthenticationError,
    "insufficient_credits": InsufficientCreditsError,
    "daily_limit_reached": DailyLimitReachedError,
    "monthly_budget_reached": MonthlyBudgetReachedError,
    "key_budget_reached": KeyBudgetReachedError,
    "account_suspended": AccountSuspendedError,
    "key_expired": KeyExpiredError,
    "key_scope_denied": KeyScopeDeniedError,
    "ip_not_allowed": IpNotAllowedError,
    "not_found": NotFoundError,
    "idempotency_in_progress": IdempotencyInProgressError,
    "invalid_request": InvalidRequestError,
    "tier_unavailable": TierUnavailableError,
    "rate_limited": RateLimitError,
    "internal_error": InternalServerError,
    "service_unavailable": ServiceUnavailableError,
    "timeout": ServerTimeoutError,
}


def test_every_contract_code_has_a_class() -> None:
    assert set(ERROR_CLASS_BY_CODE) == {c["code"] for c in ERROR_CODES} == set(EXPECTED)


@pytest.mark.parametrize("entry", ERROR_CODES, ids=lambda e: f"{e['status']}-{e['code']}")
def test_error_mapping(fake: Fake, entry: dict) -> None:
    status, code = entry["status"], entry["code"]
    with_key = code != "invalid_key"
    headers = {"X-Request-Id": "req_abc", **({"X-Credits-Charged": "0", "X-Credits-Remaining": "42"} if with_key else {})}
    fake.handle(lambda r: Reply(status, error_body(code, f"server says {code}", "req_abc"), headers=headers))
    with Flexen(TEST_KEY, base_url=fake.url, max_retries=0) as c:
        with pytest.raises(EXPECTED[code]) as info:
            c.nutrition.text("Apfel")
    e = info.value
    assert isinstance(e, APIError) and isinstance(e, FlexenError)
    assert e.status_code == status
    assert e.code == code
    assert e.request_id == "req_abc"
    assert e.message == f"server says {code}"
    assert "req_abc" in str(e) and f"server says {code}" in str(e)
    assert e.credits_charged == (0 if with_key else None)
    assert e.credits_remaining == (42 if with_key else None)
    assert len(fake.requests) == 1


def test_request_id_from_header_when_body_has_none(fake: Fake) -> None:
    fake.handle(lambda r: Reply(404, {"error": {"code": "not_found", "message": "nope"}}, headers={"X-Request-Id": "req_hdr"}))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        with pytest.raises(NotFoundError) as info:
            c.foods.barcode("4000000000000")
    assert info.value.request_id == "req_hdr"


def test_non_contract_body_maps_by_status(fake: Fake) -> None:
    fake.handle(lambda r: Reply(502, text="<html>Bad gateway</html>", headers={"Content-Type": "text/html"}))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        with pytest.raises(APIError) as info:
            c.account.balance()
    assert type(info.value) is APIError
    assert info.value.status_code == 502 and info.value.code is None
    assert info.value.body == "<html>Bad gateway</html>"


def test_unknown_code_maps_by_status(fake: Fake) -> None:
    fake.handle(lambda r: Reply(422, error_body("something_new")))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        with pytest.raises(InvalidRequestError) as info:
            c.account.balance()
    assert info.value.code == "something_new"


def test_success_that_breaks_the_schema(fake: Fake) -> None:
    fake.handle(lambda r: Reply(200, {"unexpected": True}, headers={"X-Request-Id": "req_x"}))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        with pytest.raises(UnexpectedResponseError) as info:
            c.account.balance()
    assert info.value.request_id == "req_x"


def test_connection_refused_is_api_connection_error() -> None:
    with Flexen(TEST_KEY, base_url="http://127.0.0.1:1") as c:
        with pytest.raises(APIConnectionError):
            c.account.balance()


def test_key_from_environment(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEXEN_API_KEY", "flx_test_fromenv")
    fake.handle(lambda r: Reply(200, {"credits_remaining": 1}))
    with Flexen(base_url=fake.url) as c:
        c.account.balance()
    assert fake.requests[0].headers["authorization"] == "Bearer flx_test_fromenv"


def test_explicit_key_wins(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLEXEN_API_KEY", "flx_test_fromenv")
    fake.handle(lambda r: Reply(200, {"credits_remaining": 1}))
    with Flexen(TEST_KEY, base_url=fake.url) as c:
        c.account.balance()
    assert fake.requests[0].headers["authorization"] == f"Bearer {TEST_KEY}"


def test_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FLEXEN_API_KEY", raising=False)
    with pytest.raises(FlexenError, match="FLEXEN_API_KEY"):
        Flexen()
    with pytest.raises(FlexenError, match="FLEXEN_API_KEY"):
        AsyncFlexen()


def test_key_never_shown(fake: Fake) -> None:
    fake.handle(lambda r: Reply(401, error_body("invalid_key")))
    secret = TEST_KEY[12:]
    with Flexen(TEST_KEY, base_url=fake.url, max_retries=0) as c:
        with pytest.raises(AuthenticationError) as info:
            c.account.balance()
        texts = [repr(c), str(c), str(info.value), repr(info.value), repr(vars(info.value))]
        with pytest.raises(TypeError):
            pickle.dumps(c)
    for t in texts:
        assert secret not in t


def test_short_key_not_shown_at_all() -> None:
    c = Flexen("short-secret")
    assert "short" not in repr(c)
    assert c.api_key_prefix == "***"


def test_default_base_url() -> None:
    assert Flexen(TEST_KEY).base_url == "https://api.flexen.co"
