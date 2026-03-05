from __future__ import annotations

import numpy as np
import pandas as pd


def compute_stage_allocation(stage: int, base_alloc: float, vol_factor: float | None = None) -> float:
    """Compute final stage allocation with optional volatility adjustment.

    Args:
        stage: Puddle stage value. Included for interface clarity.
        base_alloc: Base allocation fraction for the stage (0..1 expected).
        vol_factor: Optional multiplier estimated from recent volatility.

    Returns:
        Allocation capped to the [0, 1] range.
    """
    _ = stage
    alloc = float(base_alloc)
    if vol_factor is not None and np.isfinite(vol_factor):
        alloc *= float(vol_factor)

    return float(max(0.0, min(1.0, alloc)))


def estimate_vol_factor(df: pd.DataFrame) -> float:
    """Estimate a volatility sizing factor using rolling close-return volatility.

    Lower recent volatility -> factor above 1.0 (up to cap),
    Higher recent volatility -> factor below 1.0 (down to floor).
    """
    if df is None or df.empty or "Close" not in df.columns:
        return 1.0

    close = pd.to_numeric(df["Close"], errors="coerce")
    rets = close.pct_change().dropna()

    lookback = 20
    if len(rets) < lookback:
        return 1.0

    realized_vol = float(rets.tail(lookback).std(ddof=0) * np.sqrt(252.0))
    if not np.isfinite(realized_vol) or realized_vol <= 0:
        return 1.0

    target_vol = 0.20
    raw_factor = target_vol / realized_vol

    return float(np.clip(raw_factor, 0.5, 1.5))
