from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import pandas as pd


@dataclass
class PuddleSignalResult:
    """Result of puddle-stage signal evaluation with cooldown state."""

    stage: int
    alert: bool
    cooldown_active: bool
    cooldown_info: Optional[str]


def _check_cooldown(
    df: pd.DataFrame,
    sma_column: str,
    direction: str,
    cooldown_days: int,
) -> Tuple[bool, Optional[int]]:
    """Check whether the same crossover signal appeared in the cooldown window.

    The scan excludes today's candle and checks only the prior `cooldown_days`
    trading rows to preserve the original dashboard semantics.
    """
    required_rows = cooldown_days + 2
    if len(df) < required_rows or sma_column not in df.columns:
        return False, None

    close = pd.to_numeric(df["Close"], errors="coerce")
    sma = pd.to_numeric(df[sma_column], errors="coerce")

    # Historical crossover flags computed with shift(1): no forward-looking rows.
    cross_below = (close.shift(1) >= sma.shift(1)) & (close < sma)
    cross_above = (close.shift(1) < sma.shift(1)) & (close >= sma)

    if direction == "below":
        cross_flags = cross_below
    elif direction == "above":
        cross_flags = cross_above
    else:
        return False, None

    # Exclude today's candle and look only at the trailing cooldown window.
    recent = cross_flags.tail(cooldown_days + 1)[:-1]
    if recent.empty or not bool(recent.any()):
        return False, None

    true_positions = [i for i, v in enumerate(recent.tolist()) if bool(v)]
    last_signal_pos = true_positions[-1]

    days_since = len(recent) - 1 - last_signal_pos
    return True, days_since


def calculate_puddle_signal(df: pd.DataFrame, cooldown_days: int = 30) -> PuddleSignalResult:
    """Calculate puddle stage signal with cooldown filtering.

    Args:
        df: Price/indicator DataFrame indexed by datetime and containing
            `Close`, `SMA_50`, `SMA_100`, `SMA_200` columns.
        cooldown_days: Number of recent trading rows to suppress repeated
            identical signals.

    Returns:
        PuddleSignalResult describing stage, alert state, and cooldown info.
    """
    required_cols = {"Close", "SMA_50", "SMA_100", "SMA_200"}
    if df is None or df.empty or not required_cols.issubset(df.columns):
        return PuddleSignalResult(stage=0, alert=False, cooldown_active=False, cooldown_info=None)

    latest = df.iloc[-1]
    close = latest["Close"]
    sma_50 = latest["SMA_50"]
    sma_100 = latest["SMA_100"]
    sma_200 = latest["SMA_200"]

    if pd.isna(close):
        return PuddleSignalResult(stage=0, alert=False, cooldown_active=False, cooldown_info=None)

    close_series = pd.to_numeric(df["Close"], errors="coerce")
    sma_200_series = pd.to_numeric(df["SMA_200"], errors="coerce")
    cross_up_200 = (close_series.shift(1) < sma_200_series.shift(1)) & (close_series >= sma_200_series)
    stage4_today = bool(cross_up_200.iloc[-1]) if len(cross_up_200) > 0 else False

    below_50 = pd.notna(sma_50) and close < sma_50
    below_100 = pd.notna(sma_100) and close < sma_100
    below_200 = pd.notna(sma_200) and close < sma_200

    # Stage 4: 200-day cross-up signal (past-only shift-based crossover)
    if stage4_today:
        in_cooldown, days_since = _check_cooldown(df, "SMA_200", "above", cooldown_days)
        if not in_cooldown:
            return PuddleSignalResult(stage=4, alert=True, cooldown_active=False, cooldown_info=None)
        return PuddleSignalResult(
            stage=4,
            alert=False,
            cooldown_active=True,
            cooldown_info=f"200일선 상향돌파 ({days_since}일 전 발생)",
        )

    # Deepest-first downside stages (3 -> 2 -> 1)
    if below_200:
        in_cooldown, days_since = _check_cooldown(df, "SMA_200", "below", cooldown_days)
        if not in_cooldown:
            return PuddleSignalResult(stage=3, alert=True, cooldown_active=False, cooldown_info=None)
        return PuddleSignalResult(
            stage=3,
            alert=False,
            cooldown_active=True,
            cooldown_info=f"200일선 하향돌파 ({days_since}일 전 발생)",
        )

    if below_100:
        in_cooldown, days_since = _check_cooldown(df, "SMA_100", "below", cooldown_days)
        if not in_cooldown:
            return PuddleSignalResult(stage=2, alert=True, cooldown_active=False, cooldown_info=None)
        return PuddleSignalResult(
            stage=2,
            alert=False,
            cooldown_active=True,
            cooldown_info=f"100일선 하향돌파 ({days_since}일 전 발생)",
        )

    if below_50:
        in_cooldown, days_since = _check_cooldown(df, "SMA_50", "below", cooldown_days)
        if not in_cooldown:
            return PuddleSignalResult(stage=1, alert=True, cooldown_active=False, cooldown_info=None)
        return PuddleSignalResult(
            stage=1,
            alert=False,
            cooldown_active=True,
            cooldown_info=f"50일선 하향돌파 ({days_since}일 전 발생)",
        )

    return PuddleSignalResult(stage=0, alert=False, cooldown_active=False, cooldown_info=None)
