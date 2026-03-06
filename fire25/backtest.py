from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .data_provider import get_market_data
from .indicator_engine import compute_indicators
from .regime_engine import detect_market_regime
from .signals import calculate_puddle_signal
from .strategy import STAGE_DEPLOYMENT_RATES, compute_deployment, estimate_vol_factor


_RESEARCH_DATA_CACHE: dict[tuple[str, str], pd.DataFrame] = {}


@dataclass
class BacktestResult:
    """Container for walk-forward backtest outputs."""

    equity_curve: pd.Series
    benchmark_curve: pd.Series
    trades: pd.DataFrame
    metrics: dict


def run_strategy_backtest(
    symbol: str,
    start_date: str,
    initial_cash: float,
    cooldown_days: int = 30,
    stage_rates: Optional[Dict[int, float]] = None,
    cash_ratio: float = 0.10,
) -> pd.DataFrame:
    """Run a strategy research backtest on a symbol from start_date onward.

    Uses unified data provider + indicator engine and simulates staged cash
    deployment with remaining-cash tracking.
    """
    cache_key = (str(symbol), str(start_date))
    if cache_key in _RESEARCH_DATA_CACHE:
        df = _RESEARCH_DATA_CACHE[cache_key].copy()
    else:
        market_data = get_market_data(symbol, period="max")
        raw_df = market_data["df"]
        df = compute_indicators(raw_df)

        start_ts = pd.Timestamp(start_date)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize(df.index.tz)
        else:
            start_ts = start_ts.tz_convert(df.index.tz)

        df = df.loc[df.index >= start_ts].copy()
        if df.empty:
            raise ValueError(f"No data available for {symbol} from {start_date}")

        # Exclude potentially in-progress latest bar to improve reproducibility.
        today_local = pd.Timestamp.now(tz=df.index.tz).date()
        if len(df) > 1 and pd.Timestamp(df.index[-1]).date() == today_local:
            df = df.iloc[:-1].copy()
            if df.empty:
                raise ValueError(f"No completed bars available for {symbol} from {start_date}")

        _RESEARCH_DATA_CACHE[cache_key] = df.copy()

    if stage_rates is None:
        stage_rates = {1: STAGE_DEPLOYMENT_RATES[1], 2: STAGE_DEPLOYMENT_RATES[2], 3: STAGE_DEPLOYMENT_RATES[3]}

    cash_ratio = float(np.clip(cash_ratio, 0.0, 1.0))
    reserve_cash = float(initial_cash) * cash_ratio
    deployable_cash = float(initial_cash) - reserve_cash
    remaining_cash = float(deployable_cash)
    position_units = 0.0
    first_price = float(df["Close"].iloc[0])
    buy_hold_units = float(initial_cash) / first_price if first_price > 0 else 0.0

    rows = []
    for i in range(len(df)):
        hist = df.iloc[: i + 1]
        close_px = float(hist["Close"].iloc[-1])
        date = hist.index[-1]

        signal = calculate_puddle_signal(hist, cooldown_days=cooldown_days)
        stage = int(signal.stage)
        regime_info = detect_market_regime(hist, vix_value=None)
        regime = str(regime_info.get("regime", "CORRECTION"))
        regime_confidence = float(regime_info.get("confidence", 0.0))

        if signal.alert and not signal.cooldown_active and remaining_cash > 0 and close_px > 0:
            deploy_cash = float(compute_deployment(stage, remaining_cash)) if stage in (1, 2, 3, 4) else 0.0

            if stage in (1, 2, 3):
                default_rate = float(STAGE_DEPLOYMENT_RATES.get(stage, 0.0))
                custom_rate = float(stage_rates.get(stage, default_rate))
                if default_rate > 0:
                    deploy_cash *= custom_rate / default_rate

            deploy_cash = min(max(deploy_cash, 0.0), remaining_cash)
            if deploy_cash > 0:
                position_units += deploy_cash / close_px
                remaining_cash -= deploy_cash
        else:
            deploy_cash = 0.0

        position_value = position_units * close_px
        total_cash = reserve_cash + remaining_cash
        portfolio_value = total_cash + position_value
        buy_hold_value = buy_hold_units * close_px

        rows.append(
            {
                "date": date,
                "price": close_px,
                "stage": stage,
                "regime": regime,
                "regime_confidence": regime_confidence,
                "cash": float(total_cash),
                "position_value": float(position_value),
                "portfolio_value": float(portfolio_value),
                "buy_hold_value": float(buy_hold_value),
                "deploy_cash": float(deploy_cash),
            }
        )

    return pd.DataFrame(rows)


def compute_backtest_metrics(df: pd.DataFrame) -> dict:
    """Compute strategy performance metrics from research backtest output."""
    if df is None or df.empty:
        return {
            "CAGR": 0.0,
            "Max Drawdown": 0.0,
            "Sharpe Ratio": 0.0,
            "Volatility": 0.0,
            "Total Return": 0.0,
            "strategy_return": 0.0,
            "buy_hold_return": 0.0,
        }

    equity = pd.to_numeric(df["portfolio_value"], errors="coerce").dropna()
    if equity.empty:
        return {
            "CAGR": 0.0,
            "Max Drawdown": 0.0,
            "Sharpe Ratio": 0.0,
            "Volatility": 0.0,
            "Total Return": 0.0,
            "strategy_return": 0.0,
            "buy_hold_return": 0.0,
        }

    returns = equity.pct_change().dropna()
    periods = max(len(equity) - 1, 1)
    start_val = float(equity.iloc[0])
    end_val = float(equity.iloc[-1])

    cagr = (end_val / start_val) ** (252.0 / periods) - 1.0 if start_val > 0 and end_val > 0 else 0.0

    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

    vol = float(returns.std(ddof=0) * np.sqrt(252.0)) if not returns.empty else 0.0
    sharpe = float((returns.mean() / returns.std(ddof=0)) * np.sqrt(252.0)) if not returns.empty and returns.std(ddof=0) > 0 else 0.0
    total_return = (end_val / start_val - 1.0) if start_val > 0 else 0.0

    buy_hold_return = 0.0
    if "buy_hold_value" in df.columns:
        bh = pd.to_numeric(df["buy_hold_value"], errors="coerce").dropna()
        if not bh.empty and float(bh.iloc[0]) > 0:
            buy_hold_return = float(bh.iloc[-1] / bh.iloc[0] - 1.0)

    return {
        "CAGR": float(cagr),
        "Max Drawdown": float(max_dd),
        "Sharpe Ratio": float(sharpe),
        "Volatility": float(vol),
        "Total Return": float(total_return),
        "strategy_return": float(total_return),
        "buy_hold_return": float(buy_hold_return),
    }


def plot_backtest_results(df: pd.DataFrame):
    """Return a plotly figure with strategy and buy-and-hold curves."""
    fig = go.Figure()

    if df is None or df.empty:
        fig.update_layout(title="Backtest Result (No Data)")
        return fig

    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["portfolio_value"],
            mode="lines",
            name="Strategy Equity",
            line=dict(color="#10b981", width=2),
        )
    )

    if "buy_hold_value" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["buy_hold_value"],
                mode="lines",
                name="Buy & Hold",
                line=dict(color="#3b82f6", width=2, dash="dash"),
            )
        )

    fig.update_layout(
        plot_bgcolor="rgba(30, 41, 59, 0.5)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e2e8f0"),
        xaxis=dict(gridcolor="rgba(148, 163, 184, 0.2)", showgrid=True),
        yaxis=dict(gridcolor="rgba(148, 163, 184, 0.2)", showgrid=True, title="Value (USD)"),
        height=360,
        hovermode="x unified",
        margin=dict(l=40, r=20, t=30, b=20),
    )
    return fig


def _compute_metrics(equity_curve: pd.Series, num_trades: int) -> dict:
    """Compute auditable performance metrics from an equity curve."""
    if equity_curve.empty:
        return {
            "CAGR": 0.0,
            "MDD": 0.0,
            "Volatility": 0.0,
            "Sharpe": 0.0,
            "TotalReturn": 0.0,
            "NumTrades": int(num_trades),
            "MaxDD_start_end": None,
        }

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

    total_return = (end_val / start_val - 1.0) if start_val > 0 else 0.0

    maxdd_range = None
    if not drawdown.empty:
        dd_end = drawdown.idxmin()
        if pd.notna(dd_end):
            peak_series = equity_curve.loc[:dd_end]
            if not peak_series.empty:
                dd_start = peak_series.idxmax()
                maxdd_range = (dd_start, dd_end)

    return {
        "CAGR": cagr,
        "MDD": mdd,
        "Volatility": vol,
        "Sharpe": sharpe,
        "TotalReturn": float(total_return),
        "NumTrades": int(num_trades),
        "MaxDD_start_end": maxdd_range,
    }


def _stage_reason(stage: int) -> str:
    """Map stage numbers to auditable reason labels."""
    if stage == 1:
        return "stage1_below_50"
    if stage == 2:
        return "stage2_below_100"
    if stage == 3:
        return "stage3_below_200"
    if stage == 4:
        return "stage4_cross_up"
    return f"stage{stage}_unknown"


def run_backtest(
    df: pd.DataFrame,
    initial_cash: float,
    stage_rates: Optional[Dict[int, float]] = None,
    vol_adjust: bool = False,
    buy_only: bool = True,
    fee_bps: float = 1.0,
    slippage_bps: float = 2.0,
) -> BacktestResult:
    """Run a walk-forward backtest using incremental cash-based dip buying.

    Signal timing: compute at day D close using data up to D.
    Execution timing: execute planned buy at day D+1 open (no same-day execution).
    Mark-to-market: equity is recorded at each day close.
    """
    if df is None or df.empty:
        raise ValueError("run_backtest requires a non-empty DataFrame.")

    required_cols = {"Open", "Close", "SMA_50", "SMA_100", "SMA_200"}
    missing = sorted(required_cols.difference(df.columns))
    if missing:
        raise ValueError(f"run_backtest missing required columns: {missing}")

    if df["Open"].isna().any() or df["Close"].isna().any():
        raise ValueError("run_backtest detected missing values in Open/Close columns.")

    if stage_rates is None:
        stage_rates = {1: STAGE_DEPLOYMENT_RATES[1], 2: STAGE_DEPLOYMENT_RATES[2], 3: STAGE_DEPLOYMENT_RATES[3]}

    fee_rate = fee_bps / 10000.0
    slippage_rate = slippage_bps / 10000.0

    cash = float(initial_cash)
    shares = 0.0
    pending_buy_cash = None
    pending_stage = None
    pending_signal_date = None
    pending_reason = None
    pending_vol_factor = None

    equity_records = []
    trade_records = []

    for i in range(len(df)):
        row = df.iloc[i]
        open_px = float(row["Open"])
        close_px = float(row["Close"])
        date = df.index[i]

        # Execute yesterday's planned buy at today's open.
        if pending_buy_cash is not None and i > 0 and np.isfinite(open_px) and open_px > 0:
            planned_cash = min(float(pending_buy_cash), cash)
            if planned_cash > 0:
                exec_price = open_px * (1.0 + slippage_rate)
                fee = planned_cash * fee_rate
                spend = planned_cash - fee
                shares_bought = spend / exec_price if spend > 0 else 0.0

                cash -= planned_cash
                shares += shares_bought

                trade_records.append(
                    {
                        "signal_date": pending_signal_date,
                        "exec_date": date,
                        "stage": int(pending_stage) if pending_stage is not None else None,
                        "action": "BUY",
                        "planned_cash": float(planned_cash),
                        "fee": float(fee),
                        "exec_price": float(exec_price),
                        "shares_bought": float(shares_bought),
                        "cash_after": float(cash),
                        "shares_after": float(shares),
                        "vol_factor": float(pending_vol_factor) if pending_vol_factor is not None else None,
                        "reason": pending_reason,
                    }
                )

        # Clear pending order after attempting next-day execution.
        pending_buy_cash = None
        pending_stage = None
        pending_signal_date = None
        pending_reason = None
        pending_vol_factor = None

        # Mark-to-market at today's close.
        equity_close = cash + shares * close_px
        equity_records.append((date, float(equity_close)))

        # No next-day open exists on the last row.
        if i >= len(df) - 1:
            continue

        # Skip new buy signal scheduling when deployable cash is exhausted.
        if cash <= 0:
            continue

        # Compute signal at day D close for day D+1 open execution.
        hist = df.iloc[: i + 1]
        signal = calculate_puddle_signal(hist)
        if buy_only and signal.alert and not signal.cooldown_active:
            vol_factor = estimate_vol_factor(hist) if vol_adjust else None
            if signal.stage in (1, 2, 3, 4):
                planned_buy_cash = compute_deployment(signal.stage, cash, vol_factor)

                # Honor caller-provided stage_rates for stage 1/2/3 while reusing
                # centralized compute_deployment + volatility logic.
                if signal.stage in (1, 2, 3):
                    default_rate = float(STAGE_DEPLOYMENT_RATES.get(signal.stage, 0.0))
                    custom_rate = float(stage_rates.get(signal.stage, default_rate))
                    if default_rate > 0:
                        planned_buy_cash *= custom_rate / default_rate
            else:
                planned_buy_cash = 0.0

            if planned_buy_cash > 0:
                pending_buy_cash = float(planned_buy_cash)
                pending_stage = int(signal.stage)
                pending_signal_date = date
                pending_reason = _stage_reason(int(signal.stage))
                pending_vol_factor = vol_factor

    equity_curve = pd.Series(
        [v for _, v in equity_records],
        index=df.index,
        name="equity",
        dtype=float,
    )

    first_open = float(df["Open"].iloc[0])
    if not np.isfinite(first_open) or first_open <= 0:
        raise ValueError("run_backtest requires first Open to be finite and > 0 for benchmark initialization.")

    benchmark_shares = float(initial_cash) / first_open
    benchmark_curve = pd.Series(
        benchmark_shares * pd.to_numeric(df["Close"], errors="coerce").astype(float).values,
        index=df.index,
        name="benchmark",
        dtype=float,
    )

    trades = pd.DataFrame(trade_records)
    if not trades.empty:
        trades["signal_date"] = pd.to_datetime(trades["signal_date"])
        trades["exec_date"] = pd.to_datetime(trades["exec_date"])

    metrics = _compute_metrics(equity_curve, num_trades=len(trades))
    metrics["BenchmarkTotalReturn"] = (
        float(benchmark_curve.iloc[-1] / benchmark_curve.iloc[0] - 1.0)
        if len(benchmark_curve) > 1 and benchmark_curve.iloc[0] > 0
        else 0.0
    )
    return BacktestResult(
        equity_curve=equity_curve,
        benchmark_curve=benchmark_curve,
        trades=trades,
        metrics=metrics,
    )
