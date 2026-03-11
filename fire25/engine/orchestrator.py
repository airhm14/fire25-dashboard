# -*- coding: utf-8 -*-
"""Orchestrator — TEAM FIRE 25 AI 시스템 핵심 흐름 제어.

흐름:
  1. 시장데이터/포트폴리오 수집 (외부에서 전달)
  2. regime_gate 실행 (persistence filter 포함)
  3. Gemini 뉴스 수집
  4. Claude/GPT 독립 전략 생성
  5. manual_guard로 매뉴얼 위반 여부 검사
  6. conflict_detector로 합의 여부 판정
  7. 충돌 시 discussion_engine 실행
  8. 전략 안정성 검증 (Strategy Stabilizer)
  9. 최종 전략 출력

기본 3콜, 충돌 시 5콜.
"""

from __future__ import annotations

import json
from typing import Any

from fire25.engine.regime_gate import classify as classify_regime, RegimeResult
from fire25.engine.conflict_detector import detect as detect_conflict, ConflictResult
from fire25.engine.discussion_engine import run_discussion
from fire25.strategy_v2.manual_guard import validate as manual_guard_validate
from fire25.strategy_v2.manual_guard import check_puddle_cooldown, record_puddle_buy
from fire25.strategy_v2.execution_plan import build_plan
from fire25.agents import gemini_agent, claude_agent, gpt_agent

# ── Module-level state for strategy consistency ──────────────────
_prev_regime: str = ""
_prev_strategy: dict[str, Any] | None = None


def run(
    *,
    # --- Signals (from existing pipeline) ---
    defcon_triggered: bool = False,
    puddle_stage: int = 0,
    puddle_alert: bool = False,
    smart_shoulder_triggered: bool = False,
    market_regime: str = "CORRECTION",
    market_confidence: float = 0.5,
    # --- Advanced regime inputs ---
    drawdown_pct: float = 0.0,
    vix: float = 20.0,
    sma50_slope: float = 0.0,
    # --- News data ---
    articles: list[dict] | None = None,
    aggregated_signals: dict | None = None,
    theme_info: dict | None = None,
    # --- Portfolio ---
    portfolio: dict | None = None,
    # --- Macro context ---
    macro_context: dict | None = None,
    news_summary: str = "",
    # --- API keys ---
    gemini_api_key: str = "",
    claude_api_key: str = "",
    openai_api_key: str = "",
    # --- Model overrides ---
    models_config: dict | None = None,
) -> dict[str, Any]:
    """Execute full AI orchestration pipeline.

    Returns a comprehensive result dict with:
      - regime: RegimeResult
      - gemini: News summary
      - claude_raw: Raw Claude strategy
      - gpt_raw: Raw GPT strategy
      - conflict: ConflictResult
      - final_strategy: Post-guard final strategy
      - discussion: Discussion metadata (if triggered)
      - api_calls: Number of API calls made
      - strategy_consistency: Whether previous strategy was maintained
    """
    global _prev_regime, _prev_strategy

    from fire25.ai.model_registry import get_model_name

    _gemini_model = get_model_name("gemini", models_config)
    _claude_model = get_model_name("claude", models_config)
    _gpt_model = get_model_name("openai", models_config)

    api_calls = 0
    result: dict[str, Any] = {
        "regime": None,
        "gemini": None,
        "claude_raw": None,
        "gpt_raw": None,
        "conflict": None,
        "final_strategy": None,
        "discussion": None,
        "guard_violations": [],
        "api_calls": 0,
        "strategy_consistency": None,
        "puddle_cooldown_blocked": False,
    }

    # ── Step 1: Regime Gate (with persistence filter) ────────────
    regime_result: RegimeResult = classify_regime(
        defcon_triggered=defcon_triggered,
        puddle_stage=puddle_stage,
        puddle_alert=puddle_alert,
        smart_shoulder_triggered=smart_shoulder_triggered,
        market_regime=market_regime,
        market_confidence=market_confidence,
        drawdown_pct=drawdown_pct,
        vix=vix,
        sma50_slope=sma50_slope,
    )
    result["regime"] = regime_result.to_dict()
    regime = regime_result.regime

    # ── Step 1b: Strategy consistency check ──────────────────────
    if _prev_regime and regime == _prev_regime and _prev_strategy:
        result["strategy_consistency"] = "regime_unchanged"
        # If regime hasn't changed, return previous strategy (일관성)
        final = {**_prev_strategy, "_source": "consistency", "_consistency_note": "Regime 미변경 → 이전 전략 유지"}
        final["execution_plan"] = build_plan(
            strategy=final,
            portfolio=portfolio or _default_portfolio(),
            regime=regime,
        )
        result["final_strategy"] = final
        result["api_calls"] = 0
        return result

    # ── Step 1c: PUDDLE duplicate buy cooldown ───────────────────
    if regime.startswith("PUDDLE_"):
        try:
            stage = int(regime.split("_")[1])
        except (IndexError, ValueError):
            stage = 0
        if check_puddle_cooldown(stage):
            result["puddle_cooldown_blocked"] = True

    # ── Step 2: Gemini News ──────────────────────────────────────
    gemini_result = gemini_agent.run(
        articles=articles or [],
        aggregated_signals=aggregated_signals or {},
        theme_info=theme_info or {},
        api_key=gemini_api_key,
        model=_gemini_model,
    )
    api_calls += 1
    result["gemini"] = gemini_result

    # Enrich news summary
    _news_for_strategy = news_summary
    if gemini_result.get("_source") == "gemini":
        _news_for_strategy = gemini_result.get("headline_summary", "") or news_summary

    # ── Step 3: Claude + GPT independent strategies ──────────────
    _portfolio = portfolio or _default_portfolio()
    _macro = macro_context or {}

    claude_result = claude_agent.run(
        regime=regime,
        portfolio=_portfolio,
        macro_context=_macro,
        news_summary=_news_for_strategy,
        api_key=claude_api_key,
        model=_claude_model,
    )
    api_calls += 1
    result["claude_raw"] = claude_result

    gpt_result = gpt_agent.run(
        regime=regime,
        portfolio=_portfolio,
        macro_context=_macro,
        news_summary=_news_for_strategy,
        api_key=openai_api_key,
        model=_gpt_model,
    )
    api_calls += 1
    result["gpt_raw"] = gpt_result

    # ── Step 4: Manual Guard check ───────────────────────────────
    claude_violations = manual_guard_validate(claude_result, regime, portfolio=_portfolio)
    gpt_violations = manual_guard_validate(gpt_result, regime, portfolio=_portfolio)
    result["guard_violations"] = {
        "claude": claude_violations,
        "gpt": gpt_violations,
    }

    # ── Step 5: Conflict Detection (with portfolio context) ──────
    conflict: ConflictResult = detect_conflict(
        claude_result, gpt_result, portfolio=_portfolio,
    )
    result["conflict"] = conflict.to_dict()

    # ── Step 6: Discussion if needed ─────────────────────────────
    if conflict.agreed:
        # Immediate consensus — use higher-confidence strategy
        c_conf = int(claude_result.get("confidence_score", 50))
        g_conf = int(gpt_result.get("confidence_score", 50))
        winner = claude_result if c_conf >= g_conf else gpt_result
        final = {**winner, "_source": "consensus"}
    else:
        # Discussion round (+2 API calls)
        final = run_discussion(
            regime=regime,
            claude_strategy=claude_result,
            gpt_strategy=gpt_result,
            conflict_reasons=conflict.conflict_reasons,
            claude_api_key=claude_api_key,
            openai_api_key=openai_api_key,
            claude_model=_claude_model,
            gpt_model=_gpt_model,
        )
        api_calls += 2
        result["discussion"] = final.get("_discussion")

    # ── Step 7: Final Manual Guard pass ──────────────────────────
    final_violations = manual_guard_validate(final, regime, portfolio=_portfolio)
    if final_violations:
        final = _apply_guard_corrections(final, final_violations, regime)
    result["guard_violations"]["final"] = final_violations

    # ── Step 8: PUDDLE cooldown enforcement ──────────────────────
    if result["puddle_cooldown_blocked"]:
        _force_hold_buys(final)
        final["_puddle_cooldown_note"] = "동일 PUDDLE 단계 30일 쿨다운 → 매수 차단"

    # ── Step 9: Build execution plan ─────────────────────────────
    final["execution_plan"] = build_plan(
        strategy=final,
        portfolio=_portfolio,
        regime=regime,
    )

    # ── Step 10: Record PUDDLE buy & save state ──────────────────
    if regime.startswith("PUDDLE_") and not result["puddle_cooldown_blocked"]:
        has_buys = any(
            str(a.get("action", "")).upper() == "BUY" and int(a.get("amount", 0)) > 0
            for a in final.get("recommended_actions", [])
        )
        if has_buys:
            try:
                stage = int(regime.split("_")[1])
                record_puddle_buy(stage)
            except (IndexError, ValueError):
                pass

    _prev_regime = regime
    _prev_strategy = final
    result["final_strategy"] = final
    result["api_calls"] = api_calls

    return result


def _force_hold_buys(strategy: dict) -> None:
    """Convert all BUY actions to HOLD (for cooldown enforcement)."""
    for act in strategy.get("recommended_actions", []):
        if str(act.get("action", "")).upper() == "BUY":
            act["action"] = "HOLD"
            act["amount"] = 0


def _default_portfolio() -> dict:
    """Default portfolio structure when none provided."""
    return {
        "positions": [
            {"ticker": "QQQM", "shares": 0},
            {"ticker": "SCHD", "shares": 0},
            {"ticker": "IAU", "shares": 0},
            {"ticker": "SGOV", "shares": 0},
        ],
        "cash": 0,
    }


def _apply_guard_corrections(
    strategy: dict, violations: list[str], regime: str,
) -> dict:
    """Apply conservative corrections for manual guard violations."""
    corrected = dict(strategy)
    # Force all actions to HOLD when violations exist
    corrected["recommended_actions"] = [
        {"ticker": "QQQM", "action": "HOLD", "amount": 0},
        {"ticker": "SCHD", "action": "HOLD", "amount": 0},
        {"ticker": "IAU", "action": "HOLD", "amount": 0},
        {"ticker": "SGOV", "action": "HOLD", "amount": 0},
    ]
    corrected["cash_action"] = "KEEP"
    corrected["_guard_corrected"] = True
    corrected["_guard_violations"] = violations
    corrected["strategy_reason"] = (
        corrected.get("strategy_reason", "") +
        f" [매뉴얼 가드 발동: {', '.join(violations)}]"
    )
    return corrected
