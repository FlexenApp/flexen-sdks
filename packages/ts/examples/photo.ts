/**
 * Nutrition from a photo (beta).
 * Run: FLEXEN_API_KEY=flx_test_… npx tsx examples/photo.ts ./lunch.jpg
 */
import { Flexen, InvalidInputError, LIMITS } from '@flexenai/api'

const file = process.argv[2]
if (!file) throw new Error('usage: photo.ts <image file>')

const flexen = new Flexen()
try {
  const res = await flexen.nutrition.photo({ file, lang: 'en', hint: 'lunch at home' })
  console.log(res.data.dish, `${res.data.kcal.value} kcal`, `confidence ${res.data.confidence}`)
  console.log(`charged ${res.creditsCharged}, remaining ${res.creditsRemaining}`)
} catch (e) {
  if (e instanceof InvalidInputError) console.error(`not sent: ${e.message} (limit ${LIMITS.imageMaxMiB} MiB)`)
  else throw e
}
