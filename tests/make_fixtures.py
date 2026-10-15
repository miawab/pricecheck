"""Turn real OLX pages saved from a browser or curl into small test fixtures.

    python tests/make_fixtures.py search.html item.html

Only the fields olx.py reads are kept. Seller contact details, user IDs and phone
numbers never reach the fixtures (the repo is public).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pricecheck.olx import no_phones  # noqa: E402

OUT = Path(__file__).resolve().parent / "fixtures" / "olx"
HIT_KEYS = ["externalID", "title", "price", "timestamp", "createdAt", "coverPhoto", "photoCount", "product", "isSellerVerified"]


def state_of(path):
    html = Path(path).read_text(encoding="utf-8")
    start = html.find("window.state = ")
    return json.JSONDecoder().raw_decode(html, start + len("window.state = "))[0]


def trim(hit):
    out = {k: hit[k] for k in HIT_KEYS if k in hit}
    out["title"] = no_phones(out["title"])
    extra = hit.get("extraFields") or {}
    out["extraFields"] = {k: extra[k] for k in ("price", "brand", "new_used", "type") if k in extra}
    out["location"] = [{"level": l["level"], "name": l["name"]} for l in hit.get("location", [])]
    if "coverPhoto" in out:
        out["coverPhoto"] = {"id": out["coverPhoto"].get("id")}
    return out


def page(state):
    """A minimal page in the shape OLX serves: the data lives in a `window.state = {...};` script."""
    return f"<!doctype html><html><head><title>OLX</title></head><body>\n<script>window.state = {json.dumps(state, ensure_ascii=False)};</script>\n</body></html>\n"


def main(search_html, item_html):
    OUT.mkdir(parents=True, exist_ok=True)
    hits = [trim(h) for h in state_of(search_html)["algolia"]["content"]["hits"][:12]]
    for n, chunk in ((1, hits[:6]), (2, hits[6:])):
        state = {"algolia": {"content": {"hits": chunk, "nbPages": 2, "page": n - 1}}}
        (OUT / f"search_p{n}.html").write_text(page(state), encoding="utf-8")

    ad = (state_of(item_html).get("ad") or {}).get("data") or {}
    item = trim(ad)
    item["description"] = no_phones(ad.get("description"))
    item["state"] = ad.get("state")
    (OUT / "item.html").write_text(page({"ad": {"data": item}}), encoding="utf-8")
    print(f"wrote {len(hits)} listings and 1 listing page to {OUT}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
