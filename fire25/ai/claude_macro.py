# -*- coding: utf-8 -*-
"""Claude-based macro interpretation layer.

Calls the Anthropic Messages API to produce a concise Korean
macro/news interpretation block.  Falls back gracefully when the
SDK or API key is unavailable.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fire25.ai.model_registry import get_model_name

CLAUDE_PROMPT_TEMPLATE = """
당신은 TEAM FIRE 25 Dashboard의 거시경제 해석 전문 AI입니다.

역할:
- 시장 이벤트가 거시경제적으로 어떤 의미를 갖는지 해석합니다.
- 질문: "그 일이 시장에 어떤 의미가 있는가?"

엄격 규칙:
- 입력 컨텍스트에 포함된 정보만 사용하세요.
- 사실을 추가로 발명하지 마세요.
- 한국어로 짧고 명확하게 작성하세요.
- 각 항목은 1~2문장 이내로 작성하세요.
- 전략 제안, 매수/매도 방향, 포지션 조정 문장은 절대 작성하지 마세요.
- 거시경제 해석과 시장 의미만 작성하세요.
- 이벤트를 단순 재진술하지 마세요. 그 이벤트의 거시적 연결을 설명하세요.

출력은 반드시 JSON만 반환하세요.
스키마:
{{
    "macro_view": "거시경제 관점에서 현재 상황의 의미 (1~2문장)",
    "key_risk": "가장 중요한 거시 리스크 요인 (1문장)",
    "opportunity": "거시 환경에서 파생되는 기회 요인 (1문장)",
    "watch_point": "향후 주시해야 할 거시 지표 (1문장)"
}}

입력 컨텍스트:
{context_json}
""".strip()


CLAUDE_FALLBACK: dict[str, str] = {
    "macro_view": "거시 해석 데이터를 생성하지 못했습니다.",
    "key_risk": "확인 필요",
    "opportunity": "확인 필요",
    "watch_point": "핵심 지표 변화를 추적하세요.",
}


def _polish_korean_sentence(text: str) -> str:
    """Clean up a Korean sentence for dashboard display."""
    s = str(text or "").strip()
    if not s:
        return s
    # collapse multiple whitespace
    s = re.sub(r"[ \t]+", " ", s)
    # remove stray newlines
    s = re.sub(r"\n+", " ", s)
    # ensure trailing period
    if s and s[-1] not in ".!?。":
        s += "."
    # limit length (≈ 200 chars)
    if len(s) > 200:
        cut = s[:197].rsplit(" ", 1)[0] or s[:197]
        s = cut.rstrip(".,") + "…"
    return s


def _build_prompt(context: dict) -> str:
    ctx_json = json.dumps(context or {}, ensure_ascii=False)
    return CLAUDE_PROMPT_TEMPLATE.format(context_json=ctx_json)


def _parse_claude_output(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # Strip fenced code blocks
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


def interpret_macro(
    context: dict,
    api_key: str = "",
    model: str = "",
    timeout: float = 20.0,
) -> dict:
    """Call Claude to interpret macro conditions.

    Always returns a dict with macro_view / key_risk / opportunity / watch_point
    plus _source and _debug_error metadata.
    """
    out_meta: dict[str, Any] = {"_source": "fallback", "_debug_error": None}

    if not str(api_key or "").strip():
        return {**CLAUDE_FALLBACK, **out_meta, "_debug_error": "missing_api_key"}

    try:
        import anthropic  # type: ignore
    except ImportError:
        return {**CLAUDE_FALLBACK, **out_meta, "_debug_error": "missing_anthropic_sdk"}

    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        return {**CLAUDE_FALLBACK, **out_meta, "_debug_error": f"client_error:{type(e).__name__}"}

    _model = model or get_model_name("claude")

    try:
        prompt = _build_prompt(context)
    except Exception:
        return {**CLAUDE_FALLBACK, **out_meta, "_debug_error": "prompt_error"}

    try:
        message = client.messages.create(
            model=_model,
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
    except Exception as e:
        return {**CLAUDE_FALLBACK, **out_meta, "_debug_error": f"api_error:{type(e).__name__}"}

    text = ""
    try:
        text = message.content[0].text or ""
    except Exception:
        pass

    parsed = _parse_claude_output(text)
    if not parsed:
        return {**CLAUDE_FALLBACK, **out_meta, "_debug_error": "parse_error"}

    result = {
        "macro_view": _polish_korean_sentence(
            parsed.get("macro_view", "")) or CLAUDE_FALLBACK["macro_view"],
        "key_risk": _polish_korean_sentence(
            parsed.get("key_risk", "")) or CLAUDE_FALLBACK["key_risk"],
        "opportunity": _polish_korean_sentence(
            parsed.get("opportunity", "")) or CLAUDE_FALLBACK["opportunity"],
        "watch_point": _polish_korean_sentence(
            parsed.get("watch_point", "")) or CLAUDE_FALLBACK["watch_point"],
        "_source": "claude",
        "_debug_error": None,
    }
    return result
