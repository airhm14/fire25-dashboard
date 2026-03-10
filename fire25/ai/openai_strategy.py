# -*- coding: utf-8 -*-
"""OpenAI-based strategy advisor layer.

Thin wrapper around the existing ``ai_advisor`` module so the
orchestration tab can call it under the same interface as the other
AI providers.
"""

from __future__ import annotations

from typing import Any

from fire25.ai_advisor import build_context, get_ai_advice, GENERAL_FALLBACK
from fire25.ai.model_registry import get_model_name


def get_strategy_advice(
    context: dict,
    api_key: str = "",
    model: str = "",
) -> dict:
    """Run OpenAI strategy analysis using the existing ai_advisor pipeline.

    ``context`` is the decision-context dict built by
    ``decision_context_builder``.  We translate it into the shape
    expected by ``build_context`` / ``get_ai_advice``.
    """
    if not str(api_key or "").strip():
        out = dict(GENERAL_FALLBACK)
        out["_ai_source"] = "fallback"
        out["_debug_error"] = "missing_api_key"
        return out

    def _sf(v: Any, d: float = 0.0) -> float:
        try:
            return float(v) if v is not None else d
        except Exception:
            return d

    _model = model or get_model_name("openai")

    advisor_ctx = build_context(
        portfolio_weight=context.get("portfolio_weight"),
        target_weight=context.get("target_weight"),
        recent_buys=context.get("recent_buys", []),
        cash_level=str(context.get("cash_level", "중간")),
        vix=_sf(context.get("VIX"), 20.0),
        fear_greed=_sf(context.get("fear_greed"), 50.0),
        qqqm_rsi=_sf(context.get("QQQM_RSI"), 50.0),
        qqqm_sma200_gap=_sf(context.get("QQQM_SMA200_gap"), 0.0),
        treasury_10y=_sf(context.get("10Y_treasury"), 0.0),
        oil_price=_sf(context.get("oil_price"), 0.0),
        macro_summary=str(context.get("macro_summary", "")),
        top_news_summary=str(context.get("news_summary", "")),
        market_regime=str(context.get("regime", "")),
    )

    return get_ai_advice(context=advisor_ctx, api_key=api_key, model=_model)
