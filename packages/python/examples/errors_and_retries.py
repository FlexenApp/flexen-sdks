"""Error classes, retries, timeout and idempotency.

Run: FLEXEN_API_KEY=flx_test_… python examples/errors_and_retries.py
"""

import uuid

from flexen import APIError, Flexen, InsufficientCreditsError, RateLimitError, TierUnavailableError

BODY = dict(sex="female", weight_kg=64, height_cm=170, age=31, activity_level="active", goal="maintain")

with Flexen(max_retries=3, timeout=30) as client:
    try:
        # The same Idempotency-Key makes a repeat safe for 24 hours: the answer is replayed, nothing is deducted again.
        key = str(uuid.uuid4())
        first = client.goals.calculate(**BODY, idempotency_key=key)
        again = client.goals.calculate(**BODY, idempotency_key=key)
        print(first.data.calories_kcal, "replayed:", again.idempotent_replayed, "charged:", again.credits_charged)

        # max is in the contract but not available yet: a live key gets 422 tier_unavailable.
        client.nutrition.text("porridge with blueberries", tier="max")
    except TierUnavailableError:
        print("tier max is not available yet, use light")
    except InsufficientCreditsError as e:
        print(f"top up in the console, balance {e.credits_remaining}")
    except RateLimitError as e:
        print(f"still rate limited after retries, retry after {e.retry_after_seconds} s")
    except APIError as e:
        print(e.status_code, e.code, e.message, e.request_id)
