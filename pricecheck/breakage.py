"""When OLX changes its pages and the reader breaks: save what changed and open a GitLab issue.

The issue is what starts the self-healing flow in GitLab (.gitlab/duo/scraper-medic.yml):
an agent reads it, fixes olx.py, adds the attached page as a test fixture and opens a merge request.

Only the page's shape and a few listings go into the issue, never seller details:
keys about contacts, users, sellers or agents are dropped and phone numbers are removed.

Set GITLAB_TOKEN (a personal access token with the `api` scope) and GITLAB_PROJECT
(e.g. gitlab-ai-hackathon/transcend-october-2026/43397568/showcase) in .env to open issues.
Without them the report is only saved to data/broken/.
"""
import json
import os
import re
from datetime import datetime
from urllib.parse import quote

import requests
import sentry_sdk

from .olx import no_phones
from .recipe import ROOT

LABEL = "scraper-broken"
ASSIGNMENT = re.compile(r"window\.([A-Za-z_$][\w$]*)\s*=\s*")
PRIVATE_KEY = re.compile(r"contact|phone|mobile|whatsapp|email|user|seller|agent|owner|account", re.I)
TITLE_KEY = re.compile(r"^(title|name|subject)$", re.I)
PRICE_KEY = re.compile(r"price|amount", re.I)
KEEP_LISTINGS = 6


def page_data(html):
    """Every `window.<name> = {...}` blob in the page, by name."""
    found = {}
    for m in ASSIGNMENT.finditer(html):
        try:
            found[m.group(1)], _ = json.JSONDecoder().raw_decode(html, m.end())
        except ValueError:
            continue
    return found


def _is_listing(d):
    return isinstance(d, dict) and any(TITLE_KEY.match(k) for k in d) and any(PRICE_KEY.search(k) for k in d)


def _has_listing(v):
    if _is_listing(v):
        return True
    if isinstance(v, dict):
        return any(_has_listing(x) for x in v.values())
    if isinstance(v, list):
        return any(_has_listing(x) for x in v[:20])
    return False


def _scrub(v):
    if isinstance(v, dict):
        return {k: _scrub(x) for k, x in v.items() if not (PRIVATE_KEY.search(k) and not isinstance(x, bool))}
    if isinstance(v, list):
        return [_scrub(x) for x in v[:KEEP_LISTINGS]]
    if isinstance(v, str):
        return no_phones(v)[:1500]
    return v


def prune(v):
    """Keep only the branches that lead to listings (plus small values next to them, like page counts)."""
    if _is_listing(v):
        return _scrub(v)
    if isinstance(v, list):
        return [prune(x) for x in v if _has_listing(x)][:KEEP_LISTINGS]
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if PRIVATE_KEY.search(k):
                continue
            if _has_listing(x):
                out[k] = prune(x)
            elif isinstance(x, (int, float, bool)) or (isinstance(x, str) and len(x) <= 100):
                out[k] = x
        return out
    return v


def listing_paths(v, path="", out=None):
    """Where the listings now live, e.g. `state.listingSearch.page.items[]`."""
    out = [] if out is None else out
    if isinstance(v, list) and v and _is_listing(v[0]):
        out.append(f"{path}[] ({len(v)} listings; fields: {', '.join(sorted(v[0])[:25])})")
    elif _is_listing(v):
        out.append(f"{path} (one listing; fields: {', '.join(sorted(v)[:25])})")
    elif isinstance(v, dict):
        for k, x in v.items():
            if _has_listing(x):
                listing_paths(x, f"{path}.{k}" if path else k, out)
    elif isinstance(v, list):
        for i, x in enumerate(v[:20]):
            if _has_listing(x):
                listing_paths(x, f"{path}[{i}]", out)
    return out


def fixture(html):
    """A small, public-safe copy of the page in the same shape OLX served it."""
    blobs = {name: prune(data) for name, data in page_data(html).items() if _has_listing(data)}
    scripts = "\n".join(f"<script>window.{n} = {json.dumps(d, ensure_ascii=False)};</script>" for n, d in blobs.items())
    return f"<!doctype html><html><head><title>OLX</title></head><body>\n{scripts}\n</body></html>\n"


def describe(err, where):
    data = page_data(err.html)
    paths = [p for name, blob in data.items() for p in listing_paths(blob, f"window.{name}")]
    page_kind = "listing page" if "/item/" in err.url else "search page"
    fix = fixture(err.html)
    found = ", ".join(f"`window.{n}`" for n in data) or "none"
    return {
        "title": f"OLX {page_kind} layout changed: pricecheck can't read listings ({where})",
        "page_kind": page_kind,
        "fixture": fix,
        "body": f"""pricecheck stopped reading OLX while running **{where}**.

**What broke:** {err.reason}
**Page:** {err.url} ({page_kind})
**Seen at:** {datetime.now().isoformat(timespec="minutes")}

### What pricecheck expects (pricecheck/olx.py)
- page data in a `window.state = {{...}}` script
- search pages: listings at `state.algolia.content.hits[]`, page count at `state.algolia.content.nbPages`
- listing pages: the listing at `state.ad.data`

### What the page has now
- page data scripts found: {found}
- listings found at:
{chr(10).join(f"  - `{p}`" for p in paths) or "  - (no listing-like data found at all)"}

### The page, trimmed (seller details and phone numbers removed)
Save this as a test fixture (`tests/fixtures/olx/` + a new name) and make `olx.py` read it,
while the existing fixtures keep passing.

<details><summary>{page_kind} fixture ({len(fix) // 1024 + 1} KB)</summary>

```html
{fix}```

</details>

_Opened automatically by pricecheck (`pricecheck/breakage.py`)._""",
    }


def _gitlab(method, path, **kw):
    token, project = os.environ.get("GITLAB_TOKEN"), os.environ.get("GITLAB_PROJECT")
    url = f"https://gitlab.com/api/v4/projects/{quote(project, safe='')}{path}"
    r = requests.request(method, url, headers={"PRIVATE-TOKEN": token}, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def report(err, where, log=print):
    """Save the breakage under data/broken/ and open (or reuse) a GitLab issue. Returns the issue URL, if any."""
    info = describe(err, where)
    folder = ROOT / "data" / "broken" / datetime.now().strftime("%Y-%m-%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "issue.md").write_text(f"# {info['title']}\n\n{info['body']}", encoding="utf-8")
    (folder / "fixture.html").write_text(info["fixture"], encoding="utf-8")
    sentry_sdk.set_tag("olx.layout_changed", info["page_kind"])
    sentry_sdk.capture_exception(err)
    log(f"OLX layout changed: report saved to {folder}")

    if not (os.environ.get("GITLAB_TOKEN") and os.environ.get("GITLAB_PROJECT")):
        log("  (set GITLAB_TOKEN and GITLAB_PROJECT in .env to open a GitLab issue automatically)")
        return None
    try:
        open_issues = _gitlab("GET", "/issues", params={"labels": LABEL, "state": "opened"})
        if open_issues:
            log(f"  already reported: {open_issues[0]['web_url']}")
            return open_issues[0]["web_url"]
        issue = _gitlab("POST", "/issues", json={"title": info["title"], "description": info["body"], "labels": LABEL})
    except requests.RequestException as e:
        log(f"  couldn't open the GitLab issue: {e}")
        return None
    log(f"  opened {issue['web_url']}")
    return issue["web_url"]
