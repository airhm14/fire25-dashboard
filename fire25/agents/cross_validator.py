# -*- coding: utf-8 -*-
"""Cross Validator — ChatGPT o1 교차 검증 에이전트.

Claude 신호 충돌 해석을 수치·확률 관점에서 독립 검증.
conflict_detected=True일 때만 실행한다.

모델: o1 (기본값), fallback: gpt-4o
온도 파라미터 미사용 (o1 특성).
캐시: fire25/cache/cross_validation_{hash}.json
SDK: openai (gpt_agent.py와 동일)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import streamlit as st


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
_MODEL_PRIMARY: str = "o1"
_MODEL_FALLBACK: str = "gpt-4o"
_CACHE_DIR: Path = Path(__file__).parent.parent / "cache"
_MAX_COMPLETION_TOKENS: int = 4096

# QQQM 80% 상한 위반 감지용 패턴
_QQQM_CAP_PATTERN: re.Pattern = re.compile(
    r"QQQM[^0-9]*?([89]\d|\d{3,})\s*%", re.IGNORECASE
)

_SYSTEM_PROMPT: str = """당신은 TEAM FIRE 25 투자 전략 시스템의 교차 검증 에이전트입니다.

역할:
- Claude가 생성한 신호 충돌 해석을 수치·확률 관점에서 독립 검증한다
- 감성적 판단이 아니라 데이터 기반으로만 판단한다
- TEAM FIRE 25 규칙 위반 여부를 체크한다
- 매수/매도를 직접 지시하지 않는다
- 반드시 JSON만 반환한다 (마크다운, 코드블록 금지)

TEAM FIRE 25 핵심 규칙 (위반 체크용):
- QQQM 80% 상한
- 동일 PUDDLE 단계 재매수 금지
- QQQM SELL은 Smart Shoulder 또는 구조적 시장 붕괴 시만 허용
- 최종 결정은 항상 사람이 한다"""

_OUTPUT_SCHEMA: str = """{
  "validation_result": "agree|partial|disagree",
  "confidence_score": 0~100 정수,
  "quantitative_check": {
    "vix_context": "VIX 수준 해석 한 줄",
    "yield_curve_context": "금리차 해석 한 줄",
    "drawdown_context": "낙폭 해석 한 줄",
    "technical_alignment": "aligned|mixed|conflicting"
  },
  "rule_violations": [],
  "risk_adjustment": "increase|maintain|decrease",
  "divergence_from_claude": "Claude와 다른 점 (없으면 빈 문자열)",
  "final_note": "한 줄 요약"
}"""

_FALLBACK_VALIDATION: dict[str, Any] = {
    "validation_result": "partial",
    "confidence_score": 50,
    "quantitative_check": {
        "vix_context": "API 오류로 분석 불가",
        "yield_curve_context": "API 오류로 분석 불가",
        "drawdown_context": "API 오류로 분석 불가",
        "technical_alignment": "mixed",
    },
    "rule_violations": [],
    "risk_adjustment": "maintain",
    "divergence_from_claude": "",
    "final_note": "교차 검증 불가 — API 오류 또는 데이터 부족",
}

_NOT_REQUIRED: dict[str, Any] = {
    "validation_result": "not_required",
    "confidence_score": None,
    "cache_hit": False,
    "validation_hash": "",
}


# ── 규칙 위반 사전 감지 ───────────────────────────────────────────

def _pre_check_rule_violations(payload: dict) -> list[str]:
    """API 호출 없이 입력 데이터 기반으로 규칙 위반을 사전 감지.

    o1 API를 거치지 않고도 명백한 위반을 감지할 수 있는 경우를 처리.
    """
    violations: list[str] = []
    ca = payload.get("claude_analysis") or {}
    suggestion = str(ca.get("suggestion") or "")

    # QQQM 80% 상한 위반: suggestion에서 QQQM + 81% 이상 언급 감지
    for m in _QQQM_CAP_PATTERN.finditer(suggestion):
        try:
            pct = int(m.group(1))
            if pct > 80:
                violations.append("QQQM_CAP_VIOLATION")
                break
        except ValueError:
            pass

    return violations


# ── 캐시 I/O ─────────────────────────────────────────────────────

def _compute_cache_key(payload: dict) -> str:
    """입력 payload → SHA256 해시 (16자).

    signals + regime + claude_analysis 기반 (deterministic).
    """
    key_data = {
        "regime": payload.get("regime"),
        "signals": payload.get("signals"),
        "claude_analysis": payload.get("claude_analysis"),
        "active_blocks": sorted(payload.get("active_blocks") or []),
        "active_alerts": sorted(payload.get("active_alerts") or []),
    }
    raw = json.dumps(key_data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_path(hash_key: str) -> Path:
    return _CACHE_DIR / f"cross_validation_{hash_key}.json"


def _load_cache(hash_key: str) -> dict | None:
    path = _cache_path(hash_key)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(hash_key: str, data: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _cache_path(hash_key).open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 프롬프트 빌더 ─────────────────────────────────────────────────

def _build_prompt(payload: dict) -> str:
    """시스템 지침 + 입력 데이터 + 출력 스키마를 단일 user 메시지로 조합.

    o1은 system role을 별도 지원하지 않으므로 user 메시지에 통합.
    """
    signals = payload.get("signals") or {}
    tech = signals.get("technical") or {}
    macro = signals.get("macro") or {}
    news = signals.get("news") or {}
    ca = payload.get("claude_analysis") or {}
    puddle = payload.get("puddle_sizing")

    puddle_block = ""
    if puddle:
        puddle_block = f"""
[PUDDLE 비중 산출]
- 단계: PUDDLE_{puddle.get('puddle_stage', '?')}
- 기준 비중: {puddle.get('base_pct', 0)}%
- 동적 계수: {puddle.get('coefficient', 1.0)}
- 적용 비중: {puddle.get('capped_pct', 0)}%"""

    blocks_str = ", ".join(payload.get("active_blocks") or []) or "없음"
    alerts_str = ", ".join(payload.get("active_alerts") or []) or "없음"

    return f"""{_SYSTEM_PROMPT}

---

[검증 대상 입력 데이터]

Regime: {payload.get('regime', 'UNKNOWN')}

[기술적 신호]
- QQQM vs MA50: {tech.get('qqqm_vs_ma50', 'unknown')}
- QQQM vs MA200: {tech.get('qqqm_vs_ma200', 'unknown')}
- VIX: {tech.get('vix', 0)}
- 200MA 낙폭: {tech.get('drawdown_from_200ma', 0):.1%} (0.0이면 미제공)

[거시 신호]
- 매크로 편향: {macro.get('macro_bias', 'neutral')}
- 10Y-2Y 스프레드: {macro.get('spread_10y_2y', 0):.2f}

[뉴스 신호]
- 뉴스 매크로 편향: {news.get('macro_bias', 'neutral')}
- QQQM 자산 편향: {news.get('asset_bias_qqqm', 0):+d}

[조기 경보]
- 매수 차단: {blocks_str}
- 활성 알림: {alerts_str}
{puddle_block}

[Claude 충돌 해석 결과]
- 상황 요약: {ca.get('situation_summary', '')}
- 전략 일관성: {ca.get('strategy_consistency', 'caution')}
- 핵심 리스크: {ca.get('key_risk', '')}
- 검토 포인트: {ca.get('suggestion', '')}

---

[출력 형식]
아래 JSON 스키마를 정확히 따라 JSON 객체 하나만 반환하세요.
마크다운, 코드블록, 설명 문장 금지.

{_OUTPUT_SCHEMA}"""


# ── o1 API 호출 ───────────────────────────────────────────────────

def _call_o1(
    user_prompt: str,
    api_key: str,
    model: str,
    timeout: float = 60.0,
) -> tuple[str, str | None]:
    """o1 / gpt-4o API 호출. (text, error) 반환."""
    try:
        from openai import OpenAI
    except ImportError:
        return "", "missing_sdk"

    client = OpenAI(api_key=api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": user_prompt}],
        "max_completion_tokens": _MAX_COMPLETION_TOKENS,
    }
    try:
        response = client.chat.completions.create(**kwargs, timeout=timeout)
        return response.choices[0].message.content or "", None
    except Exception as e:
        return "", f"api_error:{type(e).__name__}:{e}"


# ── JSON 파싱 ────────────────────────────────────────────────────

def _parse_json_response(text: str) -> dict | None:
    """code block 제거 + trailing comma 보정 후 JSON 파싱."""
    raw = (text or "").strip()
    if not raw:
        return None
    # code block 제거
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if m:
        raw = (m.group(1) or "").strip()
    # trailing comma 보정
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # 중괄호 추출 fallback
    m2 = re.search(r"\{[\s\S]*\}", raw)
    if m2:
        try:
            obj = json.loads(m2.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


# ── 출력 검증 / 보정 ─────────────────────────────────────────────

_VALID_VALIDATION_RESULTS = {"agree", "partial", "disagree"}
_VALID_RISK_ADJUSTMENTS = {"increase", "maintain", "decrease"}
_VALID_TECH_ALIGNMENTS = {"aligned", "mixed", "conflicting"}


def _validate_output(raw: dict, pre_violations: list[str]) -> dict:
    """출력 필드 검증 및 기본값 보정.

    pre_violations: _pre_check_rule_violations()로 사전 감지된 위반 목록.
    """
    out = dict(raw)

    # validation_result
    if out.get("validation_result") not in _VALID_VALIDATION_RESULTS:
        out["validation_result"] = "partial"

    # confidence_score
    try:
        cs = int(out.get("confidence_score") or 50)
        out["confidence_score"] = max(0, min(100, cs))
    except (TypeError, ValueError):
        out["confidence_score"] = 50

    # quantitative_check
    qc = out.get("quantitative_check")
    if not isinstance(qc, dict):
        qc = {}
    qc.setdefault("vix_context", "")
    qc.setdefault("yield_curve_context", "")
    qc.setdefault("drawdown_context", "")
    if qc.get("technical_alignment") not in _VALID_TECH_ALIGNMENTS:
        qc["technical_alignment"] = "mixed"
    out["quantitative_check"] = qc

    # rule_violations: AI 감지 + pre-check 합산 (중복 제거)
    ai_violations = out.get("rule_violations")
    if not isinstance(ai_violations, list):
        ai_violations = []
    merged = list({*ai_violations, *pre_violations})
    out["rule_violations"] = merged

    # risk_adjustment
    if out.get("risk_adjustment") not in _VALID_RISK_ADJUSTMENTS:
        out["risk_adjustment"] = "maintain"

    # 문자열 필드 기본값
    out.setdefault("divergence_from_claude", "")
    out.setdefault("final_note", "")

    return out


# ── 메인 진입점 ───────────────────────────────────────────────────

def validate(
    payload: dict,
    *,
    conflict_detected: bool = True,
    api_key: str = "",
    model: str = _MODEL_PRIMARY,
) -> dict[str, Any]:
    """ChatGPT o1 교차 검증 실행.

    Args:
        payload: cross_validator 입력 dict.
        conflict_detected: signal_analyzer 결과값.
            False면 즉시 not_required 반환 (API 미호출).
        api_key: OpenAI API key. 없으면 fallback 반환.
        model: 사용 모델 (기본 o1, fallback gpt-4o).

    Returns:
        교차 검증 결과 dict.
    """
    if not conflict_detected:
        return dict(_NOT_REQUIRED)

    _api_key = str(api_key or _load_api_key("OPENAI_API_KEY")).strip()
    _model = str(model or _MODEL_PRIMARY).strip() or _MODEL_PRIMARY

    # 사전 규칙 위반 감지 (API 불필요)
    pre_violations = _pre_check_rule_violations(payload)

    # 캐시 해시 계산
    hash_key = _compute_cache_key(payload)

    # 캐시 조회
    cached = _load_cache(hash_key)
    if cached is not None:
        cached["cache_hit"] = True
        cached["validation_hash"] = hash_key
        # pre_violations가 캐시에 반영 안 됐을 수 있으므로 병합
        existing_viol = cached.get("rule_violations") or []
        cached["rule_violations"] = list({*existing_viol, *pre_violations})
        return cached

    # API key 없음 → fallback
    if not _api_key:
        result = {
            **_FALLBACK_VALIDATION,
            "rule_violations": pre_violations,
            "_error": "missing_api_key",
            "cache_hit": False,
            "validation_hash": hash_key,
        }
        return result

    # o1 API 호출 (최대 2회 시도)
    prompt = _build_prompt(payload)
    text, err = _call_o1(prompt, _api_key, _model)

    if (err or not text) and _model != _MODEL_FALLBACK:
        # primary(o1) 실패 또는 빈 응답 → fallback 모델 재시도
        text, err = _call_o1(prompt, _api_key, _MODEL_FALLBACK)

    if err or not text:
        result = {
            **_FALLBACK_VALIDATION,
            "rule_violations": pre_violations,
            "_error": err or "empty_response",
            "cache_hit": False,
            "validation_hash": hash_key,
        }
        return result

    parsed = _parse_json_response(text)
    if not parsed:
        result = {
            **_FALLBACK_VALIDATION,
            "rule_violations": pre_violations,
            "_error": f"parse_error|{(text or '')[:100]}",
            "cache_hit": False,
            "validation_hash": hash_key,
        }
        return result

    validated = _validate_output(parsed, pre_violations)
    validated["cache_hit"] = False
    validated["validation_hash"] = hash_key

    _save_cache(hash_key, validated)
    return validated
