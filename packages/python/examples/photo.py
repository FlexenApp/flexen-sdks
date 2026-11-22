"""Nutrition from a photo (beta).

Run: FLEXEN_API_KEY=flx_test_… python examples/photo.py lunch.jpg
"""

import sys

from flexenai import LIMITS, Flexen, InvalidInputError

if len(sys.argv) != 2:
    sys.exit("usage: photo.py <image file>")

with Flexen() as client:
    try:
        res = client.nutrition.photo(image_path=sys.argv[1], lang="en", hint="lunch at home")
    except InvalidInputError as e:
        sys.exit(f"not sent: {e} (limit {LIMITS['imageMaxMiB']} MiB)")
    print(res.data.dish, f"{res.data.kcal.value} kcal", f"confidence {res.data.confidence}")
    print(f"charged {res.credits_charged}, remaining {res.credits_remaining}")
