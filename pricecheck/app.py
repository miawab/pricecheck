"""Run pricecheck on your own PC: serves the page and checks brand-new listings live.

    python -m pricecheck.app        then open http://localhost:8000
"""
from datetime import date

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import model, olx
from .extract import read_listing
from .recipe import ROOT, Recipe
from .store import Store
from .update import to_item

app = FastAPI()


@app.get("/api/check")
def check(url: str, recipe: str = "monitors"):
    r = Recipe(recipe)
    lid = olx.listing_id(url)
    if not lid:
        raise HTTPException(400, "Not an OLX listing link")
    store = Store(r)
    listing = olx.details(url)
    if listing is None:
        raise HTTPException(404, "OLX didn't return that listing (removed?)")
    today = date.today().isoformat()
    old = store.listings.get(lid, {})
    store.listings[lid] = {**listing, "first_seen": old.get("first_seen", today), "last_seen": today, "removed_on": None,
                           "price_history": old.get("price_history", [[today, listing["price"]]])}
    store.save()
    if lid not in store.specs:
        spec = read_listing(r, store.listings[lid])
        if spec is None:
            raise HTTPException(502, "Gemma couldn't read this listing")
        store.add_spec(spec)
    if store.specs[lid].get("kind") != "single_item":
        raise HTTPException(422, f"This doesn't look like a single {r.item} for sale (Gemma says: {store.specs[lid].get('kind')}).")

    d = model.frame(r, store)
    mine = d[d.id == lid]
    if mine.empty:
        raise HTTPException(422, "Missing a price or size, so it can't be compared.")
    row = mine.iloc[0].to_dict()
    row.update(model.price_one(r, d[d.id != lid], row))
    return to_item(r, d, row)


app.mount("/", StaticFiles(directory=ROOT / "site", html=True), name="site")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
