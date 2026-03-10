# -*- coding: utf-8 -*-
"""Produce concise Korean dashboard text from AI outputs."""

from __future__ import annotations

import re


def short_korean(text: str, max_sentences: int = 2) -> str:
    """Trim text into short dashboard-friendly Korean sentences."""
    src = str(text or "").strip()
    if not src:
        return "데이터가 부족합니다."
    parts = [p.strip() for p in re.split(r"[.!?]\s*", src) if p.strip()]
    if not parts:
        return src
    return "\n".join(parts[: max(1, int(max_sentences))])


def format_gemini_section(gemini: dict) -> dict:
    """Return display-ready strings from Gemini event output.

    Gemini 역할: 이벤트 요약만 (해석은 Claude 영역).
    """
    _src = gemini.get("_source", gemini.get("brief_source", "fallback"))
    return {
        "headline": short_korean(gemini.get("headline_summary", ""), 2),
        "drivers": gemini.get("macro_drivers", []),
        "source": "Gemini" if _src == "gemini" else "규칙 기반",
        "_source": _src,
        "_debug_error": gemini.get("_debug_error"),
    }


def format_claude_section(claude: dict) -> dict:
    """Return display-ready strings from Claude macro output."""
    return {
        "macro_view": short_korean(claude.get("macro_view", ""), 2),
        "key_risk": short_korean(claude.get("key_risk", ""), 1),
        "opportunity": short_korean(claude.get("opportunity", ""), 1),
        "watch_point": short_korean(claude.get("watch_point", ""), 1),
        "source": claude.get("_source", "fallback"),
        "_source": claude.get("_source", "fallback"),
        "_debug_error": claude.get("_debug_error"),
    }


def format_openai_section(openai_advice: dict) -> dict:
    """Return display-ready strings from OpenAI strategy output."""
    return {
        "market_view": short_korean(openai_advice.get("market_view", ""), 2),
        "shield_alert": short_korean(openai_advice.get("shield_alert", ""), 1),
        "dip_signal": short_korean(openai_advice.get("dip_signal", ""), 1),
        "action": short_korean(openai_advice.get("action", ""), 1),
        "dip_probability": openai_advice.get("dip_probability", 0),
        "risk_level": openai_advice.get("risk_level", "보통"),
        "confidence": openai_advice.get("confidence", "낮음"),
        "source": openai_advice.get("_ai_source", "fallback"),
        "_source": openai_advice.get("_ai_source", "fallback"),
        "_debug_error": openai_advice.get("_debug_error"),
    }
