"""Core strategy modules for TEAM FIRE 25."""

from .backtest import (
	BacktestResult,
	compute_backtest_metrics,
	run_backtest,
	run_strategy_backtest,
	plot_backtest_results,
)
from .data_provider import detect_asset_type, get_market_data
from .fx_provider import convert_to_usd, get_fx_rate
from .indicator_engine import compute_indicators
from .monte_carlo import (
	calculate_fire_probability,
	compute_monte_carlo_statistics,
	plot_monte_carlo,
	simulate_monte_carlo,
	simulate_monte_carlo_with_contributions,
)
from .positioning import compute_stage_allocation
from .portfolio_engine import compute_cash, compute_portfolio_value
from .regime_engine import detect_market_regime
from .signals import PuddleSignalResult, calculate_puddle_signal
from .strategy import (
	STAGE_DEPLOYMENT_RATES,
	compute_deployment,
	detect_defcon,
	estimate_vol_factor,
	evaluate_smart_shoulder,
)

__all__ = [
	"PuddleSignalResult",
	"calculate_puddle_signal",
	"BacktestResult",
	"run_backtest",
	"run_strategy_backtest",
	"compute_backtest_metrics",
	"plot_backtest_results",
	"get_market_data",
	"detect_asset_type",
	"get_fx_rate",
	"convert_to_usd",
	"compute_indicators",
	"compute_cash",
	"compute_portfolio_value",
	"detect_market_regime",
	"simulate_monte_carlo",
	"simulate_monte_carlo_with_contributions",
	"compute_monte_carlo_statistics",
	"plot_monte_carlo",
	"calculate_fire_probability",
	"compute_stage_allocation",
	"compute_deployment",
	"detect_defcon",
	"evaluate_smart_shoulder",
	"STAGE_DEPLOYMENT_RATES",
	"estimate_vol_factor",
]
