# -*- coding: utf-8 -*-
"""Gemini Agent — 뉴스 → 구조화 이벤트 추출 + News Snapshot 생성.

3단계 파이프라인:
  1. Raw News → 정규화 (normalize_news)
  2. Gemini로 구조화 이벤트 추출 (JSON only, temperature=0)
  3. 이벤트 → News Snapshot 빌드 (점수화 · 자산 편향 · 캐시)

동일 news_ids → 동일 snapshot 재사용 (해시 기반 캐시).
파싱 실패 시 1회 재시도, 그 후 이전 snapshot fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fire25.ai.decision_context_builder import normalize_news
from fire25.ai.model_registry import get_model_name
from fire25.agents.news_snapshot import (
    SNAPSHOT_FALLBACK,
    VALID_EVENT_TYPES,
    build_snapshot,
    compute_snapshot_hash,
    normalize_event,
    snapshot_to_prompt,
)

# ── 스냅샷 캐시 (동일 news_ids → 기존 snapshot 재사용) ───────────
_snapshot_cache: dict[str, dict[str, Any]] = {}
_prev_snapshot: dict[str, Any] | None = None  # 파싱 실패 시 fallback용


def _news_ids_hash(articles: list[dict]) -> str:
    """정규화된 뉴스 제목 → 해시."""
    titles = [a.get("title", "") for a in articles]
    raw = json.dumps(titles, sort_keys=False, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── Gemini 이벤트 추출 프롬프트 ──────────────────────────────────

_EVENT_TYPES_STR = ", ".join(sorted(VALID_EVENT_TYPES))

_EXTRACT_PROMPT = """당신은 투자 뉴스 이벤트 추출기입니다.
아래 뉴스 목록을 분석하여 각 뉴스를 구조화된 이벤트 JSON으로 변환하세요.

[엄격 규칙]
- 반드시 JSON 배열만 반환하세요.
- 코드 블록(```)을 사용하지 마세요.
- JSON 앞뒤에 설명 문장을 추가하지 마세요.
- trailing comma를 사용하지 마세요.
- 같은 사건을 다룬 뉴스는 하나의 이벤트로 병합하세요.

[event_type 허용 목록 — 이 중에서만 선택]
{event_types}

[impact_direction]
- bullish: 시장/자산에 긍정적
- bearish: 시장/자산에 부정적
- neutral: 중립 또는 불확실

[severity]
1~5 정수 (1=미미, 3=보통, 5=극심)

[asset_relevance]
해당 이벤트가 영향을 미치는 자산: QQQM, SCHD, IAU, SGOV 중 선택

[입력 뉴스]
{news_json}

[출력 스키마 — JSON 배열만 반환]
[
  {{
    "news_id": "뉴스 제목 (고유 ID로 사용)",
    "title": "뉴스 제목",
    "source": "출처",
    "published_at": "발행일",
    "event_type": "위 허용 목록 중 하나",
    "impact_direction": "bullish|bearish|neutral",
    "severity": 1~5,
    "asset_relevance": ["QQQM", "SCHD"],
    "macro_tags": ["태그1", "태그2"],
    "summary": "사실 위주 1문장 요약"
  }}
]"""


def _build_extract_prompt(articles: list[dict]) -> str:
    """뉴스 목록 → 이벤트 추출 프롬프트."""
    # 최대 15개로 제한
    limited = articles[:15]
    news_data = [
        {
            "title": a.get("title", ""),
            "source": a.get("source", ""),
            "date": a.get("date", ""),
        }
        for a in limited
    ]
    return _EXTRACT_PROMPT.format(
        event_types=_EVENT_TYPES_STR,
        news_json=json.dumps(news_data, ensure_ascii=False, indent=2),
    )


def _clean_json_text(raw: str) -> str:
    """Gemini 출력 정리."""
    s = raw.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = re.sub(r",\s*([}\]])", r"\1", s)
    s = s.replace("\ufeff", "").replace("\u200b", "")
    return s.strip()


def _parse_events_output(text: str) -> list[dict] | None:
    """Gemini 응답에서 이벤트 JSON 배열 파싱."""
    raw = (text or "").strip()
    if not raw:
        return None

    # code block 제거
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = (m.group(1) or "").strip()

    raw = _clean_json_text(raw)

    # 전체를 배열로 파싱 시도
    try:
        obj = json.loads(raw)
        if isinstance(obj, list):
            return obj
    except Exception:
        pass

    # [ ... ] 블록 찾기
    m2 = re.search(r"\[[\s\S]*\]", raw)
    if m2:
        try:
            obj = json.loads(_clean_json_text(m2.group(0)))
            if isinstance(obj, list):
                return obj
        except Exception:
            pass

    # 단일 객체를 배열로 감싸기
    m3 = re.search(r"\{[\s\S]*\}", raw)
    if m3:
        try:
            obj = json.loads(_clean_json_text(m3.group(0)))
            if isinstance(obj, dict):
                return [obj]
        except Exception:
            pass

    return None


def _extract_gemini_text(response: Any) -> str:
    """google-genai 응답에서 텍스트 추출 (thinking 모델 대응)."""
    try:
        parts = response.candidates[0].content.parts
        output_parts = []
        all_texts = []
        for part in parts:
            t = getattr(part, "text", None) or ""
            is_thought = getattr(part, "thought", None)
            all_texts.append(t)
            if not is_thought:
                output_parts.append(t)
        for t in output_parts:
            if "[" in t or "{" in t:
                return t
        for t in reversed(output_parts):
            if t.strip():
                return t
        for t in all_texts:
            if "[" in t or "{" in t:
                return t
        for t in reversed(all_texts):
            if t.strip():
                return t
    except Exception:
        pass
    text = getattr(response, "text", None)
    if text:
        return text
    return ""


def _call_gemini(
    prompt: str,
    api_key: str,
    model: str,
) -> tuple[str, str | None]:
    """Gemini API 호출. Returns (text, error)."""
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError:
        return "", "missing_sdk"

    try:
        client = genai.Client(api_key=api_key)
        cfg = types.GenerateContentConfig(
            temperature=0,
            top_p=1,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=cfg,
        )
        text = _extract_gemini_text(resp)
        if not text or not text.strip():
            return "", "empty_response"
        return text, None
    except Exception as e:
        return "", f"api_error:{type(e).__name__}:{e}"


def run(
    *,
    articles: list[dict],
    aggregated_signals: dict,
    theme_info: dict,
    asset_focus: str = "growth",
    api_key: str = "",
    model: str = "",
) -> dict[str, Any]:
    """뉴스 → 구조화 이벤트 추출 → News Snapshot 생성.

    Returns:
        - news_snapshot: 전략 입력용 snapshot dict
        - events: 구조화 이벤트 목록
        - _source, _news_hash 등 메타데이터
    """
    global _prev_snapshot

    meta: dict[str, Any] = {"_agent": "gemini", "_source": "fallback", "_debug_error": None}

    # 정규화
    normalized = normalize_news(articles)
    raw_count = len(articles or [])

    if not normalized:
        return {
            **meta,
            "news_snapshot": {**SNAPSHOT_FALLBACK},
            "events": [],
            "_news_hash": "",
            "_debug_error": "no_articles",
        }

    # 캐시 조회
    nid_hash = _news_ids_hash(normalized)
    if nid_hash in _snapshot_cache:
        cached = _snapshot_cache[nid_hash]
        return {**cached, "_cache_hit": True, "_news_hash": nid_hash}

    if not str(api_key or "").strip():
        return {
            **meta,
            "news_snapshot": {**SNAPSHOT_FALLBACK},
            "events": [],
            "_news_hash": nid_hash,
            "_debug_error": "missing_api_key",
        }

    _model = model or get_model_name("gemini")
    prompt = _build_extract_prompt(normalized)

    # Gemini 호출 (최대 2회: 1회 + 재시도 1회)
    parsed_events = None
    last_error = None

    for attempt in range(2):
        text, err = _call_gemini(prompt, api_key, _model)
        if err:
            last_error = err
            if err == "missing_sdk":
                break
            continue

        parsed_events = _parse_events_output(text)
        if parsed_events is not None:
            break
        last_error = f"parse_error_attempt_{attempt + 1}|{(text or '')[:200]}"

    # 파싱 실패 → 이전 snapshot fallback
    if parsed_events is None:
        if _prev_snapshot:
            return {
                **meta,
                "news_snapshot": {**_prev_snapshot, "_source": "prev_fallback"},
                "events": [],
                "_news_hash": nid_hash,
                "_debug_error": f"parse_fail_fallback|{last_error}",
            }
        return {
            **meta,
            "news_snapshot": {**SNAPSHOT_FALLBACK},
            "events": [],
            "_news_hash": nid_hash,
            "_debug_error": last_error,
        }

    # 이벤트 정규화
    norm_events = [normalize_event(e) for e in parsed_events if isinstance(e, dict)]

    # Snapshot 빌드
    snapshot = build_snapshot(norm_events, raw_news_count=raw_count)

    result = {
        "_agent": "gemini",
        "_source": "gemini",
        "_debug_error": None,
        "_news_hash": nid_hash,
        "news_snapshot": snapshot,
        "events": norm_events,
        # 기존 호환 필드 (헤드라인 요약은 top_events에서 생성)
        "headline_summary": _build_headline_from_snapshot(snapshot),
        "risk_level": _snapshot_risk_level(snapshot),
        "risk_level_label": _snapshot_risk_label(snapshot),
        "macro_drivers": list(snapshot.get("event_scores", {}).keys()),
    }

    # 캐시 저장
    _snapshot_cache[nid_hash] = result
    _prev_snapshot = snapshot

    return result


def _build_headline_from_snapshot(snapshot: dict) -> str:
    """Snapshot → 헤드라인 요약 (기존 호환용)."""
    top = snapshot.get("top_events", [])
    if not top:
        return "주요 이벤트 없음"
    parts = []
    for ev in top[:3]:
        d_mark = {"bullish": "📈", "bearish": "📉"}.get(ev.get("impact_direction", ""), "➡️")
        parts.append(f"{d_mark} [{ev.get('event_type', '')}] {ev.get('title', '')}")
    return " | ".join(parts)


def _snapshot_risk_level(snapshot: dict) -> str:
    """Snapshot → risk_level."""
    total = sum(snapshot.get("event_scores", {}).values())
    if total <= -5:
        return "HIGH"
    if total <= -2:
        return "MODERATE"
    return "LOW"


def _snapshot_risk_label(snapshot: dict) -> str:
    """Snapshot → risk_level 한국어."""
    level = _snapshot_risk_level(snapshot)
    return {"LOW": "낮음", "MODERATE": "보통", "HIGH": "높음"}.get(level, "보통")


FALLBACK = SNAPSHOT_FALLBACK
