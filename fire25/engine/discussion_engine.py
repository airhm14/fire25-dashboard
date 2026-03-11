# -*- coding: utf-8 -*-
"""Discussion Engine — 1-round debate between Claude and GPT.

충돌 시:
  1. Claude가 GPT 전략을 검토 후 반박/수정
  2. GPT가 Claude 의견을 반영 후 최종 전략 제시
  토론은 1라운드만 수행.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fire25.ai.model_registry import get_model_name

CLAUDE_REVIEW_PROMPT = """
당신은 TEAM FIRE 25의 전략가 A(Claude)입니다.

전략가 B(GPT)가 아래 전략을 제시했습니다. 충돌 사항을 검토하고, 당신의 전략과 비교하여 반박하거나 수정하세요.

[충돌 사항]
{conflict_summary}

[GPT 전략]
{gpt_strategy_json}

[당신의 원래 전략]
{claude_strategy_json}

[Regime: {regime}]

[출력 규칙]
- 반드시 JSON 객체 하나만 반환하세요.
- 코드 블록(```)을 사용하지 마세요.

[출력 스키마]
{{
  "review_comment": "GPT 전략에 대한 검토 의견 1~2문장",
  "revised_actions": [
    {{"ticker": "QQQM", "action": "BUY|HOLD|REDUCE", "amount": 정수}},
    {{"ticker": "SCHD", "action": "BUY|HOLD|REDUCE", "amount": 정수}},
    {{"ticker": "IAU", "action": "BUY|HOLD|REDUCE", "amount": 정수}},
    {{"ticker": "SGOV", "action": "BUY|HOLD|REDUCE", "amount": 정수}}
  ],
  "revised_cash_action": "KEEP|DEPLOY|INCREASE",
  "confidence_score": 0~100
}}
""".strip()

GPT_FINAL_PROMPT = """
당신은 TEAM FIRE 25의 전략가 B(GPT)입니다.

전략가 A(Claude)가 당신의 전략을 검토하고 아래와 같이 반박/수정했습니다.
Claude의 의견을 반영하여 최종 전략을 제시하세요.

[Claude 검토 의견]
{claude_review_json}

[당신의 원래 전략]
{gpt_strategy_json}

[Regime: {regime}]

[출력 규칙]
- 반드시 JSON 객체 하나만 반환하세요.
- 코드 블록(```)을 사용하지 마세요.

[출력 스키마]
{{
  "regime": "{regime}",
  "market_view": "최종 시장 해석 1~2문장",
  "strategy_reason": "최종 전략 선택 이유 1~2문장",
  "recommended_actions": [
    {{"ticker": "QQQM", "action": "BUY|HOLD|REDUCE", "amount": 정수}},
    {{"ticker": "SCHD", "action": "BUY|HOLD|REDUCE", "amount": 정수}},
    {{"ticker": "IAU", "action": "BUY|HOLD|REDUCE", "amount": 정수}},
    {{"ticker": "SGOV", "action": "BUY|HOLD|REDUCE", "amount": 정수}}
  ],
  "cash_action": "KEEP|DEPLOY|INCREASE",
  "confidence_score": 0~100,
  "discussion_note": "토론에서 반영한 점 1문장"
}}
""".strip()


def _parse_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = (m.group(1) or "").strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    m2 = re.search(r"\{[\s\S]*\}", raw)
    if m2:
        try:
            obj = json.loads(m2.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def run_discussion(
    *,
    regime: str,
    claude_strategy: dict,
    gpt_strategy: dict,
    conflict_reasons: list[str],
    claude_api_key: str = "",
    openai_api_key: str = "",
    claude_model: str = "",
    gpt_model: str = "",
) -> dict[str, Any]:
    """Execute 1-round debate and return final strategy.

    Returns dict with:
      - Final strategy fields (regime, market_view, recommended_actions, etc.)
      - _discussion metadata (claude_review, rounds)
    """
    _claude_model = claude_model or get_model_name("claude")
    _gpt_model = gpt_model or get_model_name("openai")

    conflict_text = "\n".join(f"- {r}" for r in conflict_reasons) if conflict_reasons else "없음"

    # --- Step 1: Claude reviews GPT strategy ---
    claude_review: dict | None = None
    try:
        import anthropic
        prompt = CLAUDE_REVIEW_PROMPT.format(
            conflict_summary=conflict_text,
            gpt_strategy_json=json.dumps(gpt_strategy, ensure_ascii=False, default=str),
            claude_strategy_json=json.dumps(claude_strategy, ensure_ascii=False, default=str),
            regime=regime,
        )
        client = anthropic.Anthropic(api_key=claude_api_key)
        msg = client.messages.create(
            model=_claude_model,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
            timeout=30.0,
        )
        claude_review = _parse_json(msg.content[0].text or "")
    except Exception:
        pass

    if not claude_review:
        # If Claude review fails, fall back to averaging confidence
        return _merge_fallback(claude_strategy, gpt_strategy, regime)

    # --- Step 2: GPT reflects on Claude's review → final strategy ---
    try:
        from openai import OpenAI
        prompt = GPT_FINAL_PROMPT.format(
            claude_review_json=json.dumps(claude_review, ensure_ascii=False, default=str),
            gpt_strategy_json=json.dumps(gpt_strategy, ensure_ascii=False, default=str),
            regime=regime,
        )
        client = OpenAI(api_key=openai_api_key)
        resp = client.chat.completions.create(
            model=_gpt_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.3,
            timeout=30.0,
        )
        final = _parse_json(resp.choices[0].message.content or "")
        if final:
            final["_source"] = "discussion"
            final["_discussion"] = {
                "rounds": 1,
                "claude_review": claude_review.get("review_comment", ""),
                "discussion_note": final.get("discussion_note", ""),
            }
            final.setdefault("regime", regime)
            return final
    except Exception:
        pass

    return _merge_fallback(claude_strategy, gpt_strategy, regime, claude_review)


def _merge_fallback(
    claude: dict, gpt: dict, regime: str,
    claude_review: dict | None = None,
) -> dict[str, Any]:
    """Simple merge when discussion API calls fail."""
    c_conf = int(claude.get("confidence_score", 50))
    g_conf = int(gpt.get("confidence_score", 50))

    # Pick strategy from higher-confidence agent
    winner = claude if c_conf >= g_conf else gpt

    result = {
        "regime": regime,
        "market_view": winner.get("market_view", ""),
        "strategy_reason": winner.get("strategy_reason", ""),
        "recommended_actions": winner.get("recommended_actions", []),
        "cash_action": winner.get("cash_action", "KEEP"),
        "confidence_score": max(c_conf, g_conf),
        "_source": "merge_fallback",
        "_discussion": {
            "rounds": 0,
            "note": "토론 API 실패, 신뢰도 높은 에이전트 전략 채택",
            "claude_review": (claude_review or {}).get("review_comment", ""),
        },
    }
    return result
