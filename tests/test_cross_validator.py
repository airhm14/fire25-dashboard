# -*- coding: utf-8 -*-
"""Cross Validator 검증 테스트.

테스트 1: conflict 없음 -> o1 미호출 (validation_result="not_required")
테스트 2: conflict 있음 -> fallback 구조 확인 (API key 없음)
테스트 3: 캐시 동작 (같은 입력 2회 -> miss then hit)
테스트 4: rule_violations 감지 (QQQM 80% 상한 위반)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fire25.agents.cross_validator import (
    _compute_cache_key,
    _pre_check_rule_violations,
    _CACHE_DIR,
    validate,
)

_TEST_CACHE_DIR = _CACHE_DIR.parent / "cache_test_cv"

# ── 공통 페이로드 ────────────────────────────────────────────────

_CONFLICT_PAYLOAD = {
    "regime": "NORMAL",
    "signals": {
        "technical": {
            "qqqm_vs_ma50": "above",
            "qqqm_vs_ma200": "above",
            "vix": 26.0,
            "drawdown_from_200ma": -0.03,
        },
        "macro": {"macro_bias": "bullish", "spread_10y_2y": -0.3},
        "news": {"macro_bias": "risk_off", "asset_bias_qqqm": -1},
    },
    "puddle_sizing": None,
    "active_blocks": [],
    "active_alerts": ["VIX_SPIKE", "YIELD_CURVE_STRESS"],
    "claude_analysis": {
        "situation_summary": "기술적 지표는 양호하나 매크로 신호 혼조",
        "strategy_consistency": "caution",
        "key_risk": "VIX 상승과 금리차 역전 동시 발생",
        "suggestion": "리밸런싱 검토가 필요합니다",
    },
}


def _ok(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise AssertionError(f"검증 실패: {label}")


# ── 테스트 1: conflict 없음 -> o1 미호출 ─────────────────────────

def test_case1_no_conflict() -> None:
    """테스트 1: conflict_detected=False -> validation_result='not_required'."""
    print("\n[테스트 1] conflict 없음 -> o1 미호출")

    result = validate({}, conflict_detected=False, api_key="")
    _ok(result.get("validation_result") == "not_required",
        f"validation_result='not_required' (got: {result.get('validation_result')})")
    _ok(result.get("confidence_score") is None,
        "confidence_score=None")
    _ok(result.get("cache_hit") is False,
        "cache_hit=False")
    _ok("quantitative_check" not in result,
        "quantitative_check 필드 없음 (not_required)")

    print(f"  result: {result}")


# ── 테스트 2: conflict 있음 -> fallback 구조 확인 ────────────────

def test_case2_conflict_fallback() -> None:
    """테스트 2: conflict_detected=True, API key 없음 -> fallback 구조."""
    print("\n[테스트 2] conflict 있음 -> fallback 구조 확인 (API key 없음)")

    import fire25.agents.cross_validator as mod
    original = mod._CACHE_DIR
    tmp = _TEST_CACHE_DIR / "test2"
    if tmp.exists():
        shutil.rmtree(tmp)
    mod._CACHE_DIR = tmp

    try:
        result = validate(_CONFLICT_PAYLOAD, conflict_detected=True, api_key="")

        _ok(result.get("validation_result") in {"agree", "partial", "disagree"},
            f"validation_result 유효값 (got: {result.get('validation_result')})")
        _ok(result.get("_error") == "missing_api_key",
            f"_error='missing_api_key' (got: {result.get('_error')})")
        _ok(result.get("cache_hit") is False, "cache_hit=False")
        _ok(result.get("validation_hash") != "", "validation_hash 존재")
        _ok("quantitative_check" in result, "quantitative_check 필드 존재")
        _ok("rule_violations" in result, "rule_violations 필드 존재")
        _ok("risk_adjustment" in result, "risk_adjustment 필드 존재")
        _ok("final_note" in result, "final_note 필드 존재")
        _ok(result["risk_adjustment"] in {"increase", "maintain", "decrease"},
            f"risk_adjustment 유효값 (got: {result.get('risk_adjustment')})")

        qc = result.get("quantitative_check", {})
        _ok(qc.get("technical_alignment") in {"aligned", "mixed", "conflicting"},
            f"technical_alignment 유효값 (got: {qc.get('technical_alignment')})")

        print(f"  validation_result: {result['validation_result']}")
        print(f"  risk_adjustment: {result['risk_adjustment']}")
        print(f"  validation_hash: {result['validation_hash']}")
    finally:
        mod._CACHE_DIR = original
        if tmp.exists():
            shutil.rmtree(tmp)


# ── 테스트 3: 캐시 동작 ───────────────────────────────────────────

def test_case3_cache_behavior() -> None:
    """테스트 3: 같은 입력 2회 -> 첫째 miss, 둘째 hit."""
    print("\n[테스트 3] 캐시 동작 확인 (miss -> hit)")

    import fire25.agents.cross_validator as mod
    original = mod._CACHE_DIR
    tmp = _TEST_CACHE_DIR / "test3"
    if tmp.exists():
        shutil.rmtree(tmp)
    mod._CACHE_DIR = tmp

    try:
        # 1차 호출 (fallback, cache miss)
        r1 = validate(_CONFLICT_PAYLOAD, conflict_detected=True, api_key="")
        _ok(r1.get("cache_hit") is False, "1차 호출: cache_hit=False")
        hash1 = r1.get("validation_hash", "")
        _ok(hash1 != "", "1차 호출: validation_hash 존재")
        print(f"  hash: {hash1}")

        # 캐시 파일 직접 생성 후 2차 호출
        mock_cache = {
            "validation_result": "partial",
            "confidence_score": 60,
            "quantitative_check": {
                "vix_context": "VIX 26 — 주의 구간",
                "yield_curve_context": "10Y-2Y 역전 지속",
                "drawdown_context": "200MA 대비 -3% 낙폭",
                "technical_alignment": "mixed",
            },
            "rule_violations": [],
            "risk_adjustment": "maintain",
            "divergence_from_claude": "",
            "final_note": "신호 혼조 — 현 포지션 유지가 적절",
            "cache_hit": False,
        }
        tmp.mkdir(parents=True, exist_ok=True)
        cache_file = tmp / f"cross_validation_{hash1}.json"
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(mock_cache, f, ensure_ascii=False)

        r2 = validate(_CONFLICT_PAYLOAD, conflict_detected=True, api_key="")
        _ok(r2.get("cache_hit") is True, "2차 호출: cache_hit=True")
        _ok(r2.get("validation_hash") == hash1, "2차 호출: 동일 hash")
        print(f"  1차 hash={hash1}, 2차 hash={r2['validation_hash']}")

        # deterministic hash 확인
        hash2 = _compute_cache_key(_CONFLICT_PAYLOAD)
        _ok(hash2 == hash1, "동일 입력 -> 동일 hash (deterministic)")
    finally:
        mod._CACHE_DIR = original
        if tmp.exists():
            shutil.rmtree(tmp)


# ── 테스트 4: rule_violations 감지 (QQQM 80% 상한 위반) ─────────

def test_case4_rule_violations() -> None:
    """테스트 4: QQQM 85% 언급 -> QQQM_CAP_VIOLATION 감지."""
    print("\n[테스트 4] rule_violations 감지 (QQQM_CAP_VIOLATION)")

    # QQQM 85% 포함 payload
    payload_with_violation = {
        **_CONFLICT_PAYLOAD,
        "claude_analysis": {
            "situation_summary": "기술적 강세 지속",
            "strategy_consistency": "consistent",
            "key_risk": "과매수 우려",
            "suggestion": "QQQM을 85%까지 올려보세요",
        },
    }

    violations = _pre_check_rule_violations(payload_with_violation)
    _ok("QQQM_CAP_VIOLATION" in violations,
        f"QQQM_CAP_VIOLATION 감지됨 (got: {violations})")

    # validate 결과에도 반영되는지 확인
    import fire25.agents.cross_validator as mod
    original = mod._CACHE_DIR
    tmp = _TEST_CACHE_DIR / "test4"
    if tmp.exists():
        shutil.rmtree(tmp)
    mod._CACHE_DIR = tmp

    try:
        result = validate(payload_with_violation, conflict_detected=True, api_key="")
        _ok("QQQM_CAP_VIOLATION" in result.get("rule_violations", []),
            f"validate() 결과에 QQQM_CAP_VIOLATION 포함 (got: {result.get('rule_violations')})")

        # 정상 suggestion은 violations 없어야 함
        normal_payload = {
            **_CONFLICT_PAYLOAD,
            "claude_analysis": {
                "situation_summary": "혼조",
                "strategy_consistency": "caution",
                "key_risk": "VIX 상승",
                "suggestion": "현 포지션을 유지하며 지표를 주시하세요",
            },
        }
        normal_violations = _pre_check_rule_violations(normal_payload)
        _ok("QQQM_CAP_VIOLATION" not in normal_violations,
            f"정상 suggestion: QQQM_CAP_VIOLATION 없음 (got: {normal_violations})")

        print(f"  violations detected: {violations}")
        print(f"  validate().rule_violations: {result.get('rule_violations')}")
    finally:
        mod._CACHE_DIR = original
        if tmp.exists():
            shutil.rmtree(tmp)


# ── 메인 ─────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("TEAM FIRE 25 - Cross Validator 검증")
    print("=" * 60)

    tests = [
        test_case1_no_conflict,
        test_case2_conflict_fallback,
        test_case3_cache_behavior,
        test_case4_rule_violations,
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
