/**
 * Your own foods: upload, search, iterate, delete. Catalog calls are free.
 * Run: FLEXEN_API_KEY=flx_test_… npx tsx examples/catalog.ts
 */
import { Flexen } from '@flexen/api'

const flexen = new Flexen()

await flexen.catalog.foods.upsert({
  foods: [{ id: 'sku-10482', name: 'Protein bar hazelnut', per_100g: { kcal: 386, protein_g: 31, carbs_g: 29, fat_g: 15 } }],
})

for await (const food of flexen.catalog.foods.iterate()) console.log(food.id, food.name, food.per_100g.kcal)

// Search looks in your catalog first, then in the open sources.
const { data } = await flexen.foods.search({ q: 'protein bar', sources: ['customer_catalog', 'open_food_facts'] })
for (const r of data.results) console.log(r.name, r.source)

await flexen.catalog.foods.delete('sku-10482')
