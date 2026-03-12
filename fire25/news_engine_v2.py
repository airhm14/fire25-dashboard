# -*- coding: utf-8 -*-
"""News Engine v2 — Multi-category ingestion + token-overlap deduplication.

Fetches articles across 7 priority macro categories, classifies and scores
each article, then deduplicates using both exact-title and Jaccard
token-overlap similarity to eliminate redundant near-duplicate articles.

Priority categories:
  1. monetary_policy    — Fed / central bank policy
  2. treasury_yields    — Treasury yield movements
  3. liquidity_credit   — Liquidity / credit conditions
  4. earnings_trends    — Earnings season trends
  5. tech_ai_sector     — AI / technology signals
  6. geopolitical_risks — Geopolitical / trade risks
  7. market_sentiment   — Sentiment / volatility shifts
"""

from __future__ import annotations

import re

from fire25.news_engine import (
    STOPWORDS,
    classify_article,
    deduplicate_articles,
    fetch_news_articles,
    normalize_articles,
    score_article_impact,
)

# ── Priority category queries ────────────────────────────────────
# 3 targeted queries per category; each returns up to max_per_query articles.
# Total target: ~8 articles/category × 7 categories = ~56 raw articles.

CATEGORY_QUERIES: dict[str, list[str]] = {
    "monetary_policy": [
        "Federal Reserve FOMC interest rate decision",
        "Fed Powell rate guidance higher-for-longer",
        "central bank policy meeting inflation rates",
    ],
    "treasury_yields": [
        "US Treasury 10-year yield bond market",
        "yield curve inversion Treasury auction demand",
        "bond yield spike financing costs valuation",
    ],
    "liquidity_credit": [
        "credit spreads financial conditions liquidity",
        "banking system money market credit stress",
        "Federal Reserve balance sheet repo liquidity",
    ],
    "earnings_trends": [
        "S&P 500 earnings results quarterly guidance",
        "corporate earnings profit margins outlook",
        "earnings season beats misses revenue guidance",
    ],
    "tech_ai_sector": [
        "AI chip demand Nvidia semiconductor outlook",
        "big tech earnings cloud AI capital investment",
        "technology sector growth AI stocks Nasdaq",
    ],
    "geopolitical_risks": [
        "geopolitical risk oil supply trade disruption",
        "tariff China US trade tension sanctions",
        "Middle East conflict energy market geopolitics",
    ],
    "market_sentiment": [
        "market volatility VIX risk-off selloff correction",
        "investor sentiment fear greed stock market breadth",
        "equity market rally correction technical signals",
    ],
}


# ── Token similarity helpers ─────────────────────────────────────

def _token_set(text: str) -> set[str]:
    """Extract meaningful tokens from text for similarity comparison."""
    words = re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) >= 3}


def _jaccard_similarity(title_a: str, title_b: str) -> float:
    """Jaccard similarity between two article title token sets.

    Returns 0.0 if either title yields no meaningful tokens.
    """
    set_a = _token_set(title_a)
    set_b = _token_set(title_b)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


# ── Ingestion ────────────────────────────────────────────────────

def fetch_multi_category_articles(
    max_per_category: int = 8,
    region: str = "US",
) -> list[dict]:
    """Fetch raw articles across all 7 priority macro categories.

    Each article is tagged with ``_query_category`` for traceability.

    Args:
        max_per_category: Max articles per individual RSS query.
        region: Geographic region for RSS (default "US").

    Returns:
        Raw article list (not yet normalized or scored).
    """
    all_raw: list[dict] = []
    for category_key, queries in CATEGORY_QUERIES.items():
        raw = fetch_news_articles(
            queries=queries,
            region=region,
            max_per_query=max_per_category,
        )
        for article in raw:
            article["_query_category"] = category_key
        all_raw.extend(raw)
    return all_raw


# ── Enhanced deduplication ───────────────────────────────────────

def deduplicate_v2(
    articles: list[dict],
    similarity_threshold: float = 0.6,
) -> list[dict]:
    """Two-pass deduplication: exact-title then token-overlap similarity.

    Pass 1: Remove articles with identical titles (fast O(n)).
    Pass 2: Cluster near-duplicate articles (same event, different phrasing)
            using Jaccard similarity on title tokens. Within each cluster,
            keep the article with the highest ``impact_score``.

    Args:
        articles: Enriched articles (must have ``impact_score`` field).
        similarity_threshold: Jaccard threshold for near-duplicate detection.
            0.6 = 60% of meaningful tokens must overlap. Default 0.6.

    Returns:
        Deduplicated list with highest-impact representative per cluster.
        Order is preserved relative to the input (highest-impact wins).
    """
    # Pass 1: exact-title dedup (leverages existing engine utility)
    exact_deduped = deduplicate_articles(articles)

    # Pass 2: token-overlap similarity dedup
    kept: list[dict] = []
    for candidate in exact_deduped:
        c_title = candidate.get("title", "")
        duplicate = False
        for idx, existing in enumerate(kept):
            if _jaccard_similarity(c_title, existing.get("title", "")) >= similarity_threshold:
                # Same event — keep the one with higher impact_score
                if float(candidate.get("impact_score", 0.0)) > float(existing.get("impact_score", 0.0)):
                    kept[idx] = candidate
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return kept


# ── Full pipeline ────────────────────────────────────────────────

def get_enriched_articles(
    max_per_category: int = 8,
    lookback_days: int = 2,
    region: str = "US",
    max_total: int = 60,
) -> list[dict]:
    """Full v2 ingestion pipeline: fetch → normalize → classify → score → dedup.

    Steps:
      1. Fetch articles across all 7 priority categories
      2. Normalize (date filter, source metadata enrichment)
      3. Classify each article (news_engine category + pattern score)
      4. Score each article (impact_score + sentiment)
      5. Deduplicate (exact-title + Jaccard token-overlap)
      6. Cap at max_total

    Args:
        max_per_category: Max articles per individual RSS query.
        lookback_days: Only include articles published in the last N days.
        region: Geographic region for RSS (default "US").
        max_total: Hard cap on returned article count (default 60).

    Returns:
        Enriched, deduplicated articles ready for ``macro_event_builder``.
        Each article has: title, source, source_tier, source_weight,
        published, category, impact_score, sentiment, _query_category.
    """
    raw = fetch_multi_category_articles(
        max_per_category=max_per_category,
        region=region,
    )
    if not raw:
        return []

    normalized = normalize_articles(raw, lookback_days=lookback_days)
    if not normalized:
        return []

    enriched: list[dict] = []
    for article in normalized:
        category, score_map = classify_article(article)
        pattern_score = max(score_map.values()) if score_map else 0.0
        item = dict(article)
        item["category"] = category
        impact, sentiment = score_article_impact(item, pattern_score=pattern_score)
        item["impact_score"] = impact
        item["sentiment"] = sentiment
        enriched.append(item)

    return deduplicate_v2(enriched)[:max(1, max_total)]
