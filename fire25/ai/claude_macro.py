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

CLAUDE_PROMPT_TEMPLATE = """
당신은 TEAM FIRE 25 Dashboard의 거시경제 해석 보조 AI입니다.

규칙:
- 입력 컨텍스트에 포함된 정보만 사용하세요.
- 사실을 추가로 발명하지 마세요.
- 한국어로 짧고 명확하게 작성하세요.
- 각 항목은 1~2문장 이내로 작성하세요.
- 투자 조언(매수/매도 단정 명령)은 절대 하지 마세요.

출력은 반드시 JSON만 반환하세요.
스키마:
{{
    "macro_view": "",
    "key_risk": "",
    "opportunity": "",
    "watch_point": ""
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
    model: str = "claude-sonnet-4-20250514",
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

    try:
        prompt = _build_prompt(context)
    except Exception:
        return {**CLAUDE_FALLBACK, **out_meta, "_debug_error": "prompt_error"}

    try:
        message = client.messages.create(
            model=model,
            max_tokens=600,
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
        "macro_view": str(parsed.get("macro_view", "")).strip() or CLAUDE_FALLBACK["macro_view"],
        "key_risk": str(parsed.get("key_risk", "")).strip() or CLAUDE_FALLBACK["key_risk"],
        "opportunity": str(parsed.get("opportunity", "")).strip() or CLAUDE_FALLBACK["opportunity"],
        "watch_point": str(parsed.get("watch_point", "")).strip() or CLAUDE_FALLBACK["watch_point"],
        "_source": "claude",
        "_debug_error": None,
    }
    return result
