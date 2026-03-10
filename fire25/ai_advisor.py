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
{{
    "market_view": "",
    "shield_alert": "",
    "dip_signal": "",
    "action": ""
}}

입력 컨텍스트:
{context_json}
""".strip()


PROMPT_ERROR_FALLBACK = {
        "market_view": "AI 분석을 생성하지 못했습니다.",
        "shield_alert": "프롬프트 오류",
        "dip_signal": "확인 필요",
        "action": "설정을 점검하세요.",
}


GENERAL_FALLBACK = {
        "market_view": "시장 데이터는 혼조입니다. 핵심 지표 확인이 필요합니다.",
        "shield_alert": "방어 신호는 중립입니다. 변동성 급등 여부를 점검하세요.",
        "dip_signal": "웅줍 신호는 보조 지표와 함께 확인하세요.",
        "action": "현금 비중과 목표 비중을 유지하며 단계적으로 대응하세요.",
}


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

    # Try raw text first, then fenced code blocks, and extract the first valid JSON object.
    candidates: list[str] = [raw]
    for m in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE):
        block = (m.group(1) or "").strip()
        if block:
            candidates.append(block)

    decoder = json.JSONDecoder()
    parsed: dict | None = None
    for candidate in candidates:
        cleaned = candidate.strip()
        if not cleaned:
            continue

        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                parsed = obj
                break
        except Exception:
            pass

        for i, ch in enumerate(cleaned):
            if ch != "{":
                continue
            try:
                obj, _ = decoder.raw_decode(cleaned[i:])
                if isinstance(obj, dict):
                    parsed = obj
                    break
            except Exception:
                continue
        if parsed is not None:
            break

    if parsed is None:
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

def _build_prompt(context: dict) -> str:
    """Build model prompt safely without crashing on formatting issues."""
    try:
        context_json = json.dumps(context or {}, ensure_ascii=False)
        return AI_PROMPT_TEMPLATE.format(context_json=context_json)
    except Exception as exc:
        raise ValueError("prompt_generation_error") from exc


def generate_ai_analysis(
    context: dict,
    api_key: str,
    model: str = "gpt-4o-mini",
    timeout: float = 20.0,
    debug: bool = False,
) -> tuple[dict | None, str | None]:
    """Call OpenAI and return parsed structured analysis."""
    if not str(api_key or "").strip():
        return None, "missing_api_key"

    try:
        from openai import OpenAI
    except Exception:
        return None, "missing_openai_sdk"

    try:
        client = OpenAI(api_key=api_key)
    except Exception as e:
        return None, f"api_error:{type(e).__name__}:{str(e)}"
    try:
        prompt = _build_prompt(context)
    except Exception:
        return None, "prompt_generation_error"

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            timeout=timeout,
        )
    except Exception as e:
        return None, f"api_error:{type(e).__name__}:{str(e)}"

    text = ""
    try:
        text = response.output_text or ""
    except Exception:
        text = ""

    response_id = getattr(response, "id", None)
    usage = getattr(response, "usage", None)
    total_tokens = getattr(usage, "total_tokens", None) if usage is not None else None

    print("OPENAI RESPONSE ID:", response_id)
    if hasattr(response, "usage") and response.usage is not None:
        print("INPUT TOKENS:", response.usage.input_tokens)
        print("OUTPUT TOKENS:", response.usage.output_tokens)
        print("TOTAL TOKENS:", response.usage.total_tokens)

    print("AI RAW RESPONSE:", text)

    parsed = parse_ai_output(text)
    if not parsed:
        return None, "parse_error"

    parsed = dict(parsed)
    if response_id:
        parsed["_response_id"] = str(response_id)
    if total_tokens is not None:
        parsed["_usage_tokens"] = int(total_tokens)

    if debug:
        parsed["_ai_raw"] = text
    return parsed, None


def get_ai_advice(
    context: dict,
    api_key: str,
    model: str = "gpt-4o-mini",
) -> dict:
    """Main entry: returns robust, always-usable advice payload."""
    try:
        parsed, error_code = generate_ai_analysis(context=context, api_key=api_key, model=model)
        if error_code == "prompt_generation_error":
            out = dict(PROMPT_ERROR_FALLBACK)
            out["_ai_source"] = "fallback"
            out["_debug_error"] = "prompt_generation_error"
            return out

        if not parsed:
            out = dict(GENERAL_FALLBACK)
            out["_ai_source"] = "fallback"
            out["_debug_error"] = error_code
            return out

        out = {
            "market_view": parsed.get("market_view") or GENERAL_FALLBACK["market_view"],
            "shield_alert": parsed.get("shield_alert") or GENERAL_FALLBACK["shield_alert"],
            "dip_signal": parsed.get("dip_signal") or GENERAL_FALLBACK["dip_signal"],
            "action": parsed.get("action") or GENERAL_FALLBACK["action"],
            "_ai_source": "openai",
            "_debug_error": None,
        }
        if parsed.get("_response_id"):
            out["_response_id"] = parsed.get("_response_id")
        if parsed.get("_usage_tokens") is not None:
            out["_usage_tokens"] = parsed.get("_usage_tokens")
        return out
    except Exception:
        # Never let AI layer crash Streamlit dashboard.
        out = dict(PROMPT_ERROR_FALLBACK)
        out["_ai_source"] = "fallback"
        out["_debug_error"] = "unexpected_exception"
        return out
