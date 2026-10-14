"""Read public OLX Pakistan pages.

Polite by design: one page every 2 seconds, only public search and listing pages
(allowed by robots.txt), and seller names or phone numbers are never kept.
OLX serves at most ~50 pages per search, so recipes should point at a narrow category.
"""
import json
import re
import time

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141 Safari/537.36"}
DELAY = 2.0


def _state(url):
    html = requests.get(url, headers=HEADERS, timeout=30).text
    start = html.find("window.state = ")
    if start < 0:
        raise ValueError(f"no page data at {url}")
    state, _ = json.JSONDecoder().raw_decode(html, start + len("window.state = "))
    return state


PHONE = re.compile(r"(\+?92|0)[\s-]?3\d{2}[\s-]?\d{7}|\b\d{4}[\s-]?\d{7}\b")


def no_phones(text):
    """Sellers often put phone numbers in titles; we never keep or show them."""
    return re.sub(r"\s{2,}", " ", PHONE.sub("", text or "")).strip(" -|,")


def item_url(listing_id, title):
    """OLX redirects any '<words>-iid-<id>' to the real page, so we build links from the cleaned title
    (OLX's own links repeat the original title, phone numbers included)."""
    slug = re.sub(r"[^a-z0-9]+", "-", no_phones(title).lower()).strip("-")[:80] or "listing"
    return f"https://www.olx.com.pk/item/{slug}-iid-{listing_id}"


def _listing(hit):
    extra = hit.get("extraFields") or {}
    loc = {l["level"]: l["name"] for l in hit.get("location", [])}
    cover = (hit.get("coverPhoto") or {}).get("id") or next((p["id"] for p in hit.get("photos") or []), None)
    return {
        "id": str(hit["externalID"]),
        "url": item_url(hit["externalID"], hit["title"]),
        "title": no_phones(hit["title"]),
        "price": hit.get("price") or extra.get("price"),
        "brand_dropdown": extra.get("brand"),
        "condition_dropdown": extra.get("new_used"),
        "city": loc.get(2),
        "area": loc.get(3),
        "posted": hit.get("timestamp") or hit.get("createdAt"),
        "photo": f"https://images.olx.com.pk/thumbnails/{cover}-400x300.webp" if cover else None,
        "photos": hit.get("photoCount") or len(hit.get("photos") or []),
        "featured": hit.get("product") == "featured",
        "seller_verified": bool(hit.get("isSellerVerified")),
    }


def search(path, log=print):
    """Every listing in a search/category, e.g. 'computer-components_c708205?filter=type_eq_monitors'."""
    path = re.sub(r"^https?://(www\.)?olx\.com\.pk/", "", path.strip())
    seen, out, page = set(), [], 1
    while True:
        sep = "&" if "?" in path else "?"
        content = _state(f"https://www.olx.com.pk/{path}" + (f"{sep}page={page}" if page > 1 else ""))["algolia"]["content"]
        new = [h for h in content.get("hits", []) if str(h["externalID"]) not in seen]
        if not new:
            break
        for h in new:
            seen.add(str(h["externalID"]))
            out.append(_listing(h))
        log(f"  page {page}/{content.get('nbPages')}: {len(out)} listings")
        if page >= (content.get("nbPages") or 0):
            break
        page += 1
        time.sleep(DELAY)
    return out


def listing_id(url):
    m = re.search(r"iid-(\d+)", url)
    return m.group(1) if m else None


def details(url):
    """One listing page: the listing itself plus its description."""
    state = _state(url)
    ad = (state.get("ad") or {}).get("data") or state.get("ad") or {}
    if not ad.get("externalID"):
        return None
    row = _listing(ad)
    row["description"] = no_phones(ad.get("description"))
    row["active"] = ad.get("state") == "active"
    return row
