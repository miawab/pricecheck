"""Daily update: collect -> read new listings with Gemma -> price everything with TabPFN -> write the site's data file.

    python -m pricecheck.update monitors              # full daily run
    python -m pricecheck.update monitors --no-collect # re-price what we already have
    python -m pricecheck.update monitors --no-gemma   # collect and price, but leave new listings unread (no GPU)
    python -m pricecheck.update monitors --limit 100  # let Gemma read at most 100 listings this run (a quick first try)
    python -m pricecheck.update monitors --new-prices 30  # also look up new prices for the 30 most common models (SerpApi)

Nothing runs on its own: the data only changes when you run this.
"""
import atexit
import json
import sys
import time
from datetime import datetime

import numpy as np
import sentry_sdk

from . import breakage, model, olx, tracing
from .extract import read_listing
from .newprice import NewPrices, for_page, model_key
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


def run(name, collect=True, gemma=True, limit=None, new_prices=0):
    recipe, t0 = Recipe(name), time.time()
    store = Store(recipe)
    counts = {"new": 0, "repriced": 0, "removed": 0}

    if collect:
        log(f"collecting OLX {recipe.title.lower()}")
        try:
            found = olx.search(recipe.olx_search, log=log)
        except olx.LayoutChanged as e:
            breakage.report(e, f"python -m pricecheck.update {name}", log=log)
            log("stopped: nothing was changed. Once the fix is merged, `git pull` and run this again.")
            sys.exit(1)
        new, repriced, removed = store.merge(found)
        counts.update(new=new, repriced=repriced, removed=removed)
        store.save()
        log(f"{new} new, {repriced} changed price, {removed} gone since last run")

        todo = store.needing_details()
        log(f"fetching {len(todo)} descriptions")
        for i, l in enumerate(todo, 1):
            try:
                d = olx.details(l["url"])
            except olx.LayoutChanged as e:  # every listing page will fail the same way: report once and stop
                breakage.report(e, f"python -m pricecheck.update {name}", log=log)
                store.save()
                log("stopped fetching descriptions. Once the fix is merged, `git pull` and run this again.")
                sys.exit(1)
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
        with tracing.run("read listing"), tracing.agent(f"Read OLX listing {l['id']}: {l['title']}"):
            spec = read_listing(recipe, l)
        if spec:
            store.add_spec(spec)
        if i % 25 == 0:
            log(f"  {i}/{len(todo)}")

    d = model.frame(recipe, store)
    log(f"TabPFN pricing {len(d)} listings")
    with tracing.run("price all listings"), tracing.tool(
            "tabpfn_price_range", "TabPFN prices every listing from the others (5-fold)",
            {"listings": len(d), "recipe": recipe.name}) as span:
        d = model.price_all(recipe, d)
        acc = model.accuracy(d)
        tracing.result(span, acc)

    items = [to_item(recipe, d, r.to_dict()) for _, r in d[d.removed_on.isna()].iterrows()]

    # New prices: look up the most common models (uses SerpApi searches), then attach whatever is saved.
    newp = NewPrices(recipe)
    if new_prices:
        by_model = {}
        for it in items:
            key = model_key(it.get("brand"), it.get("model"))
            if key and key not in newp.cache:
                by_model.setdefault(key, []).append(it)
        top = sorted(by_model.values(), key=len, reverse=True)[:new_prices]
        log(f"looking up new prices for {len(top)} models ({newp.searches_left()} searches left this month)")
        for group in top:
            with tracing.run("new price"), tracing.tool("serpapi_new_price", "Google search for the same model's new price",
                                                        {"model": group[0].get("model")}) as span:
                tracing.result(span, newp.lookup(group[0]["brand"], group[0]["model"], used_hint=group[0]["q50"]))
    for it in items:
        it["new_price"] = for_page(newp.get(it.get("brand"), it.get("model")))

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
    if tracing.init():
        atexit.register(sentry_sdk.flush)  # send the last traces before the command exits
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    new_prices = int(args[args.index("--new-prices") + 1]) if "--new-prices" in args else 0
    run(args[0] if args and not args[0].startswith("--") else "monitors",
        collect="--no-collect" not in args, gemma="--no-gemma" not in args, limit=limit, new_prices=new_prices)
