# -*- coding: utf-8 -*-
"""News Agent 검증 테스트.

테스트 1: 캐시 동작 확인 (같은 입력 2회 → 첫째 miss, 둘째 hit)
테스트 2: fallback 동작 확인 (API key 없음)
테스트 3: 더미 뉴스 3개로 전체 출력 구조 확인 (API key 없음 → fallback 구조 검증)
"""

from __future__ import annotations

import json
import sys
import os
import shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fire25.agents.news_agent import (
    _compute_cache_key,
    _dedup_and_sort,
    _validate_and_clip,
    _parse_json_response,
    _CACHE_DIR,
    _FALLBACK,
    run,
)

# ── 테스트용 캐시 디렉토리 격리 ─────────────────────────────────
_TEST_CACHE_DIR = _CACHE_DIR.parent / "cache_test"

DUMMY_NEWS = [
    {
        "id": "n001",
        "title": "Fed, 금리 동결 결정",
        "source": "Reuters",
        "date": "2026-03-13",
        "content": "연방준비제도가 기준금리를 5.25%로 동결했다.",
    },
    {
        "id": "n002",
        "title": "나스닥 기술주 급등",
        "source": "Bloomberg",
        "date": "2026-03-13",
        "content": "AI 관련 기술주 중심으로 나스닥이 2% 상승했다.",
    },
    {
        "id": "n003",
        "title": "미국 고용지표 예상 하회",
        "source": "WSJ",
        "date": "2026-03-13",
        "content": "3월 신규 고용이 시장 예상치를 하회하며 경기 둔화 우려가 높아졌다.",
    },
]


def _ok(condition: bool, label: str) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    if not condition:
        raise AssertionError(f"검증 실패: {label}")


def _patch_cache_dir(tmp_dir: Path):
    """테스트용 캐시 디렉토리로 임시 교체."""
    import fire25.agents.news_agent as mod
    mod._CACHE_DIR = tmp_dir
    return mod


def _restore_cache_dir(mod):
    mod._CACHE_DIR = _CACHE_DIR


def test_unit_dedup_and_sort() -> None:
    """단위: 중복 제거 + 정렬 검증."""
    print("\n[단위] 중복 제거 + 정렬")
    items = [
        {"id": "a", "title": "A뉴스", "date": "2026-03-13"},
        {"id": "b", "title": "B뉴스", "date": "2026-03-14"},
        {"id": "a", "title": "A뉴스 중복", "date": "2026-03-12"},  # 중복
    ]
    result = _dedup_and_sort(items)
    _ok(len(result) == 2, "중복 제거 후 2개")
    _ok(result[0]["date"] >= result[1]["date"], "date 내림차순")


def test_unit_validate_clip() -> None:
    """단위: 검증 + 클리핑."""
    print("\n[단위] 검증 + 클리핑")
    raw = {
        "macro_events": [
            {"severity": 99, "impact_direction": "INVALID", "asset_relevance": None},
            {"severity": -1, "impact_direction": "bullish"},
        ],
        "macro_summary": {
            "macro_bias": "UNKNOWN",
            "asset_bias": {"QQQM": 10, "SCHD": -5, "IAU": 0, "SGOV": 3},
        },
        "digest": {
            "top_signals": [{"rank": "abc", "impact": "WRONG"}],
            "one_line_summary": "테스트",
        },
    }
    out = _validate_and_clip(raw)
    _ok(out["macro_events"][0]["severity"] == 5, "severity 99 → 5 클리핑")
    _ok(out["macro_events"][0]["impact_direction"] == "neutral", "INVALID → neutral")
    _ok(out["macro_events"][1]["severity"] == 1, "severity -1 → 1 클리핑")
    _ok(out["macro_summary"]["macro_bias"] == "neutral", "UNKNOWN macro_bias → neutral")
    _ok(out["macro_summary"]["asset_bias"]["QQQM"] == 2, "asset_bias 10 → 2 클리핑")
    _ok(out["macro_summary"]["asset_bias"]["SCHD"] == -2, "asset_bias -5 → -2 클리핑")
    _ok(out["digest"]["top_signals"][0]["rank"] == 1, "rank 'abc' → 1 변환")
    _ok(out["digest"]["top_signals"][0]["impact"] == "neutral", "WRONG impact → neutral")


def test_unit_parse_json() -> None:
    """단위: JSON 파싱 (code block, trailing comma 처리)."""
    print("\n[단위] JSON 파싱")
    # 정상 JSON
    _ok(_parse_json_response('{"a": 1}') == {"a": 1}, "정상 JSON 파싱")
    # code block
    _ok(_parse_json_response('```json\n{"b": 2}\n```') == {"b": 2}, "code block 제거")
    # trailing comma
    _ok(_parse_json_response('{"c": 3,}') == {"c": 3}, "trailing comma 처리")
    # 빈 값
    _ok(_parse_json_response("") is None, "빈 문자열 → None")
    _ok(_parse_json_response("invalid") is None, "invalid → None")


def test_case1_cache_behavior() -> None:
    """테스트 1: 캐시 동작 — 첫 번째 miss, 두 번째 hit."""
    print("\n[테스트 1] 캐시 동작 확인")

    # 임시 캐시 디렉토리 사용
    tmp = _TEST_CACHE_DIR / "test1"
    if tmp.exists():
        shutil.rmtree(tmp)

    import fire25.agents.news_agent as mod
    original = mod._CACHE_DIR
    mod._CACHE_DIR = tmp

    try:
        # 첫 번째 호출 (API key 없으므로 fallback 반환)
        r1 = run(DUMMY_NEWS, api_key="")
        _ok(r1.get("cache_hit") is False, "1차 호출: cache_hit=False (fallback)")
        _ok("news_snapshot_hash" in r1, "hash 필드 존재")
        hash1 = r1["news_snapshot_hash"]
        print(f"  hash: {hash1}")

        # 캐시 파일을 직접 생성해서 2차 호출 테스트 (실제 API 없이도 가능)
        mock_cache = {
            "news_snapshot_hash": hash1,
            "cache_hit": False,
            "macro_events": [{"event_type": "FED_POLICY", "title": "Test", "impact_direction": "neutral",
                               "severity": 3, "asset_relevance": ["QQQM"], "source": "Reuters",
                               "date": "2026-03-13", "summary": "테스트"}],
            "macro_summary": {"macro_bias": "neutral", "risk_sentiment": "중립", "asset_bias": {"QQQM": 0, "SCHD": 0, "IAU": 0, "SGOV": 0}},
            "digest": {"top_signals": [], "one_line_summary": "테스트 캐시"},
            "error": None,
        }
        tmp.mkdir(parents=True, exist_ok=True)
        cache_file = tmp / f"news_snapshot_{hash1}.json"
        with cache_file.open("w", encoding="utf-8") as f:
            json.dump(mock_cache, f, ensure_ascii=False)

        r2 = run(DUMMY_NEWS, api_key="")
        _ok(r2.get("cache_hit") is True, "2차 호출: cache_hit=True")
        _ok(r2.get("news_snapshot_hash") == hash1, "동일 hash 반환")
        print(f"  1차 hash={r1['news_snapshot_hash']}, 2차 hash={r2['news_snapshot_hash']}")
    finally:
        mod._CACHE_DIR = original
        if tmp.exists():
            shutil.rmtree(tmp)


def test_case2_fallback() -> None:
    """테스트 2: fallback 동작 — API key 없음."""
    print("\n[테스트 2] fallback 동작 확인")

    import fire25.agents.news_agent as mod
    original = mod._CACHE_DIR
    tmp = _TEST_CACHE_DIR / "test2"
    if tmp.exists():
        shutil.rmtree(tmp)
    mod._CACHE_DIR = tmp

    try:
        result = run(DUMMY_NEWS, api_key="")
        print(f"  result: {json.dumps({k: v for k, v in result.items() if k != 'macro_events'}, ensure_ascii=False, indent=2)}")
        _ok(result.get("error") == "missing_api_key", f"error='missing_api_key' (실제: {result.get('error')})")
        _ok(result.get("macro_summary", {}).get("macro_bias") == "neutral", "macro_bias=neutral (fallback)")
        _ok(isinstance(result.get("digest"), dict), "digest는 dict")
        _ok(result.get("cache_hit") is False, "cache_hit=False")
    finally:
        mod._CACHE_DIR = original
        if tmp.exists():
            shutil.rmtree(tmp)


def test_case3_dummy_news_structure() -> None:
    """테스트 3: 더미 뉴스 3개 — 전체 출력 구조 확인 (API key 없음 → fallback)."""
    print("\n[테스트 3] 더미 뉴스 3개 전체 구조 확인")

    import fire25.agents.news_agent as mod
    original = mod._CACHE_DIR
    tmp = _TEST_CACHE_DIR / "test3"
    if tmp.exists():
        shutil.rmtree(tmp)
    mod._CACHE_DIR = tmp

    try:
        result = run(DUMMY_NEWS, api_key="")
        print("  출력 JSON (전체):")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        # 구조 검증
        _ok("news_snapshot_hash" in result, "news_snapshot_hash 필드")
        _ok("cache_hit" in result, "cache_hit 필드")
        _ok("macro_events" in result, "macro_events 필드")
        _ok("macro_summary" in result, "macro_summary 필드")
        _ok("digest" in result, "digest 필드")
        _ok("error" in result, "error 필드")

        ms = result.get("macro_summary", {})
        _ok("macro_bias" in ms, "macro_summary.macro_bias")
        _ok("risk_sentiment" in ms, "macro_summary.risk_sentiment")
        _ok("asset_bias" in ms, "macro_summary.asset_bias")
        ab = ms.get("asset_bias", {})
        for asset in ["QQQM", "SCHD", "IAU", "SGOV"]:
            _ok(asset in ab, f"asset_bias.{asset}")

        digest = result.get("digest", {})
        _ok("top_signals" in digest, "digest.top_signals")
        _ok("one_line_summary" in digest, "digest.one_line_summary")

        # hash가 더미 뉴스 기준으로 deterministic인지 확인
        hash1 = result["news_snapshot_hash"]
        result2 = run(DUMMY_NEWS, api_key="")
        _ok(result2["news_snapshot_hash"] == hash1, "동일 입력 → 동일 hash (deterministic)")
    finally:
        mod._CACHE_DIR = original
        if tmp.exists():
            shutil.rmtree(tmp)


def main() -> None:
    """전체 테스트 실행."""
    print("=" * 60)
    print("TEAM FIRE 25 - News Agent 검증")
    print("=" * 60)

    tests = [
        test_unit_dedup_and_sort,
        test_unit_validate_clip,
        test_unit_parse_json,
        test_case1_cache_behavior,
        test_case2_fallback,
        test_case3_dummy_news_structure,
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
            print(f"  EXCEPTION in {t.__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"결과: {passed} passed / {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
