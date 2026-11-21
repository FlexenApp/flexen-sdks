from __future__ import annotations

import base64
import io
from pathlib import Path

import pytest

from conftest import EXAMPLES, OK_HEADERS, TEST_KEY, Fake, Reply
from flexen import IMAGE_MAX_BYTES, LIMITS, AsyncFlexen, Flexen, InvalidInputError, decoded_base64_bytes

JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01])
B64 = base64.b64encode(JPEG).decode()


@pytest.fixture
def photo_fake(fake: Fake) -> Fake:
    fake.handle(lambda r: Reply(200, EXAMPLES["nutritionPhoto"]["response"], headers={**OK_HEADERS, "X-Credits-Charged": "2"}))
    return fake


def sent(fake: Fake) -> list[str]:
    return [r.json["image_base64"] for r in fake.requests]


def test_limit_comes_from_the_contract() -> None:
    assert LIMITS["imageMaxMiB"] == 8
    assert IMAGE_MAX_BYTES == 8 * 1024 * 1024


def test_bytes_path_fileobj_and_base64(photo_fake: Fake, tmp_path: Path) -> None:
    p = tmp_path / "meal.jpg"
    p.write_bytes(JPEG)
    prefixed = f"data:image/jpeg;base64,{B64}"
    with Flexen(TEST_KEY, base_url=photo_fake.url) as c:
        res = c.nutrition.photo(image_bytes=JPEG, lang="de")
        c.nutrition.photo(image_path=p)
        c.nutrition.photo(image_path=str(p))
        c.nutrition.photo(image_bytes=io.BytesIO(JPEG))
        c.nutrition.photo(image_base64=prefixed)
    assert sent(photo_fake) == [B64, B64, B64, B64, prefixed]
    assert photo_fake.requests[0].json == {"image_base64": B64, "lang": "de"}
    assert res.credits_charged == 2
    assert res.data.beta is True
    assert res.data.dish == EXAMPLES["nutritionPhoto"]["response"]["dish"]


def test_exactly_the_limit_is_sent(photo_fake: Fake) -> None:
    with Flexen(TEST_KEY, base_url=photo_fake.url) as c:
        c.nutrition.photo(image_bytes=bytes(IMAGE_MAX_BYTES))
    assert len(photo_fake.requests) == 1
    assert decoded_base64_bytes(sent(photo_fake)[0]) == IMAGE_MAX_BYTES


def test_over_the_limit_is_rejected_without_a_request(photo_fake: Fake, tmp_path: Path) -> None:
    big = tmp_path / "big.jpg"
    big.write_bytes(bytes(IMAGE_MAX_BYTES + 1))
    with Flexen(TEST_KEY, base_url=photo_fake.url) as c:
        with pytest.raises(InvalidInputError, match="8 MiB"):
            c.nutrition.photo(image_bytes=bytes(IMAGE_MAX_BYTES + 1))
        with pytest.raises(InvalidInputError):
            c.nutrition.photo(image_path=big)
        with pytest.raises(InvalidInputError):
            c.nutrition.photo(image_bytes=io.BytesIO(bytes(IMAGE_MAX_BYTES + 1)))
        with pytest.raises(InvalidInputError):
            c.nutrition.photo(image_base64=base64.b64encode(bytes(IMAGE_MAX_BYTES + 3)).decode())
    assert photo_fake.requests == []


def test_exactly_one_source(photo_fake: Fake) -> None:
    with Flexen(TEST_KEY, base_url=photo_fake.url) as c:
        with pytest.raises(InvalidInputError):
            c.nutrition.photo()
        with pytest.raises(InvalidInputError):
            c.nutrition.photo(image_bytes=JPEG, image_base64=B64)
        with pytest.raises(InvalidInputError):
            c.nutrition.photo(image_bytes=b"")
    assert photo_fake.requests == []


@pytest.mark.anyio
async def test_async_photo(photo_fake: Fake, tmp_path: Path) -> None:
    p = tmp_path / "meal.jpg"
    p.write_bytes(JPEG)
    async with AsyncFlexen(TEST_KEY, base_url=photo_fake.url) as c:
        res = await c.nutrition.photo(image_path=p, tier="economy")
        with pytest.raises(InvalidInputError):
            await c.nutrition.photo(image_bytes=bytes(IMAGE_MAX_BYTES + 1))
    assert sent(photo_fake) == [B64]
    assert res.data.components_granularity == "dish"
