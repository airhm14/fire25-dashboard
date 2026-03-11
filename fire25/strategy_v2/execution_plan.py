# -*- coding: utf-8 -*-
"""Execution Plan — AI 전략을 실행 가능한 주문으로 변환.

정수주 계산 규칙을 적용하고, 포트폴리오 상태와 결합하여
실제 실행 가능한 주문 리스트를 생성한다.
"""

from __future__ import annotations

from typing import Any


def build_plan(
    *,
    strategy: dict[str, Any],
    portfolio: dict[str, Any],
    regime: str,
) -> dict[str, Any]:
    """Convert AI strategy into executable order plan.

    Returns:
    {
      "orders": [
        {"ticker": "QQQM", "action": "BUY", "shares": 2, "estimated_cost": ...},
        ...
      ],
      "summary": "실행 요약 문장",
      "regime": "...",
    }
    """
    actions = strategy.get("recommended_actions", [])
    cash_action = str(strategy.get("cash_action", "KEEP")).upper()

    # Build price lookup from portfolio positions
    price_map: dict[str, float] = {}
    for pos in portfolio.get("positions", []):
        price_map[pos["ticker"]] = float(pos.get("price", 0))

    available_cash = float(portfolio.get("cash", 0))
    # SGOV is also part of cash pool
    for pos in portfolio.get("positions", []):
        if pos["ticker"] == "SGOV":
            available_cash += float(pos.get("shares", 0)) * float(pos.get("price", 0))

    orders: list[dict[str, Any]] = []
    total_cost = 0.0

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
            # 정수주 계산
            if price > 0:
                max_affordable = int(available_cash / price)
                shares = min(amount, max_affordable)
            else:
                shares = amount
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
            # Find current shares
            current_shares = 0
            for pos in portfolio.get("positions", []):
                if pos["ticker"] == ticker:
                    current_shares = int(pos.get("shares", 0))
            shares = min(amount, current_shares)
            proceeds = shares * price
            orders.append({
                "ticker": ticker,
                "action": "REDUCE",
                "shares": shares,
                "estimated_proceeds": round(proceeds, 2),
            })

    # Summary
    buy_orders = [o for o in orders if o["action"] == "BUY" and o["shares"] > 0]
    sell_orders = [o for o in orders if o["action"] == "REDUCE" and o["shares"] > 0]
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

    summary = " | ".join(parts) if parts else "변동 없음"

    return {
        "orders": orders,
        "summary": summary,
        "regime": regime,
        "cash_action": cash_action,
        "remaining_cash": round(available_cash, 2),
    }
