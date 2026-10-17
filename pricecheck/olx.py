"""Read public OLX Pakistan pages.

Polite by design: one page every 2 seconds, only public search and listing pages
(allowed by robots.txt), and seller names or phone numbers are never kept.
OLX serves at most ~50 pages per search, so recipes should point at a narrow category.
"""
import json
import os
import re
import time

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/141 Safari/537.36"}
DELAY = 2.0


class LayoutChanged(ValueError):
    """OLX served a page we can't read any more. Carries the page so breakage.py can report what changed."""

    def __init__(self, url, html, reason):
        super().__init__(f"OLX page layout changed at {url}: {reason}")
        self.url, self.html, self.reason = url, html, reason


def _fetch(url):
    html = requests.get(url, headers=HEADERS, timeout=30).text
    if os.environ.get("PRICECHECK_REHEARSE_OLX_CHANGE"):
        from .rehearsal import change_layout  # demo only: pretend OLX shipped a redesign
        html = change_layout(html)
    return html


# OLX has put the page data in `window.state = {...}` and (newer) `window.__OLX_STATE__ = {...}`.
STATE_MARKERS = ("window.state = ", "window.__OLX_STATE__ = ")


def _page(url):
    """The page's data (OLX puts it in a `window.state = {...}` or `window.__OLX_STATE__ = {...}` script) and the raw HTML."""
    html = _fetch(url)
    for marker in STATE_MARKERS:
        start = html.find(marker)
        if start >= 0:
            state, _ = json.JSONDecoder().raw_decode(html, start + len(marker))
            return state, html
    raise LayoutChanged(url, html, "no `window.state` page data")


def _state(url):
    return _page(url)[0]


PHONE = re.compile(r"(\+?92|0)[\s-]?3\d{2}[\s-]?\d{7}|\b\d{4}[\s-]?\d{7}\b")


def no_phones(text):
    """Sellers often put phone numbers in titles; we never keep or show them."""
    return re.sub(r"\s{2,}", " ", PHONE.sub("", text or "")).strip(" -|,")


def item_url(listing_id, title):
    """OLX redirects any '<words>-iid-<id>' to the real page, so we build links from the cleaned title
    (OLX's own links repeat the original title, phone numbers included)."""
    slug = re.sub(r"[^a-z0-9]+", "-", no_phones(title).lower()).strip("-")[:80] or "listing"
    return f"https://www.olx.com.pk/item/{slug}-iid-{listing_id}"


def _hit_id(hit):
    """The listing id: `externalID`, or `adId` where OLX renamed it. (The hit's plain numeric `id` is an internal
    key, not the id in the listing's URL.) Raises KeyError when neither is there."""
    for key in ("externalID", "adId"):
        if hit.get(key):
            return hit[key]
    raise KeyError("externalID")


def _listing(hit):
    listing_id = _hit_id(hit)
    extra = hit.get("extraFields") or {}
    loc = {l["level"]: l["name"] for l in hit.get("location", [])}
    cover = (hit.get("coverPhoto") or {}).get("id") or next((p["id"] for p in hit.get("photos") or []), None)
    return {
        "id": str(listing_id),
        "url": item_url(listing_id, hit["title"]),
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


def _search_results(state):
    """(listings, page count) from a search page's data. OLX has served three layouts:
    `algolia.content.hits` / `nbPages`, `listingSearch.page.items` / `totalPages`,
    and (newest, in `window.__OLX_STATE__`) `search.results` / `pageCount`.
    Raises KeyError/TypeError when the page matches neither."""
    if "algolia" in state:
        content = state["algolia"]["content"]
        return content["hits"], content.get("nbPages")
    if "listingSearch" in state:
        page = state["listingSearch"]["page"]
        return page["items"], page.get("totalPages")
    if "search" in state:
        search = state["search"]
        return search["results"], search.get("pageCount")
    raise KeyError("algolia, listingSearch or search")


def search(path, log=print):
    """Every listing in a search/category, e.g. 'computer-components_c708205?filter=type_eq_monitors'."""
    path = re.sub(r"^https?://(www\.)?olx\.com\.pk/", "", path.strip())
    seen, out, page = set(), [], 1
    while True:
        sep = "&" if "?" in path else "?"
        url = f"https://www.olx.com.pk/{path}" + (f"{sep}page={page}" if page > 1 else "")
        state, html = _page(url)
        try:
            hits, page_count = _search_results(state)
            new = [h for h in hits if str(_hit_id(h)) not in seen]
            rows = [_listing(h) for h in new]
        except (KeyError, TypeError) as e:
            raise LayoutChanged(url, html, f"search results not where expected (missing {e})") from e
        if not new:
            break
        for h, row in zip(new, rows):
            seen.add(str(_hit_id(h)))
            out.append(row)
        log(f"  page {page}/{page_count}: {len(out)} listings")
        if page >= (page_count or 0):
            break
        page += 1
        time.sleep(DELAY)
    return out


def listing_id(url):
    m = re.search(r"iid-(\d+)", url)
    return m.group(1) if m else None


def details(url):
    """One listing page: the listing itself plus its description."""
    state, html = _page(url)
    if "ad" not in state:
        raise LayoutChanged(url, html, "listing data not where expected (missing 'ad')")
    ad = (state.get("ad") or {}).get("data") or state.get("ad") or {}
    if not (ad.get("externalID") or ad.get("adId")):
        return None  # removed or sold
    try:
        row = _listing(ad)
    except (KeyError, TypeError) as e:
        raise LayoutChanged(url, html, f"listing fields changed (missing {e})") from e
    row["description"] = no_phones(ad.get("description"))
    row["active"] = ad.get("state") == "active"
    return row
