# -*- coding: utf-8 -*-
"""PUDDLE sizing & signal_monitor 검증 테스트.

케이스 1: 정상 매수 허용 (VIX=18, drawdown=8%, breadth=0.6, PUDDLE_2)
케이스 2: VIX 급등 비중 하향 (VIX=32, drawdown=5%, breadth=0.4, PUDDLE_2)
케이스 3: 50일선 이탈 차단
케이스 4: 80% 상한 초과 차단
케이스 5: 동일 PUDDLE 중복 차단
케이스 6: 복합 알림 (VIX_SPIKE + YIELD_CURVE_STRESS + SGOV_CAP_WARNING)
"""

from __future__ import annotations

import sys
import os

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fire25.engine.puddle_sizing import compute_puddle_sizing
from fire25.engine.signal_monitor import evaluate_signals


def _ok(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise AssertionError(f"검증 실패: {label}")


def test_case1_normal_buy_allowed() -> None:
    """케이스 1: 정상 매수 허용 — 계수 > 1.0 예상."""
    print("\n[케이스 1] 정상 매수 허용")

    sizing = compute_puddle_sizing(
        puddle_stage=2,
        vix=18,
        drawdown_from_200ma=-0.08,
        breadth_score=0.6,
    )
    print(f"  sizing: {sizing}")

    _ok(sizing["puddle_stage"] == 2, "puddle_stage == 2")
    _ok(sizing["base_pct"] == 10.0, "base_pct == 10.0")
    _ok(sizing["coefficient"] > 1.0, f"coefficient {sizing['coefficient']} > 1.0")
    _ok(sizing["coefficient_breakdown"]["vix_adj"] == 0.2, "vix_adj == +0.2 (VIX<20)")
    _ok(sizing["coefficient_breakdown"]["drawdown_adj"] == 0.1, "drawdown_adj == +0.1 (5~10%)")
    _ok(sizing["coefficient_breakdown"]["breadth_adj"] == 0.1, "breadth_adj == +0.1 (>0.5)")

    signal = evaluate_signals(
        qqqm_price=480.0,
        qqqm_ma50=470.0,
        qqqm_ma200=450.0,
        qqqm_current_pct=65.0,
        vix=18,
        spread_10y_2y=0.2,
        sgov_current_pct=10.0,
        regime="PUDDLE_2",
        puddle_stage=2,
        last_puddle_buy_stage=None,
        cooldown_remaining_days=0,
    )
    print(f"  signal: {signal}")
    _ok(signal["buy_blocked"] is False, "buy_blocked == False")
    _ok(len(signal["block_reasons"]) == 0, "block_reasons 없음")


def test_case2_vix_spike_sizing_down() -> None:
    """케이스 2: VIX 급등으로 비중 하향 — 최소 캡 5% 적용 여부 확인."""
    print("\n[케이스 2] VIX 급등 비중 하향")

    sizing = compute_puddle_sizing(
        puddle_stage=2,
        vix=32,
        drawdown_from_200ma=-0.05,
        breadth_score=0.4,
    )
    print(f"  sizing: {sizing}")

    # vix_adj=-0.3, drawdown_adj=0.0 (4.9%<5%), breadth_adj=0.0 → coeff=0.7
    # adjusted_pct = 10 * 0.7 = 7.0 → within [5, 15] → cap_applied=False
    _ok(sizing["coefficient_breakdown"]["vix_adj"] == -0.3, "vix_adj == -0.3 (VIX≥30)")
    _ok(sizing["coefficient"] < 1.0, f"coefficient {sizing['coefficient']} < 1.0")
    _ok(sizing["capped_pct"] >= 5.0, f"capped_pct {sizing['capped_pct']} >= 5% (최소 캡)")
    _ok(sizing["capped_pct"] <= 15.0, f"capped_pct {sizing['capped_pct']} <= 15% (최대 캡)")

    # drawdown=5% → dd_abs=0.05 경계 확인 (0.05는 5%이므로 5%≤dd<10% → +0.1)
    sizing_bd = compute_puddle_sizing(
        puddle_stage=2,
        vix=32,
        drawdown_from_200ma=-0.055,  # 5.5%
        breadth_score=0.4,
    )
    print(f"  sizing (dd=5.5%): {sizing_bd}")
    _ok(sizing_bd["coefficient_breakdown"]["drawdown_adj"] == 0.1, "drawdown_adj == +0.1 at 5.5%")


def test_case3_ma50_break_blocked() -> None:
    """케이스 3: 50일선 이탈로 매수 차단."""
    print("\n[케이스 3] 50일선 이탈 차단")

    signal = evaluate_signals(
        qqqm_price=460.0,
        qqqm_ma50=470.0,      # price < ma50
        qqqm_ma200=450.0,
        qqqm_current_pct=65.0,
        vix=20,
        spread_10y_2y=0.1,
        sgov_current_pct=10.0,
        regime="PUDDLE_2",
        puddle_stage=2,
        last_puddle_buy_stage=None,
        cooldown_remaining_days=0,
    )
    print(f"  signal: {signal}")

    _ok(signal["buy_blocked"] is True, "buy_blocked == True")
    codes = [r["code"] for r in signal["block_reasons"]]
    _ok("QQQM_MA50_BREAK" in codes, "QQQM_MA50_BREAK 포함")


def test_case4_cap_violation_blocked() -> None:
    """케이스 4: 80% 상한 초과로 매수 차단."""
    print("\n[케이스 4] 80% 상한 초과 차단")

    signal = evaluate_signals(
        qqqm_price=480.0,
        qqqm_ma50=470.0,
        qqqm_ma200=450.0,
        qqqm_current_pct=78.0,
        qqqm_after_buy_pct=82.0,   # > 80
        vix=18,
        spread_10y_2y=0.1,
        sgov_current_pct=10.0,
        regime="PUDDLE_2",
        puddle_stage=2,
        last_puddle_buy_stage=None,
        cooldown_remaining_days=0,
    )
    print(f"  signal: {signal}")

    _ok(signal["buy_blocked"] is True, "buy_blocked == True")
    codes = [r["code"] for r in signal["block_reasons"]]
    _ok("QQQM_CAP_VIOLATION" in codes, "QQQM_CAP_VIOLATION 포함")


def test_case5_duplicate_puddle_blocked() -> None:
    """케이스 5: 동일 PUDDLE 단계 중복 매수 차단."""
    print("\n[케이스 5] 동일 PUDDLE 중복 차단")

    signal = evaluate_signals(
        qqqm_price=480.0,
        qqqm_ma50=470.0,
        qqqm_ma200=450.0,
        qqqm_current_pct=65.0,
        vix=18,
        spread_10y_2y=0.1,
        sgov_current_pct=10.0,
        regime="PUDDLE_2",
        puddle_stage=2,
        last_puddle_buy_stage=2,   # 동일 단계
        cooldown_remaining_days=0,
    )
    print(f"  signal: {signal}")

    _ok(signal["buy_blocked"] is True, "buy_blocked == True")
    codes = [r["code"] for r in signal["block_reasons"]]
    _ok("DUPLICATE_PUDDLE_BUY" in codes, "DUPLICATE_PUDDLE_BUY 포함")


def test_case6_compound_alerts() -> None:
    """케이스 6: 복합 알림 3개, 매수는 차단 없음."""
    print("\n[케이스 6] 복합 알림")

    signal = evaluate_signals(
        qqqm_price=480.0,
        qqqm_ma50=470.0,
        qqqm_ma200=460.0,      # price=480 < ma200*1.05=483 → VIX_SPIKE 조건 성립
        qqqm_current_pct=65.0,
        vix=22.0,              # ≥ 20
        spread_10y_2y=-0.6,    # < -0.5
        sgov_current_pct=19.0, # > 18.0
        regime="NORMAL",       # DEFCON 아님
        puddle_stage=None,
        last_puddle_buy_stage=None,
        cooldown_remaining_days=0,
    )
    print(f"  signal: {signal}")

    _ok(signal["buy_blocked"] is False, "buy_blocked == False")
    _ok(len(signal["block_reasons"]) == 0, "block_reasons 없음")

    alert_codes = [a["code"] for a in signal["alerts"]]
    print(f"  alert_codes: {alert_codes}")
    _ok("VIX_SPIKE" in alert_codes, "VIX_SPIKE 알림")
    _ok("YIELD_CURVE_STRESS" in alert_codes, "YIELD_CURVE_STRESS 알림")
    _ok("SGOV_CAP_WARNING" in alert_codes, "SGOV_CAP_WARNING 알림")
    _ok(len(signal["alerts"]) == 3, f"alerts 3개 (실제: {len(signal['alerts'])}개)")


def test_coeff_clipping() -> None:
    """보너스: 계수 클리핑 검증 (최대 1.5, 최소 0.5)."""
    print("\n[보너스] 계수 클리핑")

    # 최대: vix<20(+0.2), dd≥20%(+0.3), breadth>0.5(+0.1) → 1.6 → 클리핑 1.5
    high = compute_puddle_sizing(
        puddle_stage=3,
        vix=15,
        drawdown_from_200ma=-0.25,
        breadth_score=0.8,
    )
    print(f"  high coefficient: {high['coefficient']}")
    _ok(high["coefficient"] == 1.5, f"최대 클리핑 1.5 (raw=1.6)")

    # 최소: vix≥30(-0.3), dd<5%(0.0), breadth<0.3(-0.2) → 0.5 → 경계 정확
    low = compute_puddle_sizing(
        puddle_stage=3,
        vix=35,
        drawdown_from_200ma=-0.03,
        breadth_score=0.1,
    )
    print(f"  low coefficient: {low['coefficient']}")
    _ok(low["coefficient"] == 0.5, f"최소 클리핑 0.5 (raw=0.5)")


def main() -> None:
    """전체 테스트 실행."""
    print("=" * 60)
    print("TEAM FIRE 25 - PUDDLE sizing & signal_monitor 검증")
    print("=" * 60)

    tests = [
        test_case1_normal_buy_allowed,
        test_case2_vix_spike_sizing_down,
        test_case3_ma50_break_blocked,
        test_case4_cap_violation_blocked,
        test_case5_duplicate_puddle_blocked,
        test_case6_compound_alerts,
        test_coeff_clipping,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  ERROR: {e}")
            failed += 1
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"결과: {passed} passed / {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
