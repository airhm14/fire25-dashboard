# -*- coding: utf-8 -*-
"""News Snapshot — 뉴스 → 구조화 이벤트 → 전략 입력용 스냅샷.

3단계 구조:
  1. Raw News Layer: title, source, published_at, link, snippet
  2. Event Extraction Layer: 각 뉴스 → 구조화 이벤트 JSON (Gemini)
  3. News Snapshot Layer: 이벤트 집계 → 전략 입력용 snapshot

핵심 원칙:
  - 뉴스는 자유 서술이 아닌 구조화 데이터로만 취급
  - 동일 news_ids → 동일 snapshot 재사용 (해시 기반 캐시)
  - AI에는 snapshot만 전달 (raw news 금지)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any


# ── 허용된 event_type 목록 ───────────────────────────────────────

VALID_EVENT_TYPES = frozenset({
    "fed_policy", "inflation", "jobs", "recession", "liquidity",
    "earnings", "ai_sector", "semiconductor", "geopolitics",
    "oil", "usd", "bond_yield", "regulation", "market_breadth",
})

# 자산 목록
ASSETS = ("QQQM", "SCHD", "IAU", "SGOV")

# ── Snapshot fallback ────────────────────────────────────────────

SNAPSHOT_FALLBACK: dict[str, Any] = {
    "timestamp_bucket": "",
    "macro_bias": "neutral",
    "top_events": [],
    "event_scores": {},
    "asset_bias": {"QQQM": 0, "SCHD": 0, "IAU": 0, "SGOV": 0},
    "source_count": 0,
    "news_ids": [],
    "snapshot_hash": "",
    "raw_news_count": 0,
    "deduped_event_count": 0,
    "_source": "fallback",
}


# ── 타임스탬프 버킷 ─────────────────────────────────────────────

def get_news_bucket() -> str:
    """현재 시각 → AM/PM 버킷 문자열."""
    now = datetime.now()
    period = "AM" if now.hour < 12 else "PM"
    return now.strftime(f"%Y-%m-%d-{period}")


# ── 스냅샷 해시 ─────────────────────────────────────────────────

def compute_snapshot_hash(news_ids: list[str]) -> str:
    """정렬된 news_ids → SHA-256 해시 (16자)."""
    canonical = json.dumps(sorted(news_ids), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# ── 이벤트 정규화 ───────────────────────────────────────────────

def normalize_event(event: dict) -> dict:
    """Gemini에서 추출된 이벤트를 표준 스키마로 정규화."""
    etype = str(event.get("event_type", "")).strip().lower()
    if etype not in VALID_EVENT_TYPES:
        etype = ""  # 비표준 타입 → 빈 문자열 (집계에서 제외)

    direction = str(event.get("impact_direction", "neutral")).strip().lower()
    if direction not in ("bullish", "bearish", "neutral"):
        direction = "neutral"

    severity = event.get("severity", 1)
    try:
        severity = max(1, min(5, int(severity)))
    except (TypeError, ValueError):
        severity = 1

    # asset_relevance 정규화
    raw_assets = event.get("asset_relevance", [])
    if isinstance(raw_assets, str):
        raw_assets = [a.strip() for a in raw_assets.split(",")]
    assets = sorted(set(
        a.upper() for a in (raw_assets if isinstance(raw_assets, list) else [])
        if a.upper() in ASSETS
    ))

    # macro_tags 정규화
    raw_tags = event.get("macro_tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in raw_tags.split(",")]
    tags = sorted(set(
        t.strip().lower() for t in (raw_tags if isinstance(raw_tags, list) else [])
        if t.strip()
    ))

    return {
        "news_id": str(event.get("news_id", event.get("title", ""))).strip(),
        "title": str(event.get("title", "")).strip(),
        "source": str(event.get("source", "")).strip(),
        "published_at": str(event.get("published_at", "")).strip(),
        "event_type": etype,
        "impact_direction": direction,
        "severity": severity,
        "asset_relevance": assets,
        "macro_tags": tags,
        "summary": str(event.get("summary", "")).strip(),
        "source_count": max(1, int(event.get("source_count", 1))),
    }


# ── 중복 제거 ───────────────────────────────────────────────────

def dedup_events(events: list[dict]) -> list[dict]:
    """제목 기반 중복 제거. 동일 사건 → source_count 합산."""
    seen: dict[str, dict] = {}
    for ev in events:
        title = ev.get("title", "").strip()
        if not title:
            continue
        if title in seen:
            seen[title]["source_count"] = seen[title].get("source_count", 1) + 1
            # 더 높은 severity 사용
            if ev.get("severity", 1) > seen[title].get("severity", 1):
                seen[title]["severity"] = ev["severity"]
        else:
            seen[title] = dict(ev)
    return list(seen.values())


# ── 점수화 ───────────────────────────────────────────────────────

def _direction_score(direction: str) -> int:
    """impact_direction → +1 / -1 / 0."""
    if direction == "bullish":
        return 1
    if direction == "bearish":
        return -1
    return 0


def compute_event_scores(events: list[dict]) -> dict[str, int]:
    """event_type별 가중 점수 합산."""
    scores: dict[str, int] = {}
    for ev in events:
        etype = ev.get("event_type", "")
        if not etype:
            continue
        weighted = _direction_score(ev.get("impact_direction", "neutral")) * ev.get("severity", 1)
        scores[etype] = scores.get(etype, 0) + weighted
    return dict(sorted(scores.items()))


def compute_asset_bias(events: list[dict]) -> dict[str, int]:
    """자산별 이벤트 점수 합산."""
    bias: dict[str, int] = {a: 0 for a in ASSETS}
    for ev in events:
        weighted = _direction_score(ev.get("impact_direction", "neutral")) * ev.get("severity", 1)
        for asset in ev.get("asset_relevance", []):
            if asset in bias:
                bias[asset] += weighted
    return bias


def compute_macro_bias(event_scores: dict[str, int]) -> str:
    """event_scores 합산 → macro_bias 결정."""
    total = sum(event_scores.values())
    if total >= 3:
        return "risk_on"
    if total <= -3:
        return "risk_off"
    return "neutral"


# ── 스냅샷 빌드 ─────────────────────────────────────────────────

def build_snapshot(
    events: list[dict],
    raw_news_count: int = 0,
) -> dict[str, Any]:
    """정규화된 이벤트 목록 → 전략 입력용 News Snapshot.

    Args:
        events: normalize_event()를 거친 이벤트 목록
        raw_news_count: 원본 뉴스 개수 (UI 표시용)

    Returns:
        전략 입력용 snapshot dict
    """
    # 유효 이벤트만 필터 (event_type 있는 것만)
    valid = [e for e in events if e.get("event_type")]

    # 중복 제거
    deduped = dedup_events(valid)

    # 점수 계산
    event_scores = compute_event_scores(deduped)
    asset_bias = compute_asset_bias(deduped)
    macro_bias = compute_macro_bias(event_scores)

    # news_ids (정렬)
    news_ids = sorted(set(e.get("news_id", e.get("title", "")) for e in deduped if e.get("title")))
    snapshot_hash = compute_snapshot_hash(news_ids)

    # top_events: severity 높은 순 최대 5개
    top = sorted(deduped, key=lambda x: -x.get("severity", 1))[:5]

    return {
        "timestamp_bucket": get_news_bucket(),
        "macro_bias": macro_bias,
        "top_events": top,
        "event_scores": event_scores,
        "asset_bias": asset_bias,
        "source_count": sum(e.get("source_count", 1) for e in deduped),
        "news_ids": news_ids,
        "snapshot_hash": snapshot_hash,
        "raw_news_count": raw_news_count,
        "deduped_event_count": len(deduped),
        "_source": "computed",
    }


def snapshot_to_prompt(snapshot: dict) -> str:
    """Snapshot → Claude/GPT 입력용 구조화 텍스트."""
    if not snapshot or snapshot.get("_source") == "fallback":
        return "[뉴스 데이터 없음]"

    lines = [
        f"[뉴스 스냅샷 — {snapshot.get('timestamp_bucket', '')}]",
        f"매크로 방향: {snapshot.get('macro_bias', 'neutral')}",
        f"이벤트 수: {snapshot.get('deduped_event_count', 0)}개 (원본 {snapshot.get('raw_news_count', 0)}건)",
    ]

    # event_scores
    scores = snapshot.get("event_scores", {})
    if scores:
        score_parts = [f"{k}={v:+d}" for k, v in scores.items()]
        lines.append(f"이벤트 점수: {', '.join(score_parts)}")

    # asset_bias
    bias = snapshot.get("asset_bias", {})
    if bias:
        bias_parts = [f"{k}={v:+d}" for k, v in bias.items()]
        lines.append(f"자산 편향: {', '.join(bias_parts)}")

    # top events (최대 5개)
    top = snapshot.get("top_events", [])
    if top:
        lines.append("주요 이벤트:")
        for ev in top[:5]:
            d = ev.get("impact_direction", "neutral")
            s = ev.get("severity", 1)
            lines.append(f"  - [{ev.get('event_type','')}] {ev.get('title','')} ({d}, severity={s})")

    return "\n".join(lines)
