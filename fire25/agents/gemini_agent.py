# -*- coding: utf-8 -*-
"""Gemini Agent — 뉴스 수집 / 중복 제거 / 요약.

기존 gemini_events.py를 래핑하여 에이전트 인터페이스를 제공한다.
"""

from __future__ import annotations

from typing import Any

from fire25.ai.gemini_events import detect_events, GEMINI_FALLBACK


def run(
    *,
    articles: list[dict],
    aggregated_signals: dict,
    theme_info: dict,
    asset_focus: str = "growth",
    api_key: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Execute Gemini news agent.

    Returns structured event summary dict compatible with the orchestrator.
    """
    result = detect_events(
        articles=articles,
        aggregated_signals=aggregated_signals,
        theme_info=theme_info,
        asset_focus=asset_focus,
        api_key=api_key,
        model=model,
    )
    result.setdefault("_agent", "gemini")
    return result


FALLBACK = GEMINI_FALLBACK
