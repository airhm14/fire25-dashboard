# -*- coding: utf-8 -*-
"""GPT Agent — 전략가 B.

Claude와 동일 역할, 동일 입력으로 독립 전략을 생성한다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fire25.ai.model_registry import get_model_name

STRATEGY_PROMPT = """
당신은 TEAM FIRE 25의 전략가 B(GPT)입니다.

[당신의 역할]
- 동일한 입력을 받는 전략가 A(Claude)와 독립적으로 전략을 생성합니다.
- 시장 해석 + 실행 전략 최적화를 수행합니다.
- ETF 교체/자산군 변경은 금지입니다.

[핵심 철학]
Buy Fear · Rebalance Strength · Protect Core Asset · Compound Long Term

[포트폴리오 구조 — 고정]
허용 종목: QQQM / SCHD / IAU / SGOV (이외 금지)
목표 비중: QQQM 72% / SCHD 16% / IAU 2% / SGOV 10%
비중 허용 편차: QQQM ±5% / SCHD ±3% / IAU ±2%

[핵심 자산 규칙 — QQQM]
- QQQM은 기본 = HOLD. 매도(REDUCE)는 Smart Shoulder 또는 구조적 리스크(아래 정의)에서만 허용.
- 구조적 리스크: breadth collapse, AI/반도체 disruption, 유동성 충격, 크레딧 스트레스, 경기침체 공식 선언
- QQQM 비중 캡: 최대 80%
  · ≤70%: 추가 매수 가능
  · 70~77%: 소량 매수 허용, 리밸런싱 불필요
  · 77~80%: 신규 매수 금지, 비중 하향 검토
  · >80%: 반드시 비중 축소, SCHD/IAU로 분산

[Regime 정보]
현재 Regime: {regime}

[Regime별 AI 권한]
- NORMAL: 목표비중 배분, 비중 허용범위 안에서만 미세조정
- DEFCON (VIX ≤14 & RSI ≥70): 신규자금 SGOV 우선 배치, breadth/liquidity/earnings/macro 보고 강도 조절
- PUDDLE_1~4: 현금성 자산(SGOV+현금) 기준 투입 원칙
  · PUDDLE_1: 매수 금지 (투입률 0%) — 낙폭 작고 변동성 높아 관망
  · PUDDLE_2: 현금의 10% 투입 — 초기 진입
  · PUDDLE_3: 현금의 25% 투입 — 본격 진입
  · PUDDLE_4: 현금의 50% 투입 — 적극 진입
  · 같은 단계 중복 매수 금지, 30일 쿨다운 적용
  · AI는 매크로/변동성/캐피튤레이션 여부에 따라 투입률을 ±조절 가능
- SMART_SHOULDER: QQQM 과집중 리스크 관리, 시장 추세 훼손 여부 해석, 리스크 축소 방향 유지

[전략 안정성 규칙]
- 일일 비중 변동 ≤5%
- 최소 거래 단위 ≥1% (그 미만은 HOLD 처리)
- SGOV 비중 ≤20% (DEFCON 제외)
- 일일 현금 사용 ≤25%
- Regime 미변경 시 이전 전략 유지 방향 (일관성)

[입력 데이터]
포트폴리오: {portfolio_json}
거시지표: {macro_json}
뉴스 요약: {news_summary}

[출력 규칙]
- 반드시 JSON 객체 하나만 반환하세요.
- 코드 블록(```)을 사용하지 마세요.
- JSON 앞뒤에 설명 문장을 추가하지 마세요.

[출력 스키마]
{{
  "regime": "{regime}",
  "market_view": "현재 시장에 대한 해석 1~2문장",
  "strategy_reason": "이 전략을 선택한 이유 1~2문장",
  "risk_level": "LOW|MODERATE|HIGH",
  "recommended_actions": [
    {{"ticker": "QQQM", "action": "BUY|HOLD|REDUCE", "amount": 정수_또는_0}},
    {{"ticker": "SCHD", "action": "BUY|HOLD|REDUCE", "amount": 정수_또는_0}},
    {{"ticker": "IAU", "action": "BUY|HOLD|REDUCE", "amount": 정수_또는_0}},
    {{"ticker": "SGOV", "action": "BUY|HOLD|REDUCE", "amount": 정수_또는_0}}
  ],
  "cash_action": "KEEP|DEPLOY|INCREASE",
  "confidence_score": 0~100_정수,
  "reason_codes": ["코드1", "코드2"]
}}
""".strip()


FALLBACK: dict[str, Any] = {
    "regime": "NORMAL",
    "market_view": "전략 생성에 실패했습니다.",
    "strategy_reason": "",
    "risk_level": "MODERATE",
    "recommended_actions": [
        {"ticker": "QQQM", "action": "HOLD", "amount": 0},
        {"ticker": "SCHD", "action": "HOLD", "amount": 0},
        {"ticker": "IAU", "action": "HOLD", "amount": 0},
        {"ticker": "SGOV", "action": "HOLD", "amount": 0},
    ],
    "cash_action": "KEEP",
    "confidence_score": 0,
    "reason_codes": ["FALLBACK"],
    "_source": "fallback",
    "_debug_error": None,
}


def _parse_output(text: str) -> dict | None:
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


def run(
    *,
    regime: str,
    portfolio: dict,
    macro_context: dict,
    news_summary: str = "",
    api_key: str = "",
    model: str = "",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Execute GPT strategy agent."""
    meta: dict[str, Any] = {"_agent": "gpt", "_source": "fallback", "_debug_error": None}

    if not str(api_key or "").strip():
        return {**FALLBACK, **meta, "_debug_error": "missing_api_key"}

    try:
        from openai import OpenAI
    except ImportError:
        return {**FALLBACK, **meta, "_debug_error": "missing_sdk"}

    _model = model or get_model_name("openai")

    prompt = STRATEGY_PROMPT.format(
        regime=regime,
        portfolio_json=json.dumps(portfolio, ensure_ascii=False),
        macro_json=json.dumps(macro_context, ensure_ascii=False),
        news_summary=news_summary,
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=0,
            seed=42,
            timeout=timeout,
        )
        text = response.choices[0].message.content or ""
    except Exception as e:
        return {**FALLBACK, **meta, "_debug_error": f"api_error:{type(e).__name__}:{e}"}

    parsed = _parse_output(text)
    if not parsed:
        snippet = (text or "")[:200].replace("\n", " ")
        return {**FALLBACK, **meta, "_debug_error": f"parse_error|{snippet}"}

    parsed["_agent"] = "gpt"
    parsed["_source"] = "gpt"
    parsed["_debug_error"] = None
    parsed.setdefault("regime", regime)
    parsed.setdefault("confidence_score", 50)
    parsed.setdefault("cash_action", "KEEP")
    parsed.setdefault("risk_level", "MODERATE")
    parsed.setdefault("reason_codes", [])
    parsed.setdefault("recommended_actions", FALLBACK["recommended_actions"])
    parsed.setdefault("recommended_actions", FALLBACK["recommended_actions"])
    return parsed
