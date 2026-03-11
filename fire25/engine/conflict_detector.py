# -*- coding: utf-8 -*-
"""Conflict Detector — Claude vs GPT 전략 합의/충돌 판정.

즉시 합의 (차이 < 10%):
  - 종목별 action 동일 방향
  - 비중 차이 < 10%
  - cash_action 동일
  - confidence 차이 < 25

토론 호출 (차이 ≥ 10%):
  - BUY vs REDUCE 방향 충돌
  - 종목 비중 차이 > 10%
  - 현금 사용 차이 > 20%
  - confidence 차이 ≥ 25
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


def _estimate_alloc_pct(actions: list[dict], portfolio: dict | None = None) -> dict[str, float]:
    """Estimate allocation % implied by each action.

    Uses amount * price / total_value if portfolio is provided,
    otherwise uses amount directly as a rough proxy.
    """
    price_map: dict[str, float] = {}
    total_value = 0.0
    if portfolio:
        for pos in portfolio.get("positions", []):
            p = float(pos.get("price", 0))
            s = float(pos.get("shares", 0))
            price_map[pos["ticker"]] = p
            total_value += p * s
        total_value += float(portfolio.get("cash", 0))

    out: dict[str, float] = {}
    for a in (actions or []):
        ticker = a.get("ticker", "")
        amount = int(a.get("amount", 0))
        price = price_map.get(ticker, 0)
        if total_value > 0 and price > 0:
            out[ticker] = (amount * price / total_value) * 100
        else:
            out[ticker] = float(amount)
    return out


_OPPOSITE_PAIRS = {
    frozenset({"BUY", "REDUCE"}),
}

# ── Threshold constants ──────────────────────────────────────────
CONFIDENCE_THRESHOLD: int = 25        # confidence gap triggering discussion
ALLOC_DIFF_THRESHOLD: float = 10.0    # % allocation difference
CASH_USAGE_DIFF_THRESHOLD: float = 20.0  # % cash usage difference


def detect(
    claude_strategy: dict[str, Any],
    gpt_strategy: dict[str, Any],
    portfolio: dict[str, Any] | None = None,
    confidence_threshold: int = CONFIDENCE_THRESHOLD,
    alloc_diff_threshold: float = ALLOC_DIFF_THRESHOLD,
    cash_usage_diff_threshold: float = CASH_USAGE_DIFF_THRESHOLD,
) -> ConflictResult:
    """Compare two strategies and determine if they agree or conflict.

    Conflict triggers:
      1. BUY vs SELL (REDUCE) direction conflict on any ticker
      2. Allocation difference > 10% on any ticker
      3. Cash usage difference > 20%
      4. Confidence gap > 25
    """
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

    # --- 3) cash usage difference check ---
    c_alloc = _estimate_alloc_pct(claude_strategy.get("recommended_actions", []), portfolio)
    g_alloc = _estimate_alloc_pct(gpt_strategy.get("recommended_actions", []), portfolio)

    c_total_deploy = sum(
        v for t, v in c_alloc.items()
        if _actions_to_map(claude_strategy.get("recommended_actions", [])).get(t, {}).get("action") == "BUY"
    )
    g_total_deploy = sum(
        v for t, v in g_alloc.items()
        if _actions_to_map(gpt_strategy.get("recommended_actions", [])).get(t, {}).get("action") == "BUY"
    )
    cash_diff = abs(c_total_deploy - g_total_deploy)
    if cash_diff >= cash_usage_diff_threshold:
        reasons.append(
            f"현금 사용 차이: Claude {c_total_deploy:.1f}% vs GPT {g_total_deploy:.1f}% (diff={cash_diff:.1f}%)"
        )

    # --- 4) per-ticker action & allocation comparison ---
    c_map = _actions_to_map(claude_strategy.get("recommended_actions", []))
    g_map = _actions_to_map(gpt_strategy.get("recommended_actions", []))
    all_tickers = set(c_map) | set(g_map)

    for ticker in sorted(all_tickers):
        c_act = c_map.get(ticker, {"action": "HOLD", "amount": 0})
        g_act = g_map.get(ticker, {"action": "HOLD", "amount": 0})

        direction_conflict = frozenset({c_act["action"], g_act["action"]}) in _OPPOSITE_PAIRS

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
        else:
            # Check allocation % difference
            c_pct = c_alloc.get(ticker, 0.0)
            g_pct = g_alloc.get(ticker, 0.0)
            pct_diff = abs(c_pct - g_pct)
            if pct_diff >= alloc_diff_threshold:
                reasons.append(
                    f"{ticker} 비중 차이: Claude {c_pct:.1f}% vs GPT {g_pct:.1f}% (diff={pct_diff:.1f}%)"
                )
                action_conflicts.append({
                    "ticker": ticker,
                    "type": "allocation",
                    "claude": {**c_act, "alloc_pct": round(c_pct, 1)},
                    "gpt": {**g_act, "alloc_pct": round(g_pct, 1)},
                })

    agreed = len(reasons) == 0

    return ConflictResult(
        agreed=agreed,
        conflict_reasons=reasons,
        action_conflicts=action_conflicts,
        confidence_gap=conf_gap,
        cash_conflict=cash_conflict,
    )
