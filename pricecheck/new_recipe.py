"""Draft a recipe for any OLX category: Gemma looks at real listings and suggests what to extract.

    python -m pricecheck.new_recipe phones "https://www.olx.com.pk/mobile-phones_c1453"

Writes recipes/<name>.toml. Read it, fix anything that looks off, then run
    python -m pricecheck.update <name> --limit 100
"""
import json
import re
import sys
import time

import ollama

from . import olx
from .extract import MODEL
from .recipe import COMMON_FIELDS, ROOT

SAMPLE_DETAILS = 8  # descriptions to read (2 s each), on top of ~30 titles

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "item": {"type": "string"},
        "inspect": {"type": "string"},
        "fields": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"},
            "label": {"type": "string"},
            "type": {"type": "string", "enum": ["number", "integer", "boolean", "enum", "string"]},
            "unit": {"type": "string"},
            "values": {"type": "array", "items": {"type": "string"}},
            "describe": {"type": "string"},
        }, "required": ["name", "label", "type", "unit", "values", "describe"]}},
        "filters": {"type": "array", "items": {"type": "string"}},
        "similar_on": {"type": "array", "items": {"type": "string"}},
        "required": {"type": "array", "items": {"type": "string"}},
        "group_by": {"type": "string"},
        "reputable": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "item", "inspect", "fields", "filters", "similar_on", "required", "group_by", "reputable"],
}

PROMPT = """You are designing a price checker for used items on OLX Pakistan.
Below are real listings from one OLX category. Decide which facts about an item most change its price,
so another model can read each listing and fill them in.

Return:
- title: plural category name for a page heading (e.g. "Phones")
- item: singular item name (e.g. "mobile phone")
- inspect: what a buyer should check in person before paying (one sentence, no full stop)
- fields: 4 to 8 facts that drive price. Always include "brand" (string) and "model" (string) first.
  Use snake_case names; put units in the name when numeric (e.g. storage_gb). type is one of number, integer,
  boolean, enum, string. For enum, list the allowed lowercase values including "unknown". unit is shown after
  numbers (e.g. "GB"), else "". describe tells the reader model exactly what to write, including "null if not stated".
  Don't include condition, box, warranty or faults: those are always extracted.
- filters: 2 to 4 field names a buyer would filter by
- similar_on: 2 to 3 field names that must match for two listings to be comparable
- required: field names without which a price can't be judged (often 0 or 1)
- group_by: one field whose groups have very different prices (used to spot typos)
- reputable: lowercase well-known brands in this category, [] if brand doesn't matter

Listings:
{listings}"""


def short_keys(names):
    taken, keys = {f["key"] for f in COMMON_FIELDS}, {}
    for n in names:
        parts = n.split("_")
        for cand in [parts[0][:1], "".join(p[0] for p in parts), parts[0][:2], parts[0][:3], n]:
            if cand not in taken:
                keys[n] = cand
                taken.add(cand)
                break
    return keys


def toml_value(v):
    return json.dumps(v, ensure_ascii=False)  # JSON strings and string arrays are valid TOML


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    name, url = re.sub(r"\W+", "_", sys.argv[1].lower()), sys.argv[2]
    print(f"Reading listings from {url} ...")
    path = re.sub(r"^https?://(www\.)?olx\.com\.pk/", "", url.strip())
    hits, _ = olx._search_results(olx._state(f"https://www.olx.com.pk/{path}"))
    listings = [olx._listing(h) for h in hits]
    if not listings:
        sys.exit("No listings found at that link. Copy the address of an OLX category page and try again.")
    lines = []
    for i, l in enumerate(listings[:30]):
        line = f"- {l['title']} | Rs {l['price']}"
        if i < SAMPLE_DETAILS:
            time.sleep(olx.DELAY)
            d = olx.details(l["url"]) or {}
            line += f" | {(d.get('description') or '')[:300].replace(chr(10), ' ')}"
        lines.append(line)

    print(f"Gemma is drafting a recipe from {len(lines)} listings ...")
    resp = ollama.chat(model=MODEL, format=SCHEMA, think=False, options={"temperature": 0},
                       messages=[{"role": "user", "content": PROMPT.format(listings="\n".join(lines))}])
    r = json.loads(resp.message.content)

    fields = [f for f in r["fields"] if f["name"] not in {c["name"] for c in COMMON_FIELDS}]
    keys = short_keys([f["name"] for f in fields])
    names = set(keys)
    keep = lambda xs: [x for x in xs if x in names]
    out = [
        f"# Drafted by Gemma from {len(lines)} listings at {url}",
        "# Read it before running: fix field names, enum values or descriptions that look off.",
        "",
        f"name = {toml_value(name)}",
        f"title = {toml_value(r['title'])}",
        f"item = {toml_value(r['item'])}",
        f"olx_search = {toml_value(url)}",
        f"inspect = {toml_value(r['inspect'])}",
        f"filters = {toml_value(keep(r['filters']))}",
        f"similar_on = {toml_value(keep(r['similar_on']))}",
        f"required = {toml_value(keep(r['required']))}",
        f"group_by = {toml_value(r['group_by'])}" if r["group_by"] in names else "",
        f"reputable = {toml_value([b.lower() for b in r['reputable']])}",
        'hints = ""',
        "",
    ]
    for f in fields:
        out += ["[[fields]]", f"key = {toml_value(keys[f['name']])}", f"name = {toml_value(f['name'])}",
                f"label = {toml_value(f['label'])}", f"type = {toml_value(f['type'])}"]
        if f["unit"]:
            out.append(f"unit = {toml_value(f['unit'])}")
        if f["type"] == "enum":
            values = [v.lower() for v in f["values"]] + ([] if "unknown" in f["values"] else ["unknown"])
            out.append(f"values = {toml_value(values)}")
        out += [f"describe = {toml_value(f['describe'])}", ""]

    dest = ROOT / "recipes" / f"{name}.toml"
    if dest.exists():
        dest = dest.with_name(f"{name}.draft.toml")
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"\nWrote {dest}\nFields: {', '.join(names)}\n"
          f"Next: read the file, then try it on 100 listings:\n  python -m pricecheck.update {name} --limit 100")


if __name__ == "__main__":
    main()
