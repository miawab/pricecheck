"""TabPFN prices listings; plain code turns the price range into bargaining advice.

TabPFN never needs training ahead of time: it reads the current listings as examples
every time it predicts, so prices follow the market as the data refreshes.
"""
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import KFold

from . import recipe as _settings  # noqa: F401  (loads .env, which has TABPFN_TOKEN)

WINDOW_DAYS = 120  # listings older than this describe a different market; keep them archived, don't price from them
TWIN_CITIES = {"Islamabad", "Rawalpindi"}
COMMON = ["condition", "has_box", "has_warranty", "has_fault", "city_group", "photos", "featured", "seller_verified", "age_days", "removed"]


def frame(recipe, store):
    """One row per usable listing: a single working item, with a price and its specs."""
    rows = []
    for lid, spec in store.specs.items():
        l = store.listings.get(lid)
        if l is None or spec.get("kind") != "single_item" or not l.get("price"):
            continue
        rows.append({**l, **spec})
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    for f in recipe.fields:  # Gemma sometimes writes "unknown" where a number belongs
        if f["type"] in ("number", "integer") and f["name"] in d:
            d[f["name"]] = pd.to_numeric(d[f["name"]], errors="coerce")
    d = d[d.price.between(1000, 5_000_000)].dropna(subset=recipe.required).copy()
    # Prices wildly off their group's median (typos, wrong category, "price on call" placeholders)
    # are still shown and judged, but TabPFN doesn't learn from them.
    if recipe.group_by:
        group = d[recipe.group_by]
        group = group.round() if pd.api.types.is_numeric_dtype(group) else group.astype(str)
        ratio = d.price / d.groupby(group).price.transform("median")
    else:
        ratio = d.price / d.price.median()
    d["outlier"] = (ratio > 4) | (ratio < 0.25)
    d["age_days"] = (time.time() - d.posted.astype(float)) / 86400
    d = d[d.age_days <= WINDOW_DAYS].copy()
    d["removed"] = d.removed_on.notna()
    if "brand" not in d:
        d["brand"] = "unknown"
    # With a reputable list, small brands are pooled as "other"; without one, every brand stands alone.
    d["brand_group"] = d.brand.where(d.brand.isin(recipe.reputable), "other") if recipe.reputable else d.brand.fillna("unknown")
    d["reputable"] = d.brand.isin(recipe.reputable)
    d["condition"] = d.condition.where(d.condition != "unknown", d.condition_dropdown.fillna("unknown"))
    d["city_group"] = np.select([d.city.isin(TWIN_CITIES), d.city == "Lahore", d.city == "Karachi"],
                                ["isb_rwp", "lahore", "karachi"], "other")
    return d.reset_index(drop=True)


CATEGORICAL = {"brand_group", "condition", "city_group"}


def features(recipe, d):
    cols = [c for c in recipe.spec_names if c not in ("brand", "model")] + ["brand_group"] + COMMON
    kinds = {f["name"]: f["type"] for f in recipe.fields}
    X = pd.DataFrame(index=d.index)
    for c in cols:
        if c in CATEGORICAL or kinds.get(c) in ("enum", "string"):
            X[c] = d[c].astype(str).astype("category").cat.codes.astype(float)
        else:
            X[c] = pd.to_numeric(d[c].astype(object).map(lambda v: float(v) if isinstance(v, bool) else v), errors="coerce")
    return X.to_numpy(dtype=float)


def _fit_predict(X_train, y_train, X_test):
    from tabpfn import TabPFNRegressor  # imported here so the rest (advice, similar, tests) works without torch

    model = TabPFNRegressor(device="cpu", random_state=0).fit(X_train, y_train)
    q = model.predict(X_test, output_type="quantiles", quantiles=[0.25, 0.5, 0.75])
    return np.exp(np.array(q).T)  # rows: q25, q50, q75 in rupees


def price_all(recipe, d, folds=5):
    """Price every listing with a model that never saw it (so its own price can't leak in)."""
    X, y = features(recipe, d), np.log(d.price.to_numpy())
    clean = ~d.outlier.to_numpy()
    out = np.zeros((len(d), 3))
    for train, test in KFold(folds, shuffle=True, random_state=0).split(X):
        train = train[clean[train]]
        out[test] = _fit_predict(X[train], y[train], X[test])
    d = d.copy()
    d[["q25", "q50", "q75"]] = out
    return d


def price_one(recipe, d, row):
    """Price a listing that isn't in the data yet (live check)."""
    d = d[~d.outlier]
    both = pd.concat([d, pd.DataFrame([row])], ignore_index=True)
    X = features(recipe, both)
    q = _fit_predict(X[:-1], np.log(d.price.to_numpy()), X[-1:])[0]
    return dict(zip(["q25", "q50", "q75"], q))


def round500(x):
    return int(round(x / 500) * 500)


def advice(price, q25, q50, q75):
    """Turn a price range into what to do. Code decides; the model only supplied the range."""
    gap = price / q50 - 1
    if q75 / q25 > 2.2:
        verdict, say = "unsure", "Similar listings vary too much in price to judge this one. Compare it with the similar listings below."
    elif price < q25 * 0.6:
        verdict, say = "too_cheap", "Far below similar listings. Check carefully in person: it may be faulty, stolen or a scam."
    elif price <= q25:
        verdict, say = "good_deal", "Cheaper than most similar listings. A small discount is still worth asking for."
    elif price <= q75:
        verdict, say = "fair", "In the usual range. There's some room to bargain."
    else:
        verdict, say = "overpriced", "Above the usual range. Bargain hard or look at the cheaper similar listings."
    target_low, target_high = min(price, q25), min(price, q50)
    return {
        "verdict": verdict,
        "say": say,
        "gap_pct": round(gap * 100),
        "open_at": round500(min(price, q25) * 0.92),
        "fair_from": round500(target_low),
        "fair_to": round500(target_high),
        "max_pay": round500(min(price, q75)),  # never more than they ask, never above the usual range
    }


def similar(recipe, d, row, n=6):
    """Active listings matching the recipe's `similar_on` fields; nearby cities first, then cheapest."""
    m = d[(d.removed_on.isna()) & (d.id != row.get("id"))]
    for f in recipe.similar_on:
        v = row.get(f)
        if v is None or v == "unknown" or (isinstance(v, float) and np.isnan(v)):
            continue
        tol = recipe.tolerance.get(f)
        m = m[(m[f] - v).abs() <= tol] if tol is not None else m[m[f] == v]
    near = (m.city_group == row.get("city_group")).astype(int)
    m = m.assign(_near=near).sort_values(["_near", "price"], ascending=[False, True])
    return m.head(n)


def accuracy(d):
    """How close the middle of the range lands to real asking prices, vs the simple 'same specs' median."""
    err = (d.q50 - d.price).abs() / d.price
    inside = ((d.price >= d.q25) & (d.price <= d.q75)).mean()
    return {"median_error_pct": round(float(err.median()) * 100, 1),
            "within_15_pct": round(float((err <= 0.15).mean()) * 100, 1),
            "range_hit_pct": round(float(inside) * 100), "n": int(len(d))}
