# -*- coding: utf-8 -*-
"""Portfolio Strategy — 포트폴리오 상태 정보 구축.

오케스트레이터에 전달할 포트폴리오 dict를 구성한다.
"""

from __future__ import annotations

from typing import Any

# 목표 비중 (Manual 고정)
TARGET_WEIGHTS = {
    "QQQM": 72.0,
    "SCHD": 16.0,
    "IAU": 2.0,
    "SGOV": 10.0,  # Cash sleeve
}


def build_portfolio_input(
    *,
    qqqm_shares: float = 0,
    schd_shares: float = 0,
    iau_shares: float = 0,
    sgov_shares: float = 0,
    cash_deposit: float = 0,
    qqqm_price: float = 0,
    schd_price: float = 0,
    iau_price: float = 0,
    sgov_price: float = 0,
) -> dict[str, Any]:
    """Build portfolio dict for orchestrator input.

    Returns format compatible with agent prompts:
    {
      "positions": [...],
      "cash": ...,
      "total_value": ...,
      "weights": {...},
      "target_weights": {...},
    }
    """
    positions = [
        {"ticker": "QQQM", "shares": int(qqqm_shares), "price": round(qqqm_price, 2)},
        {"ticker": "SCHD", "shares": int(schd_shares), "price": round(schd_price, 2)},
        {"ticker": "IAU", "shares": int(iau_shares), "price": round(iau_price, 2)},
        {"ticker": "SGOV", "shares": int(sgov_shares), "price": round(sgov_price, 2)},
    ]

    values = {
        "QQQM": qqqm_shares * qqqm_price,
        "SCHD": schd_shares * schd_price,
        "IAU": iau_shares * iau_price,
        "SGOV": sgov_shares * sgov_price,
    }
    total_invested = sum(values.values())
    total_value = total_invested + cash_deposit

    weights: dict[str, float] = {}
    if total_value > 0:
        for ticker, val in values.items():
            weights[ticker] = round(val / total_value * 100, 1)
        weights["cash"] = round(cash_deposit / total_value * 100, 1)
    else:
        weights = {"QQQM": 0, "SCHD": 0, "IAU": 0, "SGOV": 0, "cash": 0}

    return {
        "positions": positions,
        "cash": round(cash_deposit, 2),
        "total_value": round(total_value, 2),
        "weights": weights,
        "target_weights": dict(TARGET_WEIGHTS),
    }
