"""Nutrition from free text, with a few per-call settings.

Run: FLEXEN_API_KEY=flx_test_… python examples/text.py
A test key returns a fixed example and costs nothing.
"""

from flexen import Flexen

with Flexen() as client:  # reads FLEXEN_API_KEY
    res = client.nutrition.text("2 slices of wholemeal bread with gouda and an apple", lang="en", nutrients="eu7")
    for item in res.data.items:
        review = ", check this one" if item.needs_review else ""
        print(f"{item.name}: {item.kcal.value} kcal ({item.kcal.low} to {item.kcal.high}), source {item.source}{review}")
    print(f"total {res.data.total.kcal.value} kcal, measured: {res.data.measured}")
    print(f"charged {res.credits_charged}, remaining {res.credits_remaining}, request {res.request_id}")
