"""Optional Sentry agent tracing: shows each price check as an agent run with its model and tool steps.

    invoke_agent pricecheck               one "is this price fair?" check
      execute_tool fetch_olx_listing      read the OLX page
      chat gemma4:...                     Gemma reads the listing (tokens, retries, failures)
      execute_tool tabpfn_price_range     TabPFN predicts the usual range
      execute_tool bargain_advice         code turns the range into what to offer

Set SENTRY_DSN in .env to turn it on; without it every helper here does nothing.
Only public listing text is sent (trimmed); no IPs or personal data (send_default_pii=False).
"""
import json
import os
from contextlib import contextmanager

import sentry_sdk

from . import recipe as _settings  # noqa: F401  (loads .env, which may set SENTRY_DSN)

AGENT = "pricecheck"


def init():
    dsn = os.environ.get("SENTRY_DSN")
    if dsn:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=1.0, send_default_pii=False,
                        environment=os.environ.get("PRICECHECK_ENV", "local"))
    return bool(dsn)


def messages(role, text):
    return json.dumps([{"role": role, "parts": [{"type": "text", "content": str(text)[:2000]}]}])


def run(name):
    """Root of a trace for work that doesn't come from a web request (the update command)."""
    return sentry_sdk.start_transaction(op="pricecheck.update", name=name)


@contextmanager
def _span(op, name, data):
    with sentry_sdk.start_span(op=op, name=name) as span:
        for k, v in data.items():
            span.set_data(k, v)
        yield span


@contextmanager
def agent(task):
    with _span("gen_ai.invoke_agent", f"invoke_agent {AGENT}", {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": AGENT,
        "gen_ai.input.messages": messages("user", task),
    }) as span:
        yield span


@contextmanager
def chat(model, prompt):
    with _span("gen_ai.chat", f"chat {model}", {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "ollama",
        "gen_ai.request.model": model,
        "gen_ai.agent.name": AGENT,
        "gen_ai.input.messages": messages("user", prompt),
    }) as span:
        yield span


@contextmanager
def tool(name, description, arguments):
    with _span("gen_ai.execute_tool", f"execute_tool {name}", {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.agent.name": AGENT,
        "gen_ai.tool.name": name,
        "gen_ai.tool.description": description,
        "gen_ai.tool.call.arguments": json.dumps(arguments, default=str),
    }) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status("internal_error")
            span.set_data("error.type", type(exc).__name__)
            raise


def result(span, value):
    span.set_data("gen_ai.tool.call.result", json.dumps(value, default=str)[:2000])
