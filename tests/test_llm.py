"""Tests for the LLM adapter: off/cached behavior, no key or package required."""

import importlib

from omnis import llm


def test_module_imports_without_anthropic_or_key():
    # The module is already imported; re-importing must not require anthropic.
    importlib.reload(llm)
    assert llm is not None


def test_off_mode_returns_none(monkeypatch):
    monkeypatch.delenv("OMNIS_LLM_MODE", raising=False)
    assert llm.get_mode() == "off"
    assert llm.complete("any prompt", purpose="test") is None


def test_cached_mode_round_trips(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("OMNIS_LLM_MODE", "cached")
    prompt = "Summarize requirement POL-X"
    # Cache miss returns None (caller falls back to template).
    assert llm.complete(prompt, purpose="test") is None
    # After writing, the same prompt replays from cache.
    llm.write_cache(prompt, "A cached auditor narrative.", purpose="test")
    assert llm.complete(prompt, purpose="test") == "A cached auditor narrative."


def test_live_mode_without_key_returns_none(monkeypatch):
    monkeypatch.setenv("OMNIS_LLM_MODE", "live")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # No key: returns None and never imports anthropic.
    assert llm.complete("prompt", purpose="test") is None


def test_prompt_hash_stable():
    assert llm.prompt_hash("abc") == llm.prompt_hash("abc")
    assert llm.prompt_hash("abc") != llm.prompt_hash("abd")
