# TEAM FIRE 25 Platform v1.0 Release Notes

## Status
- Version: v1.0 (freeze)
- Date: 2026-03-07
- Scope: final stabilization and architecture cleanup

## Architecture Summary
- UI: `fire25_v1.0.py`
- Engines: `data_provider.py`, `indicator_engine.py`, `signals.py`, `strategy.py`, `portfolio_engine.py`, `backtest.py`, `monte_carlo.py`, `macro_summary.py`, `regime_engine.py`, `fx_provider.py`

## Final Stabilization Changes
- Removed duplicated dashboard-side strategy calculations and converted to engine-driven condition evaluation.
- Kept puddle/cooldown as a single source via `calculate_puddle_signal(...)`.
- Added/used strategy engine evaluators for DEFCON and Smart Shoulder condition checks.
- Added Market Regime engine integration and exported API for future reuse.
- Added backtest context columns (`regime`, `regime_confidence`) without changing execution behavior.
- Migrated deprecated Streamlit `use_container_width=True` to `width='stretch'` in `fire25_v1.0.py`.

## Verification
- Unit tests: `python -m pytest -q` passed.
- Dashboard smoke checks: Strategy Lab and FIRE Simulator run successfully.
- Numeric format cleanup verified (`:,2f`, `%{y:,2f}`, `%{value:,2f}` not found in `fire25_v1.0.py`).

## Notes
- No new trading features were added in freeze pass.
- Core intent of v1.0: stable personal quant research platform with clear module boundaries.
