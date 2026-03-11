# -*- coding: utf-8 -*-
"""Orchestrator — TEAM FIRE 25 AI 시스템 핵심 흐름 제어.

전략 일관성 강화 설계:
  1. 시장 스냅샷 생성
  2. normalized decision_context 생성
  3. strategy_hash 생성
  4. 캐시 조회 (hit → 기존 전략 반환)
  5. Regime Lock 체크 (예외 조건 아니면 유지)
  6. Gemini 뉴스 수집
  7. Claude/GPT 독립 전략 생성
  8. Conflict Detection
  9. Discussion (충돌 시)
  10. Manual Guard
  11. Strategy Stabilizer
  12. 전략 + strategy_hash 캐시 저장

기본 3콜, 충돌 시 5콜, 캐시 hit 시 0콜.
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
from fire25.ai.decision_context_builder import (
    build_decision_context,
    compute_strategy_hash,
    normalize_news,
)
from fire25.storage.strategy_cache import get_cached_strategy, store_strategy

# ── Module-level state for strategy consistency ──────────────────
_prev_regime: str = ""
_prev_strategy: dict[str, Any] | None = None
_prev_hash: str = ""
_prev_puddle_stage: int = 0
_prev_smart_shoulder: bool = False


def _regime_lock_exception(
    *,
    regime: str,
    prev_regime: str,
    puddle_stage: int,
    prev_puddle_stage: int,
    smart_shoulder_triggered: bool,
    prev_smart_shoulder: bool,
    guard_violations: list[str],
) -> str | None:
    """Regime unchanged인데도 전략을 새로 생성해야 하는 예외 조건 확인.

    Returns: 예외 사유 문자열 (None이면 예외 없음 → 기존 전략 유지).
    """
    # 1. Smart Shoulder 새로 발동
    if smart_shoulder_triggered and not prev_smart_shoulder:
        return "smart_shoulder_newly_triggered"

    # 2. PUDDLE deeper stage 진입
    if puddle_stage > prev_puddle_stage and puddle_stage >= 1:
        return f"puddle_deeper_stage_{prev_puddle_stage}_to_{puddle_stage}"

    # 3. Manual guard 위반 보정 필요
    if guard_violations:
        return "manual_guard_violation_correction"

    return None


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
    """Execute full AI orchestration pipeline with strategy consistency.

    Returns a comprehensive result dict with:
      - regime, gemini, claude_raw, gpt_raw, conflict, final_strategy
      - strategy_hash, cache_hit, regime_changed, reused_strategy
      - decision_context snapshot
    """
    global _prev_regime, _prev_strategy, _prev_hash
    global _prev_puddle_stage, _prev_smart_shoulder

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
        # 일관성 메타데이터
        "strategy_hash": "",
        "cache_hit": False,
        "regime_changed": True,
        "reused_strategy": False,
        "regime_lock_exception": None,
        "decision_context": None,
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

    regime_changed = (_prev_regime != "" and regime != _prev_regime) or _prev_regime == ""
    result["regime_changed"] = regime_changed

    # ── Step 2: Build normalized decision_context ────────────────
    _portfolio = portfolio or _default_portfolio()
    _macro = macro_context or {}
    _articles = articles or []

    nb_for_ctx = {}
    if isinstance(aggregated_signals, dict):
        nb_for_ctx["aggregated_signals"] = aggregated_signals
    if isinstance(theme_info, dict):
        nb_for_ctx["theme_info"] = theme_info

    decision_ctx = build_decision_context(
        portfolio=_portfolio,
        vix=vix,
        fear_greed=_macro.get("fear_greed"),
        qqqm_rsi=_macro.get("QQQM_RSI"),
        qqqm_sma200_gap=_macro.get("QQQM_SMA200_gap"),
        treasury_10y=_macro.get("10Y_treasury"),
        oil_price=_macro.get("oil_price"),
        regime=regime,
        defcon_active=defcon_triggered,
        puddle_stage=puddle_stage,
        smart_shoulder_triggered=smart_shoulder_triggered,
        macro_summary_text=_macro.get("macro_summary", ""),
        news_summary_text=news_summary,
        news_items=_articles,
        shock_events=_macro.get("shock_events"),
        risk_radar=_macro.get("risk_radar"),
    )
    result["decision_context"] = decision_ctx

    # ── Step 3: Compute strategy_hash ────────────────────────────
    strategy_hash = compute_strategy_hash(decision_ctx)
    result["strategy_hash"] = strategy_hash

    # ── Step 4: Cache lookup ─────────────────────────────────────
    cached = get_cached_strategy(strategy_hash)
    if cached:
        result["cache_hit"] = True
        result["reused_strategy"] = True
        result["strategy_consistency"] = "cache_hit"
        final = {
            **cached,
            "_source": "cache",
            "_consistency_note": f"동일 입력 캐시 재사용 (hash={strategy_hash})",
        }
        final["execution_plan"] = build_plan(
            strategy=final,
            portfolio=_portfolio,
            regime=regime,
        )
        result["final_strategy"] = final
        result["api_calls"] = 0
        return result

    # ── Step 5: Regime Lock 체크 ─────────────────────────────────
    if not regime_changed and _prev_strategy and _prev_hash:
        # Regime 미변경 — 예외 조건 확인
        lock_exception = _regime_lock_exception(
            regime=regime,
            prev_regime=_prev_regime,
            puddle_stage=puddle_stage,
            prev_puddle_stage=_prev_puddle_stage,
            smart_shoulder_triggered=smart_shoulder_triggered,
            prev_smart_shoulder=_prev_smart_shoulder,
            guard_violations=[],  # 아직 guard 실행 전이므로 빈 리스트
        )
        if lock_exception is None:
            # 예외 없음 → 이전 전략 유지
            result["strategy_consistency"] = "regime_lock"
            result["reused_strategy"] = True
            final = {
                **_prev_strategy,
                "_source": "regime_lock",
                "_consistency_note": "Regime 미변경 + 예외 없음 → 이전 전략 유지",
            }
            final["execution_plan"] = build_plan(
                strategy=final,
                portfolio=_portfolio,
                regime=regime,
            )
            result["final_strategy"] = final
            result["api_calls"] = 0
            return result
        else:
            result["regime_lock_exception"] = lock_exception

    # ── Step 5b: PUDDLE duplicate buy cooldown ───────────────────
    if regime.startswith("PUDDLE_"):
        try:
            stage = int(regime.split("_")[1])
        except (IndexError, ValueError):
            stage = 0
        if check_puddle_cooldown(stage):
            result["puddle_cooldown_blocked"] = True

    # ── Step 6: Gemini News ──────────────────────────────────────
    gemini_result = gemini_agent.run(
        articles=_articles,
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

    # ── Step 7: Claude + GPT independent strategies ──────────────
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

    # ── Step 8: Manual Guard check ───────────────────────────────
    claude_violations = manual_guard_validate(claude_result, regime, portfolio=_portfolio)
    gpt_violations = manual_guard_validate(gpt_result, regime, portfolio=_portfolio)
    result["guard_violations"] = {
        "claude": claude_violations,
        "gpt": gpt_violations,
    }

    # ── Step 9: Conflict Detection ───────────────────────────────
    conflict: ConflictResult = detect_conflict(
        claude_result, gpt_result, portfolio=_portfolio,
    )
    result["conflict"] = conflict.to_dict()

    # ── Step 10: Discussion if needed ────────────────────────────
    if conflict.agreed:
        c_conf = int(claude_result.get("confidence_score", 50))
        g_conf = int(gpt_result.get("confidence_score", 50))
        winner = claude_result if c_conf >= g_conf else gpt_result
        final = {**winner, "_source": "consensus"}
    else:
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

    # ── Step 11: Final Manual Guard pass ─────────────────────────
    final_violations = manual_guard_validate(final, regime, portfolio=_portfolio)
    if final_violations:
        final = _apply_guard_corrections(final, final_violations, regime)
    result["guard_violations"]["final"] = final_violations

    # ── Step 12: PUDDLE cooldown enforcement ─────────────────────
    if result["puddle_cooldown_blocked"]:
        _force_hold_buys(final)
        final["_puddle_cooldown_note"] = "동일 PUDDLE 단계 30일 쿨다운 → 매수 차단"

    # ── Step 13: Build execution plan ────────────────────────────
    final["execution_plan"] = build_plan(
        strategy=final,
        portfolio=_portfolio,
        regime=regime,
    )

    # ── Step 14: Record PUDDLE buy & save state ──────────────────
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

    # ── Step 15: Cache storage ───────────────────────────────────
    # 캐시에 저장할 클린 전략 (실행 계획은 포트폴리오 상태에 따라 달라지므로 제외)
    cache_strategy = {k: v for k, v in final.items() if k != "execution_plan"}
    store_strategy(strategy_hash, cache_strategy, decision_ctx)

    # ── Save module state ────────────────────────────────────────
    _prev_regime = regime
    _prev_strategy = final
    _prev_hash = strategy_hash
    _prev_puddle_stage = puddle_stage
    _prev_smart_shoulder = smart_shoulder_triggered

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
