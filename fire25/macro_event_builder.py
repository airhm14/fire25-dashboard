# -*- coding: utf-8 -*-
"""Macro Event Builder — Converts enriched articles into structured macro events.

Produces a deterministically-ranked list of top-5 macro events in the schema:

    {
        "type":             "monetary_policy",
        "title":            "Fed signals higher-for-longer rates",
        "impact_direction": "bearish_equity",
        "confidence":       0.72,
        "summary":          "The Federal Reserve signaled...",
        "source":           "Reuters",
        "date":             "2026-03-12",
    }

Ranking is fully deterministic:
  1. impact_score   DESC  (higher = more market-moving)
  2. recency        DESC  (more recent = higher priority)
  3. source_reliability DESC  (core > secondary > unknown)
  4. title          ASC   (alphabetical tiebreak)
"""

from __future__ import annotations

from datetime import datetime, timezone

# ── Category → event type mapping ───────────────────────────────
# Maps news_engine CATEGORY_RULES keys to human-readable event types
# shared with gemini_agent's VALID_EVENT_TYPES where applicable.

CATEGORY_TO_TYPE: dict[str, str] = {
    "POLICY_RATE_RISK":    "monetary_policy",
    "YIELD_PRESSURE":      "treasury_yield",
    "INFLATION_PRESSURE":  "inflation",
    "LABOR_SOFTNESS":      "jobs_labor",
    "GROWTH_SLOWDOWN":     "growth_recession",
    "TECH_AI_SUPPORT":     "tech_sector",
    "GEOPOLITICAL_CONFLICT": "geopolitical",
    "ENERGY_SUPPLY_RISK":  "energy_oil",
    "MARKET_STRESS":       "market_stress",
    "OTHER":               "other",
}

# ── Baseline impact directions per category ──────────────────────
# Reflects the typical market impact of each macro theme.
# Sentiment score may override for strongly positive/negative signals.

CATEGORY_BASE_DIRECTION: dict[str, str] = {
    "POLICY_RATE_RISK":    "bearish_equity",
    "YIELD_PRESSURE":      "bearish_equity",
    "INFLATION_PRESSURE":  "bearish_equity",
    "LABOR_SOFTNESS":      "bearish_equity",
    "GROWTH_SLOWDOWN":     "bearish_equity",
    "TECH_AI_SUPPORT":     "bullish_nasdaq",
    "GEOPOLITICAL_CONFLICT": "bearish_equity",
    "ENERGY_SUPPLY_RISK":  "bearish_equity",
    "MARKET_STRESS":       "bearish_equity",
    "OTHER":               "neutral",
}

# ── Source reliability scores ────────────────────────────────────
SOURCE_RELIABILITY: dict[str, float] = {
    "core":      1.00,
    "secondary": 0.85,
    "unknown":   0.30,
}

TOP_N_EVENTS = 5

# Sentiment thresholds for direction override
_STRONG_BULLISH = 0.40
_STRONG_BEARISH = -0.40
_MILD_BULLISH   = 0.10


# ── Internal helpers ─────────────────────────────────────────────

def _derive_impact_direction(article: dict) -> str:
    """Derive impact direction from category baseline + sentiment signal.

    Tech sector is handled separately: negative sentiment flips it to bearish.
    For other categories:
      - Strong positive sentiment (>0.40) overrides to bullish_equity.
      - Strong negative sentiment (<-0.40) confirms the category baseline.
      - Mild positive sentiment (0.10–0.40) returns neutral.
      - Otherwise: category baseline.
    """
    category = article.get("category", "OTHER")
    sentiment = float(article.get("sentiment", 0.0))
    base = CATEGORY_BASE_DIRECTION.get(category, "neutral")

    if category == "TECH_AI_SUPPORT":
        return "bearish_nasdaq" if sentiment < _STRONG_BEARISH else "bullish_nasdaq"

    if sentiment > _STRONG_BULLISH:
        return "bullish_equity"
    if sentiment < _STRONG_BEARISH:
        return base               # confirms bearish baseline
    if sentiment > _MILD_BULLISH:
        return "neutral"
    return base


def _compute_confidence(article: dict) -> float:
    """Compute event confidence in [0.0, 1.0].

    Weighted combination of normalized impact_score (60%) and
    source reliability (40%).  Max observed impact_score ≈ 5.0.
    """
    impact = float(article.get("impact_score", 0.0))
    tier = article.get("source_tier", "unknown")
    source_rel = SOURCE_RELIABILITY.get(tier, 0.30)
    normalized_impact = min(1.0, impact / 5.0)
    confidence = 0.6 * normalized_impact + 0.4 * source_rel
    return round(min(1.0, max(0.0, confidence)), 2)


def _extract_date(article: dict) -> str:
    """Return YYYY-MM-DD date string from article published field."""
    published = article.get("published", "")
    if published:
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return ""


def _recency_score(article: dict) -> float:
    """Return UTC Unix timestamp for recency-based sorting (higher = newer)."""
    published = article.get("published", "")
    if not published:
        return 0.0
    try:
        dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return float(dt.timestamp())
    except Exception:
        return 0.0


def _build_summary(article: dict) -> str:
    """Extract a clean summary ≤ 150 chars from article summary or title."""
    summary = (article.get("summary") or "").strip()
    title = (article.get("title") or "").strip()
    text = summary if len(summary) > len(title) else title
    if len(text) > 150:
        truncated = text[:147].rsplit(" ", 1)[0]
        return (truncated or text[:147]) + "..."
    return text


# ── Public API ───────────────────────────────────────────────────

def build_macro_events(
    articles: list[dict],
    top_n: int = TOP_N_EVENTS,
) -> list[dict]:
    """Convert enriched articles into a ranked list of structured macro events.

    Each input article must be enriched with: category, impact_score,
    sentiment, source_tier, source_weight, published, title, source.
    Articles with category "OTHER" and zero impact_score are retained but
    ranked last.

    Deterministic sorting guarantees: identical inputs always produce
    identical output regardless of Python dict ordering or list shuffling.

    Args:
        articles: Enriched articles from ``news_engine_v2.get_enriched_articles()``.
        top_n:    Maximum number of events to return (default 5).

    Returns:
        Ranked list of macro event dicts (internal ``_*`` fields stripped).
        Schema: type, title, impact_direction, confidence, summary, source, date.
    """
    events: list[dict] = []
    for article in articles:
        category = article.get("category", "OTHER")
        source_tier = article.get("source_tier", "unknown")
        event = {
            "type":             CATEGORY_TO_TYPE.get(category, "other"),
            "title":            (article.get("title") or "").strip(),
            "impact_direction": _derive_impact_direction(article),
            "confidence":       _compute_confidence(article),
            "summary":          _build_summary(article),
            "source":           (article.get("source") or "").strip(),
            "date":             _extract_date(article),
            # Internal ranking fields — stripped before return
            "_impact_score":       float(article.get("impact_score", 0.0)),
            "_recency":            _recency_score(article),
            "_source_reliability": SOURCE_RELIABILITY.get(source_tier, 0.30),
        }
        events.append(event)

    # Deterministic sort: impact DESC → recency DESC → reliability DESC → title ASC
    events.sort(key=lambda e: (
        -round(e["_impact_score"], 4),
        -round(e["_recency"], 0),
        -round(e["_source_reliability"], 4),
        e["title"],
    ))

    # Strip internal fields and cap at top_n
    result: list[dict] = []
    for ev in events[:top_n]:
        result.append({k: v for k, v in ev.items() if not k.startswith("_")})
    return result


def macro_events_to_prompt(macro_events: list[dict]) -> str:
    """Format macro_events list as a structured text block for AI prompts.

    Used by claude_agent and gpt_agent to inject macro event context
    into strategy generation prompts.

    Args:
        macro_events: Output of ``build_macro_events()``.

    Returns:
        Multi-line Korean-labelled text block. Returns "[매크로 이벤트 없음]"
        when the input list is empty.
    """
    if not macro_events:
        return "[매크로 이벤트 없음]"

    direction_icons: dict[str, str] = {
        "bullish_equity":  "↑",
        "bullish_nasdaq":  "↑",
        "bearish_equity":  "↓",
        "bearish_nasdaq":  "↓",
        "neutral":         "→",
    }

    lines = ["[매크로 구조화 이벤트 — 상위 신호]"]
    for i, ev in enumerate(macro_events, 1):
        icon = direction_icons.get(ev.get("impact_direction", "neutral"), "→")
        conf = ev.get("confidence", 0.0)
        lines.append(
            f"  {i}. [{ev.get('type', '')}] {icon} {ev.get('title', '')} "
            f"(확신도={conf:.2f}, 출처={ev.get('source', '')}, {ev.get('date', '')})"
        )
        if ev.get("summary"):
            lines.append(f"     → {ev['summary']}")

    return "\n".join(lines)
