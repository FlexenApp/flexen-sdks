"""Async client with your own foods: upload, iterate, search, delete. Catalog calls are free.

Run: FLEXEN_API_KEY=flx_test_… python examples/async_catalog.py
"""

import asyncio

from flexen import AsyncFlexen

FOOD = {"id": "sku-10482", "name": "Protein bar hazelnut", "per_100g": {"kcal": 386, "protein_g": 31, "carbs_g": 29, "fat_g": 15}}


async def main() -> None:
    async with AsyncFlexen() as client:
        await client.catalog.foods.upsert([FOOD])
        async for food in client.catalog.foods.iterate():
            print(food.id, food.name, food.per_100g.kcal)
        # Search looks in your catalog first, then in the open sources.
        res = await client.foods.search("protein bar", sources=["customer_catalog", "open_food_facts"])
        for r in res.data.results:
            print(r.name, r.source)
        await client.catalog.foods.delete("sku-10482")


asyncio.run(main())
