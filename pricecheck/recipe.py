"""Load a category recipe (recipes/<name>.toml) and build Gemma's prompt and answer schema from it."""
import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Settings and keys (TABPFN_TOKEN, PRICECHECK_MODEL, ...) live in .env next to the code.
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# Fields every category gets, whatever the recipe says.
COMMON_FIELDS = [
    {"key": "k", "name": "kind", "type": "enum",
     "values": ["single_item", "shop_multiple_models", "bundle", "broken_or_parts", "wanted", "other"],
     "describe": "listing kind (see below)"},
    {"key": "c", "name": "condition", "type": "enum", "values": ["new", "like_new", "used", "unknown"], "describe": "condition"},
    {"key": "bx", "name": "has_box", "type": "boolean", "describe": "comes with box"},
    {"key": "w", "name": "has_warranty", "type": "boolean", "describe": "has warranty"},
    {"key": "f", "name": "has_fault", "type": "boolean", "describe": "seller admits a fault (lines, dead pixels, cracks, missing parts)"},
]

JSON_TYPES = {"string": "string", "boolean": "boolean", "number": ["number", "null"], "integer": ["integer", "null"]}

PROMPT = """You read Pakistani OLX listings for a {item} and extract facts.
Answer with these keys:
{key_lines}
Listing kinds:
  single_item: one working {item} for sale (even if used, or with a shop's checking warranty), or a shop selling units of ONE model at one price
  shop_multiple_models: a shop advertising several different sizes/models/prices in one ad
  bundle: sold together with other things (a PC, laptop, full setup)
  broken_or_parts: not working, broken, or only parts
  wanted: someone wants to buy
Rules:
- Only use what the text says. If a fact isn't stated, use unknown / null / false. Don't guess from the price.
- The seller's brand dropdown is often wrong; trust the brand written in the title/description.
- Text may mix English and Roman Urdu.
{hints}
Title: {{title}}
Seller's brand dropdown: {{brand}}
Seller's condition dropdown: {{condition}}
Description:
{{description}}"""


class Recipe:
    def __init__(self, name):
        data = tomllib.loads((ROOT / "recipes" / f"{name}.toml").read_text(encoding="utf-8"))
        defaults = {"hints": "", "filters": [], "similar_on": [], "tolerance": {}, "required": [],
                    "group_by": None, "reputable": [], "inspect": ""}
        self.__dict__.update({**defaults, **data})
        self.fields = COMMON_FIELDS + data["fields"]
        self.keys = {f["key"]: f["name"] for f in self.fields}
        self.data_dir = ROOT / "data" / self.name
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def spec_names(self):
        """Columns the recipe adds (not the common ones)."""
        return [f["name"] for f in self.fields if f not in COMMON_FIELDS]

    def schema(self):
        props = {}
        for f in self.fields:
            if f["type"] == "enum":
                props[f["key"]] = {"type": "string", "enum": f["values"]}
            else:
                props[f["key"]] = {"type": JSON_TYPES[f["type"]]}
        return {"type": "object", "properties": props, "required": list(props)}

    def prompt(self):
        lines = "\n".join(f"{f['key']} = {f['describe']}" for f in self.fields)
        return PROMPT.format(item=self.item, key_lines=lines, hints=self.hints.strip())
