# -*- coding: utf-8 -*-
"""Execution Plan — AI 전략을 실행 가능한 주문으로 변환.

정수주 계산 규칙을 적용하고, 포트폴리오 상태와 결합하여
실제 실행 가능한 주문 리스트를 생성한다.

Strategy Stabilizer 적용:
  - 일일 비중 변동 ≤5%
  - 최소 거래 단위 ≥1% (그 미만 → HOLD 처리)
  - 일일 현금 사용 ≤25%

PUDDLE 투입 알고리즘:
  - PUDDLE_1: 0% (매수 금지)
  - PUDDLE_2: 현금의 10%
  - PUDDLE_3: 현금의 25%
  - PUDDLE_4: 현금의 50%
"""

from __future__ import annotations

from typing import Any

# ── PUDDLE deploy rates (% of available cash) ────────────────────
PUDDLE_DEPLOY_RATES: dict[int, float] = {1: 0.0, 2: 10.0, 3: 25.0, 4: 50.0}

# ── Strategy Stabilizer constants ────────────────────────────────
MAX_DAILY_WEIGHT_CHANGE: float = 5.0
MIN_TRADE_PCT: float = 1.0
MAX_DAILY_CASH_USAGE_PCT: float = 25.0


def build_plan(
    *,
    strategy: dict[str, Any],
    portfolio: dict[str, Any],
    regime: str,
) -> dict[str, Any]:
    """Convert AI strategy into executable order plan.

    Returns:
    {
      "orders": [...],
      "summary": "실행 요약 문장",
      "regime": "...",
      "puddle_deploy_pct": float or None,
      "stabilizer_applied": [...],
    }
    """
    actions = strategy.get("recommended_actions", [])
    cash_action = str(strategy.get("cash_action", "KEEP")).upper()

    # Build price lookup from portfolio positions
    price_map: dict[str, float] = {}
    shares_map: dict[str, int] = {}
    for pos in portfolio.get("positions", []):
        price_map[pos["ticker"]] = float(pos.get("price", 0))
        shares_map[pos["ticker"]] = int(pos.get("shares", 0))

    # Total portfolio value
    total_value: float = float(portfolio.get("cash", 0))
    for pos in portfolio.get("positions", []):
        total_value += float(pos.get("shares", 0)) * float(pos.get("price", 0))

    # Available cash = cash + SGOV value
    available_cash = float(portfolio.get("cash", 0))
    for pos in portfolio.get("positions", []):
        if pos["ticker"] == "SGOV":
            available_cash += float(pos.get("shares", 0)) * float(pos.get("price", 0))

    # ── PUDDLE deploy cap ────────────────────────────────────────
    regime_upper = regime.upper() if regime else ""
    puddle_deploy_pct: float | None = None
    puddle_cash_cap: float = available_cash  # default: no cap

    if regime_upper.startswith("PUDDLE_"):
        try:
            stage = int(regime_upper.split("_")[1])
        except (IndexError, ValueError):
            stage = 0
        puddle_deploy_pct = PUDDLE_DEPLOY_RATES.get(stage, 0.0)
        puddle_cash_cap = available_cash * puddle_deploy_pct / 100.0

    # ── Daily cash usage cap (25%) ───────────────────────────────
    daily_cash_cap = available_cash * MAX_DAILY_CASH_USAGE_PCT / 100.0
    effective_cash_cap = min(
        puddle_cash_cap if puddle_deploy_pct is not None else daily_cash_cap,
        daily_cash_cap,
    )

    orders: list[dict[str, Any]] = []
    total_cost = 0.0
    stabilizer_notes: list[str] = []

    for act in actions:
        ticker = str(act.get("ticker", "")).upper()
        action = str(act.get("action", "HOLD")).upper()
        amount = int(act.get("amount", 0))

        if action == "HOLD" or amount == 0:
            orders.append({
                "ticker": ticker,
                "action": "HOLD",
                "shares": 0,
                "estimated_cost": 0,
            })
            continue

        price = price_map.get(ticker, 0)

        if action == "BUY":
            # --- Strategy stabilizer: min trade check ---
            if total_value > 0 and price > 0:
                trade_pct = (amount * price / total_value) * 100
                if trade_pct < MIN_TRADE_PCT:
                    stabilizer_notes.append(
                        f"{ticker}: 거래 비중 {trade_pct:.2f}% < {MIN_TRADE_PCT}% → HOLD"
                    )
                    orders.append({
                        "ticker": ticker,
                        "action": "HOLD",
                        "shares": 0,
                        "estimated_cost": 0,
                        "_stabilizer": f"min_trade ({trade_pct:.2f}%)",
                    })
                    continue

            # --- Strategy stabilizer: daily weight change cap ---
            if total_value > 0 and price > 0:
                weight_change = (amount * price / total_value) * 100
                if weight_change > MAX_DAILY_WEIGHT_CHANGE:
                    max_shares = int(MAX_DAILY_WEIGHT_CHANGE / 100 * total_value / price)
                    if max_shares < amount:
                        stabilizer_notes.append(
                            f"{ticker}: 비중 변동 {weight_change:.1f}% → {MAX_DAILY_WEIGHT_CHANGE}% 캡 적용"
                        )
                        amount = max_shares

            # --- Cash cap enforcement ---
            remaining_budget = effective_cash_cap - total_cost
            if remaining_budget <= 0:
                stabilizer_notes.append(f"{ticker}: 현금 한도 초과 → HOLD")
                orders.append({
                    "ticker": ticker,
                    "action": "HOLD",
                    "shares": 0,
                    "estimated_cost": 0,
                    "_stabilizer": "cash_cap_exceeded",
                })
                continue

            # 정수주 계산
            if price > 0:
                max_by_budget = int(remaining_budget / price)
                max_affordable = int(available_cash / price) if available_cash > 0 else 0
                shares = min(amount, max_by_budget, max_affordable)
            else:
                shares = amount

            if shares <= 0:
                orders.append({
                    "ticker": ticker,
                    "action": "HOLD",
                    "shares": 0,
                    "estimated_cost": 0,
                    "_stabilizer": "insufficient_cash",
                })
                continue

            cost = shares * price
            total_cost += cost
            available_cash -= cost
            orders.append({
                "ticker": ticker,
                "action": "BUY",
                "shares": shares,
                "estimated_cost": round(cost, 2),
            })

        elif action == "REDUCE":
            current_shares = shares_map.get(ticker, 0)

            # --- Strategy stabilizer: min trade check ---
            if total_value > 0 and price > 0:
                trade_pct = (amount * price / total_value) * 100
                if trade_pct < MIN_TRADE_PCT:
                    stabilizer_notes.append(
                        f"{ticker}: 매도 비중 {trade_pct:.2f}% < {MIN_TRADE_PCT}% → HOLD"
                    )
                    orders.append({
                        "ticker": ticker,
                        "action": "HOLD",
                        "shares": 0,
                        "estimated_cost": 0,
                        "_stabilizer": f"min_trade ({trade_pct:.2f}%)",
                    })
                    continue

            shares = min(amount, current_shares)
            proceeds = shares * price
            orders.append({
                "ticker": ticker,
                "action": "REDUCE",
                "shares": shares,
                "estimated_proceeds": round(proceeds, 2),
            })

    # Summary
    buy_orders = [o for o in orders if o["action"] == "BUY" and o.get("shares", 0) > 0]
    sell_orders = [o for o in orders if o["action"] == "REDUCE" and o.get("shares", 0) > 0]
    hold_orders = [o for o in orders if o["action"] == "HOLD"]

    parts = []
    if buy_orders:
        buy_str = ", ".join(f"{o['ticker']} {o['shares']}주" for o in buy_orders)
        parts.append(f"매수: {buy_str}")
    if sell_orders:
        sell_str = ", ".join(f"{o['ticker']} {o['shares']}주" for o in sell_orders)
        parts.append(f"매도: {sell_str}")
    if hold_orders and not buy_orders and not sell_orders:
        parts.append("전 종목 홀드")
    if cash_action != "KEEP":
        parts.append(f"현금 전략: {cash_action}")
    if puddle_deploy_pct is not None:
        parts.append(f"PUDDLE 투입률: {puddle_deploy_pct:.0f}%")

    summary = " | ".join(parts) if parts else "변동 없음"

    return {
        "orders": orders,
        "summary": summary,
        "regime": regime,
        "cash_action": cash_action,
        "remaining_cash": round(available_cash, 2),
        "puddle_deploy_pct": puddle_deploy_pct,
        "stabilizer_applied": stabilizer_notes,
    }
