# -*- coding: utf-8 -*-
"""Signal Conflict Analyzer — 지표 충돌 해석 에이전트 (Claude).

충돌 감지 → Claude 해석 → 캐시 저장 흐름.
Claude는 해석·설명 엔진으로만 동작 (실행 지시 금지).

충돌 감지 규칙 (5종, Claude 호출 전 자동 판정):
  1. QQQM MA50 위 + 뉴스 risk_off
  2. QQQM MA200 아래 + 뉴스 risk_on
  3. macro bullish + active_alerts 2개 이상
  4. Regime=NORMAL + VIX >= 25
  5. 뉴스 QQQM 매수 편향 + MA50 이탈 차단

캐시: fire25/cache/signal_analysis_{hash}.json
SDK: anthropic (기존 claude_macro.py와 동일)
모델: claude-sonnet-4-6
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from fire25.utils.api_keys import get_api_key
from typing import Any

# ── 상수 ─────────────────────────────────────────────────────────
_MODEL_DEFAULT: str = "claude-sonnet-4-6"
_CACHE_DIR: Path = Path(__file__).parent.parent / "cache"

# 직접 지시 금지어 패턴 (suggestion 후처리용)
_FORBIDDEN_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"매수하세요"), "매수 여부를 검토해보세요"),
    (re.compile(r"매도하세요"), "매도 여부를 검토해보세요"),
    (re.compile(r"팔아야\s*합니다"), "매도 검토가 필요할 수 있습니다"),
    (re.compile(r"사야\s*합니다"), "매수 검토가 필요할 수 있습니다"),
    (re.compile(r"즉시\s*매수"), "단계적 매수 검토"),
    (re.compile(r"즉시\s*매도"), "단계적 매도 검토"),
]

_SYSTEM_PROMPT: str = """당신은 TEAM FIRE 25 투자 전략 시스템의 신호 해석 에이전트입니다.

TEAM FIRE 25 핵심 원칙:
- QQQM이 core 자산 (기본 HOLD, 80% 상한)
- Regime 기반 의사결정 (NORMAL / PUDDLE / DEFCON / SMART_SHOULDER)
- PUDDLE = 200일 이평선 하향 돌파 시 단계적 매수
- 동일 단계 재매수 금지, 30 trading days 쿨다운
- 최종 결정은 항상 사람이 한다

당신의 역할:
- 지표 간 충돌 상황을 해석하고 설명한다
- 과거 유사 국면과 비교한다
- 전략 방향의 논리적 일관성을 검토한다
- 매수/매도를 직접 지시하지 않는다
- 반드시 JSON만 반환한다 (마크다운, 코드블록 금지)"""

_FALLBACK_ANALYSIS: dict[str, Any] = {
    "situation_summary": "신호 분석 불가 — API 오류 또는 데이터 부족",
    "conflicting_signals": [],
    "historical_analogy": "",
    "strategy_consistency": "caution",
    "key_risk": "",
    "suggestion": "지표 데이터를 직접 확인하시기 바랍니다.",
}


# ── 충돌 감지 (5규칙) ─────────────────────────────────────────────

def _detect_conflict(payload: dict) -> tuple[bool, str]:
    """5가지 규칙 기반 충돌 감지. (conflict, conflict_type) 반환.

    충돌 조건 중 하나라도 해당하면 True.
    Claude 호출 전에 실행 — 불필요한 API 호출 방지.

    Args:
        payload: signal_analyzer 입력 dict.

    Returns:
        (conflict_detected, conflict_type_string).
    """
    signals = payload.get("signals") or {}
    tech = signals.get("technical") or {}
    macro = signals.get("macro") or {}
    news = signals.get("news") or {}
    regime = str(payload.get("regime") or "")
    active_blocks = payload.get("active_blocks") or []
    active_alerts = payload.get("active_alerts") or []

    vix = float(tech.get("vix", 0))
    ma50_pos = str(tech.get("qqqm_vs_ma50", "above"))
    ma200_pos = str(tech.get("qqqm_vs_ma200", "above"))
    news_macro_bias = str(news.get("macro_bias", "neutral"))
    macro_bias = str(macro.get("macro_bias", "neutral"))
    asset_bias_qqqm = int(news.get("asset_bias_qqqm", 0))

    conflicts: list[str] = []

    # 규칙 1: MA50 위 + 뉴스 risk_off (기술적 강세 ↔ 뉴스 약세)
    if ma50_pos == "above" and news_macro_bias == "risk_off":
        conflicts.append("TECH_ABOVE_NEWS_RISK_OFF")

    # 규칙 2: MA200 아래 + 뉴스 risk_on (기술적 약세 ↔ 뉴스 강세)
    if ma200_pos == "below" and news_macro_bias == "risk_on":
        conflicts.append("TECH_BELOW_NEWS_RISK_ON")

    # 규칙 3: macro bullish + alert 2개 이상 (거시 낙관 ↔ 복수 경보)
    if macro_bias == "bullish" and len(active_alerts) >= 2:
        conflicts.append("MACRO_BULLISH_MULTI_ALERT")

    # 규칙 4: NORMAL + VIX >= 25 (정상 국면 판정 ↔ 고변동성)
    if regime == "NORMAL" and vix >= 25:
        conflicts.append("NORMAL_REGIME_HIGH_VIX")

    # 규칙 5: 뉴스 QQQM 매수 편향 + MA50 이탈 차단 (매수 신호 ↔ 기술적 차단)
    if asset_bias_qqqm >= 1 and "QQQM_MA50_BREAK" in active_blocks:
        conflicts.append("NEWS_BUY_SIGNAL_MA50_BLOCKED")

    if not conflicts:
        return False, ""

    return True, " | ".join(conflicts)


# ── 캐시 I/O ─────────────────────────────────────────────────────

def _compute_cache_key(payload: dict) -> str:
    """입력 payload → SHA256 해시 (16자).

    regime + puddle_stage + signals 기반 해시 (deterministic).
    """
    key_data = {
        "regime": payload.get("regime"),
        "puddle_stage": payload.get("puddle_stage"),
        "signals": payload.get("signals"),
        "active_blocks": sorted(payload.get("active_blocks") or []),
        "active_alerts": sorted(payload.get("active_alerts") or []),
    }
    raw = json.dumps(key_data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(hash_key: str) -> Path:
    return _CACHE_DIR / f"signal_analysis_{hash_key}.json"


def _load_cache(hash_key: str) -> dict | None:
    """파일 캐시 조회. 없거나 손상 시 None."""
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
        with _cache_path(hash_key).open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── Claude API 호출 ───────────────────────────────────────────────

def _build_user_prompt(payload: dict, conflict_type: str) -> str:
    """신호 데이터 + 충돌 유형 → Claude user prompt.

    Args:
        payload: signal_analyzer 입력 dict.
        conflict_type: 감지된 충돌 유형 문자열.

    Returns:
        Claude user prompt 문자열.
    """
    schema = {
        "situation_summary": "현재 신호 충돌 상황 요약 (한국어 2~3문장)",
        "conflicting_signals": [
            {
                "signal_a": "신호 A 이름",
                "signal_b": "신호 B 이름",
                "interpretation": "두 신호가 충돌하는 이유와 의미 (한국어 1문장)",
            }
        ],
        "historical_analogy": "유사 과거 국면 예시 및 당시 결과 (한국어 1~2문장)",
        "strategy_consistency": "consistent|caution|inconsistent",
        "key_risk": "현재 국면의 핵심 리스크 (한국어 1문장)",
        "suggestion": "검토 권고사항 — '검토해보세요', '주의가 필요합니다' 형태 (한국어 1~2문장)",
    }

    return (
        "아래 투자 신호 데이터에서 충돌이 감지되었습니다. 해석해주세요.\n\n"
        f"[감지된 충돌 유형]\n{conflict_type}\n\n"
        "[신호 데이터]\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "[출력 형식 — JSON만 반환, 설명 없음]\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}"
    )


def _call_claude(
    user_prompt: str,
    api_key: str,
    model: str,
) -> tuple[str, str | None]:
    """Claude API 호출. (text, error) 반환.

    system_prompt와 user_prompt 분리 사용.

    Args:
        user_prompt: 신호 데이터 + 스키마 포함 user prompt.
        api_key: Anthropic API 키.
        model: 모델명.

    Returns:
        (응답 텍스트, 오류 코드) — 정상 시 오류 None.
    """
    try:
        import anthropic  # type: ignore
    except ImportError:
        return "", "missing_sdk"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=1000,
            temperature=0,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            timeout=30.0,
        )
        text = msg.content[0].text or ""
        if not text.strip():
            return "", "empty_response"
        return text, None
    except Exception as e:
        return "", f"api_error:{type(e).__name__}:{e}"


# ── JSON 파싱 ─────────────────────────────────────────────────────

def _parse_json_response(text: str) -> dict | None:
    """Claude 응답 텍스트 → dict 파싱.

    code block 제거 → 전체 파싱 → { } 블록 추출 순으로 시도.
    """
    raw = (text or "").strip()
    if not raw:
        return None

    # code block 제거
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = (m.group(1) or "").strip()

    # trailing comma 제거
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    raw = raw.replace("\u201c", '"').replace("\u201d", '"')

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    m2 = re.search(r"\{[\s\S]*\}", raw)
    if m2:
        try:
            obj = json.loads(re.sub(r",\s*([}\]])", r"\1", m2.group(0)))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    return None


# ── suggestion 금지어 sanitizer ──────────────────────────────────

def _sanitize_suggestion(text: str) -> tuple[str, bool]:
    """suggestion에서 직접 지시 금지어를 소프트 표현으로 치환.

    TEAM FIRE 25 원칙: 최종 결정은 항상 사람이 한다.
    Claude가 직접 매수/매도 지시를 포함하는 경우 자동 치환.

    Args:
        text: suggestion 원문.

    Returns:
        (치환된 텍스트, 치환 발생 여부).
    """
    modified = False
    result = str(text or "")
    for pattern, replacement in _FORBIDDEN_PATTERNS:
        new_text, count = pattern.subn(replacement, result)
        if count > 0:
            result = new_text
            modified = True
    return result, modified


# ── 출력 검증 ─────────────────────────────────────────────────────

def _validate_output(raw: dict) -> dict:
    """Claude 출력 구조 검증 및 정규화.

    Args:
        raw: 파싱된 Claude 응답 dict.

    Returns:
        검증/정규화된 dict.
    """
    result = dict(raw)

    # strategy_consistency 허용값 검증
    sc = result.get("strategy_consistency", "caution")
    if sc not in {"consistent", "caution", "inconsistent"}:
        result["strategy_consistency"] = "caution"

    # suggestion 금지어 sanitize
    suggestion = str(result.get("suggestion", ""))
    sanitized, was_modified = _sanitize_suggestion(suggestion)
    result["suggestion"] = sanitized
    if was_modified:
        result["_suggestion_sanitized"] = True

    # conflicting_signals 타입 보정
    if not isinstance(result.get("conflicting_signals"), list):
        result["conflicting_signals"] = []

    # 필수 문자열 필드 기본값
    for field in ("situation_summary", "historical_analogy", "key_risk"):
        if not isinstance(result.get(field), str):
            result[field] = ""

    return result


# ── 메인 함수 ─────────────────────────────────────────────────────

def analyze(
    payload: dict,
    *,
    api_key: str = "",
    model: str = _MODEL_DEFAULT,
) -> dict[str, Any]:
    """지표 충돌 감지 + Claude 해석.

    처리 흐름:
      1. 충돌 5규칙 자동 판정 (conflict_detected)
      2. conflict=False → Claude 미호출, 즉시 반환
      3. 캐시 키 생성 + 파일 캐시 조회
      4. Claude API 호출 (최대 2회 시도)
      5. JSON 파싱 + 검증 + suggestion sanitize
      6. 파일 캐시 저장

    Args:
        payload: 신호 데이터 dict (regime/signals/active_blocks 등).
        api_key: Anthropic API 키. 미입력 시 환경변수 ANTHROPIC_API_KEY 사용.
        model: Claude 모델명. 기본값 claude-sonnet-4-6.

    Returns:
        dict:
            conflict_detected (bool): 충돌 감지 여부.
            conflict_type (str): 충돌 유형 코드 (미감지 시 빈 문자열).
            claude_analysis (dict|None): Claude 해석 결과 (미감지 시 None).
            cache_hit (bool): 파일 캐시 적중 여부.
            analysis_hash (str): 캐시 키.
    """
    _api_key = str(api_key or get_api_key("ANTHROPIC_API_KEY")).strip()

    # 1. 충돌 감지
    conflict_detected, conflict_type = _detect_conflict(payload)

    if not conflict_detected:
        return {
            "conflict_detected": False,
            "conflict_type": "",
            "claude_analysis": None,
            "cache_hit": False,
            "analysis_hash": "",
        }

    # 2. 캐시 키
    hash_key = _compute_cache_key(payload)

    # 3. 파일 캐시 조회
    cached = _load_cache(hash_key)
    if cached is not None:
        cached["cache_hit"] = True
        cached["analysis_hash"] = hash_key
        return cached

    # 4. API 키 없으면 fallback
    if not _api_key:
        return {
            "conflict_detected": True,
            "conflict_type": conflict_type,
            "claude_analysis": {
                **_FALLBACK_ANALYSIS,
                "_error": "missing_api_key",
            },
            "cache_hit": False,
            "analysis_hash": hash_key,
        }

    # 5. Claude 호출 (최대 2회)
    user_prompt = _build_user_prompt(payload, conflict_type)
    parsed: dict | None = None
    last_error: str | None = None

    for attempt in range(2):
        text, err = _call_claude(user_prompt, _api_key, model)
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
            "conflict_detected": True,
            "conflict_type": conflict_type,
            "claude_analysis": {
                **_FALLBACK_ANALYSIS,
                "_error": last_error or "parse_failed",
            },
            "cache_hit": False,
            "analysis_hash": hash_key,
        }

    # 6. 검증 + sanitize
    validated = _validate_output(parsed)

    result: dict[str, Any] = {
        "conflict_detected": True,
        "conflict_type": conflict_type,
        "claude_analysis": validated,
        "cache_hit": False,
        "analysis_hash": hash_key,
    }

    # 7. 캐시 저장
    _save_cache(hash_key, result)

    return result
