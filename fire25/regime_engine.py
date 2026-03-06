from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


REGIMES = ("BULL", "CORRECTION", "BEAR", "RECOVERY")


def _safe_float(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    return v


def _get_last(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    return _safe_float(series.iloc[-1])


def _crossed_above(close: pd.Series, ref: pd.Series) -> bool:
    if close is None or ref is None or len(close) < 2 or len(ref) < 2:
        return False

    prev_close = _safe_float(close.iloc[-2])
    prev_ref = _safe_float(ref.iloc[-2])
    curr_close = _safe_float(close.iloc[-1])
    curr_ref = _safe_float(ref.iloc[-1])

    if None in (prev_close, prev_ref, curr_close, curr_ref):
        return False

    return prev_close <= prev_ref and curr_close > curr_ref


def detect_market_regime(df: pd.DataFrame, vix_value: float | None) -> dict[str, Any]:
    """Classify current market regime using QQQM trend, momentum, and volatility context.

    Returns:
        {
            "regime": "BULL / CORRECTION / BEAR / RECOVERY",
            "confidence": float,
            "reason": list[str],
        }
    """
    if df is None or df.empty:
        return {
            "regime": "CORRECTION",
            "confidence": 0.0,
            "reason": ["No market data available"],
        }

    close = pd.to_numeric(df.get("Close"), errors="coerce")
    sma_50 = pd.to_numeric(df.get("SMA_50"), errors="coerce")
    sma_200 = pd.to_numeric(df.get("SMA_200"), errors="coerce")
    rsi = pd.to_numeric(df.get("RSI"), errors="coerce")

    price_now = _get_last(close)
    sma50_now = _get_last(sma_50)
    sma200_now = _get_last(sma_200)
    rsi_now = _get_last(rsi)
    rsi_prev = _safe_float(rsi.iloc[-2]) if len(rsi) >= 2 else None
    vix_now = _safe_float(vix_value)

    scores: dict[str, int] = {name: 0 for name in REGIMES}
    reasons: dict[str, list[str]] = {name: [] for name in REGIMES}

    if None not in (price_now, sma50_now, sma200_now):
        if price_now > sma50_now and sma50_now > sma200_now:
            scores["BULL"] += 1
            reasons["BULL"].append("Price above SMA50 and SMA50 above SMA200")

        if price_now < sma50_now and price_now > sma200_now:
            scores["CORRECTION"] += 1
            reasons["CORRECTION"].append("Price below SMA50 but above SMA200")

        if price_now < sma200_now:
            scores["BEAR"] += 1
            reasons["BEAR"].append("Price below SMA200")

    if rsi_now is not None:
        if 40.0 <= rsi_now <= 70.0:
            scores["BULL"] += 1
            reasons["BULL"].append("RSI in constructive zone (40-70)")

        if 30.0 <= rsi_now <= 45.0:
            scores["CORRECTION"] += 1
            reasons["CORRECTION"].append("RSI in pullback zone (30-45)")

        if rsi_now < 35.0:
            scores["BEAR"] += 1
            reasons["BEAR"].append("RSI below 35")

        if rsi_prev is not None and rsi_now > 40.0 and rsi_now > rsi_prev:
            scores["RECOVERY"] += 1
            reasons["RECOVERY"].append("RSI rising above 40")

    if vix_now is not None:
        if vix_now < 20.0:
            scores["BULL"] += 1
            reasons["BULL"].append("VIX below 20")

        if 20.0 <= vix_now <= 30.0:
            scores["CORRECTION"] += 1
            reasons["CORRECTION"].append("VIX between 20 and 30")

        if vix_now > 25.0:
            scores["BEAR"] += 1
            reasons["BEAR"].append("VIX above 25")

        if vix_now < 25.0:
            scores["RECOVERY"] += 1
            reasons["RECOVERY"].append("VIX easing below stress threshold")

    if _crossed_above(close, sma_200):
        scores["RECOVERY"] += 1
        reasons["RECOVERY"].append("Price crossed above SMA200")

    if max(scores.values()) == 0:
        return {
            "regime": "CORRECTION",
            "confidence": 0.0,
            "reason": ["Insufficient indicator signals"],
        }

    # Tie-break is ordered to stay conservative under ambiguous states.
    tie_break = ["BEAR", "CORRECTION", "RECOVERY", "BULL"]
    regime = max(tie_break, key=lambda name: (scores[name], -tie_break.index(name)))

    confidence = float(np.clip(scores[regime] / 3.0, 0.0, 1.0))

    return {
        "regime": regime,
        "confidence": confidence,
        "reason": reasons[regime] if reasons[regime] else ["Rule-based fallback classification"],
    }
