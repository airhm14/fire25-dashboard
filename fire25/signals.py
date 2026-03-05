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

    recent = df.iloc[-(cooldown_days + 1):-1]
    last_signal_idx = None

    for i in range(len(recent) - 1):
        current_close = recent.iloc[i]["Close"]
        next_close = recent.iloc[i + 1]["Close"]
        current_sma = recent.iloc[i][sma_column]
        next_sma = recent.iloc[i + 1][sma_column]

        if pd.isna(current_sma) or pd.isna(next_sma) or pd.isna(current_close) or pd.isna(next_close):
            continue

        if direction == "below":
            if current_close >= current_sma and next_close < next_sma:
                last_signal_idx = i + 1
        elif direction == "above":
            if current_close < current_sma and next_close >= next_sma:
                last_signal_idx = i + 1

    if last_signal_idx is None:
        return False, None

    days_since = len(recent) - 1 - last_signal_idx
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

    below_50 = pd.notna(sma_50) and close < sma_50
    below_100 = pd.notna(sma_100) and close < sma_100
    below_200 = pd.notna(sma_200) and close < sma_200

    # Stage 4: 200-day cross-up signal (requires valid previous/current SMA_200)
    if len(df) >= 2:
        prev = df.iloc[-2]
        prev_close = prev["Close"]
        prev_sma_200 = prev["SMA_200"]
        if pd.notna(prev_close) and pd.notna(prev_sma_200) and pd.notna(sma_200):
            was_below_200 = prev_close < prev_sma_200
            is_above_200 = close > sma_200
            if was_below_200 and is_above_200:
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
