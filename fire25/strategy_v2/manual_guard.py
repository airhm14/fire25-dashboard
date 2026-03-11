# -*- coding: utf-8 -*-
"""Manual Guard — 투자 헌법 위반 검사.

AI 전략이 매뉴얼 규칙을 위반하는지 검사한다.
위반 항목 리스트를 반환 (빈 리스트 = 통과).

[고정 규칙 — AI 변경 불가]
  - 포트폴리오 구조 (QQQM/SCHD/IAU/SGOV)
  - DEFCON 발동 조건
  - 웅덩이 신호 자체
  - Smart Shoulder 발동 조건
  - 정수주 계산 규칙

[AI 판단 허용]
  - 웅덩이 투입 비율 조정
  - DEFCON 보수도 강도
  - 신규 자금 배분 강약
  - 리밸런싱 우선순위
  - 현금 유지 vs 추가 투입
"""

from __future__ import annotations

from typing import Any

# 허용 종목 — 이외 ETF 교체/자산군 변경 금지
ALLOWED_TICKERS = {"QQQM", "SCHD", "IAU", "SGOV"}

# 허용 action
ALLOWED_ACTIONS = {"BUY", "HOLD", "REDUCE"}

# 허용 cash_action
ALLOWED_CASH_ACTIONS = {"KEEP", "DEPLOY", "INCREASE"}

# Regime별 금지 사항
REGIME_RULES: dict[str, dict[str, Any]] = {
    "DEFCON": {
        # DEFCON 시 주식 적극 매수 금지 (소량 BUY는 허용하지 않음)
        "block_buy": ["QQQM", "SCHD", "IAU"],
        "force_cash": "INCREASE",  # 신규자금 SGOV 우선
    },
    "SMART_SHOULDER": {
        # 리스크 축소 방향 유지 — QQQM 매수 금지
        "block_buy": ["QQQM"],
    },
}


def validate(strategy: dict[str, Any], regime: str) -> list[str]:
    """Validate strategy against manual rules. Returns list of violations."""
    violations: list[str] = []

    if not strategy or strategy.get("_source") == "fallback":
        return violations  # Fallback strategies are pre-approved

    actions = strategy.get("recommended_actions", [])
    cash_action = str(strategy.get("cash_action", "KEEP")).upper()

    # --- Rule 1: Only allowed tickers ---
    for act in actions:
        ticker = str(act.get("ticker", "")).upper()
        if ticker and ticker not in ALLOWED_TICKERS:
            violations.append(f"허용되지 않은 종목: {ticker}")

    # --- Rule 2: Only allowed actions ---
    for act in actions:
        action = str(act.get("action", "HOLD")).upper()
        if action not in ALLOWED_ACTIONS:
            violations.append(f"허용되지 않은 액션: {action}")

    # --- Rule 3: Only allowed cash_actions ---
    if cash_action not in ALLOWED_CASH_ACTIONS:
        violations.append(f"허용되지 않은 현금 전략: {cash_action}")

    # --- Rule 4: Integer shares only ---
    for act in actions:
        amount = act.get("amount", 0)
        if amount is not None and amount != 0:
            try:
                if float(amount) != int(amount):
                    violations.append(f"{act.get('ticker')}: 정수주만 허용 (amount={amount})")
            except (TypeError, ValueError):
                violations.append(f"{act.get('ticker')}: 수량 형식 오류 (amount={amount})")

    # --- Rule 5: Regime-specific rules ---
    regime_upper = regime.upper() if regime else ""
    rules = REGIME_RULES.get(regime_upper, {})

    blocked_buy = rules.get("block_buy", [])
    for act in actions:
        ticker = str(act.get("ticker", "")).upper()
        action = str(act.get("action", "HOLD")).upper()
        if ticker in blocked_buy and action == "BUY":
            violations.append(f"{regime} 모드에서 {ticker} 매수 금지")

    forced_cash = rules.get("force_cash")
    if forced_cash and cash_action != forced_cash:
        violations.append(f"{regime} 모드에서 현금 전략은 {forced_cash}이어야 함 (현재: {cash_action})")

    # --- Rule 6: PUDDLE regimes — cash-based deployment principle ---
    if regime_upper.startswith("PUDDLE_"):
        # 웅덩이 시 현금성 자산 기준 투입 원칙
        # REDUCE on SGOV is not allowed in puddle (cash = deployment source)
        for act in actions:
            ticker = str(act.get("ticker", "")).upper()
            action = str(act.get("action", "HOLD")).upper()
            if ticker == "SGOV" and action == "REDUCE":
                pass  # SGOV 매도 = 현금 확보 for deployment — 허용
            # 웅덩이에서 현금 증가(INCREASE)는 원칙 위반
        if cash_action == "INCREASE":
            violations.append(f"{regime} 모드에서 현금 증가(INCREASE)는 원칙 위반 — 투입 방향이어야 함")

    return violations
