/**
 * Nutrition from free text, with a few per-call settings.
 * Run: FLEXEN_API_KEY=flx_test_… npx tsx examples/text.ts
 * A test key returns a fixed example and costs nothing.
 */
import { Flexen } from '@flexenai/api'

const flexen = new Flexen() // reads FLEXEN_API_KEY

const res = await flexen.nutrition.text({
  text: '2 slices of wholemeal bread with gouda and an apple',
  lang: 'en',
  nutrients: 'eu7',
  energy_unit: 'kcal',
})

for (const item of res.data.items) {
  console.log(`${item.name}: ${item.kcal.value} kcal (${item.kcal.low} to ${item.kcal.high}), source ${item.source}${item.needs_review ? ', check this one' : ''}`)
}
console.log(`total ${res.data.total.kcal.value} kcal, measured: ${res.data.measured}`)
console.log(`charged ${res.creditsCharged}, remaining ${res.creditsRemaining}, request ${res.requestId}`)
