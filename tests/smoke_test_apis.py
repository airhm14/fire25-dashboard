# -*- coding: utf-8 -*-
"""API Smoke Test — 각 에이전트 단독 실제 호출 확인.

사용 전 환경변수 설정 (Windows CMD):
  set GEMINI_API_KEY=your_gemini_key_here
  set ANTHROPIC_API_KEY=your_anthropic_key_here
  set OPENAI_API_KEY=your_openai_key_here

또는 PowerShell:
  $env:GEMINI_API_KEY="your_gemini_key_here"
  $env:ANTHROPIC_API_KEY="your_anthropic_key_here"
  $env:OPENAI_API_KEY="your_openai_key_here"

실행:
  python -X utf8 tests/smoke_test_apis.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
_CLAUDE_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

_DUMMY_NEWS = [
    {
        "id": "s001",
        "title": "Fed Holds Rates Steady Amid Inflation Concerns",
        "source": "Reuters",
        "date": "2026-03-13",
        "content": "The Federal Reserve kept interest rates unchanged at 5.25%, citing persistent inflation.",
    },
    {
        "id": "s002",
        "title": "Nasdaq Surges 2% on AI Chip Demand",
        "source": "Bloomberg",
        "date": "2026-03-13",
        "content": "Technology stocks led gains as AI chip demand boosted investor confidence.",
    },
]

_SIGNAL_ANALYZER_PAYLOAD = {
    "regime": "NORMAL",
    "puddle_stage": 0,
    "signals": {
        "technical": {"vix": 26.0, "qqqm_vs_ma50": "above", "qqqm_vs_ma200": "above"},
        "macro": {"macro_bias": "bullish"},
        "news": {"macro_bias": "risk_off", "asset_bias_qqqm": 0, "one_line_summary": "혼조"},
    },
    "active_blocks": [],
    "active_alerts": ["VIX_SPIKE"],
}

_CROSS_VALIDATOR_PAYLOAD = {
    "regime": "NORMAL",
    "signals": {
        "technical": {"qqqm_vs_ma50": "above", "qqqm_vs_ma200": "above",
                      "vix": 26.0, "drawdown_from_200ma": -0.03},
        "macro": {"macro_bias": "bullish", "spread_10y_2y": -0.3},
        "news": {"macro_bias": "risk_off", "asset_bias_qqqm": -1},
    },
    "puddle_sizing": None,
    "active_blocks": [],
    "active_alerts": ["VIX_SPIKE"],
    "claude_analysis": {
        "situation_summary": "기술적 양호, 매크로 혼조",
        "strategy_consistency": "caution",
        "key_risk": "VIX 상승",
        "suggestion": "현 포지션 유지 검토가 필요합니다",
    },
}


def _ok(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise AssertionError(f"검증 실패: {label}")


def _skip(label: str, reason: str) -> None:
    print(f"  [SKIP] {label} — {reason}")


# ── Smoke Test 1: Gemini (news_agent) ────────────────────────────

def smoke_test_gemini_news_agent() -> None:
    print("\n[Smoke 1] Gemini — news_agent.run()")
    if not _GEMINI_KEY:
        _skip("news_agent", "GEMINI_API_KEY 미설정")
        return

    import shutil
    from pathlib import Path
    from fire25.agents.news_agent import run, _CACHE_DIR

    # 캐시 격리
    tmp = _CACHE_DIR.parent / "cache_smoke_gemini"
    if tmp.exists():
        shutil.rmtree(tmp)

    import fire25.agents.news_agent as _na_mod
    _na_mod._CACHE_DIR = tmp

    try:
        t0 = time.time()
        result = run(_DUMMY_NEWS, api_key=_GEMINI_KEY)
        elapsed = time.time() - t0

        print(f"  응답 시간: {elapsed:.1f}s")
        _ok(result.get("error") is None, f"error=None (got: {result.get('error')})")
        _ok("macro_events" in result, "macro_events 존재")
        _ok("macro_summary" in result, "macro_summary 존재")
        _ok("digest" in result, "digest 존재")
        _ok(result.get("cache_hit") is False, "첫 호출: cache_hit=False")

        digest = result.get("digest") or {}
        summary = digest.get("one_line_summary", "")
        _ok(bool(summary), f"one_line_summary 존재: {summary[:50]}")
        print(f"  one_line_summary: {summary[:60]}")
        print(f"  macro_bias: {(result.get('macro_summary') or {}).get('macro_bias', 'N/A')}")
    finally:
        _na_mod._CACHE_DIR = _CACHE_DIR
        if tmp.exists():
            shutil.rmtree(tmp)


# ── Smoke Test 2: Claude (signal_analyzer) ───────────────────────

def smoke_test_claude_signal_analyzer() -> None:
    print("\n[Smoke 2] Claude — signal_analyzer.analyze()")
    if not _CLAUDE_KEY:
        _skip("signal_analyzer", "ANTHROPIC_API_KEY 미설정")
        return

    import shutil
    from fire25.agents.signal_analyzer import analyze, _CACHE_DIR

    tmp = _CACHE_DIR.parent / "cache_smoke_claude"
    if tmp.exists():
        shutil.rmtree(tmp)

    import fire25.agents.signal_analyzer as _sa_mod
    _sa_mod._CACHE_DIR = tmp

    try:
        t0 = time.time()
        result = analyze(_SIGNAL_ANALYZER_PAYLOAD, api_key=_CLAUDE_KEY)
        elapsed = time.time() - t0

        print(f"  응답 시간: {elapsed:.1f}s")
        _ok(result.get("conflict_detected") is True, "conflict_detected=True")
        _ok(result.get("claude_analysis") is not None, "claude_analysis 존재")

        ca = result.get("claude_analysis") or {}
        _ok(ca.get("_error") is None, f"claude_analysis._error=None (got: {ca.get('_error')})")
        _ok("situation_summary" in ca, "situation_summary 존재")
        _ok("strategy_consistency" in ca, "strategy_consistency 존재")

        print(f"  conflict_type: {result.get('conflict_type')}")
        print(f"  strategy_consistency: {ca.get('strategy_consistency')}")
        print(f"  situation_summary: {str(ca.get('situation_summary', ''))[:60]}")
    finally:
        _sa_mod._CACHE_DIR = _CACHE_DIR
        if tmp.exists():
            shutil.rmtree(tmp)


# ── Smoke Test 3: OpenAI o1 (cross_validator) ────────────────────

def smoke_test_openai_cross_validator() -> None:
    print("\n[Smoke 3] OpenAI o1 — cross_validator.validate()")
    if not _OPENAI_KEY:
        _skip("cross_validator", "OPENAI_API_KEY 미설정")
        return

    import shutil
    from fire25.agents.cross_validator import validate, _CACHE_DIR

    tmp = _CACHE_DIR.parent / "cache_smoke_openai"
    if tmp.exists():
        shutil.rmtree(tmp)

    import fire25.agents.cross_validator as _cv_mod
    _cv_mod._CACHE_DIR = tmp

    try:
        t0 = time.time()
        result = validate(
            _CROSS_VALIDATOR_PAYLOAD,
            conflict_detected=True,
            api_key=_OPENAI_KEY,
        )
        elapsed = time.time() - t0

        print(f"  응답 시간: {elapsed:.1f}s")
        _ok(result.get("validation_result") in {"agree", "partial", "disagree"},
            f"validation_result 유효 (got: {result.get('validation_result')})")
        _ok(result.get("_error") is None, f"_error=None (got: {result.get('_error')})")
        _ok("quantitative_check" in result, "quantitative_check 존재")

        qc = result.get("quantitative_check") or {}
        _ok(qc.get("technical_alignment") in {"aligned", "mixed", "conflicting"},
            f"technical_alignment 유효 (got: {qc.get('technical_alignment')})")

        print(f"  validation_result: {result.get('validation_result')}")
        print(f"  confidence_score: {result.get('confidence_score')}")
        print(f"  risk_adjustment: {result.get('risk_adjustment')}")
        print(f"  final_note: {str(result.get('final_note',''))[:60]}")
    finally:
        _cv_mod._CACHE_DIR = _CACHE_DIR
        if tmp.exists():
            shutil.rmtree(tmp)


# ── 메인 ─────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("TEAM FIRE 25 — API Smoke Test")
    print("=" * 60)
    print()

    # API key 상태 표시
    print("환경변수 상태:")
    print(f"  GEMINI_API_KEY:     {'SET (' + _GEMINI_KEY[:8] + '...)' if _GEMINI_KEY else 'NOT SET'}")
    print(f"  ANTHROPIC_API_KEY:  {'SET (' + _CLAUDE_KEY[:8] + '...)' if _CLAUDE_KEY else 'NOT SET'}")
    print(f"  OPENAI_API_KEY:     {'SET (' + _OPENAI_KEY[:8] + '...)' if _OPENAI_KEY else 'NOT SET'}")

    if not any([_GEMINI_KEY, _CLAUDE_KEY, _OPENAI_KEY]):
        print()
        print("API key가 하나도 설정되지 않았습니다.")
        print("설정 방법 (Windows CMD):")
        print("  set GEMINI_API_KEY=AIza...")
        print("  set ANTHROPIC_API_KEY=sk-ant-...")
        print("  set OPENAI_API_KEY=sk-...")
        print()
        print("설정 방법 (PowerShell):")
        print('  $env:GEMINI_API_KEY="AIza..."')
        print('  $env:ANTHROPIC_API_KEY="sk-ant-..."')
        print('  $env:OPENAI_API_KEY="sk-..."')
        sys.exit(0)

    tests = [
        smoke_test_gemini_news_agent,
        smoke_test_claude_signal_analyzer,
        smoke_test_openai_cross_validator,
    ]

    passed, failed, skipped = 0, 0, 0
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
    print("(SKIP은 API key 없는 경우 정상)")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
