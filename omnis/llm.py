"""Single LLM adapter with three modes: off (default), cached, live.

OMNIS never requires an API key. This module is the one place a runtime LLM call
can happen, and it ships dormant: with no environment variable set the mode is
"off" and `complete()` returns None, so every caller falls back to its
deterministic template. The module imports and runs with no `anthropic` package
and no key installed; the package is imported lazily inside the live branch only.

Modes (env var OMNIS_LLM_MODE):
  off     return None. The shipped default for judges.
  cached  replay a previously recorded response from data/llm_cache/, keyed by a
          sha256 of the prompt. A cache miss returns None (caller falls back).
  live    call the Anthropic API only if ANTHROPIC_API_KEY is present (otherwise
          return None), log the call to reports/llm_calls.jsonl (purpose, prompt
          hash, token estimate, rough USD cost), and write the response into the
          cache so a later offline run can replay it.

Provenance note: any file under data/llm_cache/ was produced by a real `live`
call during development and is replayed verbatim in `cached` mode. Cost figures
are rough estimates from a token-count heuristic, not billed amounts.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

CACHE_DIR = Path("data/llm_cache")
LOG_PATH = Path("reports/llm_calls.jsonl")

# Default model for live mode. Cheapest current Claude tier; live is dormant by
# default so this only matters if a key is supplied on purpose.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Rough USD per token, used only for the logged cost estimate (not billing).
# Approximate Haiku pricing per million tokens: ~$1 in, ~$5 out.
PRICE_PER_INPUT_TOKEN = 1.0 / 1_000_000
PRICE_PER_OUTPUT_TOKEN = 5.0 / 1_000_000


def get_mode() -> str:
    return os.environ.get("OMNIS_LLM_MODE", "off").strip().lower() or "off"


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _cache_path(prompt: str) -> Path:
    return CACHE_DIR / f"{prompt_hash(prompt)}.json"


def _estimate_tokens(text: str) -> int:
    # Cheap heuristic: ~4 characters per token. Good enough for a cost estimate.
    return max(1, len(text) // 4)


def read_cache(prompt: str) -> str | None:
    path = _cache_path(prompt)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("response")
    except (json.JSONDecodeError, OSError):
        return None


def write_cache(prompt: str, response: str, purpose: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"purpose": purpose, "prompt": prompt, "response": response}
    _cache_path(prompt).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _log_call(purpose: str, prompt: str, response: str, model: str) -> None:
    in_tokens = _estimate_tokens(prompt)
    out_tokens = _estimate_tokens(response)
    cost = in_tokens * PRICE_PER_INPUT_TOKEN + out_tokens * PRICE_PER_OUTPUT_TOKEN
    record = {
        "ts": time.time(),
        "purpose": purpose,
        "model": model,
        "prompt_hash": prompt_hash(prompt),
        "est_input_tokens": in_tokens,
        "est_output_tokens": out_tokens,
        "est_cost_usd": round(cost, 6),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _live(prompt: str, purpose: str, model: str, max_tokens: int) -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # lazy: only imported when live mode is actually used
    except ImportError:
        return None
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    response = "".join(block.text for block in message.content if block.type == "text")
    _log_call(purpose, prompt, response, model)
    write_cache(prompt, response, purpose)
    return response


def complete(
    prompt: str,
    purpose: str = "narrative",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 512,
) -> str | None:
    """Return an LLM completion, or None when unavailable (callers fall back).

    Never raises on a missing key or package; off/cached degrade to None.
    """
    mode = get_mode()
    if mode == "off":
        return None
    if mode == "cached":
        return read_cache(prompt)
    if mode == "live":
        return _live(prompt, purpose, model, max_tokens)
    return None
