from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
import re
from urllib.parse import quote_plus

try:
    import feedparser
except Exception:  # pragma: no cover - runtime-safe fallback
    feedparser = None


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

CATEGORY_KEYWORDS = {
    "FED": [
        "federal reserve",
        "fed",
        "powell",
        "rate cut",
        "rate hike",
        "interest rate",
        "fomc",
    ],
    "BOND_YIELD": [
        "treasury yield",
        "10-year yield",
        "bond yield",
        "long-term yields",
        "treasury",
        "yield",
    ],
    "INFLATION": [
        "inflation",
        "cpi",
        "ppi",
        "core inflation",
        "prices",
        "pce",
    ],
    "LABOR": ["jobs", "payrolls", "unemployment", "labor market", "hiring"],
    "GROWTH": ["gdp", "recession", "consumer spending", "economic slowdown", "growth"],
    "TECH_AI": ["ai", "artificial intelligence", "nvidia", "semiconductor", "big tech", "cloud"],
    "GEOPOLITICS": ["tariff", "war", "sanction", "china", "middle east", "trade tension"],
    "RISK": ["volatility", "selloff", "correction", "market turmoil", "risk-off", "vix"],
}

CATEGORY_WEIGHTS = {
    "FED": 1.5,
    "BOND_YIELD": 1.4,
    "INFLATION": 1.4,
    "LABOR": 1.1,
    "GROWTH": 1.2,
    "TECH_AI": 1.2,
    "GEOPOLITICS": 1.3,
    "RISK": 1.5,
    "OTHER": 0.5,
}

POSITIVE_PHRASES = [
    "rate cut",
    "cooling inflation",
    "ai demand",
    "recovery",
    "optimism",
    "beat expectations",
]

NEGATIVE_PHRASES = [
    "rate hike",
    "hot inflation",
    "selloff",
    "recession",
    "war",
    "tariff",
    "volatility",
    "uncertainty",
]

DEFAULT_QUERIES = [
    "Federal Reserve markets",
    "US Treasury yields stock market",
    "inflation stock market",
    "AI big tech stocks",
    "market volatility VIX",
    "US recession outlook",
]


def get_macro_market_news(limit: int = 8) -> list[dict]:
    """Backward-compatible helper returning normalized macro headlines list.

    Returned item fields are compatible with dashboard usage:
    title, source, published, query, link, summary.
    """
    try:
        raw = fetch_google_news(queries=DEFAULT_QUERIES, region="US", max_per_query=8)
        normalized = normalize_articles(raw, lookback_days=2)
        deduped = deduplicate_articles(normalized)
        return deduped[: max(1, limit)]
    except Exception:
        return []


def build_news_macro_brief(news_items: list[dict]) -> dict:
    """Backward-compatible briefing format for existing dashboard integration.

    Returns:
    {
        "headline_summary": [str, ...],
        "watchpoints": [str, ...],
        "dominant_topics": [str, ...],
    }
    """
    if not news_items:
        return {
            "headline_summary": [
                "최근 주요 매크로 뉴스 유입이 제한적이라 지표 기반 해석이 유효합니다.",
                "단기적으로는 금리와 변동성 흐름을 중심으로 시장을 점검할 필요가 있습니다.",
                "앞으로는 연준 발언과 장기금리 방향을 함께 확인하는 접근이 적절합니다.",
            ],
            "watchpoints": [
                "미국 10년물 금리",
                "VIX 방향성",
            ],
            "dominant_topics": ["OTHER"],
        }

    enriched = []
    for article in news_items[:5]:
        category, score_map = classify_article(article)
        keyword_score = max(score_map.values()) if score_map else 0
        a = dict(article)
        a["category"] = category
        impact_score, sentiment = score_article_impact(a, keyword_score=keyword_score)
        a["impact_score"] = impact_score
        a["sentiment"] = sentiment
        enriched.append(a)

    signal = aggregate_news_signal(enriched)
    brief = generate_macro_brief(enriched, signal, asset_focus="growth")

    return {
        "headline_summary": [
            brief.get("headline_summary", ""),
            *(brief.get("macro_drivers", [])[:2]),
        ][:3],
        "watchpoints": brief.get("watch_points", [])[:2],
        "dominant_topics": signal.get("dominant_categories", ["OTHER"]),
    }


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fallback_output(message: str = "뉴스 데이터 수집 실패") -> dict:
    return {
        "status": "fallback",
        "as_of": _now_str(),
        "article_count": 0,
        "headline_summary": f"{message}로 지표 기반 해석을 우선 적용합니다.",
        "macro_drivers": ["뉴스 입력 없음: VIX/금리/심리 지표 중심 판단"],
        "market_implication": "단기적으로는 변동성 지표와 장기금리 방향을 우선 점검하는 접근이 유효합니다.",
        "watch_points": ["미국 10년물 금리", "VIX 방향성", "연준 발언"],
        "sentiment_score": 0.0,
        "risk_level": "MODERATE",
        "articles": [],
    }


def _region_params(region: str) -> tuple[str, str, str]:
    region_map = {
        "US": ("en-US", "US", "US:en"),
        "KR": ("ko", "KR", "KR:ko"),
    }
    return region_map.get((region or "US").upper(), region_map["US"])


def _clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _entry_datetime(entry) -> datetime:
    if getattr(entry, "published_parsed", None):
        try:
            t = entry.published_parsed
            return datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, tzinfo=timezone.utc)
        except Exception:
            pass
    published = _clean_text(getattr(entry, "published", ""))
    if published:
        try:
            dt = parsedate_to_datetime(published)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def fetch_google_news(
    queries: list[str],
    region: str = "US",
    max_per_query: int = 8,
) -> list[dict]:
    """Fetch raw articles from Google News RSS using feedparser."""
    if not queries:
        return []
    if feedparser is None:
        return []

    hl, gl, ceid = _region_params(region)
    items: list[dict] = []

    for query in queries:
        q = (query or "").strip()
        if not q:
            continue
        url = f"{GOOGLE_NEWS_RSS}?q={quote_plus(q)}&hl={hl}&gl={gl}&ceid={ceid}"
        try:
            feed = feedparser.parse(url)
            entries = getattr(feed, "entries", [])[: max(1, max_per_query)]
            for entry in entries:
                source_obj = getattr(entry, "source", None)
                if isinstance(source_obj, dict):
                    source = _clean_text(source_obj.get("title", ""))
                else:
                    source = _clean_text(getattr(source_obj, "title", ""))

                dt = _entry_datetime(entry)
                published_iso = dt.isoformat() if dt != datetime.min.replace(tzinfo=timezone.utc) else ""
                items.append(
                    {
                        "title": _clean_text(getattr(entry, "title", "")),
                        "link": _clean_text(getattr(entry, "link", "")),
                        "published": published_iso,
                        "source": source or "Google News",
                        "summary": _clean_text(getattr(entry, "summary", "")),
                        "query": q,
                    }
                )
        except Exception:
            continue
    return items


def normalize_articles(raw_articles: list[dict], lookback_days: int = 2) -> list[dict]:
    """Normalize article text and apply lookback filter."""
    if not raw_articles:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, lookback_days))
    normalized: list[dict] = []

    for article in raw_articles:
        title = _clean_text(article.get("title", ""))
        if not title:
            continue

        published_raw = _clean_text(article.get("published", ""))
        published_dt = datetime.min.replace(tzinfo=timezone.utc)
        if published_raw:
            try:
                published_dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                if published_dt.tzinfo is None:
                    published_dt = published_dt.replace(tzinfo=timezone.utc)
            except Exception:
                published_dt = datetime.min.replace(tzinfo=timezone.utc)

        if lookback_days > 0 and published_dt != datetime.min.replace(tzinfo=timezone.utc):
            if published_dt < cutoff:
                continue

        normalized.append(
            {
                "title": title,
                "link": _clean_text(article.get("link", "")),
                "published": published_dt.isoformat() if published_dt != datetime.min.replace(tzinfo=timezone.utc) else "",
                "source": _clean_text(article.get("source", "")) or "Google News",
                "summary": _clean_text(article.get("summary", "")),
                "query": _clean_text(article.get("query", "")),
            }
        )

    normalized.sort(key=lambda x: x.get("published", ""), reverse=True)
    return normalized


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """Deduplicate articles by normalized title (v1 rule)."""
    seen: set[str] = set()
    out: list[dict] = []
    for article in articles:
        key = (article.get("title", "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(article)
    return out


def classify_article(article: dict) -> tuple[str, dict[str, int]]:
    """Classify article into one primary macro category by keyword hits."""
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()

    score_map: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text)
        score_map[category] = hits

    best_category = "OTHER"
    best_score = 0
    for category, score in score_map.items():
        if score > best_score:
            best_category = category
            best_score = score

    if best_score == 0:
        return "OTHER", score_map
    return best_category, score_map


def score_article_impact(article: dict, keyword_score: int) -> tuple[float, float]:
    """Return (impact_score, sentiment) using rule-based phrase scoring."""
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()

    pos_hits = sum(1 for w in POSITIVE_PHRASES if w in text)
    neg_hits = sum(1 for w in NEGATIVE_PHRASES if w in text)

    if pos_hits == 0 and neg_hits == 0:
        sentiment = 0.0
    else:
        sentiment = (pos_hits - neg_hits) / max(1, pos_hits + neg_hits)
        sentiment = max(-1.0, min(1.0, sentiment))

    category = article.get("category", "OTHER")
    base_weight = CATEGORY_WEIGHTS.get(category, CATEGORY_WEIGHTS["OTHER"])

    magnitude = 1.0 + (0.20 * keyword_score) + (0.15 * abs(sentiment))
    impact_score = round(base_weight * magnitude, 3)
    return impact_score, round(sentiment, 3)


def aggregate_news_signal(articles: list[dict]) -> dict:
    """Aggregate article-level signals into macro drivers and risk metrics."""
    if not articles:
        return {
            "sentiment_score": 0.0,
            "risk_level": "MODERATE",
            "dominant_categories": ["OTHER"],
            "macro_drivers": ["주요 카테고리 신호가 부족해 지표 기반 해석이 우선됩니다."],
        }

    sentiments = [float(a.get("sentiment", 0.0)) for a in articles]
    avg_sentiment = round(sum(sentiments) / len(sentiments), 3)

    if avg_sentiment <= -0.5:
        risk_level = "HIGH"
    elif avg_sentiment <= 0.2:
        risk_level = "MODERATE"
    else:
        risk_level = "LOW"

    category_counter = Counter(a.get("category", "OTHER") for a in articles)
    dominant_categories = [k for k, _ in category_counter.most_common(3)]

    label_map = {
        "FED": "연준/금리",
        "BOND_YIELD": "국채금리",
        "INFLATION": "인플레이션",
        "LABOR": "고용",
        "GROWTH": "경기성장",
        "TECH_AI": "AI/기술",
        "GEOPOLITICS": "지정학",
        "RISK": "위험심리",
        "OTHER": "기타",
    }

    macro_drivers = []
    for cat in dominant_categories:
        label = label_map.get(cat, "기타")
        share = category_counter[cat] / len(articles)
        macro_drivers.append(f"{label} 이슈 비중이 {share * 100:.0f}%로 상대적으로 높습니다.")

    return {
        "sentiment_score": avg_sentiment,
        "risk_level": risk_level,
        "dominant_categories": dominant_categories,
        "macro_drivers": macro_drivers[:3],
    }


def generate_macro_brief(articles: list[dict], signal: dict, asset_focus: str = "growth") -> dict:
    """Generate investor-friendly Korean macro briefing text."""
    if not articles:
        return {
            "headline_summary": "최근 확인 가능한 핵심 뉴스가 제한적이어서 지표 중심의 보수적 해석이 유효합니다.",
            "macro_drivers": signal.get("macro_drivers", []),
            "market_implication": "방향성 확신보다 변동성 관리에 우선순위를 두는 접근이 적절합니다.",
            "watch_points": ["미국 10년물 금리", "VIX 방향성", "연준 발언"],
        }

    top = articles[:5]
    lead = top[0]
    lead_title = lead.get("title", "주요 매크로 뉴스")
    lead_source = lead.get("source", "주요 외신")

    dom = signal.get("dominant_categories", ["OTHER"])
    dom_text_map = {
        "FED": "연준 정책",
        "BOND_YIELD": "장기금리",
        "INFLATION": "물가",
        "LABOR": "고용",
        "GROWTH": "경기",
        "TECH_AI": "AI/기술",
        "GEOPOLITICS": "지정학",
        "RISK": "위험심리",
        "OTHER": "거시 일반",
    }
    dom_ko = [dom_text_map.get(x, "거시 일반") for x in dom[:2]]
    dom_phrase = "·".join(dom_ko)

    headline_summary = (
        f"최근 {dom_phrase} 이슈가 동시 부각되며 시장의 단기 방향성 변동이 커진 모습입니다. "
        f"대표 뉴스({lead_source})인 '{lead_title}'는 투자심리에 직접적인 영향을 줄 수 있습니다."
    )

    sentiment_score = float(signal.get("sentiment_score", 0.0))
    if sentiment_score <= -0.2:
        implication = "단기적으로 위험자산 변동성 확대 가능성이 있어 방어 비중 관리와 분할 접근이 유효합니다."
    elif sentiment_score >= 0.2:
        implication = "단기 심리가 개선 국면이라 추세 추종이 가능하지만, 과열 신호 병행 점검이 필요합니다."
    else:
        implication = "명확한 한 방향 신호가 약해 지표 확인 후 단계적으로 대응하는 전략이 적절합니다."

    watch_points = ["미국 10년물 금리", "VIX 방향성", "연준 발언"]
    if "TECH_AI" in dom:
        watch_points.append("대형 기술주/반도체 뉴스 흐름")
    if "INFLATION" in dom:
        watch_points.append("CPI/PCE 물가 지표")
    if "GEOPOLITICS" in dom:
        watch_points.append("무역/관세 관련 정책 헤드라인")

    if (asset_focus or "").lower() == "growth":
        watch_points.insert(0, "나스닥 대형 성장주 심리")

    dedup_watch = []
    for item in watch_points:
        if item not in dedup_watch:
            dedup_watch.append(item)

    return {
        "headline_summary": headline_summary,
        "macro_drivers": signal.get("macro_drivers", [])[:3],
        "market_implication": implication,
        "watch_points": dedup_watch[:4],
    }


def get_news_brief(
    lookback_days: int = 2,
    max_articles: int = 20,
    region: str = "US",
    asset_focus: str = "growth",
) -> dict:
    """Public API: return structured news-based macro briefing.

    The function is fault-tolerant and always returns a dict shape.
    """
    try:
        queries = list(DEFAULT_QUERIES)
        if (asset_focus or "").lower() == "growth":
            queries.append("Nasdaq growth stocks outlook")

        raw = fetch_google_news(queries=queries, region=region, max_per_query=8)
        if not raw:
            return _fallback_output("뉴스 RSS 응답 부재")

        normalized = normalize_articles(raw, lookback_days=lookback_days)
        deduped = deduplicate_articles(normalized)
        articles = deduped[: max(1, max_articles)]

        enriched = []
        for article in articles:
            category, score_map = classify_article(article)
            keyword_score = max(score_map.values()) if score_map else 0

            article_copy = dict(article)
            article_copy["category"] = category
            impact_score, sentiment = score_article_impact(article_copy, keyword_score=keyword_score)
            article_copy["impact_score"] = impact_score
            article_copy["sentiment"] = sentiment
            enriched.append(article_copy)

        signal = aggregate_news_signal(enriched)
        brief = generate_macro_brief(enriched, signal, asset_focus=asset_focus)

        return {
            "status": "ok",
            "as_of": _now_str(),
            "article_count": len(enriched),
            "headline_summary": brief["headline_summary"],
            "macro_drivers": brief["macro_drivers"],
            "market_implication": brief["market_implication"],
            "watch_points": brief["watch_points"],
            "sentiment_score": signal["sentiment_score"],
            "risk_level": signal["risk_level"],
            "articles": enriched,
        }
    except Exception:
        return _fallback_output("뉴스 엔진 처리 예외 발생")
