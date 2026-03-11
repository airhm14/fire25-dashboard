# -*- coding: utf-8 -*-
"""Gemini-based news event detection layer.

Calls the Google Generative AI SDK directly with an explicit API key
so it works with Streamlit secrets (not just os.getenv).
Falls back to the existing ``news_engine`` path when possible.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Re-use payload builder from news_engine if available.
try:
    from fire25.news_engine import build_gemini_payload
except ImportError:
    def build_gemini_payload(*_a: Any, **_kw: Any) -> dict:  # type: ignore[misc]
        return {}

from fire25.ai.model_registry import get_model_name

GEMINI_FALLBACK: dict[str, Any] = {
    "headline_summary": "Gemini 이벤트 탐지를 실행하지 못했습니다.",
    "macro_drivers": [],
    "market_implication": "",
    "risk_level": "MODERATE",
    "risk_level_label": "보통",
    "brief_source": "fallback",
    "_source": "fallback",
    "_debug_error": None,
}


def _build_prompt(payload: dict) -> str:
    schema = (
        '{\n'
        '  "headline_summary": "오늘 핵심 이벤트 1~2문장",\n'
        '  "macro_drivers": ["driver1", "driver2"],\n'
        '  "market_implication": "시장 시사점 1문장",\n'
        '  "risk_level": "LOW|MODERATE|HIGH",\n'
        '  "risk_level_label": "낮음|보통|높음"\n'
        '}'
    )
    return (
        "당신은 투자 대시보드용 이벤트 요약기입니다.\n"
        "오늘 일어난 핵심 이벤트를 간결하게 요약하세요.\n"
        "해석이나 전략 제안은 하지 마세요. 사실만 요약하세요.\n"
        "한국어로 작성하세요.\n\n"
        "[엄격 규칙]\n"
        "- 반드시 JSON 객체 하나만 반환하세요.\n"
        "- 코드 블록(```)을 사용하지 마세요.\n"
        "- JSON 앞뒤에 설명 문장을 추가하지 마세요.\n"
        "- trailing comma를 사용하지 마세요.\n"
        "- 아래 스키마에 없는 필드를 추가하지 마세요.\n\n"
        "[입력 데이터]\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "[출력 스키마 — 이 형태의 JSON만 반환]\n"
        f"{schema}"
    )


def _clean_json_like_text(raw: str) -> str:
    """Sanitize common Gemini quirks so ``json.loads`` succeeds."""
    s = raw
    # smart / curly quotes → ASCII
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    # trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # stray BOM / zero-width chars
    s = s.replace("\ufeff", "").replace("\u200b", "")
    return s.strip()


def _parse_gemini_output(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None

    # 1) strip fenced code blocks if present
    m_fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m_fence:
        raw = (m_fence.group(1) or "").strip()

    # 2) sanitize
    raw = _clean_json_like_text(raw)

    # 3) try full text as JSON
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 4) extract first { ... } block
    m_obj = re.search(r"\{[\s\S]*\}", raw)
    if m_obj:
        candidate = _clean_json_like_text(m_obj.group(0))
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    return None


def detect_events(
    articles: list[dict],
    aggregated_signals: dict,
    theme_info: dict,
    asset_focus: str = "growth",
    api_key: str = "",
    model: str = "",
) -> dict:
    """Run Gemini event detection and return structured result.

    ``api_key`` is the Gemini API key passed explicitly from Streamlit
    secrets.  When empty, returns fallback immediately.
    """
    meta: dict[str, Any] = {"_source": "fallback", "_debug_error": None}

    if not str(api_key or "").strip():
        return {**GEMINI_FALLBACK, **meta, "_debug_error": "missing_api_key"}

    if not articles:
        return {**GEMINI_FALLBACK, **meta, "_debug_error": "no_articles"}

    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError:
        return {**GEMINI_FALLBACK, **meta, "_debug_error": "missing_sdk"}

    try:
        payload = build_gemini_payload(articles, aggregated_signals, theme_info, asset_focus)
    except Exception:
        payload = {"articles": articles[:10]}

    try:
        _model_name = model or get_model_name("gemini")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_model_name,
            contents=_build_prompt(payload),
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=800,
            ),
        )
        text = getattr(response, "text", "") or ""
    except Exception as e:
        return {**GEMINI_FALLBACK, **meta, "_debug_error": f"api_error:{type(e).__name__}:{e}"}

    # Debug logging (dev only)
    print(f"GEMINI RAW RESPONSE ({len(text)} chars):", text[:500])

    parsed = _parse_gemini_output(text)
    if not parsed:
        return {**GEMINI_FALLBACK, **meta, "_debug_error": "parse_error"}

    # Normalize macro_drivers to list
    drivers = parsed.get("macro_drivers", [])
    if isinstance(drivers, str):
        drivers = [d.strip() for d in drivers.split(",") if d.strip()] if drivers else []
    elif not isinstance(drivers, list):
        drivers = []

    result = {
        "headline_summary": str(parsed.get("headline_summary", "")).strip()
            or GEMINI_FALLBACK["headline_summary"],
        "macro_drivers": drivers,
        "market_implication": str(parsed.get("market_implication", "")).strip(),
        "risk_level": str(parsed.get("risk_level", "MODERATE")),
        "risk_level_label": str(parsed.get("risk_level_label", "보통")),
        "brief_source": "gemini",
        "_source": "gemini",
        "_debug_error": None,
    }
    return result
