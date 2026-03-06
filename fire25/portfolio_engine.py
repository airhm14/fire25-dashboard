from __future__ import annotations

from typing import Any

from .fx_provider import convert_to_usd


def compute_cash(sgov_qty: float, sgov_price: float, cash_deposit: float, currency: str) -> dict[str, float]:
    """Compute USD-normalized cash sleeve (SGOV + deposit cash)."""
    sgov_raw_value = float(sgov_qty) * float(sgov_price)
    sgov_value = convert_to_usd(sgov_raw_value, currency)
    cash_total = float(sgov_value) + float(cash_deposit)
    return {
        "sgov_value": float(sgov_value),
        "cash_total": float(cash_total),
    }


def compute_portfolio_value(assets: dict[str, dict[str, Any]], cash: float) -> dict[str, Any]:
    """Compute USD-normalized asset values, portfolio total, and weights."""
    asset_values: dict[str, float] = {}

    for symbol, meta in assets.items():
        qty = float(meta.get("qty", 0.0))
        price = float(meta.get("price", 0.0))
        currency = str(meta.get("currency", "USD"))
        raw_value = qty * price
        asset_values[symbol] = float(convert_to_usd(raw_value, currency))

    total_asset_value = sum(asset_values.values())
    total_value = float(total_asset_value + float(cash))

    if total_value > 0:
        asset_weights = {k: (v / total_value) * 100.0 for k, v in asset_values.items()}
        cash_weight = (float(cash) / total_value) * 100.0
    else:
        asset_weights = {k: 0.0 for k in asset_values}
        cash_weight = 0.0

    return {
        "asset_values": asset_values,
        "asset_weights": asset_weights,
        "cash_weight": float(cash_weight),
        "total_value": float(total_value),
    }
