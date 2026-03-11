# -*- coding: utf-8 -*-
"""Decision Context Builder — 전략 입력 정규화 · 스냅샷 · 해시.

모든 전략 판단 전에 입력 데이터를 결정론적으로 정규화한다.

핵심 기능:
  1. 뉴스 정렬/중복 제거/구조화
  2. 지표 소수점 고정 + None/NaN 처리
  3. 포트폴리오 ticker순 정렬
  4. 타임스탬프 버킷 (1시간 단위)
  5. strategy_hash 생성 (동일 입력 → 동일 해시)
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any


# ── Safe type converters ─────────────────────────────────────────

def _sf(value: Any, default: float = 0.0, ndigits: int = 2) -> float:
    """Safe float with fixed rounding. NaN/None → default."""
    try:
        if value is None or value == "":
            return round(float(default), ndigits)
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return round(float(default), ndigits)
        return round(f, ndigits)
    except Exception:
        return round(float(default), ndigits)


def _si(value: Any, default: int = 0) -> int:
    """Safe int. NaN/None → default."""
    try:
        if value is None or value == "":
            return int(default)
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return int(default)
        return int(f)
    except Exception:
        return int(default)


# ── Timestamp bucket ─────────────────────────────────────────────

def get_timestamp_bucket(bucket_minutes: int = 60) -> str:
    """현재 시각을 bucket 단위로 내림 (기본 1시간)."""
    now = datetime.now()
    floored_minute = (now.minute // bucket_minutes) * bucket_minutes
    return now.replace(
        minute=floored_minute, second=0, microsecond=0,
    ).strftime("%Y-%m-%d %H:%M")


# ── News normalization ───────────────────────────────────────────

def _date_sort_key(date_str: str) -> int:
    """날짜 문자열 → 정렬용 정수 (높을수록 최신)."""
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S",
    ):
        try:
            return int(datetime.strptime(str(date_str).strip()[:25], fmt).timestamp())
        except (ValueError, TypeError):
            continue
    return 0


def normalize_news(articles: list[dict] | None) -> list[dict]:
    """뉴스 정규화: date desc → source asc → title asc, 중복 제거."""
    if not articles:
        return []
    seen: set[str] = set()
    out: list[dict] = []
    for a in articles:
        title = str(a.get("title", "")).strip()
        if not title or title in seen:
            continue
        seen.add(title)
        out.append({
            "title": title,
            "source": str(a.get("source", "")).strip(),
            "date": str(a.get("date", a.get("published", ""))).strip(),
            "link": str(a.get("link", "")).strip(),
            "tags": sorted(a.get("tags", []))
                   if isinstance(a.get("tags"), list) else [],
        })
    out.sort(key=lambda x: (
        -_date_sort_key(x["date"]),
        x["source"],
        x["title"],
    ))
    return out


# ── Portfolio normalization ──────────────────────────────────────

def normalize_portfolio(portfolio: dict | None) -> dict:
    """포트폴리오 정규화: ticker ASC 정렬, 소수점 고정."""
    if not portfolio:
        return {
            "positions": [], "cash": 0.0, "total_value": 0.0,
            "weights": {}, "target_weights": {},
        }
    positions = sorted(
        [
            {
                "ticker": str(p.get("ticker", "")).upper(),
                "shares": int(p.get("shares", 0)),
                "price": round(float(p.get("price", 0)), 2),
            }
            for p in portfolio.get("positions", [])
        ],
        key=lambda x: x["ticker"],
    )
    weights_raw = portfolio.get("weights") or {}
    target_raw = portfolio.get("target_weights") or {}
    return {
        "positions": positions,
        "cash": round(float(portfolio.get("cash", 0)), 2),
        "total_value": round(float(portfolio.get("total_value", 0)), 2),
        "weights": dict(sorted(
            {k: round(float(v), 2) for k, v in weights_raw.items()}.items(),
        )),
        "target_weights": dict(sorted(
            {k: round(float(v), 2) for k, v in target_raw.items()}.items(),
        )),
    }


# ── Main builder ─────────────────────────────────────────────────

def build_decision_context(
    *,
    # Portfolio (structured)
    portfolio: dict | None = None,
    # Portfolio (legacy flat — only used when portfolio is None)
    portfolio_weight: dict | None = None,
    target_weight: dict | None = None,
    cash_level: str = "중간",
    # Indicators
    vix: float | None = None,
    fear_greed: int | None = None,
    qqqm_rsi: float | None = None,
    qqqm_sma200_gap: float | None = None,
    treasury_10y: float | None = None,
    oil_price: float | None = None,
    # Regime & state
    regime: str = "CORRECTION",
    defcon_active: bool = False,
    puddle_stage: int = 0,
    smart_shoulder_triggered: bool = False,
    # Text summaries
    macro_summary_text: str = "",
    news_summary_text: str = "",
    # Structured news/signals
    news_brief: dict | None = None,
    news_items: list[dict] | None = None,
    shock_events: list[str] | None = None,
    risk_radar: dict | None = None,
    # News snapshot (구조화 이벤트 기반)
    news_snapshot: dict | None = None,
) -> dict:
    """정규화된 decision context 스냅샷 반환.

    동일 입력 → 동일 출력을 보장한다.
    """
    nb = news_brief if isinstance(news_brief, dict) else {}

    # ── Portfolio ─────────────────────────────────────────────
    norm_pf = normalize_portfolio(portfolio)
    if not portfolio:
        # Legacy: build minimal struct from flat weights
        pw = portfolio_weight or {}
        tw = target_weight or {}
        norm_pf["weights"] = dict(sorted(
            {k: round(float(v), 2) for k, v in pw.items()}.items(),
        ))
        norm_pf["target_weights"] = dict(sorted(
            {k: round(float(v), 2) for k, v in tw.items()}.items(),
        ))

    # ── Indicators (소수점 고정) ──────────────────────────────
    indicators = {
        "10Y_treasury": _sf(treasury_10y, 0.0),
        "QQQM_RSI": _sf(qqqm_rsi, 50.0),
        "QQQM_SMA200_gap": _sf(qqqm_sma200_gap, 0.0),
        "VIX": _sf(vix, 20.0),
        "cash_level": str(cash_level or "중간"),
        "fear_greed": _si(fear_greed, 50),
        "oil_price": _sf(oil_price, 0.0),
    }

    # ── Signals (정렬) ────────────────────────────────────────
    signals = {
        "dominant_categories": sorted(nb.get("dominant_categories", [])),
        "risk_level_label": str(nb.get("risk_level_label", "보통")),
        "shock_events": sorted(shock_events or []),
        "risk_radar": dict(sorted(
            {k: _sf(v) for k, v in (risk_radar or {}).items()}.items(),
        )) if risk_radar else {},
    }

    # ── Manual state (레짐 정보 명시) ─────────────────────────
    manual_state = {
        "defcon_active": bool(defcon_active),
        "puddle_stage": int(puddle_stage),
        "regime": str(regime),
        "smart_shoulder_triggered": bool(smart_shoulder_triggered),
    }

    # ── News (정규화) ─────────────────────────────────────────
    norm_news = normalize_news(news_items)

    # ── News Snapshot (구조화 이벤트 기반) ────────────────────
    _snapshot = news_snapshot if isinstance(news_snapshot, dict) else {}

    return {
        "timestamp_bucket": get_timestamp_bucket(),
        "regime": str(regime),
        "portfolio": norm_pf,
        "indicators": indicators,
        "signals": signals,
        "news_items": norm_news,
        "manual_state": manual_state,
        "macro_summary": str(macro_summary_text or ""),
        "news_summary": str(news_summary_text or ""),
        "news_snapshot": _snapshot,
    }


# ── Strategy hash ────────────────────────────────────────────────

def compute_strategy_hash(context: dict) -> str:
    """decision_context → 결정론적 SHA-256 해시 (16자).

    동일한 입력 조합이면 반드시 동일 해시를 반환한다.
    뉴스 순서가 달라도 정규화 후 동일하면 같은 해시.
    """
    # news_snapshot이 있으면 snapshot_hash 사용 (뉴스 안정성 강화)
    _snap = context.get("news_snapshot") or {}
    if _snap.get("snapshot_hash"):
        news_key = _snap["snapshot_hash"]
    else:
        news_key = [n.get("title", "") for n in context.get("news_items", [])]

    hash_input = {
        "regime": context.get("regime", ""),
        "portfolio": context.get("portfolio", {}),
        "indicators": context.get("indicators", {}),
        "signals": context.get("signals", {}),
        "news_key": news_key,
        "manual_state": context.get("manual_state", {}),
    }
    canonical = json.dumps(hash_input, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def context_to_json(ctx: dict) -> str:
    """Compact deterministic JSON string for prompt embedding."""
    return json.dumps(ctx, ensure_ascii=False, sort_keys=True, default=str)
