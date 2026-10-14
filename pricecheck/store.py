"""Everything we know about a category's listings, in data/<recipe>/.

listings.json  id -> listing, with first_seen, last_seen, removed_on and price_history
specs.jsonl    id -> what Gemma read out of the listing (written once per listing)

Removed listings are kept: a listing that vanishes was probably sold, and its last
price is the closest thing to a real sale price that OLX lets us see.
"""
import json
from datetime import date


class Store:
    def __init__(self, recipe):
        self.dir = recipe.data_dir
        self.listings_path = self.dir / "listings.json"
        self.specs_path = self.dir / "specs.jsonl"
        self.listings = json.loads(self.listings_path.read_text(encoding="utf-8")) if self.listings_path.exists() else {}
        self.specs = {}
        if self.specs_path.exists():
            for line in self.specs_path.open(encoding="utf-8"):
                s = json.loads(line)
                self.specs[s["id"]] = s

    def save(self):
        tmp = self.listings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.listings, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.listings_path)

    def add_spec(self, spec):
        self.specs[spec["id"]] = spec
        with self.specs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(spec, ensure_ascii=False) + "\n")

    def merge(self, current, today=None):
        """Merge today's search results. Returns counts of new, repriced and removed listings."""
        today = today or date.today().isoformat()
        seen = {r["id"] for r in current}
        new = repriced = removed = 0
        for r in current:
            old = self.listings.get(r["id"])
            if old is None:
                self.listings[r["id"]] = {**r, "first_seen": today, "last_seen": today, "removed_on": None,
                                          "price_history": [[today, r["price"]]]}
                new += 1
                continue
            if r["price"] != old["price"]:
                old["price_history"].append([today, r["price"]])
                repriced += 1
            description = old.get("description")
            old.update(r)
            old.update(last_seen=today, removed_on=None)
            if description is not None:
                old["description"] = description
        for lid, old in self.listings.items():
            if lid not in seen and old["removed_on"] is None:
                old["removed_on"] = today
                removed += 1
        return new, repriced, removed

    def needing_details(self):
        return [l for l in self.listings.values() if l["removed_on"] is None and l.get("description") is None]

    def needing_specs(self):
        return [l for l in self.listings.values() if l.get("description") is not None and l["id"] not in self.specs]
