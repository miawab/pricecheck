"""Gemma (running locally through Ollama) reads one listing into the recipe's columns."""
import json
import os

import ollama

from . import recipe as _settings  # noqa: F401  (loads .env, which may set PRICECHECK_MODEL)

# Smaller PCs can use a smaller Gemma, e.g. PRICECHECK_MODEL=gemma4:e2b-it-qat in .env (see README).
MODEL = os.environ.get("PRICECHECK_MODEL", "gemma4:e4b-it-qat")


def read_listing(recipe, listing):
    prompt = recipe.prompt().format(
        title=listing["title"],
        brand=listing.get("brand_dropdown"),
        condition=listing.get("condition_dropdown"),
        description=(listing.get("description") or "")[:1200],
    )
    for _ in range(3):
        resp = ollama.chat(model=MODEL, format=recipe.schema(), think=False,
                           options={"temperature": 0, "num_predict": 200},
                           messages=[{"role": "user", "content": prompt}])
        try:
            short = json.loads(resp.message.content)
        except json.JSONDecodeError:
            continue  # answer got cut off; ask again
        spec = {recipe.keys[k]: v for k, v in short.items() if k in recipe.keys}
        if isinstance(spec.get("brand"), str):
            spec["brand"] = spec["brand"].lower().strip()
        return {"id": listing["id"], **spec}
    return None
