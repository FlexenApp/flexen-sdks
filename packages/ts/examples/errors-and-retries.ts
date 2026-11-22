/**
 * Error classes, retries, timeout and idempotency.
 * Run: FLEXEN_API_KEY=flx_test_… npx tsx examples/errors-and-retries.ts
 */
import { APIError, Flexen, InsufficientCreditsError, RateLimitError, TierUnavailableError } from '@flexenai/api'

const flexen = new Flexen({ maxRetries: 3, timeoutMs: 30_000 })

try {
  // The same Idempotency-Key makes a repeat safe for 24 hours: the answer is replayed, nothing is deducted again.
  const key = crypto.randomUUID()
  const first = await flexen.goals.calculate({ sex: 'female', weight_kg: 64, height_cm: 170, age: 31, activity_level: 'active', goal: 'maintain' }, { idempotencyKey: key })
  const again = await flexen.goals.calculate({ sex: 'female', weight_kg: 64, height_cm: 170, age: 31, activity_level: 'active', goal: 'maintain' }, { idempotencyKey: key })
  console.log(first.data.calories_kcal, 'replayed:', again.idempotentReplayed, 'charged:', again.creditsCharged)

  // max is in the contract but not available yet: a live key gets 422 tier_unavailable.
  await flexen.nutrition.text({ text: 'porridge with blueberries', tier: 'max' })
} catch (e) {
  if (e instanceof TierUnavailableError) console.log('tier max is not available yet, use light')
  else if (e instanceof InsufficientCreditsError) console.log(`top up in the console, balance ${e.creditsRemaining}`)
  else if (e instanceof RateLimitError) console.log(`still rate limited after retries, retry after ${e.retryAfterSeconds} s`)
  else if (e instanceof APIError) console.log(e.status, e.code, e.apiMessage, e.requestId)
  else throw e
}
