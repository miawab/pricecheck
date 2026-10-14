"""Run pricecheck on your own PC: serves the page and checks brand-new listings live.

    python -m pricecheck.app        then open http://localhost:8000
"""
from datetime import date

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from . import model, olx, tracing
from .extract import read_listing
from .recipe import ROOT, Recipe
from .store import Store
from .update import to_item

tracing.init()  # before FastAPI starts, so each request becomes a trace
app = FastAPI()


@app.get("/api/check")
def check(url: str, recipe: str = "monitors"):
    with tracing.agent(f"Is this OLX {recipe} price fair? {url}") as run:
        item = _check(url, Recipe(recipe))
        a = item["advice"]
        run.set_data("gen_ai.output.messages", tracing.messages(
            "assistant", f"{a['verdict']}: usual Rs {item['q25']}-{item['q75']}, open at {a['open_at']}, max {a['max_pay']}"))
        return item


def _check(url, r):
    lid = olx.listing_id(url)
    if not lid:
        raise HTTPException(400, "Not an OLX listing link")
    store = Store(r)
    with tracing.tool("fetch_olx_listing", "Read the public OLX listing page", {"url": url}) as span:
        listing = olx.details(url)
        tracing.result(span, {"found": listing is not None, "price": (listing or {}).get("price")})
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
    others = d[d.id != lid]
    with tracing.tool("tabpfn_price_range", "TabPFN predicts the usual asking price range from similar listings",
                      {"example_listings": len(others), "recipe": r.name}) as span:
        row.update(model.price_one(r, others, row))
        tracing.result(span, {k: round(row[k]) for k in ("q25", "q50", "q75")})
    with tracing.tool("bargain_advice", "Plain code turns the range into what to offer",
                      {"price": row["price"], "q25": round(row["q25"]), "q75": round(row["q75"])}) as span:
        item = to_item(r, d, row)
        tracing.result(span, item["advice"])
    return item


app.mount("/", StaticFiles(directory=ROOT / "site", html=True), name="site")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
