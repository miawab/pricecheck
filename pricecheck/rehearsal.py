"""A pretend OLX redesign, for rehearsing the self-healing loop on demand.

OLX can't be asked to change its site on cue, so with PRICECHECK_REHEARSE_OLX_CHANGE=1
every page pricecheck downloads is rewritten the way a real redesign might look:

    before: window.state = {"algolia": {"content": {"hits": [...], "nbPages": 38}}}
    after:  window.state = {"listingSearch": {"page": {"items": [...], "totalPages": 38}}}

The listings themselves are the real ones from OLX; only where they sit in the page moves.
Listing pages are left alone.
"""
import json

MARKER = "window.state = "


def change_layout(html):
    start = html.find(MARKER)
    if start < 0:
        return html
    begin = start + len(MARKER)
    state, end = json.JSONDecoder().raw_decode(html, begin)
    content = (state.get("algolia") or {}).get("content")
    if content is None:
        return html
    rest = {k: v for k, v in content.items() if k not in ("hits", "nbPages")}
    state["listingSearch"] = {"page": {"items": content.get("hits", []), "totalPages": content.get("nbPages"), **rest}}
    del state["algolia"]
    return html[:begin] + json.dumps(state, ensure_ascii=False) + html[end:]
