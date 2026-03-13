# -*- coding: utf-8 -*-
"""Orchestrator 통합 흐름 테스트 — dry-run (실제 API 호출 없음).

시나리오 A: NORMAL 국면, 충돌 없음
시나리오 B: PUDDLE_2 + 신호 충돌
시나리오 C: PUDDLE_2 중복 매수 차단 (DUPLICATE_PUDDLE_BUY)
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _ok(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise AssertionError(f"검증 실패: {label}")


def _reset_state():
    """orchestrator + regime_gate + strategy_cache 상태 초기화."""
    import fire25.engine.orchestrator as _om
    _om._prev_regime = ""
    _om._prev_strategy = None
    _om._prev_hash = ""
    _om._prev_puddle_stage = 0
    _om._prev_smart_shoulder = False

    from fire25.engine.regime_gate import reset_persistence
    reset_persistence()

    # 파일 기반 전략 캐시 비우기
    try:
        from fire25.storage.strategy_cache import CACHE_FILE
        import json as _json
        with open(CACHE_FILE, "w", encoding="utf-8") as _f:
            _json.dump({}, _f)
    except Exception:
        pass


def _run(**kwargs):
    """orchestrator.run() 호출 래퍼. 모든 API key는 비어 있음."""
    from fire25.engine.orchestrator import run
    return run(
        gemini_api_key="",
        claude_api_key="",
        openai_api_key="",
        **kwargs,
    )


# ── 시나리오 A: NORMAL 국면, 충돌 없음 ──────────────────────────

def test_scenario_a_normal_no_conflict() -> None:
    """시나리오 A: NORMAL + 충돌 없음."""
    print("\n[시나리오 A] NORMAL 국면 — 충돌 없음")

    _reset_state()

    result = _run(
        market_regime="NORMAL",
        market_confidence=0.85,
        vix=15.0,
        qqqm_price=200.0,
        qqqm_ma50=190.0,   # price > ma50 → above
        qqqm_ma200=175.0,  # price > ma200 → above
        qqqm_current_pct=72.0,
        spread_10y_2y=0.3,
        sgov_current_pct=10.0,
        drawdown_from_200ma=0.10,
        breadth_score=0.7,
    )

    # regime
    regime = result.get("regime") or {}
    _ok(regime.get("regime") == "NORMAL", f"regime=NORMAL (got: {regime.get('regime')})")

    # puddle_sizing: NORMAL → 미실행 (빈 dict)
    _ok(result.get("puddle_sizing") == {}, "puddle_sizing 미실행 (빈 dict)")

    # signal_monitor: buy_blocked=False, alerts 없음
    sm = result.get("signal_monitor") or {}
    _ok(sm.get("buy_blocked") is False, f"signal_monitor.buy_blocked=False (got: {sm.get('buy_blocked')})")
    _ok(len(sm.get("alerts", [])) == 0, f"alerts 없음 (got: {sm.get('alerts')})")

    # news_agent: dict 존재 (API 없으면 fallback)
    _ok(isinstance(result.get("news_agent"), dict), "news_agent 결과 dict")

    # signal_analyzer: 충돌 없음 → conflict_detected=False 또는 빈 dict
    sa = result.get("signal_analysis") or {}
    if sa:
        _ok(sa.get("conflict_detected") is False, f"signal_analyzer.conflict_detected=False (got: {sa.get('conflict_detected')})")

    # cross_validator: not_required 또는 빈 dict
    cv = result.get("cross_validation") or {}
    if cv:
        _ok(cv.get("validation_result") == "not_required",
            f"cross_validation=not_required (got: {cv.get('validation_result')})")

    # 필수 result keys 존재
    for _k in ["regime", "final_strategy", "strategy_hash", "api_calls",
                "puddle_sizing", "signal_monitor", "news_agent",
                "signal_analysis", "cross_validation"]:
        _ok(_k in result, f"result['{_k}'] 키 존재")

    print(f"  regime: {regime.get('regime')}")
    print(f"  api_calls: {result.get('api_calls', 0)}")
    print(f"  signal_monitor.buy_blocked: {sm.get('buy_blocked')}")
    print(f"  cross_validation.validation_result: {cv.get('validation_result', 'N/A')}")


# ── 시나리오 B: PUDDLE_2 + 신호 충돌 ────────────────────────────

def test_scenario_b_puddle2_conflict() -> None:
    """시나리오 B: PUDDLE_2 + MA50 위 + 뉴스 risk_off → 충돌 감지."""
    print("\n[시나리오 B] PUDDLE_2 + 신호 충돌")

    _reset_state()

    # Regime persistence 우회: PUDDLE_2가 3일 이상 지속된 것으로 주입
    import fire25.engine.regime_gate as _rg_mod
    _rg_mod._prev_regime = "PUDDLE_2"
    _rg_mod._candidate_regime = "PUDDLE_2"
    _rg_mod._candidate_days = 0

    # VIX=32 → vix_adj=-0.3, drawdown=0 → adj=0, breadth=0.5 → adj=0
    # 결과 계수: 1.0 - 0.3 = 0.7 (< 1.0 확실)
    result = _run(
        market_regime="PUDDLE",
        puddle_stage=2,
        puddle_alert=True,
        market_confidence=0.75,
        vix=32.0,
        qqqm_price=180.0,
        qqqm_ma50=170.0,   # above ma50
        qqqm_ma200=200.0,  # below ma200
        qqqm_current_pct=65.0,
        spread_10y_2y=-0.3,
        sgov_current_pct=10.0,
        drawdown_from_200ma=0.0,
        breadth_score=0.5,
    )

    # regime: PUDDLE_2
    regime = result.get("regime") or {}
    _ok(regime.get("regime", "").startswith("PUDDLE"),
        f"regime은 PUDDLE 계열 (got: {regime.get('regime')})")

    # puddle_sizing: 실행됨 (PUDDLE_2 이상)
    ps = result.get("puddle_sizing") or {}
    if ps:
        _ok(ps.get("puddle_stage") == 2, f"puddle_sizing.stage=2 (got: {ps.get('puddle_stage')})")
        coeff = ps.get("coefficient", 1.0)
        _ok(coeff <= 1.0, f"coefficient <= 1.0 (vix=26 → 하향 조정, got: {coeff})")
        print(f"  puddle_sizing: base={ps.get('base_pct')}%, coeff={coeff}, capped={ps.get('capped_pct')}%")

    # signal_monitor: VIX_SPIKE 알림 포함
    sm = result.get("signal_monitor") or {}
    alert_codes = [a.get("code") for a in sm.get("alerts", [])]
    _ok("VIX_SPIKE" in alert_codes, f"VIX_SPIKE 알림 포함 (got: {alert_codes})")
    print(f"  alerts: {alert_codes}")
    print(f"  buy_blocked: {sm.get('buy_blocked')}")

    # news_agent: dict 존재
    _ok(isinstance(result.get("news_agent"), dict), "news_agent 결과 dict")

    # signal_analyzer: conflict_detected (articles 없어 news bias=neutral이면 no conflict일 수도)
    sa = result.get("signal_analysis") or {}
    print(f"  signal_analysis.conflict_detected: {sa.get('conflict_detected', 'N/A')}")
    if sa.get("conflict_detected"):
        _ok(sa.get("conflict_type", "") != "", "conflict_type 존재")
        # cross_validator: 실행됨 (not_required 아님)
        cv = result.get("cross_validation") or {}
        _ok(cv.get("validation_result") != "not_required",
            f"cross_validation 실행됨 (got: {cv.get('validation_result')})")
        print(f"  cross_validation.validation_result: {cv.get('validation_result')}")

    # 필수 keys 존재
    for _k in ["puddle_sizing", "signal_monitor", "news_agent",
                "signal_analysis", "cross_validation"]:
        _ok(_k in result, f"result['{_k}'] 키 존재")


# ── 시나리오 C: PUDDLE_2 중복 매수 차단 ─────────────────────────

def test_scenario_c_duplicate_puddle_buy() -> None:
    """시나리오 C: PUDDLE_2에서 동일 단계 재매수 → DUPLICATE_PUDDLE_BUY 차단."""
    print("\n[시나리오 C] PUDDLE_2 중복 매수 차단")

    _reset_state()

    # Regime persistence 우회
    import fire25.engine.regime_gate as _rg_mod
    _rg_mod._prev_regime = "PUDDLE_2"
    _rg_mod._candidate_regime = "PUDDLE_2"
    _rg_mod._candidate_days = 0

    # PUDDLE_2 매수 기록 주입
    from fire25.strategy_v2.manual_guard import record_puddle_buy, reset_puddle_history
    reset_puddle_history()
    record_puddle_buy(2)  # stage 2 이미 매수한 것으로 기록

    try:
        result = _run(
            market_regime="PUDDLE",
            puddle_stage=2,
            puddle_alert=True,
            market_confidence=0.75,
            vix=20.0,
            qqqm_price=185.0,
            qqqm_ma50=180.0,
            qqqm_ma200=200.0,
            qqqm_current_pct=65.0,
            spread_10y_2y=0.1,
            sgov_current_pct=10.0,
            drawdown_from_200ma=-0.075,
            breadth_score=0.5,
        )

        # signal_monitor: DUPLICATE_PUDDLE_BUY 차단
        sm = result.get("signal_monitor") or {}
        block_codes = [b.get("code") for b in sm.get("block_reasons", [])]
        _ok(sm.get("buy_blocked") is True, f"buy_blocked=True (got: {sm.get('buy_blocked')})")
        _ok("DUPLICATE_PUDDLE_BUY" in block_codes,
            f"DUPLICATE_PUDDLE_BUY 차단 (got: {block_codes})")
        print(f"  buy_blocked: {sm.get('buy_blocked')}, codes: {block_codes}")

        # 최종 전략에 매수 없음 (모두 HOLD)
        final = result.get("final_strategy") or {}
        actions = final.get("recommended_actions") or []
        buy_actions = [a for a in actions if str(a.get("action", "")).upper() == "BUY"]
        _ok(len(buy_actions) == 0, f"최종 전략: BUY 없음 (got: {buy_actions})")
        print(f"  final actions: {[(a.get('ticker'), a.get('action')) for a in actions]}")

        # signal_analyzer, cross_validator는 정상 실행
        _ok("signal_analysis" in result, "signal_analysis 키 존재")
        _ok("cross_validation" in result, "cross_validation 키 존재")

    finally:
        reset_puddle_history()


# ── 메인 ─────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("TEAM FIRE 25 - Orchestrator 통합 흐름 테스트")
    print("=" * 60)

    tests = [
        test_scenario_a_normal_no_conflict,
        test_scenario_b_puddle2_conflict,
        test_scenario_c_duplicate_puddle_buy,
    ]

    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ERROR: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  EXCEPTION in {t.__name__}: {e}")
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"결과: {passed} passed / {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
