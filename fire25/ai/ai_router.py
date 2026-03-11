# -*- coding: utf-8 -*-
"""Multi-AI orchestration router with Streamlit caching support.

Calls Gemini → Claude → OpenAI in sequence, caching each result
independently so partial failures don't block the others.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from .gemini_events import detect_events, GEMINI_FALLBACK
from .claude_macro import interpret_macro, CLAUDE_FALLBACK
from .openai_strategy import get_strategy_advice
from .model_registry import get_model_name
from fire25.ai_advisor import GENERAL_FALLBACK


# ---------------------------------------------------------------------------
# Cached wrappers (TTL = 15 min each; errors are also cached to avoid retries)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def _cached_gemini(
    articles_json: str,
    signals_json: str,
    themes_json: str,
    asset_focus: str,
    gemini_api_key: str,
    gemini_model: str = "",
) -> dict:
    import json
    articles = json.loads(articles_json)
    signals = json.loads(signals_json)
    themes = json.loads(themes_json)
    result = detect_events(articles, signals, themes, asset_focus, api_key=gemini_api_key, model=gemini_model)
    # Don't cache failures — raise so st.cache_data skips storing
    if result.get("_debug_error"):
        _cached_gemini.clear()
    return result


@st.cache_data(ttl=900, show_spinner=False)
def _cached_claude(context_json: str, api_key: str, model: str) -> dict:
    import json
    context = json.loads(context_json)
    return interpret_macro(context, api_key=api_key, model=model)


@st.cache_data(ttl=900, show_spinner=False)
def _cached_openai(context_json: str, api_key: str, model: str) -> dict:
    import json
    context = json.loads(context_json)
    return get_strategy_advice(context, api_key=api_key, model=model)


# ---------------------------------------------------------------------------
# Public orchestration entry point
# ---------------------------------------------------------------------------

def run_all(
    *,
    decision_context: dict,
    articles: list[dict] | None = None,
    aggregated_signals: dict | None = None,
    theme_info: dict | None = None,
    asset_focus: str = "growth",
    openai_api_key: str = "",
    claude_api_key: str = "",
    gemini_api_key: str = "",
    models_config: dict | None = None,
) -> dict[str, dict]:
    """Orchestrate all three AI providers and return their results.

    Returns ``{"gemini": {...}, "claude": {...}, "openai": {...}}``.
    Each value is guaranteed to be a non-None dict with fallback content.
    """
    import json

    _gemini_model = get_model_name("gemini", models_config)
    _claude_model = get_model_name("claude", models_config)
    _openai_model = get_model_name("openai", models_config)

    # --- Gemini ---
    try:
        gemini_result = _cached_gemini(
            articles_json=json.dumps(articles or [], ensure_ascii=False),
            signals_json=json.dumps(aggregated_signals or {}, ensure_ascii=False),
            themes_json=json.dumps(theme_info or {}, ensure_ascii=False),
            asset_focus=asset_focus,
            gemini_api_key=gemini_api_key,
            gemini_model=_gemini_model,
        )
    except Exception:
        gemini_result = dict(GEMINI_FALLBACK)

    # --- Claude ---
    try:
        claude_result = _cached_claude(
            context_json=json.dumps(decision_context, ensure_ascii=False),
            api_key=claude_api_key,
            model=_claude_model,
        )
    except Exception:
        claude_result = dict(CLAUDE_FALLBACK)

    # --- OpenAI ---
    try:
        openai_result = _cached_openai(
            context_json=json.dumps(decision_context, ensure_ascii=False),
            api_key=openai_api_key,
            model=_openai_model,
        )
    except Exception:
        openai_result = dict(GENERAL_FALLBACK)
        openai_result["_ai_source"] = "fallback"
        openai_result["_debug_error"] = "router_exception"

    # Attach resolved model names for UI display
    gemini_result["_model"] = _gemini_model
    claude_result["_model"] = _claude_model
    openai_result["_model"] = _openai_model

    return {
        "gemini": gemini_result,
        "claude": claude_result,
        "openai": openai_result,
    }
