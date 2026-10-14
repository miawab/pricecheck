"""Daily update: collect -> read new listings with Gemma -> price everything with TabPFN -> write the site's data file.

    python -m pricecheck.update monitors              # full daily run
    python -m pricecheck.update monitors --no-collect # re-price what we already have
    python -m pricecheck.update monitors --no-gemma   # collect and price, but leave new listings unread (no GPU)
    python -m pricecheck.update monitors --limit 100  # let Gemma read at most 100 listings this run (a quick first try)

Nothing runs on its own: the data only changes when you run this.
"""
import json
import sys
import time
from datetime import datetime

import numpy as np

from . import model, olx
from .extract import read_listing
from .recipe import ROOT, Recipe
from .store import Store

SITE_DATA = ROOT / "site" / "data"
PUBLIC_FIELDS = ["id", "url", "title", "price", "photo", "city", "area", "posted", "first_seen", "brand", "model",
                 "condition", "has_box", "has_warranty", "has_fault", "reputable", "featured"]


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def clean(v):
    if isinstance(v, (np.floating, float)):
        return None if np.isnan(v) else round(float(v), 1)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def to_item(recipe, d, row):
    """What the page needs for one listing: its facts, its price range, advice and similar listings."""
    item = {k: clean(row.get(k)) for k in PUBLIC_FIELDS + recipe.spec_names}
    item["title"] = olx.no_phones(item["title"])
    item.update(q25=round(row["q25"]), q50=round(row["q50"]), q75=round(row["q75"]),
                advice=model.advice(row["price"], row["q25"], row["q50"], row["q75"]),
                first_price=row["price_history"][0][1],
                similar=[str(x) for x in model.similar(recipe, d, row).id])
    return item


def page_info(recipe):
    """What the page needs to know about the recipe: titles, which filters to show, how to label specs."""
    fields = [{"name": f["name"], "label": f.get("label", f["name"].replace("_", " ")), "type": f["type"],
               "unit": f.get("unit", "")} for f in recipe.fields if f["name"] in recipe.spec_names]
    return {"name": recipe.name, "title": recipe.title, "item": recipe.item, "filters": recipe.filters,
            "fields": fields, "similar_on": recipe.similar_on, "has_reputable": bool(recipe.reputable),
            "inspect": recipe.inspect}


def write_index():
    """List of recipes that have data, for the page's category switcher."""
    recipes = []
    for p in sorted(SITE_DATA.glob("*.json")):
        if p.name != "index.json":
            r = json.loads(p.read_text(encoding="utf-8"))["recipe"]
            recipes.append({"name": r["name"], "title": r["title"]})
    (SITE_DATA / "index.json").write_text(json.dumps(recipes), encoding="utf-8")


def run(name, collect=True, gemma=True, limit=None):
    recipe, t0 = Recipe(name), time.time()
    store = Store(recipe)
    counts = {"new": 0, "repriced": 0, "removed": 0}

    if collect:
        log(f"collecting OLX {recipe.title.lower()}")
        new, repriced, removed = store.merge(olx.search(recipe.olx_search, log=log))
        counts.update(new=new, repriced=repriced, removed=removed)
        store.save()
        log(f"{new} new, {repriced} changed price, {removed} gone since last run")

        todo = store.needing_details()
        log(f"fetching {len(todo)} descriptions")
        for i, l in enumerate(todo, 1):
            try:
                d = olx.details(l["url"])
            except Exception as e:  # one bad page shouldn't stop the run
                log(f"  {l['id']}: {e}")
                d = None
            l["description"] = (d or {}).get("description", "")
            if i % 50 == 0:
                store.save()
                log(f"  {i}/{len(todo)}")
            time.sleep(olx.DELAY)
        store.save()

    todo = store.needing_specs() if gemma else []
    if limit is not None:
        todo = todo[:limit]
    log(f"Gemma reading {len(todo)} listings" if gemma else f"skipping Gemma ({len(store.needing_specs())} listings wait to be read)")
    for i, l in enumerate(todo, 1):
        spec = read_listing(recipe, l)
        if spec:
            store.add_spec(spec)
        if i % 25 == 0:
            log(f"  {i}/{len(todo)}")

    d = model.frame(recipe, store)
    log(f"TabPFN pricing {len(d)} listings")
    d = model.price_all(recipe, d)
    acc = model.accuracy(d)

    items = [to_item(recipe, d, r.to_dict()) for _, r in d[d.removed_on.isna()].iterrows()]

    out = {
        "recipe": page_info(recipe),
        "updated": datetime.now().isoformat(timespec="minutes"),
        "accuracy": acc,
        "counts": {**counts, "active": len(items), "priced": len(d),
                   "removed_kept": int(d.removed.sum())},
        "listings": items,
    }
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / f"{recipe.name}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    write_index()
    log(f"done in {(time.time() - t0) / 60:.1f} min: {len(items)} listings on the site, typical error {acc['median_error_pct']}%")


if __name__ == "__main__":
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    run(args[0] if args and not args[0].startswith("--") else "monitors",
        collect="--no-collect" not in args, gemma="--no-gemma" not in args, limit=limit)
