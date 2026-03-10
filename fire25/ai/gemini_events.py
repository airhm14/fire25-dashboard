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
    schema = {
        "headline_summary": "string (오늘 핵심 이벤트 1~2문장)",
        "market_implication": "string (시장 시사점 1문장)",
        "macro_drivers": ["string"],
        "risk_level_label": "낮음|보통|높음",
    }
    return (
        "당신은 투자 대시보드용 이벤트 요약기입니다.\n"
        "오늘 일어난 핵심 이벤트를 간결하게 요약하세요.\n"
        "해석이나 전략 제안은 하지 마세요. 사실만 요약하세요.\n"
        "한국어로 작성하세요. JSON 외 텍스트 금지.\n\n"
        "[입력 데이터]\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        "[아래 스키마의 JSON으로만 출력]\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )


def _parse_gemini_output(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE):
        block = (m.group(1) or "").strip()
        if block:
            raw = block
            break
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            obj = json.loads(m.group(0))
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
        import google.generativeai as genai  # type: ignore
    except ImportError:
        return {**GEMINI_FALLBACK, **meta, "_debug_error": "missing_sdk"}

    try:
        payload = build_gemini_payload(articles, aggregated_signals, theme_info, asset_focus)
    except Exception:
        payload = {"articles": articles[:10]}

    try:
        _model_name = model or get_model_name("gemini")
        genai.configure(api_key=api_key)
        gmodel = genai.GenerativeModel(_model_name)
        response = gmodel.generate_content(
            _build_prompt(payload),
            generation_config={"temperature": 0.2, "max_output_tokens": 800},
            request_options={"timeout": 15},
        )
        text = getattr(response, "text", "") or ""
    except Exception as e:
        return {**GEMINI_FALLBACK, **meta, "_debug_error": f"api_error:{type(e).__name__}"}

    parsed = _parse_gemini_output(text)
    if not parsed:
        return {**GEMINI_FALLBACK, **meta, "_debug_error": "parse_error"}

    result = {
        "headline_summary": str(parsed.get("headline_summary", "")).strip()
            or GEMINI_FALLBACK["headline_summary"],
        "macro_drivers": parsed.get("macro_drivers", []),
        "market_implication": str(parsed.get("market_implication", "")).strip(),
        "risk_level": str(parsed.get("risk_level", "MODERATE")),
        "risk_level_label": str(parsed.get("risk_level_label", "보통")),
        "brief_source": "gemini",
        "_source": "gemini",
        "_debug_error": None,
    }
    return result
