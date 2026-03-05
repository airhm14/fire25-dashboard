from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np
import pandas as pd

from .signals import calculate_puddle_signal
from .positioning import compute_stage_allocation, estimate_vol_factor


@dataclass
class BacktestResult:
    """Container for walk-forward backtest outputs."""

    equity_curve: pd.Series
    trades: pd.DataFrame
    metrics: dict


def _compute_metrics(equity_curve: pd.Series) -> dict:
    """Compute simple performance metrics from an equity curve."""
    if equity_curve.empty:
        return {"CAGR": 0.0, "MDD": 0.0, "Vol": 0.0, "Sharpe": 0.0}

    returns = equity_curve.pct_change().dropna()
    periods = max(len(equity_curve) - 1, 1)

    start_val = float(equity_curve.iloc[0])
    end_val = float(equity_curve.iloc[-1])

    if start_val > 0 and end_val > 0:
        cagr = (end_val / start_val) ** (252.0 / periods) - 1.0
    else:
        cagr = 0.0

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1.0
    mdd = float(drawdown.min()) if not drawdown.empty else 0.0

    vol = float(returns.std(ddof=0) * np.sqrt(252.0)) if not returns.empty else 0.0
    sharpe = 0.0
    if not returns.empty and returns.std(ddof=0) > 0:
        sharpe = float((returns.mean() / returns.std(ddof=0)) * np.sqrt(252.0))

    return {"CAGR": cagr, "MDD": mdd, "Vol": vol, "Sharpe": sharpe}


def run_backtest(
    df: pd.DataFrame,
    initial_cash: float,
    stage_alloc: Dict[int, float],
    fee_bps: float = 1.0,
    slippage_bps: float = 2.0,
    use_vol_adjustment: bool = False,
) -> BacktestResult:
    """Run a walk-forward backtest using incremental cash-based dip buying.

    Signal timing: compute at day D close using data up to D.
    Execution timing: execute planned buy at day D+1 open (no same-day execution).
    Mark-to-market: equity is recorded at each day close.
    """
    required_cols = {"Open", "Close", "SMA_50", "SMA_100", "SMA_200"}
    if df is None or df.empty or not required_cols.issubset(df.columns):
        empty_curve = pd.Series(dtype=float)
        empty_trades = pd.DataFrame(
            columns=[
                "signal_date",
                "exec_date",
                "stage",
                "action",
                "price",
                "buy_amount",
                "shares_bought",
                "cash_after",
            ]
        )
        return BacktestResult(equity_curve=empty_curve, trades=empty_trades, metrics=_compute_metrics(empty_curve))

    fee_rate = fee_bps / 10000.0
    slippage_rate = slippage_bps / 10000.0

    cash = float(initial_cash)
    shares = 0.0
    pending_buy_amount = None
    pending_stage = None
    pending_signal_date = None

    equity_records = []
    trade_records = []

    for i in range(len(df)):
        row = df.iloc[i]
        open_px = float(row["Open"])
        close_px = float(row["Close"])
        date = df.index[i]

        # Execute yesterday's planned buy at today's open.
        if pending_buy_amount is not None and i > 0 and np.isfinite(open_px) and open_px > 0:
            buy_amount = min(float(pending_buy_amount), cash)
            if buy_amount > 0:
                exec_price = open_px * (1.0 + slippage_rate)
                gross_notional = buy_amount / (1.0 + fee_rate)
                fee = gross_notional * fee_rate
                shares_bought = gross_notional / exec_price

                cash -= buy_amount
                shares += shares_bought

                trade_records.append(
                    {
                        "signal_date": pending_signal_date,
                        "exec_date": date,
                        "stage": int(pending_stage) if pending_stage is not None else None,
                        "action": "BUY",
                        "price": float(open_px),
                        "buy_amount": float(buy_amount),
                        "shares_bought": float(shares_bought),
                        "cash_after": float(cash),
                    }
                )

        # Clear pending order after attempting next-day execution.
        pending_buy_amount = None
        pending_stage = None
        pending_signal_date = None

        # Mark-to-market at today's close.
        equity_close = cash + shares * close_px
        equity_records.append((date, float(equity_close)))

        # Compute signal at day D close for day D+1 open execution.
        hist = df.iloc[: i + 1]
        signal = calculate_puddle_signal(hist)
        if signal.alert and not signal.cooldown_active:
            if signal.stage == 4:
                buy_amount = cash
            else:
                base_alloc = float(stage_alloc.get(signal.stage, 0.0))
                vol_factor = estimate_vol_factor(hist) if use_vol_adjustment else None
                alloc = compute_stage_allocation(signal.stage, base_alloc, vol_factor)
                buy_amount = cash * alloc

            if buy_amount > 0:
                pending_buy_amount = float(buy_amount)
                pending_stage = int(signal.stage)
                pending_signal_date = date

    equity_curve = pd.Series(
        [v for _, v in equity_records],
        index=pd.Index([d for d, _ in equity_records]),
        name="equity",
        dtype=float,
    )

    trades = pd.DataFrame(trade_records)
    if not trades.empty:
        trades["signal_date"] = pd.to_datetime(trades["signal_date"])
        trades["exec_date"] = pd.to_datetime(trades["exec_date"])

    metrics = _compute_metrics(equity_curve)
    return BacktestResult(equity_curve=equity_curve, trades=trades, metrics=metrics)
