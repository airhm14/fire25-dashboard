# -*- coding: utf-8 -*-
"""Macro Summary Engine — Derives a machine-readable macro_summary block.

Consumes the structured macro_events list from ``macro_event_builder``
and produces a compact regime interpretation dict:

    {
        "liquidity_regime":     "neutral" | "tightening" | "easing",
        "risk_sentiment":       "risk_off" | "slightly_risk_off" | "neutral"
                                | "slightly_risk_on" | "risk_on",
        "nasdaq_bias":          "bearish" | "mildly_bearish" | "neutral"
                                | "mildly_bullish" | "bullish",
        "macro_risk_level":     float  # 0.0 (low risk) → 1.0 (extreme risk)
        "dominant_event_types": list[str],  # ordered by first occurrence
        "event_count":          int,
    }

All derivations are pure functions with no randomness — identical inputs
always produce identical outputs.
"""

from __future__ import annotations

# ── Direction sets ───────────────────────────────────────────────

BEARISH = frozenset({"bearish_equity", "bearish_nasdaq"})
BULLISH = frozenset({"bullish_equity", "bullish_nasdaq"})

# ── Event type groupings ─────────────────────────────────────────

# Types that signal tightening (if bearish) or easing (if bullish)
LIQUIDITY_TYPES = frozenset({"monetary_policy", "treasury_yield", "market_stress"})

# Types that contribute to Nasdaq direction
NASDAQ_TYPES = frozenset({"tech_sector", "monetary_policy", "treasury_yield", "market_stress"})

# ── Per-type weights for macro_risk_level ────────────────────────
# Higher weight = larger influence on the computed risk level.

RISK_WEIGHTS: dict[str, float] = {
    "monetary_policy":  0.25,
    "treasury_yield":   0.20,
    "market_stress":    0.20,
    "inflation":        0.15,
    "geopolitical":     0.15,
    "growth_recession": 0.15,
    "energy_oil":       0.10,
    "jobs_labor":       0.10,
    "tech_sector":      0.05,
    "other":            0.02,
}

# ── Sentiment score thresholds ───────────────────────────────────
_RISK_OFF_HARD   = -0.50
_RISK_OFF_SOFT   = -0.20
_RISK_ON_HARD    =  0.50
_RISK_ON_SOFT    =  0.20

_LIQUIDITY_THRESHOLD = 0.60
_LIQUIDITY_RATIO     = 1.50

_NASDAQ_BULLISH_HARD  =  1.0
_NASDAQ_BULLISH_SOFT  =  0.3
_NASDAQ_BEARISH_HARD  = -1.0
_NASDAQ_BEARISH_SOFT  = -0.3

_RISK_LEVEL_BASE  = 0.30   # minimum macro_risk_level (never zero)
_RISK_LEVEL_RANGE = 0.65   # scale applied to the normalised score


# ── Internal computation helpers ─────────────────────────────────

def _weighted_sentiment(macro_events: list[dict]) -> float:
    """Confidence-weighted directional sentiment across all events.

    Returns a value in [-1.0, 1.0]:
      +1.0 = all events strongly bullish with high confidence
      -1.0 = all events strongly bearish with high confidence
    """
    if not macro_events:
        return 0.0

    weighted_sum = 0.0
    weight_total = 0.0
    for ev in macro_events:
        direction = ev.get("impact_direction", "neutral")
        confidence = float(ev.get("confidence", 0.5))
        type_weight = RISK_WEIGHTS.get(ev.get("type", "other"), 0.02)

        score = (
            1.0 if direction in BULLISH
            else -1.0 if direction in BEARISH
            else 0.0
        )
        weighted_sum += score * confidence * type_weight
        weight_total += type_weight

    if weight_total == 0.0:
        return 0.0
    return round(max(-1.0, min(1.0, weighted_sum / weight_total)), 3)


def _liquidity_regime(macro_events: list[dict]) -> str:
    """Derive liquidity regime from monetary and yield event signals.

    Tightening: bearish monetary_policy / treasury_yield / market_stress events
                dominate with confidence > 0.60 and 1.5× the easing score.
    Easing:     bullish monetary_policy events dominate similarly.
    Neutral:    default when signals are mixed or below threshold.
    """
    tightening = 0.0
    easing = 0.0
    for ev in macro_events:
        if ev.get("type") not in LIQUIDITY_TYPES:
            continue
        direction = ev.get("impact_direction", "neutral")
        confidence = float(ev.get("confidence", 0.5))
        if direction in BEARISH:
            tightening += confidence
        elif direction in BULLISH:
            easing += confidence

    if tightening > _LIQUIDITY_THRESHOLD and tightening > easing * _LIQUIDITY_RATIO:
        return "tightening"
    if easing > _LIQUIDITY_THRESHOLD and easing > tightening * _LIQUIDITY_RATIO:
        return "easing"
    return "neutral"


def _risk_sentiment(sentiment_score: float, macro_events: list[dict]) -> str:
    """Derive risk sentiment label from weighted sentiment + market_stress events.

    Market stress events with bearish direction immediately push toward risk_off
    regardless of the overall sentiment score.
    """
    stress_bearish = any(
        ev.get("type") == "market_stress" and ev.get("impact_direction") in BEARISH
        for ev in macro_events
    )

    if sentiment_score <= _RISK_OFF_HARD or stress_bearish:
        return "risk_off"
    if sentiment_score <= _RISK_OFF_SOFT:
        return "slightly_risk_off"
    if sentiment_score >= _RISK_ON_HARD:
        return "risk_on"
    if sentiment_score >= _RISK_ON_SOFT:
        return "slightly_risk_on"
    return "neutral"


def _nasdaq_bias(macro_events: list[dict]) -> str:
    """Derive Nasdaq directional bias from relevant event types.

    Tech sector events carry 2× weight relative to macro events (monetary,
    yield, stress) since they have the most direct Nasdaq impact.

    Net score > 1.0 → bullish, > 0.3 → mildly_bullish,
                < -1.0 → bearish, < -0.3 → mildly_bearish, else neutral.
    """
    bullish_score = 0.0
    bearish_score = 0.0
    for ev in macro_events:
        if ev.get("type") not in NASDAQ_TYPES:
            continue
        direction = ev.get("impact_direction", "neutral")
        confidence = float(ev.get("confidence", 0.5))
        weight = 2.0 if ev.get("type") == "tech_sector" else 1.0
        if direction in BULLISH:
            bullish_score += confidence * weight
        elif direction in BEARISH:
            bearish_score += confidence * weight

    net = bullish_score - bearish_score
    if net >= _NASDAQ_BULLISH_HARD:
        return "bullish"
    if net >= _NASDAQ_BULLISH_SOFT:
        return "mildly_bullish"
    if net <= _NASDAQ_BEARISH_HARD:
        return "bearish"
    if net <= _NASDAQ_BEARISH_SOFT:
        return "mildly_bearish"
    return "neutral"


def _macro_risk_level(macro_events: list[dict]) -> float:
    """Compute overall macro risk level in [0.0, 1.0].

    Bearish events increase the risk level weighted by their type importance
    and event confidence.  Bullish events provide a small reduction (30% of
    equivalent bearish weight) — they mitigate but don't eliminate risk.

    Base of 0.30 ensures the level never reaches zero (there is always
    some macro uncertainty).
    """
    if not macro_events:
        return 0.50

    risk_score = 0.0
    weight_total = 0.0
    for ev in macro_events:
        etype = ev.get("type", "other")
        direction = ev.get("impact_direction", "neutral")
        confidence = float(ev.get("confidence", 0.5))
        type_weight = RISK_WEIGHTS.get(etype, 0.02)

        if direction in BEARISH:
            risk_score += confidence * type_weight
        elif direction in BULLISH:
            risk_score -= confidence * type_weight * 0.30  # mild offset

        weight_total += type_weight

    if weight_total == 0.0:
        return 0.50

    normalized = _RISK_LEVEL_BASE + (risk_score / weight_total) * _RISK_LEVEL_RANGE
    return round(max(0.0, min(1.0, normalized)), 2)


# ── Public API ───────────────────────────────────────────────────

def generate_macro_summary(macro_events: list[dict]) -> dict:
    """Generate the macro_summary block from structured macro events.

    Args:
        macro_events: Output of ``macro_event_builder.build_macro_events()``.

    Returns:
        Macro summary dict suitable for injection into ``decision_context``
        and AI strategy agent prompts.  All fields are present even when
        ``macro_events`` is empty (safe fallback values).
    """
    if not macro_events:
        return {
            "liquidity_regime":    "neutral",
            "risk_sentiment":      "neutral",
            "nasdaq_bias":         "neutral",
            "macro_risk_level":    0.50,
            "dominant_event_types": [],
            "event_count":         0,
        }

    sentiment_score = _weighted_sentiment(macro_events)

    # Build dominant_event_types: ordered by first appearance, de-duplicated
    seen_types: list[str] = []
    for ev in macro_events:
        t = ev.get("type", "other")
        if t != "other" and t not in seen_types:
            seen_types.append(t)

    return {
        "liquidity_regime":    _liquidity_regime(macro_events),
        "risk_sentiment":      _risk_sentiment(sentiment_score, macro_events),
        "nasdaq_bias":         _nasdaq_bias(macro_events),
        "macro_risk_level":    _macro_risk_level(macro_events),
        "dominant_event_types": seen_types[:4],
        "event_count":         len(macro_events),
    }


def macro_summary_to_prompt(macro_summary: dict) -> str:
    """Format macro_summary as a structured text block for AI prompts.

    Args:
        macro_summary: Output of ``generate_macro_summary()``.

    Returns:
        Multi-line Korean-labelled text block. Returns "[매크로 요약 없음]"
        when event_count is 0 or the dict is empty.
    """
    if not macro_summary or not macro_summary.get("event_count"):
        return "[매크로 요약 없음]"

    risk = float(macro_summary.get("macro_risk_level", 0.5))
    risk_label = (
        "높음" if risk >= 0.65
        else "보통" if risk >= 0.40
        else "낮음"
    )
    dominant = ", ".join(macro_summary.get("dominant_event_types", []))

    lines = [
        "[매크로 요약]",
        f"  유동성 레짐  : {macro_summary.get('liquidity_regime', 'neutral')}",
        f"  리스크 심리  : {macro_summary.get('risk_sentiment', 'neutral')}",
        f"  나스닥 방향  : {macro_summary.get('nasdaq_bias', 'neutral')}",
        f"  거시 리스크  : {risk:.2f} ({risk_label})",
        f"  주요 이벤트  : {dominant or '없음'}",
    ]
    return "\n".join(lines)
