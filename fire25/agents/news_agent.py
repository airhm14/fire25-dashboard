# -*- coding: utf-8 -*-
"""News Agent — Gemini를 활용한 뉴스 구조화 + digest 생성.

입력: news_items (id/title/source/date/content)
출력: macro_events + macro_summary + digest (asset_bias, top_signals)
캐시: 파일 기반 (fire25/cache/news_snapshot_{hash}.json)

SDK: google-genai (기존 gemini_agent.py와 동일 — google-generativeai 아님)
모델: gemini-1.5-flash (비용 효율)
온도: 0 (deterministic)

파싱 실패 시 1회 재시도, 그 후 fallback 반환.
severity 1~5, asset_bias -2~+2 범위 강제 클리핑.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import streamlit as st

from fire25.ai.model_registry import get_model_name


def _load_api_key(key_name: str) -> str:
    # 1순위: st.secrets
    try:
        val = st.secrets[key_name]
        if val:
            return val
    except Exception:
        pass
    # 2순위: 환경변수
    return os.environ.get(key_name, "")

# ── 상수 ─────────────────────────────────────────────────────────
_MODEL_DEFAULT: str = get_model_name("gemini")
_CACHE_DIR: Path = Path(__file__).parent.parent / "cache"
_ASSETS: list[str] = ["QQQM", "SCHD", "IAU", "SGOV"]

_SYSTEM_PROMPT: str = (
    "당신은 TEAM FIRE 25 투자 전략 시스템의 뉴스 분석 에이전트입니다.\n"
    "아래 뉴스들을 분석하여 반드시 JSON만 반환하세요.\n"
    "다른 설명, 마크다운, 코드블록 없이 순수 JSON만 반환합니다.\n"
    "관련 자산: QQQM (미국 나스닥 ETF), SCHD (배당 ETF), IAU (금 ETF), SGOV (단기채 ETF)"
)

_FALLBACK: dict[str, Any] = {
    "news_snapshot_hash": "",
    "cache_hit": False,
    "macro_events": [],
    "macro_summary": {
        "macro_bias": "neutral",
        "risk_sentiment": "",
        "asset_bias": {"QQQM": 0, "SCHD": 0, "IAU": 0, "SGOV": 0},
    },
    "digest": {
        "top_signals": [],
        "one_line_summary": "뉴스 분석 불가 — API 오류 또는 데이터 부족",
    },
    "error": None,
}

# ── JSON 스키마 (프롬프트용) ────────────────────────────────────────
_OUTPUT_SCHEMA: dict = {
    "macro_events": [
        {
            "event_type": "FED_POLICY|INFLATION|EMPLOYMENT|TECH_AI|GEOPOLITICAL|MARKET_STRESS|YIELD|OTHER",
            "title": "뉴스 제목",
            "impact_direction": "bullish|bearish|neutral",
            "severity": "1~5 정수",
            "asset_relevance": ["해당 자산 — QQQM/SCHD/IAU/SGOV 중 선택"],
            "source": "출처",
            "date": "날짜 (YYYY-MM-DD)",
            "summary": "한국어 1문장 팩트 요약",
        }
    ],
    "macro_summary": {
        "macro_bias": "risk_on|risk_off|neutral",
        "risk_sentiment": "전반적 시장 심리 한국어 1문장",
        "asset_bias": {
            "QQQM": "-2~+2 정수 (-2:강매도, -1:약매도, 0:중립, +1:약매수, +2:강매수)",
            "SCHD": "-2~+2 정수",
            "IAU": "-2~+2 정수",
            "SGOV": "-2~+2 정수",
        },
    },
    "digest": {
        "top_signals": [
            {
                "rank": "1~3 정수",
                "signal": "신호 제목 (간결하게)",
                "impact": "bullish|bearish|neutral",
                "reason": "한국어 이유 1문장",
            }
        ],
        "one_line_summary": "오늘 시장 핵심 한 줄 요약 (한국어)",
    },
}


# ── 캐시 I/O ─────────────────────────────────────────────────────

def _compute_cache_key(news_items: list[dict]) -> str:
    """sorted news ids → SHA256 해시 (16자).

    id 필드 없으면 title을 fallback으로 사용.
    """
    ids = sorted(
        str(item.get("id", "") or item.get("title", "")).strip()
        for item in news_items
    )
    raw = json.dumps(ids, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(hash_key: str) -> Path:
    """캐시 파일 경로."""
    return _CACHE_DIR / f"news_snapshot_{hash_key}.json"


def _load_cache(hash_key: str) -> dict | None:
    """파일 캐시 조회. 없거나 손상 시 None 반환."""
    path = _cache_path(hash_key)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(hash_key: str, data: dict) -> None:
    """파일 캐시 저장. 실패해도 예외 발생하지 않음."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(hash_key)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 전처리 ───────────────────────────────────────────────────────

def _dedup_and_sort(news_items: list[dict]) -> list[dict]:
    """id 기준 중복 제거, date-title 기준 deterministic 정렬.

    Args:
        news_items: 원본 뉴스 항목 목록.

    Returns:
        중복 제거 + 정렬된 뉴스 항목 목록.
    """
    seen: set[str] = set()
    unique: list[dict] = []
    for item in news_items:
        key = str(item.get("id", "") or item.get("title", "")).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    # date 내림차순, 동일 date면 title 오름차순 (deterministic)
    unique.sort(
        key=lambda x: (x.get("date", ""), x.get("title", "")),
        reverse=True,
    )
    return unique


# ── 프롬프트 빌더 ─────────────────────────────────────────────────

def _build_user_prompt(news_items: list[dict]) -> str:
    """뉴스 목록 → Gemini user prompt.

    뉴스는 최대 15개로 제한 (토큰 절약), content는 300자 이내.

    Args:
        news_items: 정제된 뉴스 항목 목록.

    Returns:
        Gemini user prompt 문자열.
    """
    news_data = [
        {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "source": item.get("source", ""),
            "date": item.get("date", ""),
            "content": (item.get("content", "") or "")[:300],
        }
        for item in news_items[:15]
    ]

    return (
        "아래 뉴스들을 분석하여 JSON 형식으로 구조화하세요.\n\n"
        "[뉴스 목록]\n"
        f"{json.dumps(news_data, ensure_ascii=False, indent=2)}\n\n"
        "[반환할 JSON 형식 — 이 구조 그대로 출력, 설명 없이 JSON만]\n"
        f"{json.dumps(_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}"
    )


# ── Gemini API 호출 ───────────────────────────────────────────────

def _call_gemini(
    user_prompt: str,
    api_key: str,
    model: str,
) -> tuple[str, str | None]:
    """Gemini API 호출. (text, error) 반환.

    google-genai SDK 사용 (기존 gemini_agent.py와 동일).
    system_instruction으로 system prompt 분리.

    Args:
        user_prompt: 뉴스 + 스키마 포함 user prompt.
        api_key: Gemini API 키.
        model: 모델명 (예: gemini-1.5-flash).

    Returns:
        (응답 텍스트, 오류 코드) — 정상 시 오류 코드 None.
    """
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError:
        return "", "missing_sdk"

    try:
        client = genai.Client(api_key=api_key)
        cfg = types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0,
            top_p=1,
            max_output_tokens=4096,
        )
        resp = client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=cfg,
        )
        # 응답 텍스트 추출 (thinking 모델 대응)
        text = _extract_text(resp)
        if not text or not text.strip():
            return "", "empty_response"
        return text, None
    except Exception as e:
        return "", f"api_error:{type(e).__name__}:{e}"


def _extract_text(response: Any) -> str:
    """google-genai 응답에서 텍스트 추출."""
    try:
        parts = response.candidates[0].content.parts
        for part in parts:
            t = getattr(part, "text", None) or ""
            if t and ("{" in t or "[" in t):
                return t
        for part in parts:
            t = getattr(part, "text", None) or ""
            if t.strip():
                return t
    except Exception:
        pass
    return getattr(response, "text", "") or ""


# ── JSON 파싱 ─────────────────────────────────────────────────────

def _clean_json_text(raw: str) -> str:
    """Gemini 출력 공통 클리닝."""
    s = raw.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = re.sub(r",\s*([}\]])", r"\1", s)  # trailing comma 제거
    s = s.replace("\ufeff", "").replace("\u200b", "")
    return s.strip()


def _parse_json_response(text: str) -> dict | None:
    """Gemini 응답 텍스트 → dict 파싱.

    code block 제거 → 전체 파싱 → { } 블록 추출 순으로 시도.

    Args:
        text: Gemini 응답 텍스트.

    Returns:
        파싱된 dict. 실패 시 None.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # code block 제거
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = (m.group(1) or "").strip()

    raw = _clean_json_text(raw)

    # 전체 파싱 시도
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # { ... } 블록 찾기
    m2 = re.search(r"\{[\s\S]*\}", raw)
    if m2:
        try:
            obj = json.loads(_clean_json_text(m2.group(0)))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    return None


# ── 검증 & 클리핑 ─────────────────────────────────────────────────

def _clip_severity(val: Any) -> int:
    """severity 1~5 범위 클리핑."""
    try:
        return max(1, min(5, int(val)))
    except (TypeError, ValueError):
        return 3


def _clip_asset_bias(val: Any) -> int:
    """asset_bias -2~+2 범위 클리핑."""
    try:
        return max(-2, min(2, int(val)))
    except (TypeError, ValueError):
        return 0


def _validate_impact(val: Any) -> str:
    """impact_direction 허용값 검증."""
    return val if val in {"bullish", "bearish", "neutral"} else "neutral"


def _validate_macro_bias(val: Any) -> str:
    """macro_bias 허용값 검증."""
    return val if val in {"risk_on", "risk_off", "neutral"} else "neutral"


def _validate_and_clip(raw: dict) -> dict:
    """Gemini 출력 전체 검증 및 클리핑.

    - macro_events: severity 클리핑, impact_direction 검증
    - macro_summary: macro_bias 검증, asset_bias 클리핑
    - digest: top_signals impact 검증, rank 정수 보정

    Args:
        raw: Gemini 파싱 결과 dict.

    Returns:
        검증/클리핑된 dict.
    """
    result = dict(raw)

    # macro_events
    events = result.get("macro_events")
    if isinstance(events, list):
        for ev in events:
            if isinstance(ev, dict):
                ev["severity"] = _clip_severity(ev.get("severity", 3))
                ev["impact_direction"] = _validate_impact(ev.get("impact_direction"))
                if not isinstance(ev.get("asset_relevance"), list):
                    ev["asset_relevance"] = []
    else:
        result["macro_events"] = []

    # macro_summary
    ms = result.get("macro_summary")
    if not isinstance(ms, dict):
        ms = {}
    ms["macro_bias"] = _validate_macro_bias(ms.get("macro_bias"))
    if not isinstance(ms.get("risk_sentiment"), str):
        ms["risk_sentiment"] = ""
    ab = ms.get("asset_bias")
    if not isinstance(ab, dict):
        ab = {}
    for asset in _ASSETS:
        ab[asset] = _clip_asset_bias(ab.get(asset, 0))
    ms["asset_bias"] = ab
    result["macro_summary"] = ms

    # digest
    digest = result.get("digest")
    if not isinstance(digest, dict):
        digest = {}
    signals = digest.get("top_signals")
    if isinstance(signals, list):
        for sig in signals:
            if isinstance(sig, dict):
                sig["impact"] = _validate_impact(sig.get("impact"))
                try:
                    sig["rank"] = int(sig.get("rank", 1))
                except (TypeError, ValueError):
                    sig["rank"] = 1
    else:
        digest["top_signals"] = []
    if not isinstance(digest.get("one_line_summary"), str):
        digest["one_line_summary"] = ""
    result["digest"] = digest

    return result


# ── 메인 함수 ─────────────────────────────────────────────────────

def run(
    news_items: list[dict],
    *,
    api_key: str = "",
    model: str = _MODEL_DEFAULT,
) -> dict[str, Any]:
    """뉴스 구조화 + digest 생성.

    처리 흐름:
      1. id 기준 중복 제거, date 기준 정렬
      2. SHA256 캐시 키 생성 (sorted news ids)
      3. 파일 캐시 조회 (hit → 즉시 반환)
      4. Gemini API 호출 (최대 2회 시도)
      5. JSON 파싱 + 검증/클리핑
      6. 파일 캐시 저장

    Args:
        news_items: 뉴스 항목 목록. 각 항목: {id, title, source, date, content}.
        api_key: Gemini API 키. 미입력 시 환경변수 GEMINI_API_KEY 사용.
        model: Gemini 모델명. 기본값 gemini-1.5-flash.

    Returns:
        dict:
            news_snapshot_hash (str): 캐시 키.
            cache_hit (bool): 파일 캐시 적중 여부.
            macro_events (list): 구조화된 이벤트 목록.
            macro_summary (dict): macro_bias, risk_sentiment, asset_bias.
            digest (dict): top_signals, one_line_summary.
            error (str|None): 오류 코드 (정상 시 None).
    """
    _api_key = str(api_key or _load_api_key("GEMINI_API_KEY")).strip()

    if not news_items:
        return {**_FALLBACK, "error": "no_news_items"}

    # 1. 전처리
    clean_items = _dedup_and_sort(news_items)

    # 2. 캐시 키
    hash_key = _compute_cache_key(clean_items)

    # 3. 파일 캐시 조회
    cached = _load_cache(hash_key)
    if cached is not None:
        cached["cache_hit"] = True
        cached["news_snapshot_hash"] = hash_key
        return cached

    # 4. API 키 없으면 fallback
    if not _api_key:
        return {**_FALLBACK, "news_snapshot_hash": hash_key, "error": "missing_api_key"}

    # 5. 프롬프트 생성
    user_prompt = _build_user_prompt(clean_items)

    # 6. Gemini 호출 (최대 2회)
    parsed: dict | None = None
    last_error: str | None = None

    for attempt in range(2):
        text, err = _call_gemini(user_prompt, _api_key, model)
        if err:
            last_error = err
            if err == "missing_sdk":
                break
            continue
        parsed = _parse_json_response(text)
        if parsed is not None:
            break
        last_error = f"parse_error_attempt_{attempt + 1}|{(text or '')[:120]}"

    if parsed is None:
        return {
            **_FALLBACK,
            "news_snapshot_hash": hash_key,
            "error": last_error or "parse_failed",
        }

    # 7. 검증 + 클리핑
    validated = _validate_and_clip(parsed)

    result: dict[str, Any] = {
        "news_snapshot_hash": hash_key,
        "cache_hit": False,
        "macro_events": validated.get("macro_events", []),
        "macro_summary": validated.get("macro_summary", _FALLBACK["macro_summary"]),
        "digest": validated.get("digest", _FALLBACK["digest"]),
        "error": None,
    }

    # 8. 파일 캐시 저장
    _save_cache(hash_key, result)

    return result
