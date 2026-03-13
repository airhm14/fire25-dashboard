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
  - QQQM 핵심자산 규칙 (default=HOLD, 매도는 구조적 리스크만)
  - QQQM 비중 캡 (80%)
  - 포트폴리오 편차 한도 (QQQM ±5%, SCHD ±3%, IAU ±2%)
  - 전략 안정성 규칙

[AI 판단 허용]
  - 웅덩이 투입 비율 조정 (±)
  - DEFCON 보수도 강도
  - 신규 자금 배분 강약
  - 리밸런싱 우선순위
  - 현금 유지 vs 추가 투입
"""

from __future__ import annotations

from typing import Any

# ── 허용 종목/액션 ──────────────────────────────────────────────
ALLOWED_TICKERS = {"QQQM", "SCHD", "IAU", "SGOV"}
ALLOWED_ACTIONS = {"BUY", "HOLD", "REDUCE"}
ALLOWED_CASH_ACTIONS = {"KEEP", "DEPLOY", "INCREASE"}

# ── 목표 비중 & 편차 한도 ───────────────────────────────────────
TARGET_WEIGHTS: dict[str, float] = {"QQQM": 72, "SCHD": 16, "IAU": 2, "SGOV": 10}
DEVIATION_LIMITS: dict[str, float] = {"QQQM": 5, "SCHD": 3, "IAU": 2}

# ── QQQM 비중 캡 존 ─────────────────────────────────────────────
QQQM_CAP_MAX: float = 80.0
QQQM_ZONE_BUY_OK: float = 70.0       # ≤70% 추가 매수 가능
QQQM_ZONE_SMALL_BUY: float = 77.0    # 70~77% 소량 매수 허용
QQQM_ZONE_NO_BUY: float = 80.0       # 77~80% 신규 매수 금지

# ── 전략 안정성 한도 ─────────────────────────────────────────────
MAX_DAILY_WEIGHT_CHANGE: float = 5.0   # 일일 비중 변동 ≤5%
MIN_TRADE_PCT: float = 1.0            # 최소 거래 단위 ≥1%
SGOV_MAX_PCT: float = 20.0            # SGOV ≤20% (DEFCON 제외)
MAX_DAILY_CASH_USAGE: float = 25.0    # 일일 현금 사용 ≤25%

# ── PUDDLE 투입률 ────────────────────────────────────────────────
PUDDLE_DEPLOY_RATES: dict[int, float] = {1: 0, 2: 10, 3: 25, 4: 50}

# ── Regime별 금지 사항 ───────────────────────────────────────────
REGIME_RULES: dict[str, dict[str, Any]] = {
    "DEFCON": {
        "block_buy": ["QQQM", "SCHD", "IAU"],
        "force_cash": "INCREASE",
    },
    "SMART_SHOULDER": {
        "block_buy": ["QQQM"],
    },
}

# ── 구조적 리스크 키워드 (QQQM 매도 허용 조건) ──────────────────
STRUCTURAL_RISK_KEYWORDS = {
    "breadth_collapse", "ai_disruption", "semiconductor_disruption",
    "liquidity_shock", "credit_stress", "recession_declared",
}

# ── PUDDLE 중복 매수 방지 (모듈 레벨 상태) ──────────────────────
_puddle_buy_history: dict[int, float] = {}  # stage → timestamp


def _get_qqqm_weight_pct(portfolio: dict | None) -> float:
    """Calculate QQQM weight % from portfolio."""
    if not portfolio:
        return 0.0
    total_value = float(portfolio.get("cash", 0))
    qqqm_value = 0.0
    for pos in portfolio.get("positions", []):
        val = float(pos.get("shares", 0)) * float(pos.get("price", 0))
        total_value += val
        if pos.get("ticker") == "QQQM":
            qqqm_value = val
    return (qqqm_value / total_value * 100) if total_value > 0 else 0.0


def _get_ticker_weight_pct(portfolio: dict | None, ticker: str) -> float:
    """Calculate ticker weight % from portfolio."""
    if not portfolio:
        return 0.0
    total_value = float(portfolio.get("cash", 0))
    ticker_value = 0.0
    for pos in portfolio.get("positions", []):
        val = float(pos.get("shares", 0)) * float(pos.get("price", 0))
        total_value += val
        if pos.get("ticker") == ticker:
            ticker_value = val
    return (ticker_value / total_value * 100) if total_value > 0 else 0.0


def validate(
    strategy: dict[str, Any],
    regime: str,
    portfolio: dict[str, Any] | None = None,
    prev_strategy: dict[str, Any] | None = None,
) -> list[str]:
    """Validate strategy against manual rules. Returns list of violations."""
    violations: list[str] = []

    if not strategy or strategy.get("_source") == "fallback":
        return violations

    actions = strategy.get("recommended_actions", [])
    cash_action = str(strategy.get("cash_action", "KEEP")).upper()
    regime_upper = regime.upper() if regime else ""

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

    # --- Rule 6: QQQM Core Asset Rule ---
    for act in actions:
        ticker = str(act.get("ticker", "")).upper()
        action = str(act.get("action", "HOLD")).upper()
        if ticker == "QQQM" and action == "REDUCE":
            if regime_upper != "SMART_SHOULDER":
                risk_flags = strategy.get("_structural_risks", set())
                if not (risk_flags and STRUCTURAL_RISK_KEYWORDS & set(risk_flags)):
                    violations.append(
                        "QQQM 매도는 Smart Shoulder 또는 구조적 리스크에서만 허용"
                    )

    # --- Rule 7: QQQM Weight Cap Zones ---
    if portfolio:
        qqqm_pct = _get_qqqm_weight_pct(portfolio)
        for act in actions:
            ticker = str(act.get("ticker", "")).upper()
            action = str(act.get("action", "HOLD")).upper()
            if ticker == "QQQM" and action == "BUY":
                if qqqm_pct > QQQM_ZONE_NO_BUY:
                    violations.append(
                        f"QQQM 비중 {qqqm_pct:.1f}% > 80%: 반드시 비중 축소 필요, 매수 금지"
                    )
                elif qqqm_pct > QQQM_ZONE_SMALL_BUY:
                    violations.append(
                        f"QQQM 비중 {qqqm_pct:.1f}% (77~80% 존): 신규 매수 금지, 비중 하향 검토"
                    )
        if qqqm_pct > QQQM_CAP_MAX:
            has_reduce = any(
                str(a.get("ticker", "")).upper() == "QQQM"
                and str(a.get("action", "")).upper() == "REDUCE"
                for a in actions
            )
            if not has_reduce:
                violations.append(
                    f"QQQM 비중 {qqqm_pct:.1f}% > 80%: 비중 축소 미포함"
                )

    # --- Rule 8: Portfolio deviation limits ---
    if portfolio:
        for ticker, limit in DEVIATION_LIMITS.items():
            current_pct = _get_ticker_weight_pct(portfolio, ticker)
            target = TARGET_WEIGHTS.get(ticker, 0)
            deviation = abs(current_pct - target)
            # Only flag existing over-deviation combined with action that worsens it
            for act in actions:
                act_ticker = str(act.get("ticker", "")).upper()
                act_action = str(act.get("action", "HOLD")).upper()
                if act_ticker == ticker:
                    if deviation > limit and act_action == "BUY" and current_pct > target:
                        violations.append(
                            f"{ticker} 편차 {deviation:.1f}% > ±{limit}%: 추가 매수 시 편차 확대"
                        )
                    elif deviation > limit and act_action == "REDUCE" and current_pct < target:
                        violations.append(
                            f"{ticker} 편차 {deviation:.1f}% > ±{limit}%: 추가 매도 시 편차 확대"
                        )

    # --- Rule 9: SGOV cap ≤20% (DEFCON 제외) ---
    if portfolio and regime_upper != "DEFCON":
        sgov_pct = _get_ticker_weight_pct(portfolio, "SGOV")
        for act in actions:
            ticker = str(act.get("ticker", "")).upper()
            action = str(act.get("action", "HOLD")).upper()
            if ticker == "SGOV" and action == "BUY" and sgov_pct >= SGOV_MAX_PCT:
                violations.append(
                    f"SGOV 비중 {sgov_pct:.1f}% ≥ {SGOV_MAX_PCT}%: 추가 매수 금지 (DEFCON 제외)"
                )

    # --- Rule 10: PUDDLE rules ---
    if regime_upper.startswith("PUDDLE_"):
        # PUDDLE_1 = NO BUY (0%)
        stage = int(regime_upper.split("_")[1]) if "_" in regime_upper else 0
        if stage == 1:
            for act in actions:
                ticker = str(act.get("ticker", "")).upper()
                action = str(act.get("action", "HOLD")).upper()
                if action == "BUY" and ticker != "SGOV":
                    violations.append(
                        f"PUDDLE_1에서 {ticker} 매수 금지 (투입률 0% — 관망)"
                    )

        # 웅덩이에서 현금 증가(INCREASE)는 원칙 위반
        if cash_action == "INCREASE":
            violations.append(
                f"{regime} 모드에서 현금 증가(INCREASE)는 원칙 위반 — 투입 방향이어야 함"
            )

    # --- Rule 11: Strategy Stabilizer — minimum trade size ---
    if portfolio:
        total_value = float(portfolio.get("cash", 0))
        for pos in portfolio.get("positions", []):
            total_value += float(pos.get("shares", 0)) * float(pos.get("price", 0))
        if total_value > 0:
            for act in actions:
                ticker = str(act.get("ticker", "")).upper()
                action = str(act.get("action", "HOLD")).upper()
                amount = int(act.get("amount", 0))
                if action != "HOLD" and amount > 0:
                    price = 0.0
                    for pos in portfolio.get("positions", []):
                        if pos.get("ticker") == ticker:
                            price = float(pos.get("price", 0))
                    trade_pct = (amount * price / total_value * 100) if price > 0 else 0
                    if 0 < trade_pct < MIN_TRADE_PCT:
                        violations.append(
                            f"{ticker}: 거래 비중 {trade_pct:.2f}% < 최소 {MIN_TRADE_PCT}% — HOLD 처리 권고"
                        )

    return violations


def record_puddle_buy(stage: int) -> None:
    """Record a PUDDLE buy for duplicate prevention."""
    import time
    _puddle_buy_history[stage] = time.time()


def check_puddle_cooldown(stage: int, cooldown_days: int = 30) -> bool:
    """Check if PUDDLE stage is in cooldown. Returns True if blocked."""
    import time
    last_buy = _puddle_buy_history.get(stage)
    if last_buy is None:
        return False
    elapsed = time.time() - last_buy
    return elapsed < (cooldown_days * 86400)


def get_last_puddle_buy_stage() -> int | None:
    """Return the most recently bought PUDDLE stage, or None if no history."""
    if not _puddle_buy_history:
        return None
    return max(_puddle_buy_history.keys(), key=lambda s: _puddle_buy_history[s])


def get_puddle_remaining_days(stage: int, cooldown_days: int = 30) -> int:
    """Return remaining cooldown days for given PUDDLE stage.

    Args:
        stage: PUDDLE 단계.
        cooldown_days: 쿨다운 기간 (일). 기본 30일.

    Returns:
        잔여 일수. 쿨다운 미적용 시 0.
    """
    import time
    last_buy = _puddle_buy_history.get(stage)
    if last_buy is None:
        return 0
    elapsed_days = (time.time() - last_buy) / 86400
    remaining = cooldown_days - elapsed_days
    return max(0, int(remaining))


def reset_puddle_history() -> None:
    """Reset PUDDLE buy history (for testing)."""
    _puddle_buy_history.clear()
