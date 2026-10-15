"""Pretend OLX redesigns, for rehearsing the self-healing loop on demand.

OLX can't be asked to change its site on cue, so with PRICECHECK_REHEARSE_OLX_CHANGE=<variant>
every search page pricecheck downloads is rewritten the way a real redesign might look.
The listings themselves are the real ones from OLX; only where and how they sit in the page changes.
Listing pages are left alone. Each variant is a different break, so the loop can be rehearsed again
after an earlier one has been healed.

    1  results move:        state.algolia.content.hits     -> state.listingSearch.page.items
    2  page data renamed:   window.state = {...}           -> window.__OLX_STATE__ = {...}, results under search.results
    3  listing id renamed:  hit.externalID                 -> hit.adId (results stay where they are)
"""
import json
import os

MARKER = "window.state = "


def _results_moved(state):
    content = state.pop("algolia")["content"]
    rest = {k: v for k, v in content.items() if k not in ("hits", "nbPages")}
    state["listingSearch"] = {"page": {"items": content.get("hits", []), "totalPages": content.get("nbPages"), **rest}}
    return state, MARKER


def _data_renamed(state):
    content = state.pop("algolia")["content"]
    state["search"] = {"results": content.get("hits", []), "pageCount": content.get("nbPages")}
    return state, "window.__OLX_STATE__ = "


def _id_renamed(state):
    for hit in state["algolia"]["content"].get("hits", []):
        hit["adId"] = hit.pop("externalID")
    return state, MARKER


VARIANTS = {"1": _results_moved, "2": _data_renamed, "3": _id_renamed}


def change_layout(html, variant=None):
    variant = str(variant or os.environ.get("PRICECHECK_REHEARSE_OLX_CHANGE") or "1")
    start = html.find(MARKER)
    if start < 0:
        return html
    begin = start + len(MARKER)
    state, end = json.JSONDecoder().raw_decode(html, begin)
    if "algolia" not in state:  # not a search page
        return html
    state, marker = VARIANTS[variant](state)
    return html[:start] + marker + json.dumps(state, ensure_ascii=False) + html[end:]
