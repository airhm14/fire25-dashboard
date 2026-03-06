from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def _clean_returns(returns) -> np.ndarray:
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        raise ValueError("simulate_monte_carlo requires non-empty historical returns")
    return arr


def simulate_monte_carlo(
    returns,
    years: int,
    simulations: int,
    initial_capital: float,
) -> pd.DataFrame:
    """Bootstrap random return paths and simulate portfolio evolution."""
    hist_returns = _clean_returns(returns)
    days = int(max(years, 1) * 252)
    sims = int(max(simulations, 1))

    rng = np.random.default_rng()
    sampled = rng.choice(hist_returns, size=(days, sims), replace=True)

    paths = np.empty((days + 1, sims), dtype=float)
    paths[0, :] = float(initial_capital)
    for t in range(1, days + 1):
        paths[t, :] = paths[t - 1, :] * (1.0 + sampled[t - 1, :])

    cols = [f"sim_{i + 1}" for i in range(sims)]
    return pd.DataFrame(paths, columns=cols)


def simulate_monte_carlo_with_contributions(
    returns,
    years: int,
    simulations: int,
    initial_capital: float,
    annual_investment: float,
) -> pd.DataFrame:
    """Monte Carlo simulation with daily contributions from annual investment."""
    hist_returns = _clean_returns(returns)
    days = int(max(years, 1) * 252)
    sims = int(max(simulations, 1))
    daily_contribution = float(annual_investment) / 252.0

    rng = np.random.default_rng()
    sampled = rng.choice(hist_returns, size=(days, sims), replace=True)

    paths = np.empty((days + 1, sims), dtype=float)
    paths[0, :] = float(initial_capital)
    for t in range(1, days + 1):
        paths[t, :] = paths[t - 1, :] * (1.0 + sampled[t - 1, :]) + daily_contribution

    cols = [f"sim_{i + 1}" for i in range(sims)]
    return pd.DataFrame(paths, columns=cols)


def compute_monte_carlo_statistics(
    simulation_paths: pd.DataFrame,
    initial_capital: float,
    years: int,
) -> dict:
    """Compute distribution statistics from simulation paths."""
    if simulation_paths is None or simulation_paths.empty:
        return {
            "median_final_value": 0.0,
            "5th_percentile": 0.0,
            "95th_percentile": 0.0,
            "max_drawdown_distribution": np.array([]),
            "CAGR_distribution": np.array([]),
        }

    final_values = simulation_paths.iloc[-1].astype(float).values
    median_final = float(np.median(final_values))
    p5 = float(np.percentile(final_values, 5))
    p95 = float(np.percentile(final_values, 95))

    values = simulation_paths.astype(float).values
    running_max = np.maximum.accumulate(values, axis=0)
    drawdowns = values / running_max - 1.0
    mdd_dist = np.min(drawdowns, axis=0)

    base = float(initial_capital)
    y = max(float(years), 1.0)
    cagr_dist = np.where(base > 0, (final_values / base) ** (1.0 / y) - 1.0, 0.0)

    return {
        "median_final_value": median_final,
        "5th_percentile": p5,
        "95th_percentile": p95,
        "max_drawdown_distribution": mdd_dist,
        "CAGR_distribution": cagr_dist,
    }


def plot_monte_carlo(simulation_paths: pd.DataFrame):
    """Plot simulation fan chart with sample paths, median, and confidence bands."""
    fig = go.Figure()
    if simulation_paths is None or simulation_paths.empty:
        fig.update_layout(title="Monte Carlo (No Data)")
        return fig

    paths = simulation_paths.astype(float)
    x = np.arange(len(paths))

    max_lines = min(paths.shape[1], 120)
    for i in range(max_lines):
        col = paths.columns[i]
        fig.add_trace(
            go.Scatter(
                x=x,
                y=paths[col].values,
                mode="lines",
                line=dict(color="rgba(148,163,184,0.18)", width=1),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    median_path = paths.median(axis=1)
    p5 = paths.quantile(0.05, axis=1)
    p95 = paths.quantile(0.95, axis=1)

    fig.add_trace(
        go.Scatter(
            x=x,
            y=p95.values,
            mode="lines",
            line=dict(color="rgba(59,130,246,0.0)", width=0.1),
            showlegend=False,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=p5.values,
            mode="lines",
            fill="tonexty",
            fillcolor="rgba(59,130,246,0.18)",
            line=dict(color="rgba(59,130,246,0.0)", width=0.1),
            name="5-95% Band",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=median_path.values,
            mode="lines",
            name="Median Path",
            line=dict(color="#10b981", width=3),
        )
    )

    fig.update_layout(
        plot_bgcolor="rgba(30, 41, 59, 0.5)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#e2e8f0"),
        xaxis=dict(title="Trading Days", gridcolor="rgba(148, 163, 184, 0.2)", showgrid=True),
        yaxis=dict(title="Portfolio Value (USD)", gridcolor="rgba(148, 163, 184, 0.2)", showgrid=True),
        height=360,
        hovermode="x unified",
        margin=dict(l=40, r=20, t=20, b=20),
    )
    return fig


def calculate_fire_probability(simulation_paths: pd.DataFrame, target_value: float) -> float:
    """Probability of reaching target value at least once within horizon."""
    if simulation_paths is None or simulation_paths.empty:
        return 0.0

    values = simulation_paths.astype(float).values
    reached = (values >= float(target_value)).any(axis=0)
    return float(np.mean(reached))
