"""Gemma (running locally through Ollama) reads one listing into the recipe's columns."""
import json
import os

import ollama
import sentry_sdk

from . import recipe as _settings  # noqa: F401  (loads .env, which may set PRICECHECK_MODEL)
from . import tracing

# Smaller PCs can use a smaller Gemma, e.g. PRICECHECK_MODEL=gemma4:e2b-it-qat in .env (see README).
MODEL = os.environ.get("PRICECHECK_MODEL", "gemma4:e4b-it-qat")


def read_listing(recipe, listing):
    prompt = recipe.prompt().format(
        title=listing["title"],
        brand=listing.get("brand_dropdown"),
        condition=listing.get("condition_dropdown"),
        description=(listing.get("description") or "")[:1200],
    )
    for attempt in range(1, 4):
        with tracing.chat(MODEL, prompt) as span:
            resp = ollama.chat(model=MODEL, format=recipe.schema(), think=False,
                               options={"temperature": 0, "num_predict": 200},
                               messages=[{"role": "user", "content": prompt}])
            span.set_data("gen_ai.response.model", resp.model)
            span.set_data("gen_ai.output.messages", tracing.messages("assistant", resp.message.content))
            span.set_data("gen_ai.response.finish_reasons", json.dumps([resp.done_reason]))
            span.set_data("gen_ai.usage.input_tokens", resp.prompt_eval_count)
            span.set_data("gen_ai.usage.output_tokens", resp.eval_count)
            span.set_data("pricecheck.attempt", attempt)
            try:
                short = json.loads(resp.message.content)
            except json.JSONDecodeError:
                span.set_status("internal_error")  # answer got cut off; ask again
                span.set_data("error.type", "invalid_json")
                continue
        spec = {recipe.keys[k]: v for k, v in short.items() if k in recipe.keys}
        if isinstance(spec.get("brand"), str):
            spec["brand"] = spec["brand"].lower().strip()
        return {"id": listing["id"], **spec}
    sentry_sdk.capture_message(f"Gemma gave no valid answer for listing {listing['id']} after 3 tries", level="warning")
    return None
