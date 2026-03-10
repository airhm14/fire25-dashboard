# -*- coding: utf-8 -*-
"""Collect and summarize all signal data into a compact context dict
that can be consumed by any AI provider (Gemini, Claude, OpenAI)."""

from __future__ import annotations

import json
from typing import Any


def _sf(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _si(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def build_decision_context(
    *,
    portfolio_weight: dict | None = None,
    target_weight: dict | None = None,
    cash_level: str = "중간",
    vix: float | None = None,
    fear_greed: int | None = None,
    qqqm_rsi: float | None = None,
    qqqm_sma200_gap: float | None = None,
    treasury_10y: float | None = None,
    oil_price: float | None = None,
    regime: str = "CORRECTION",
    macro_summary_text: str = "",
    news_summary_text: str = "",
    news_brief: dict | None = None,
    shock_events: list[str] | None = None,
    risk_radar: dict | None = None,
) -> dict:
    """Return a flat, JSON-serialisable context dict."""
    nb = news_brief if isinstance(news_brief, dict) else {}
    return {
        "portfolio_weight": portfolio_weight or {},
        "target_weight": target_weight or {},
        "cash_level": str(cash_level or "중간"),
        "VIX": _sf(vix, 20.0),
        "fear_greed": _si(fear_greed, 50),
        "QQQM_RSI": _sf(qqqm_rsi, 50.0),
        "QQQM_SMA200_gap": _sf(qqqm_sma200_gap, 0.0),
        "10Y_treasury": _sf(treasury_10y, 0.0),
        "oil_price": _sf(oil_price, 0.0),
        "regime": str(regime),
        "macro_summary": str(macro_summary_text or ""),
        "news_summary": str(news_summary_text or ""),
        "risk_level_label": str(nb.get("risk_level_label", "보통")),
        "dominant_categories": nb.get("dominant_categories", []),
        "shock_events": shock_events or [],
        "risk_radar": risk_radar or {},
    }


def context_to_json(ctx: dict) -> str:
    """Compact JSON string for prompt embedding."""
    return json.dumps(ctx, ensure_ascii=False)
