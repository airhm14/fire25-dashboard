"""Strategy-level deployment rules for TEAM FIRE 25."""

from __future__ import annotations

import numpy as np
import pandas as pd


STAGE_DEPLOYMENT_RATES = {1: 0.15, 2: 0.35, 3: 0.50, 4: 1.00}


def detect_defcon(vix_value: float | None, rsi_value: float | None) -> bool:
    """Detect DEFCON saving state from VIX and RSI thresholds."""
    if vix_value is None or rsi_value is None:
        return False
    if not np.isfinite(float(vix_value)) or not np.isfinite(float(rsi_value)):
        return False
    return float(vix_value) <= 14.0 and float(rsi_value) >= 70.0


def evaluate_smart_shoulder(df: pd.DataFrame, qqqm_pct: float) -> dict:
    """Evaluate Smart Shoulder conditions and return condition breakdown."""
    over_threshold = float(qqqm_pct) > 77.0

    below_sma20 = False
    if df is not None and not df.empty and {"Close", "SMA_20"}.issubset(df.columns):
        close_now = pd.to_numeric(df["Close"], errors="coerce").iloc[-1]
        sma20_now = pd.to_numeric(df["SMA_20"], errors="coerce").iloc[-1]
        below_sma20 = bool(pd.notna(close_now) and pd.notna(sma20_now) and float(close_now) < float(sma20_now))

    after_high = False
    if df is not None and len(df) >= 252 and "High" in df.columns:
        high_series = pd.to_numeric(df["High"], errors="coerce")
        high_52w = high_series.tail(252).max()
        recent_20d_high = high_series.tail(20).max()
        if pd.notna(high_52w) and pd.notna(recent_20d_high) and float(high_52w) > 0:
            after_high = float(recent_20d_high) >= float(high_52w) * 0.99

    triggered = bool(over_threshold and below_sma20 and after_high)
    rebalancing_needed = bool(over_threshold and not triggered)

    reasons = []
    if not over_threshold:
        reasons.append("QQQM 비중 77% 초과 미충족")
    if not below_sma20:
        reasons.append("20일선 하향돌파 미충족")
    if not after_high:
        reasons.append("최근 전고점 갱신 후 조건 미충족")

    return {
        "over_threshold": over_threshold,
        "below_sma20": below_sma20,
        "after_high": after_high,
        "triggered": triggered,
        "rebalancing_needed": rebalancing_needed,
        "reasons": reasons,
    }


def estimate_vol_factor(df: pd.DataFrame, lookback: int = 20, target_vol: float = 0.20) -> float:
    """Estimate volatility scaling factor using annualized close-return volatility.

    Lower realized volatility -> factor above 1.0 (up to 1.5)
    Higher realized volatility -> factor below 1.0 (down to 0.5)
    """
    if df is None or df.empty or "Close" not in df.columns:
        return 1.0

    close = pd.to_numeric(df["Close"], errors="coerce")
    rets = close.pct_change().dropna()
    if len(rets) < int(lookback):
        return 1.0

    realized_vol = float(rets.tail(int(lookback)).std(ddof=0) * np.sqrt(252.0))
    if not np.isfinite(realized_vol) or realized_vol <= 0:
        return 1.0

    raw_factor = float(target_vol) / realized_vol
    return float(np.clip(raw_factor, 0.5, 1.5))


def compute_deployment(stage: int, remaining_cash: float, vol_factor: float | None = None) -> float:
    """Determine how much cash to deploy for each puddle stage.

    Stage logic:
    stage 1 -> deploy 15%
    stage 2 -> deploy 35%
    stage 3 -> deploy 50%
    stage 4 -> deploy 100% (200-day MA recovery)
    """
    base_rate = float(STAGE_DEPLOYMENT_RATES.get(stage, 0.0))
    adjusted_rate = base_rate

    if vol_factor is not None and np.isfinite(vol_factor):
        adjusted_rate = min(max(base_rate * float(vol_factor), 0.0), 1.0)

    # Stage 4 is always capped to 100% of remaining cash.
    if stage == 4:
        adjusted_rate = min(adjusted_rate, 1.0)

    return float(remaining_cash) * adjusted_rate
