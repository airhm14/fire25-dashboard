# -*- coding: utf-8 -*-
"""Gemini-based news event detection layer.

Wraps the existing ``news_engine`` Gemini integration so the
orchestration tab can display its output separately.
"""

from __future__ import annotations

from typing import Any

# Re-use existing Gemini path already implemented in news_engine.
try:
    from fire25.news_engine import (
        build_gemini_payload,
        try_generate_gemini_brief,
        is_gemini_enabled,
    )
except ImportError:
    def is_gemini_enabled() -> bool:
        return False

    def build_gemini_payload(*_a: Any, **_kw: Any) -> dict:
        return {}

    def try_generate_gemini_brief(*_a: Any, **_kw: Any) -> dict | None:
        return None


GEMINI_FALLBACK: dict[str, Any] = {
    "headline_summary": "Gemini 이벤트 탐지를 실행하지 못했습니다.",
    "macro_drivers": [],
    "market_implication": "",
    "risk_level": "MODERATE",
    "risk_level_label": "보통",
    "brief_source": "fallback",
}


def detect_events(
    articles: list[dict],
    aggregated_signals: dict,
    theme_info: dict,
    asset_focus: str = "growth",
) -> dict:
    """Run Gemini event detection and return structured result.

    Returns a dict with at least:
      headline_summary, macro_drivers, market_implication,
      risk_level, risk_level_label, brief_source
    """
    if not is_gemini_enabled() or not articles:
        return dict(GEMINI_FALLBACK)

    try:
        payload = build_gemini_payload(articles, aggregated_signals, theme_info, asset_focus)
        result = try_generate_gemini_brief(payload)
        if result and isinstance(result, dict):
            result.setdefault("brief_source", "gemini")
            return result
    except Exception:
        pass

    return dict(GEMINI_FALLBACK)
