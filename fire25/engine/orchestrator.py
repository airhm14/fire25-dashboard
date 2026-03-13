# -*- coding: utf-8 -*-
"""Orchestrator — TEAM FIRE 25 AI 시스템 핵심 흐름 제어.

전략 일관성 강화 설계:
  1. 시장 스냅샷 생성
  2. normalized decision_context 생성
  3. strategy_hash 생성
  4. 캐시 조회 (hit → 기존 전략 반환)
  5. Regime Lock 체크 (예외 조건 아니면 유지)
  5c. PUDDLE 동적 비중 산출
  5d. 조기 경보 신호 판정
  6a. Gemini 뉴스 수집
  6b. News Agent digest 생성
  6c. Signal Conflict Analyzer (Claude 해석)
  6d. Cross Validator (o1 교차 검증)
  7. 최종 전략 구성 (signal_analyzer 기반)
  8. Manual Guard
  9. 전략 + strategy_hash 캐시 저장
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fire25.engine.regime_gate import classify as classify_regime, RegimeResult
from fire25.strategy_v2.manual_guard import validate as manual_guard_validate
from fire25.strategy_v2.manual_guard import (
    check_puddle_cooldown,
    record_puddle_buy,
    get_last_puddle_buy_stage,
    get_puddle_remaining_days,
)
from fire25.engine.puddle_sizing import compute_puddle_sizing
from fire25.engine.signal_monitor import evaluate_signals
from fire25.agents.news_agent import run as news_agent_run
from fire25.agents.signal_analyzer import analyze as signal_analyzer_analyze
from fire25.agents.cross_validator import validate as cross_validator_validate
from fire25.strategy_v2.execution_plan import build_plan
from fire25.agents import gemini_agent
from fire25.ai.decision_context_builder import (
    build_decision_context,
    compute_strategy_hash,
    normalize_news,
)
from fire25.storage.strategy_cache import get_cached_strategy, store_strategy
from fire25.macro_event_builder import build_macro_events
from fire25.macro_summary_engine import generate_macro_summary

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
    drawdown_from_200ma: float = 0.0,
    vix: float = 20.0,
    sma50_slope: float = 0.0,
    breadth_score: float = 0.5,
    # --- Signal monitor inputs ---
    qqqm_price: float = 0.0,
    qqqm_ma50: float = 0.0,
    qqqm_ma200: float = 0.0,
    qqqm_current_pct: float = 0.0,
    qqqm_after_buy_pct: float | None = None,
    spread_10y_2y: float = 0.0,
    sgov_current_pct: float = 0.0,
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
      - regime, gemini, final_strategy
      - signal_analysis, cross_validation
      - strategy_hash, cache_hit, regime_changed, reused_strategy
      - decision_context snapshot
    """
    global _prev_regime, _prev_strategy, _prev_hash
    global _prev_puddle_stage, _prev_smart_shoulder

    from fire25.ai.model_registry import get_model_name

    _gemini_model = get_model_name("gemini", models_config)

    api_calls = 0
    result: dict[str, Any] = {
        "regime": None,
        "gemini": None,
        "final_strategy": None,
        "guard_violations": {"final": []},
        "api_calls": 0,
        "strategy_consistency": None,
        "puddle_cooldown_blocked": False,
        "puddle_sizing": {},
        "signal_monitor": {},
        # 일관성 메타데이터
        "strategy_hash": "",
        "cache_hit": False,
        "regime_changed": True,
        "reused_strategy": False,
        "regime_lock_exception": None,
        "decision_context": None,
        "news_snapshot": None,
        "macro_events": [],
        "macro_summary": {},
        "news_agent": {},
        "signal_analysis": {},
        "cross_validation": {},
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

    # ── Step 2b: Macro intelligence pipeline (v2) ────────────────
    # Use passed-in enriched articles if available; otherwise fetch via v2.
    # Articles are considered enriched when they carry an impact_score field.
    _enriched_for_macro = _articles
    _articles_are_enriched = _articles and any(
        a.get("impact_score") is not None for a in _articles[:3]
    )
    if not _articles_are_enriched:
        try:
            from fire25.news_engine_v2 import get_enriched_articles as _get_v2
            _enriched_for_macro = _get_v2() or _articles
        except Exception:
            _enriched_for_macro = _articles

    _macro_events: list[dict] = []
    _macro_summary: dict = {}
    try:
        _macro_events = build_macro_events(_enriched_for_macro)
        _macro_summary = generate_macro_summary(_macro_events)
    except Exception:
        pass

    result["macro_events"] = _macro_events
    result["macro_summary"] = _macro_summary

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
        macro_events=_macro_events,
        macro_summary=_macro_summary,
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

    # ── Step 5c: PUDDLE 동적 비중 계수 산출 ──────────────────────
    if regime.startswith("PUDDLE_") and regime_result.puddle_stage >= 2:
        _puddle_sizing = compute_puddle_sizing(
            puddle_stage=regime_result.puddle_stage,
            vix=vix,
            drawdown_from_200ma=drawdown_from_200ma,
            breadth_score=breadth_score,
        )
        result["puddle_sizing"] = _puddle_sizing

    # ── Step 5d: 조기 경보 신호 판정 ─────────────────────────────
    _last_puddle_buy_stage = get_last_puddle_buy_stage()
    _cooldown_remaining = 0
    if regime.startswith("PUDDLE_"):
        try:
            _stage = int(regime.split("_")[1])
            _cooldown_remaining = get_puddle_remaining_days(_stage)
        except (IndexError, ValueError):
            pass

    _signal_result = evaluate_signals(
        qqqm_price=qqqm_price,
        qqqm_ma50=qqqm_ma50,
        qqqm_ma200=qqqm_ma200,
        qqqm_current_pct=qqqm_current_pct,
        qqqm_after_buy_pct=qqqm_after_buy_pct,
        vix=vix,
        spread_10y_2y=spread_10y_2y,
        sgov_current_pct=sgov_current_pct,
        regime=regime,
        puddle_stage=regime_result.puddle_stage if regime_result.puddle_stage > 0 else None,
        last_puddle_buy_stage=_last_puddle_buy_stage,
        cooldown_remaining_days=_cooldown_remaining,
    )
    result["signal_monitor"] = _signal_result

    # ── Step 6: Gemini News → 구조화 이벤트 추출 + Snapshot ─────
    gemini_result = gemini_agent.run(
        articles=_articles,
        aggregated_signals=aggregated_signals or {},
        theme_info=theme_info or {},
        api_key=gemini_api_key,
        model=_gemini_model,
    )
    api_calls += 1
    result["gemini"] = gemini_result

    # News Snapshot 추출 (Gemini 결과에서)
    _news_snapshot = gemini_result.get("news_snapshot") or {}
    result["news_snapshot"] = _news_snapshot

    # decision_context에 snapshot 반영 (해시 안정성 강화)
    decision_ctx["news_snapshot"] = _news_snapshot
    strategy_hash = compute_strategy_hash(decision_ctx)
    result["strategy_hash"] = strategy_hash

    # ── Step 6b: News Agent → digest 생성 ────────────────────────
    _news_agent_items = _to_news_agent_items(_articles)
    if _news_agent_items:
        try:
            _news_agent_result = news_agent_run(
                _news_agent_items,
                api_key=gemini_api_key,
            )
            result["news_agent"] = _news_agent_result
        except Exception:
            result["news_agent"] = {}

    # ── Step 6c: Signal Conflict Analyzer ────────────────────────
    _na = result["news_agent"]
    _na_macro = _na.get("macro_summary") or {}
    _na_asset_bias = _na_macro.get("asset_bias") or {}
    _sa_payload = {
        "regime": regime,
        "puddle_stage": regime_result.puddle_stage,
        "signals": {
            "technical": {
                "vix": vix,
                "qqqm_vs_ma50": "above" if qqqm_price >= qqqm_ma50 else "below",
                "qqqm_vs_ma200": "above" if qqqm_price >= qqqm_ma200 else "below",
            },
            "macro": {
                "macro_bias": _macro_summary.get("macro_bias", "neutral"),
            },
            "news": {
                "macro_bias": _na_macro.get("macro_bias", "neutral"),
                "asset_bias_qqqm": int(_na_asset_bias.get("QQQM", 0)),
                "one_line_summary": (_na.get("digest") or {}).get("one_line_summary", ""),
            },
        },
        "active_blocks": [r["code"] for r in _signal_result.get("block_reasons", [])],
        "active_alerts": [a["code"] for a in _signal_result.get("alerts", [])],
    }
    try:
        result["signal_analysis"] = signal_analyzer_analyze(
            _sa_payload,
            api_key=claude_api_key,
        )
    except Exception:
        result["signal_analysis"] = {}

    # ── Step 6d: Cross Validator (o1 교차 검증) ──────────────────
    _sa_result = result["signal_analysis"]
    _cv_conflict = bool(_sa_result.get("conflict_detected", False))
    _cv_payload = {
        "regime": regime,
        "signals": _sa_payload.get("signals", {}),
        "puddle_sizing": result["puddle_sizing"] or None,
        "active_blocks": _sa_payload.get("active_blocks", []),
        "active_alerts": _sa_payload.get("active_alerts", []),
        "claude_analysis": (_sa_result.get("claude_analysis") or {}),
    }
    try:
        result["cross_validation"] = cross_validator_validate(
            _cv_payload,
            conflict_detected=_cv_conflict,
            api_key=openai_api_key,
        )
    except Exception:
        result["cross_validation"] = {}

    # ── Step 7: 최종 전략 구성 (signal_analyzer 기반) ─────────────
    _sa_result = result["signal_analysis"]
    _cv_result = result["cross_validation"]
    _sa_cl = _sa_result.get("claude_analysis") or {}
    _market_view = (
        _sa_cl.get("situation_summary")
        or f"Regime: {regime} — 신호 분석 기반 전략"
    )
    _strategy_reason = _sa_cl.get("key_risk") or ""
    _cash_action = {
        "NORMAL": "KEEP",
        "DEFCON": "INCREASE",
        "SMART_SHOULDER": "KEEP",
    }.get(regime, "DEPLOY" if regime.startswith("PUDDLE_") else "KEEP")
    _cv_vr = (_cv_result.get("validation_result") or "")
    _conf_raw = (
        _cv_result.get("confidence_score")
        if _cv_vr not in ("not_required", "")
        else _sa_result.get("confidence_score")
    )
    _conf_score = int(_conf_raw) if _conf_raw is not None else 50

    final: dict[str, Any] = {
        "_source": "signal_analyzer",
        "market_view": _market_view,
        "strategy_reason": _strategy_reason,
        "cash_action": _cash_action,
        "confidence_score": _conf_score,
        "recommended_actions": [
            {"ticker": "QQQM", "action": "HOLD", "amount": 0},
            {"ticker": "SCHD", "action": "HOLD", "amount": 0},
            {"ticker": "IAU", "action": "HOLD", "amount": 0},
            {"ticker": "SGOV", "action": "HOLD", "amount": 0},
        ],
    }

    # ── Step 8: Final Manual Guard pass ──────────────────────────
    final_violations = manual_guard_validate(final, regime, portfolio=_portfolio)
    if final_violations:
        final = _apply_guard_corrections(final, final_violations, regime)
    result["guard_violations"]["final"] = final_violations

    # ── Step 12: PUDDLE cooldown enforcement ─────────────────────
    if result["puddle_cooldown_blocked"]:
        _force_hold_buys(final)
        final["_puddle_cooldown_note"] = "동일 PUDDLE 단계 30일 쿨다운 → 매수 차단"

    # ── Step 12b: Signal monitor buy block enforcement ────────────
    if _signal_result.get("buy_blocked") and not result["puddle_cooldown_blocked"]:
        _force_hold_buys(final)
        codes = [r["code"] for r in _signal_result.get("block_reasons", [])]
        final["_signal_monitor_note"] = f"조기 경보 차단: {', '.join(codes)}"

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


def _to_news_agent_items(articles: list[dict]) -> list[dict]:
    """orchestrator 기사 포맷 → news_agent 입력 포맷 변환.

    news_engine 포맷 (title/source/published/summary/link) →
    news_agent 포맷 (id/title/source/date/content).
    """
    items: list[dict] = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        _link = a.get("link") or ""
        _id = _link or hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
        _date = (a.get("published") or "")[:10]  # YYYY-MM-DD
        _content = a.get("summary") or a.get("content") or ""
        items.append({
            "id": _id,
            "title": title,
            "source": a.get("source") or "",
            "date": _date,
            "content": _content,
        })
    return items


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
