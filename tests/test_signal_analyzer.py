# -*- coding: utf-8 -*-
"""Signal Analyzer 검증 테스트.

테스트 1: 충돌 없음 -> Claude 미호출 (conflict_detected=False, claude_analysis=None)
테스트 2: 충돌 감지 -> fallback 구조 확인 (API key 없음)
테스트 3: 캐시 동작 (같은 입력 2회 -> miss then hit)
테스트 4: Suggestion sanitizer 검증 (매수하세요, 매도하세요 치환)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fire25.agents.signal_analyzer import (
    _detect_conflict,
    _compute_cache_key,
    _sanitize_suggestion,
    _CACHE_DIR,
    analyze,
)

_TEST_CACHE_DIR = _CACHE_DIR.parent / "cache_test_sa"


def _ok(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise AssertionError(f"검증 실패: {label}")


# ── 공통 페이로드 팩토리 ─────────────────────────────────────────

def _no_conflict_payload() -> dict:
    """충돌 없는 정상 페이로드."""
    return {
        "regime": "NORMAL",
        "puddle_stage": 0,
        "signals": {
            "technical": {"vix": 15.0, "qqqm_vs_ma50": "above", "qqqm_vs_ma200": "above"},
            "macro": {"macro_bias": "neutral"},
            "news": {"macro_bias": "neutral", "asset_bias_qqqm": 0, "one_line_summary": ""},
        },
        "active_blocks": [],
        "active_alerts": [],
    }


def _conflict_payload() -> dict:
    """규칙 1 충돌 (TECH_ABOVE_NEWS_RISK_OFF): MA50 위 + 뉴스 risk_off."""
    return {
        "regime": "NORMAL",
        "puddle_stage": 0,
        "signals": {
            "technical": {"vix": 18.0, "qqqm_vs_ma50": "above", "qqqm_vs_ma200": "above"},
            "macro": {"macro_bias": "neutral"},
            "news": {"macro_bias": "risk_off", "asset_bias_qqqm": 0, "one_line_summary": "글로벌 리스크 확대"},
        },
        "active_blocks": [],
        "active_alerts": [],
    }


# ── 테스트 1: 충돌 없음 -> Claude 미호출 ──────────────────────────

def test_case1_no_conflict() -> None:
    """테스트 1: 충돌 없음 -> conflict_detected=False, claude_analysis=None."""
    print("\n[테스트 1] 충돌 없음 -> Claude 미호출")

    payload = _no_conflict_payload()
    conflict, ctype = _detect_conflict(payload)
    _ok(conflict is False, "_detect_conflict: conflict=False")
    _ok(ctype == "", "_detect_conflict: type=''")

    # analyze 직접 호출 (API key 있어도 충돌 없으면 Claude 안 부름)
    result = analyze(payload, api_key="")
    _ok(result.get("conflict_detected") is False, "analyze: conflict_detected=False")
    _ok(result.get("claude_analysis") is None, "analyze: claude_analysis=None")
    _ok(result.get("analysis_hash") == "", "analyze: analysis_hash='' (no hash for no conflict)")

    print(f"  result keys: {list(result.keys())}")


# ── 테스트 2: 충돌 감지 -> fallback 구조 확인 ────────────────────

def test_case2_conflict_fallback() -> None:
    """테스트 2: 충돌 감지 -> API key 없음 -> fallback 구조."""
    print("\n[테스트 2] 충돌 감지 -> fallback 구조 확인 (API key 없음)")

    import fire25.agents.signal_analyzer as mod
    original = mod._CACHE_DIR
    tmp = _TEST_CACHE_DIR / "test2"
    if tmp.exists():
        shutil.rmtree(tmp)
    mod._CACHE_DIR = tmp

    try:
        payload = _conflict_payload()

        # 충돌 감지 확인
        conflict, ctype = _detect_conflict(payload)
        _ok(conflict is True, "_detect_conflict: conflict=True")
        _ok("TECH_ABOVE_NEWS_RISK_OFF" in ctype, f"conflict_type contains TECH_ABOVE_NEWS_RISK_OFF (got: {ctype})")

        # API key 없는 analyze
        result = analyze(payload, api_key="")
        _ok(result.get("conflict_detected") is True, "analyze: conflict_detected=True")
        _ok(result.get("conflict_type") != "", "analyze: conflict_type 비어있지 않음")
        _ok(result.get("claude_analysis") is not None, "analyze: claude_analysis 존재")
        _ok(result.get("cache_hit") is False, "analyze: cache_hit=False")
        _ok(result.get("analysis_hash") != "", "analyze: analysis_hash 존재")

        _ca = result["claude_analysis"]
        _ok(_ca.get("_error") == "missing_api_key", f"claude_analysis._error='missing_api_key' (got: {_ca.get('_error')})")
        _ok("strategy_consistency" in _ca, "claude_analysis.strategy_consistency 존재")
        _ok("suggestion" in _ca, "claude_analysis.suggestion 존재")
        _ok("situation_summary" in _ca, "claude_analysis.situation_summary 존재")

        print(f"  conflict_type: {result['conflict_type']}")
        print(f"  strategy_consistency: {_ca.get('strategy_consistency')}")
    finally:
        mod._CACHE_DIR = original
        if tmp.exists():
            shutil.rmtree(tmp)


# ── 테스트 3: 캐시 동작 ───────────────────────────────────────────

def test_case3_cache_behavior() -> None:
    """테스트 3: 같은 입력 2회 -> 첫째 miss, 둘째 hit."""
    print("\n[테스트 3] 캐시 동작 확인 (miss -> hit)")

    import fire25.agents.signal_analyzer as mod
    original = mod._CACHE_DIR
    tmp = _TEST_CACHE_DIR / "test3"
    if tmp.exists():
        shutil.rmtree(tmp)
    mod._CACHE_DIR = tmp

    try:
        payload = _conflict_payload()

        # 1차 호출 (API key 없음 -> fallback, but NOT cached because fallback)
        r1 = analyze(payload, api_key="")
        _ok(r1.get("cache_hit") is False, "1차 호출: cache_hit=False")
        hash1 = r1.get("analysis_hash", "")
        _ok(hash1 != "", "1차 호출: analysis_hash 존재")
        print(f"  hash: {hash1}")

        # 캐시 파일 직접 생성 (API 없이 2차 hit 테스트)
        mock_cache = {
            "conflict_detected": True,
            "conflict_type": "TECH_ABOVE_NEWS_RISK_OFF",
            "claude_analysis": {
                "situation_summary": "테스트 캐시 상황",
                "conflicting_signals": ["TECH_ABOVE_NEWS_RISK_OFF"],
                "historical_analogy": "2022년 상반기",
                "strategy_consistency": "caution",
                "key_risk": "뉴스 하방 + 기술적 상방 괴리",
                "suggestion": "단계적 접근이 적절할 수 있습니다.",
            },
            "cache_hit": False,
        }
        tmp.mkdir(parents=True, exist_ok=True)
        cache_file = tmp / f"signal_analysis_{hash1}.json"
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(mock_cache, f, ensure_ascii=False)

        # 2차 호출 (캐시 hit)
        r2 = analyze(payload, api_key="")
        _ok(r2.get("cache_hit") is True, "2차 호출: cache_hit=True")
        _ok(r2.get("analysis_hash") == hash1, "2차 호출: 동일 hash")
        print(f"  1차 hash={hash1}, 2차 hash={r2['analysis_hash']}")

        # 동일 입력 -> 동일 hash (deterministic)
        hash2 = _compute_cache_key(payload)
        _ok(hash2 == hash1, "동일 입력 -> 동일 hash (deterministic)")
    finally:
        mod._CACHE_DIR = original
        if tmp.exists():
            shutil.rmtree(tmp)


# ── 테스트 4: Suggestion sanitizer ──────────────────────────────

def test_case4_sanitizer() -> None:
    """테스트 4: 직접 지시 금지어 치환 확인."""
    print("\n[테스트 4] Suggestion sanitizer 검증")

    cases = [
        ("QQQM을 매수하세요.", "매수하세요", "매수 여부를 검토해보세요"),
        ("IAU를 매도하세요.", "매도하세요", "매도 여부를 검토해보세요"),
        ("지금 팔아야 합니다.", "팔아야 합니다", "매도 검토가 필요할 수 있습니다"),
        ("사야 합니다.", "사야 합니다", "매수 검토가 필요할 수 있습니다"),
        ("즉시 매수해야 합니다.", "즉시 매수", "단계적 매수 검토"),
        ("즉시 매도하는 것이 좋습니다.", "즉시 매도", "단계적 매도 검토"),
    ]

    for original_text, forbidden_word, expected_replacement in cases:
        sanitized, was_modified = _sanitize_suggestion(original_text)
        _ok(forbidden_word not in sanitized, f"'{forbidden_word}' 제거됨")
        _ok(expected_replacement in sanitized, f"'{expected_replacement}'로 치환됨 (결과: {sanitized})")
        _ok(was_modified is True, f"was_modified=True ('{forbidden_word}' 케이스)")

    # 정상 문장은 변경 없어야 함
    normal = "지표를 종합적으로 검토해보시기 바랍니다."
    normal_result, normal_modified = _sanitize_suggestion(normal)
    _ok(normal_result == normal, "정상 문장 변경 없음")
    _ok(normal_modified is False, "정상 문장: was_modified=False")

    print("  모든 금지어 패턴 치환 확인 완료")


# ── 메인 ─────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("TEAM FIRE 25 - Signal Analyzer 검증")
    print("=" * 60)

    tests = [
        test_case1_no_conflict,
        test_case2_conflict_fallback,
        test_case3_cache_behavior,
        test_case4_sanitizer,
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
