"""What does the same model cost new? A Google search through SerpApi, read for Pakistani rupee prices.

Each model is searched once and saved in data/<recipe>/new_prices.json, because the free SerpApi
plan allows 250 searches a month. Without SERPAPI_KEY in .env this quietly does nothing.
"""
import json
import os
import re
import statistics
from datetime import date

import requests

from . import recipe as _settings  # noqa: F401  (loads .env, which has SERPAPI_KEY)

MONTHLY_BUDGET = 200  # leave some of the 250 free searches for trying things by hand
PRICE = re.compile(r"(?:Rs\.?|PKR|₨)\s*([\d,]{4,10})", re.I)


def model_key(brand, model):
    m = re.sub(r"[^A-Z0-9]", "", str(model or "").upper())
    if len(m) < 4 or m in {"UNKNOWN", "NONE"}:  # too vague to search for a specific model
        return None
    return f"{str(brand or '').lower()}|{m}"


class NewPrices:
    def __init__(self, recipe):
        self.path = recipe.data_dir / "new_prices.json"
        self.item = recipe.item
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.cache.setdefault("_searches", {})

    def save(self):
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def searches_left(self):
        return MONTHLY_BUDGET - self.cache["_searches"].get(date.today().strftime("%Y-%m"), 0)

    def get(self, brand, model):
        key = model_key(brand, model)
        return self.cache.get(key) if key else None

    def lookup(self, brand, model, used_hint=None):
        """Cached result, or one search if we have budget. used_hint (a typical used price) filters out
        prices that clearly belong to something else, like a cable or a whole PC."""
        key = model_key(brand, model)
        if not key:
            return None
        if key in self.cache:
            return self.cache[key]
        if not os.environ.get("SERPAPI_KEY") or self.searches_left() <= 0:
            return None
        try:
            found = self._search(brand, model, used_hint)
        except (requests.RequestException, ValueError):
            return None  # slow or failed search: skip it, try again another time
        month = date.today().strftime("%Y-%m")
        self.cache["_searches"][month] = self.cache["_searches"].get(month, 0) + 1
        self.cache[key] = found
        self.save()
        return found

    def _search(self, brand, model, used_hint):
        query = f"{brand} {model} {self.item} price in Pakistan"
        r = requests.get("https://serpapi.com/search.json", timeout=60, params={
            "engine": "google", "q": query, "gl": "pk", "hl": "en", "num": 10, "api_key": os.environ["SERPAPI_KEY"]})
        data = r.json()
        model_up = re.sub(r"[^A-Z0-9]", "", str(model).upper())
        sources = []
        for res in data.get("organic_results", []) + data.get("shopping_results", []):
            text = " ".join(str(res.get(k, "")) for k in ("title", "snippet", "price"))
            if any(s in str(res.get("link") or res.get("product_link") or "") for s in ("olx.", "facebook.")):
                continue  # other people's used listings and posts, not a shop price
            if model_up not in re.sub(r"[^A-Z0-9]", "", text.upper()):
                continue  # a result about some other model
            prices = [int(p.replace(",", "")) for p in PRICE.findall(text)]
            ext = (res.get("rich_snippet", {}).get("top", {}).get("detected_extensions") or {})
            if ext.get("price") and str(ext.get("currency", "")).lower() in ("rs", "pkr", "₨"):
                prices.append(int(ext["price"]))
            if isinstance(res.get("extracted_price"), (int, float)):
                prices.append(int(res["extracted_price"]))
            prices = [p for p in prices if 3000 <= p <= 3_000_000]
            if used_hint:
                prices = [p for p in prices if used_hint * 0.6 <= p <= used_hint * 4]
            if prices:
                sources.append({"site": res.get("source") or res.get("displayed_link", "")[:40],
                                "link": res.get("link") or res.get("product_link"), "price": statistics.median(prices)})
        result = {"query": query, "checked": date.today().isoformat(), "sources": sources[:5]}
        if sources:
            prices = [s["price"] for s in sources]
            result.update(price=int(statistics.median(prices)), low=int(min(prices)), high=int(max(prices)),
                          # shops that roughly agree; otherwise the page shows the range and links, not one number
                          confident=len(prices) >= 2 and max(prices) / min(prices) <= 1.6)
        return result


def for_page(found):
    """The part of a lookup the page shows."""
    if not found or "price" not in found:
        return None
    return {k: found[k] for k in ("price", "low", "high", "confident")} | {
        "sources": [{"site": s["site"], "link": s["link"], "price": s["price"]} for s in found["sources"]]}
