# -*- coding: utf-8 -*-
"""Gemini Agent — 뉴스 수집 / 중복 제거 / 요약.

기존 gemini_events.py를 래핑하여 에이전트 인터페이스를 제공한다.
뉴스 정규화 후 동일 news_ids → 캐시 재사용.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fire25.ai.gemini_events import detect_events, GEMINI_FALLBACK
from fire25.ai.decision_context_builder import normalize_news

# ── 뉴스 요약 캐시 (동일 news_ids → 기존 summary 재사용) ────────
_summary_cache: dict[str, dict[str, Any]] = {}


def _news_ids_hash(articles: list[dict]) -> str:
    """정규화된 뉴스 목록 → 해시."""
    titles = [a.get("title", "") for a in articles]
    raw = json.dumps(titles, sort_keys=False, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def run(
    *,
    articles: list[dict],
    aggregated_signals: dict,
    theme_info: dict,
    asset_focus: str = "growth",
    api_key: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Execute Gemini news agent with normalization + cache.

    Returns structured event summary dict compatible with the orchestrator.
    """
    # 뉴스 정규화: 정렬 + 중복 제거
    normalized = normalize_news(articles)

    # 캐시 조회
    nid_hash = _news_ids_hash(normalized)
    if nid_hash in _summary_cache:
        cached = _summary_cache[nid_hash]
        return {**cached, "_cache_hit": True, "_news_hash": nid_hash}

    # 정규화된 뉴스로 이벤트 탐지
    result = detect_events(
        articles=normalized,
        aggregated_signals=aggregated_signals,
        theme_info=theme_info,
        asset_focus=asset_focus,
        api_key=api_key,
        model=model,
    )
    result.setdefault("_agent", "gemini")
    result["_news_hash"] = nid_hash

    # 성공 시 캐시 저장
    if result.get("_source") == "gemini":
        _summary_cache[nid_hash] = result

    return result


FALLBACK = GEMINI_FALLBACK
