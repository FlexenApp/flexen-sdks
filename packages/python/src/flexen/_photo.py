"""Photo input: path, bytes, file object or Base64, with the contract's size limit enforced before anything is sent."""

from __future__ import annotations

import base64
import os
import re
from typing import BinaryIO, Union

from ._errors import InvalidInputError
from ._generated import LIMITS

#: Largest decoded photo the contract accepts, in bytes (LIMITS["imageMaxMiB"] MiB).
IMAGE_MAX_BYTES: int = int(LIMITS["imageMaxMiB"]) * 1024 * 1024

_DATA_URL_PREFIX = re.compile(r"^data:image/[A-Za-z0-9.+-]+;base64,")

ImageBytes = Union[bytes, bytearray, memoryview, BinaryIO]
ImagePath = Union[str, os.PathLike[str]]


def decoded_base64_bytes(b64: str) -> int:
    """Decoded size of a Base64 string, computed from its length (like the API does before decoding)."""
    s = re.sub(r"\s+", "", _DATA_URL_PREFIX.sub("", b64, count=1))
    padding = 2 if s.endswith("==") else 1 if s.endswith("=") else 0
    return (len(s) * 3) // 4 - padding


def _too_large(size: int) -> InvalidInputError:
    return InvalidInputError(
        f"The photo has {size} bytes; the API accepts at most {LIMITS['imageMaxMiB']} MiB ({IMAGE_MAX_BYTES} bytes) "
        "before Base64 encoding. Nothing was sent."
    )


def to_image_base64(*, image_path: ImagePath | None = None, image_bytes: ImageBytes | None = None, image_base64: str | None = None) -> str:
    given = [x is not None for x in (image_path, image_bytes, image_base64)]
    if sum(given) != 1:
        raise InvalidInputError("Pass exactly one of image_path, image_bytes or image_base64.")
    if image_base64 is not None:
        if not isinstance(image_base64, str) or image_base64 == "":
            raise InvalidInputError("image_base64 must be a non-empty string.")
        size = decoded_base64_bytes(image_base64)
        if size > IMAGE_MAX_BYTES:
            raise _too_large(size)
        return image_base64
    if image_path is not None:
        size = os.stat(image_path).st_size
        if size > IMAGE_MAX_BYTES:
            raise _too_large(size)
        with open(image_path, "rb") as f:
            data = f.read(IMAGE_MAX_BYTES + 1)
    elif isinstance(image_bytes, (bytes, bytearray, memoryview)):
        data = bytes(image_bytes)
    elif image_bytes is not None and hasattr(image_bytes, "read"):
        data = image_bytes.read(IMAGE_MAX_BYTES + 1)
        if not isinstance(data, (bytes, bytearray)):
            raise InvalidInputError("image_bytes file object must be opened in binary mode.")
    else:
        raise InvalidInputError("image_bytes must be bytes, bytearray, memoryview or a binary file object.")
    if len(data) == 0:
        raise InvalidInputError("The photo is empty.")
    if len(data) > IMAGE_MAX_BYTES:
        raise _too_large(len(data))
    return base64.b64encode(data).decode("ascii")
