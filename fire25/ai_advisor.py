from __future__ import annotations

import json
import re
from typing import Any


AI_PROMPT_TEMPLATE = """
당신은 TEAM FIRE 25 Dashboard의 거시 투자 보조 AI입니다.

규칙:
- 입력으로 제공된 요약 신호만 사용하세요.
- 사실을 추가로 발명하지 마세요.
- 투자 자문(매수/매도 단정 명령)을 하지 마세요.
- 한국어로 짧고 명확하게 작성하세요.
- 각 항목은 1~2문장 이내로 작성하세요.

출력은 반드시 JSON만 반환하세요.
스키마:
{
  "market_view": "",
  "shield_alert": "",
  "dip_signal": "",
  "action": ""
}

입력 컨텍스트:
{context_json}
""".strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def build_context(
    portfolio_weight: dict | None,
    target_weight: dict | None,
    recent_buys: list | None,
    cash_level: str,
    vix: float | int | None,
    fear_greed: float | int | None,
    qqqm_rsi: float | int | None,
    qqqm_sma200_gap: float | int | None,
    treasury_10y: float | int | None,
    oil_price: float | int | None,
    macro_summary: str,
    top_news_summary: str,
    market_regime: str,
) -> dict:
    """Build compact structured context for the AI advisor layer."""
    return {
        "portfolio_weight": _safe_dict(portfolio_weight),
        "target_weight": _safe_dict(target_weight),
        "recent_buys": _safe_list(recent_buys),
        "cash_level": str(cash_level or "미확인"),
        "VIX": _safe_float(vix, 20.0),
        "fear_greed": _safe_float(fear_greed, 50.0),
        "QQQM_RSI": _safe_float(qqqm_rsi, 50.0),
        "QQQM_SMA200_gap": _safe_float(qqqm_sma200_gap, 0.0),
        "10Y_treasury": _safe_float(treasury_10y, 0.0),
        "oil_price": _safe_float(oil_price, 0.0),
        "macro_summary": str(macro_summary or ""),
        "top_news_summary": str(top_news_summary or ""),
        "market_regime": str(market_regime or ""),
    }


def parse_ai_output(text: str) -> dict | None:
    """Parse JSON output from model safely."""
    raw = (text or "").strip()
    if not raw:
        return None

    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*", "", raw).strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()

    try:
        parsed = json.loads(raw)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return None
        try:
            parsed = json.loads(m.group(0))
        except Exception:
            return None

    if not isinstance(parsed, dict):
        return None

    result = {
        "market_view": str(parsed.get("market_view", "")).strip(),
        "shield_alert": str(parsed.get("shield_alert", "")).strip(),
        "dip_signal": str(parsed.get("dip_signal", "")).strip(),
        "action": str(parsed.get("action", "")).strip(),
    }

    if not any(result.values()):
        return None
    return result


def generate_ai_analysis(
    context: dict,
    api_key: str,
    model: str = "gpt-4.1-mini",
    timeout: float = 20.0,
) -> dict | None:
    """Call OpenAI and return parsed structured analysis."""
    if not str(api_key or "").strip():
        return None

    try:
        from openai import OpenAI
    except Exception:
        return None

    client = OpenAI(api_key=api_key)
    prompt = AI_PROMPT_TEMPLATE.format(
        context_json=json.dumps(context, ensure_ascii=False)
    )

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt}
                    ],
                }
            ],
            timeout=timeout,
        )
    except Exception:
        return None

    text = ""
    try:
        text = response.output_text or ""
    except Exception:
        text = ""

    return parse_ai_output(text)


def get_ai_advice(
    context: dict,
    api_key: str,
    model: str = "gpt-4.1-mini",
) -> dict:
    """Main entry: returns robust, always-usable advice payload."""
    fallback = {
        "market_view": "시장 데이터는 혼조입니다. 핵심 지표 확인이 필요합니다.",
        "shield_alert": "방어 신호는 중립입니다. 변동성 급등 여부를 점검하세요.",
        "dip_signal": "웅줍 신호는 보조 지표와 함께 확인하세요.",
        "action": "현금 비중과 목표 비중을 유지하며 단계적으로 대응하세요.",
    }

    parsed = generate_ai_analysis(context=context, api_key=api_key, model=model)
    if not parsed:
        return fallback

    result = {
        "market_view": parsed.get("market_view") or fallback["market_view"],
        "shield_alert": parsed.get("shield_alert") or fallback["shield_alert"],
        "dip_signal": parsed.get("dip_signal") or fallback["dip_signal"],
        "action": parsed.get("action") or fallback["action"],
    }
    return result
