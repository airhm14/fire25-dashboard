# -*- coding: utf-8 -*-
"""Conflict Detector — Claude vs GPT 전략 합의/충돌 판정.

즉시 합의:
  - 종목별 action 대부분 동일
  - cash_action 동일
  - confidence 차이 25 미만

토론 호출:
  - BUY vs REDUCE 같은 방향 충돌
  - cash_action 충돌
  - 수량 차이 큼
  - confidence 차이 25 이상
  - 핵심 논거가 정반대
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConflictResult:
    """Conflict analysis between two strategy proposals."""
    agreed: bool
    conflict_reasons: list[str] = field(default_factory=list)
    action_conflicts: list[dict[str, Any]] = field(default_factory=list)
    confidence_gap: int = 0
    cash_conflict: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "agreed": self.agreed,
            "conflict_reasons": self.conflict_reasons,
            "action_conflicts": self.action_conflicts,
            "confidence_gap": self.confidence_gap,
            "cash_conflict": self.cash_conflict,
        }


def _actions_to_map(actions: list[dict]) -> dict[str, dict]:
    """Convert recommended_actions list to ticker-keyed dict."""
    out: dict[str, dict] = {}
    for a in (actions or []):
        ticker = a.get("ticker", "")
        if ticker:
            out[ticker] = {
                "action": str(a.get("action", "HOLD")).upper(),
                "amount": int(a.get("amount", 0)),
            }
    return out


_OPPOSITE_PAIRS = {
    frozenset({"BUY", "REDUCE"}),
}


def detect(
    claude_strategy: dict[str, Any],
    gpt_strategy: dict[str, Any],
    confidence_threshold: int = 25,
    amount_threshold: int = 5,
) -> ConflictResult:
    """Compare two strategies and determine if they agree or conflict."""
    reasons: list[str] = []
    action_conflicts: list[dict[str, Any]] = []

    # --- 1) confidence gap ---
    c_conf = int(claude_strategy.get("confidence_score", 50))
    g_conf = int(gpt_strategy.get("confidence_score", 50))
    conf_gap = abs(c_conf - g_conf)

    if conf_gap >= confidence_threshold:
        reasons.append(f"신뢰도 차이 큼: Claude {c_conf} vs GPT {g_conf} (gap={conf_gap})")

    # --- 2) cash_action ---
    c_cash = str(claude_strategy.get("cash_action", "KEEP")).upper()
    g_cash = str(gpt_strategy.get("cash_action", "KEEP")).upper()
    cash_conflict = c_cash != g_cash

    if cash_conflict:
        reasons.append(f"현금 전략 충돌: Claude={c_cash} vs GPT={g_cash}")

    # --- 3) per-ticker action comparison ---
    c_map = _actions_to_map(claude_strategy.get("recommended_actions", []))
    g_map = _actions_to_map(gpt_strategy.get("recommended_actions", []))
    all_tickers = set(c_map) | set(g_map)

    for ticker in sorted(all_tickers):
        c_act = c_map.get(ticker, {"action": "HOLD", "amount": 0})
        g_act = g_map.get(ticker, {"action": "HOLD", "amount": 0})

        direction_conflict = frozenset({c_act["action"], g_act["action"]}) in _OPPOSITE_PAIRS
        amount_diff = abs(c_act["amount"] - g_act["amount"])

        if direction_conflict:
            reasons.append(
                f"{ticker} 방향 충돌: Claude={c_act['action']} vs GPT={g_act['action']}"
            )
            action_conflicts.append({
                "ticker": ticker,
                "type": "direction",
                "claude": c_act,
                "gpt": g_act,
            })
        elif amount_diff >= amount_threshold:
            reasons.append(
                f"{ticker} 수량 차이: Claude={c_act['amount']} vs GPT={g_act['amount']}"
            )
            action_conflicts.append({
                "ticker": ticker,
                "type": "amount",
                "claude": c_act,
                "gpt": g_act,
            })

    agreed = len(reasons) == 0

    return ConflictResult(
        agreed=agreed,
        conflict_reasons=reasons,
        action_conflicts=action_conflicts,
        confidence_gap=conf_gap,
        cash_conflict=cash_conflict,
    )
