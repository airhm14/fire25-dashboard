from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
import json
import logging
import os
import re
from urllib.parse import quote_plus, urlparse

try:
    import feedparser
except Exception:  # pragma: no cover
    feedparser = None


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
# Legacy Gemini model constant removed — all Gemini calls now go through
# fire25/ai/gemini_events.py using the google-genai SDK + model_registry.

LOGGER = logging.getLogger(__name__)

ASSET_LIST = ["QQQM", "SCHD", "IAU", "SGOV"]

TRUSTED_SOURCES = {
    "reuters.com": {"name": "Reuters", "tier": "core", "weight": 1.00},
    "bloomberg.com": {"name": "Bloomberg", "tier": "core", "weight": 1.00},
    "cnbc.com": {"name": "CNBC", "tier": "core", "weight": 1.00},
    "wsj.com": {"name": "WSJ", "tier": "core", "weight": 1.00},
    "ft.com": {"name": "Financial Times", "tier": "core", "weight": 1.00},
    "marketwatch.com": {"name": "MarketWatch", "tier": "secondary", "weight": 0.85},
    "finance.yahoo.com": {"name": "Yahoo Finance", "tier": "secondary", "weight": 0.80},
    "apnews.com": {"name": "Associated Press", "tier": "secondary", "weight": 0.85},
    "barrons.com": {"name": "Barron's", "tier": "secondary", "weight": 0.85},
}

SOURCE_NAME_HINTS = {
    "reuters": "reuters.com",
    "bloomberg": "bloomberg.com",
    "cnbc": "cnbc.com",
    "wsj": "wsj.com",
    "wall street journal": "wsj.com",
    "financial times": "ft.com",
    " ft ": "ft.com",
    "marketwatch": "marketwatch.com",
    "yahoo finance": "finance.yahoo.com",
    "associated press": "apnews.com",
    "ap news": "apnews.com",
    " ap ": "apnews.com",
    "barron's": "barrons.com",
    "barrons": "barrons.com",
}

DEFAULT_QUERIES = [
    "Federal Reserve markets",
    "US Treasury yields stock market",
    "inflation stock market",
    "AI big tech stocks",
    "market volatility VIX",
    "US recession outlook",
    "geopolitics market impact",
    "middle east conflict oil",
    "iran israel war oil",
    "energy supply disruption",
    "bond yield spike",
    "global inflation outlook",
    "shipping disruption oil markets",
]

DIRECT_TRUSTED_RSS = [
    ("Reuters", "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best"),
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ("Associated Press", "https://apnews.com/hub/business/rss"),
]

CATEGORY_WEIGHTS = {
    "POLICY_RATE_RISK": 1.5,
    "YIELD_PRESSURE": 1.4,
    "INFLATION_PRESSURE": 1.4,
    "LABOR_SOFTNESS": 1.1,
    "GROWTH_SLOWDOWN": 1.2,
    "TECH_AI_SUPPORT": 1.2,
    "GEOPOLITICAL_CONFLICT": 1.3,
    "ENERGY_SUPPLY_RISK": 1.3,
    "MARKET_STRESS": 1.5,
    "OTHER": 0.5,
}

CATEGORY_RULES = {
    "POLICY_RATE_RISK": {
        "core": ["fed", "federal reserve", "fomc", "interest rate", "rate cut", "rate hike"],
        "actor": ["powell", "central bank", "policy"],
        "impact": ["guidance", "outlook", "pricing", "tightening", "easing"],
    },
    "YIELD_PRESSURE": {
        "core": ["treasury", "bond yield", "10-year", "long-term yields", "yield"],
        "actor": ["us", "auction", "bond market"],
        "impact": ["valuation", "pressure", "higher-for-longer", "financing cost"],
    },
    "INFLATION_PRESSURE": {
        "core": ["inflation", "cpi", "ppi", "pce", "core inflation", "prices"],
        "actor": ["consumer", "services", "wage"],
        "impact": ["sticky", "hot", "cooling", "disinflation"],
    },
    "LABOR_SOFTNESS": {
        "core": ["jobs", "payrolls", "unemployment", "labor market"],
        "actor": ["employer", "hiring", "layoff"],
        "impact": ["slowdown", "softening", "weakness"],
    },
    "GROWTH_SLOWDOWN": {
        "core": ["gdp", "recession", "economic slowdown", "consumer spending", "growth"],
        "actor": ["household", "business", "manufacturing"],
        "impact": ["slowdown", "contraction", "downturn"],
    },
    "TECH_AI_SUPPORT": {
        "core": ["ai", "artificial intelligence", "nvidia", "semiconductor", "big tech", "cloud"],
        "actor": ["chip", "software", "hyperscaler"],
        "impact": ["demand", "investment", "earnings beat", "guidance raise"],
    },
    "GEOPOLITICAL_CONFLICT": {
        "core": ["war", "conflict", "sanction", "tariff", "trade tension"],
        "actor": ["china", "middle east", "russia", "ukraine"],
        "impact": ["escalation", "disruption", "retaliation"],
    },
    "ENERGY_SUPPLY_RISK": {
        "core": ["oil", "crude", "opec", "energy"],
        "actor": ["shipping", "strait", "pipeline", "refinery"],
        "impact": ["disruption", "supply", "surge", "spike"],
    },
    "MARKET_STRESS": {
        "core": ["volatility", "selloff", "correction", "market turmoil", "risk-off", "vix"],
        "actor": ["equity", "stocks", "investor"],
        "impact": ["panic", "de-risk", "drawdown"],
    },
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

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "over", "under", "after", "before",
    "amid", "will", "are", "was", "were", "has", "have", "had", "its", "their", "about", "market",
    "markets", "stock", "stocks", "news", "says", "say", "new", "us", "u.s", "today", "latest", "update",
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _risk_level_label(level: str) -> str:
    return {"HIGH": "높음", "MODERATE": "보통", "LOW": "낮음"}.get(level, "보통")


def _fallback_output(message: str = "뉴스 데이터 수집 실패") -> dict:
    return {
        "status": "fallback",
        "as_of": _now_str(),
        "article_count": 0,
        "headline_summary": f"{message}. 데이터 기반 거시 요약을 우선 참고하세요.",
        "macro_drivers": ["핵심 뉴스 신호 부재"],
        "market_implication": "현재는 금리·변동성 지표 중심의 보수적 해석이 적절합니다.",
        "portfolio_implication": "현금성 자산과 방어 비중을 유지하며 신호 확인 후 분할 접근이 유효합니다.",
        "asset_implications": {
            "QQQM": "금리와 변동성 민감도가 높아 밸류에이션 부담 변화를 함께 점검하세요.",
            "SCHD": "배당/퀄리티 방어 역할을 기대하되 경기 둔화 시 이익 전망을 함께 확인하세요.",
            "IAU": "실질금리와 위험회피 수요 변화에 따라 헤지 역할이 달라질 수 있습니다.",
            "SGOV": "단기금리 구간에서 현금성 완충 자산으로 변동성 대응에 유리합니다.",
        },
        "watch_points": ["미국 10년물 금리 방향", "VIX 재상승 여부", "연준 발언 및 금리 경로 변화"],
        "sentiment_score": 0.0,
        "risk_level": "MODERATE",
        "risk_level_label": "보통",
        "dominant_terms": [],
        "dominant_bigrams": [],
        "raw_article_count": 0,
        "normalized_article_count": 0,
        "matched_core_count": 0,
        "matched_secondary_count": 0,
        "matched_unknown_count": 0,
        "articles": [],
        "brief_source": "rule_based",
    }


def is_gemini_enabled() -> bool:
    """Return True when Gemini API key is available."""
    return bool((os.getenv("GEMINI_API_KEY") or "").strip())


def _strip_json_fence(text: str) -> str:
    """Remove Markdown code fences if model wrapped JSON output."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*", "", raw).strip()
        if raw.endswith("```"):
            raw = raw[:-3].strip()
    return raw


def _safe_parse_json(text: str) -> dict | None:
    """Parse JSON object safely; return None for invalid payload."""
    try:
        cleaned = _strip_json_fence(text)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def build_gemini_payload(
    articles: list[dict],
    aggregated_signals: dict,
    theme_info: dict,
    asset_focus: str,
) -> dict:
    """Build compact structured input for Gemini interpretation."""
    top_articles = []
    for item in articles[:8]:
        top_articles.append(
            {
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "source_tier": item.get("source_tier", "unknown"),
                "published": item.get("published", ""),
                "category": item.get("category", "OTHER"),
                "impact_score": float(item.get("impact_score", 0.0)),
                "sentiment": float(item.get("sentiment", 0.0)),
                "summary": item.get("summary", ""),
            }
        )

    return {
        "asset_focus": (asset_focus or "growth").lower(),
        "portfolio_assets": ASSET_LIST,
        "top_trusted_articles": top_articles,
        "dominant_categories": aggregated_signals.get("dominant_categories", []),
        "dominant_terms": theme_info.get("dominant_terms", [])[:8],
        "dominant_bigrams": theme_info.get("dominant_bigrams", [])[:6],
        "category_scores": aggregated_signals.get("category_scores", {}),
        "core_source_count": int(aggregated_signals.get("core_article_count", 0)),
        "secondary_source_count": int(aggregated_signals.get("secondary_article_count", 0)),
        "sentiment_score": float(aggregated_signals.get("sentiment_score", 0.0)),
        "risk_level": aggregated_signals.get("risk_level", "MODERATE"),
        "risk_level_label": aggregated_signals.get("risk_level_label", "보통"),
    }


def _gemini_prompt(payload: dict) -> str:
    """Create strict Korean JSON-only prompt for dashboard interpretation."""
    schema = {
        "headline_summary": "string",
        "market_implication": "string",
        "portfolio_implication": "string",
        "asset_implications": {
            "QQQM": "string",
            "SCHD": "string",
            "IAU": "string",
            "SGOV": "string",
        },
        "watch_points": ["string", "string", "string"],
        "risk_level_label": "낮음|보통|높음",
    }

    return (
        "당신은 개인 투자 대시보드용 신뢰 뉴스 해석기입니다.\\n"
        "이 작업은 투자자문이 아니라 시나리오 해석과 모니터링 포인트 정리입니다.\\n"
        "주어진 구조화 입력을 넘어서 사실을 추정하거나 발명하지 마세요.\\n"
        "핵심(core) 출처에서 반복 확인된 테마를 우선하세요.\\n"
        "QQQM, SCHD, IAU, SGOV 관점을 반드시 포함하세요.\\n"
        "문장은 간결하고 자연스러운 한국어로 작성하세요.\\n"
        "매수/매도 지시를 금지합니다.\\n"
        "지금 중요한 점과 다음 점검 포인트를 중심으로 작성하세요.\\n"
        "JSON 외 텍스트를 출력하지 마세요. 마크다운 금지.\\n\\n"
        "[입력 데이터]\\n"
        f"{json.dumps(payload, ensure_ascii=False)}\\n\\n"
        "[반드시 아래 스키마의 JSON으로만 출력]\\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )


def _validate_ai_output(payload: dict) -> dict | None:
    """Validate and normalize Gemini JSON output schema."""
    if not isinstance(payload, dict):
        return None

    out = {
        "headline_summary": str(payload.get("headline_summary", "")).strip(),
        "market_implication": str(payload.get("market_implication", "")).strip(),
        "portfolio_implication": str(payload.get("portfolio_implication", "")).strip(),
        "asset_implications": {},
        "watch_points": [],
        "risk_level_label": str(payload.get("risk_level_label", "")).strip(),
    }

    asset_implications = payload.get("asset_implications", {})
    if not isinstance(asset_implications, dict):
        asset_implications = {}
    for asset in ASSET_LIST:
        out["asset_implications"][asset] = str(asset_implications.get(asset, "")).strip()

    watch_points = payload.get("watch_points", [])
    if isinstance(watch_points, list):
        out["watch_points"] = [str(x).strip() for x in watch_points if str(x).strip()][:4]

    if out["risk_level_label"] not in {"낮음", "보통", "높음"}:
        out["risk_level_label"] = ""

    required_text_fields = [
        out["headline_summary"],
        out["market_implication"],
        out["portfolio_implication"],
    ]
    if not all(required_text_fields):
        return None

    if not out["watch_points"]:
        return None

    return out


def generate_ai_macro_brief(payload: dict, timeout_sec: int = 12) -> dict | None:
    """Legacy Gemini path — disabled.

    All Gemini AI generation now goes through ``fire25.ai.gemini_events``
    using the new ``google-genai`` SDK.  This function returns ``None``
    so callers fall back to the rule-based summary.
    """
    return None


def try_generate_gemini_brief(payload: dict) -> dict | None:
    """Best-effort Gemini wrapper. Never raises."""
    if not is_gemini_enabled():
        return None
    try:
        return generate_ai_macro_brief(payload)
    except Exception:
        return None


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


def extract_domain(url: str) -> str:
    """Extract canonical domain from URL."""
    try:
        netloc = (urlparse(url).netloc or "").lower().strip()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc
    except Exception:
        return ""


def enrich_source_metadata(article: dict) -> dict:
    """Attach source metadata using both domain and source-title matching."""
    out = dict(article)
    domain = extract_domain(out.get("link", ""))
    out["domain"] = domain
    source_text = f" {str(out.get('source', '')).strip().lower()} "

    matched_key = None
    for key in TRUSTED_SOURCES.keys():
        if domain == key or domain.endswith(f".{key}"):
            matched_key = key
            break

    if not matched_key and source_text.strip():
        for hint, key in SOURCE_NAME_HINTS.items():
            if hint in source_text:
                matched_key = key
                break

    if matched_key:
        meta = TRUSTED_SOURCES[matched_key]
        out["source"] = meta["name"]
        out["source_tier"] = meta["tier"]
        out["source_weight"] = float(meta["weight"])
        out["trusted_source"] = True
    else:
        out["source"] = out.get("source") or "기타 출처"
        out["source_tier"] = "unknown"
        out["source_weight"] = 0.3
        out["trusted_source"] = False

    return out


def fetch_news_articles(queries: list[str], region: str = "US", max_per_query: int = 8) -> list[dict]:
    """RSS ingestion from Google News using feedparser."""
    if feedparser is None or not queries:
        return []

    hl, gl, ceid = _region_params(region)
    out: list[dict] = []

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
                    source_title = _clean_text(source_obj.get("title", ""))
                else:
                    source_title = _clean_text(getattr(source_obj, "title", ""))

                dt = _entry_datetime(entry)
                published = dt.isoformat() if dt != datetime.min.replace(tzinfo=timezone.utc) else ""
                out.append(
                    {
                        "title": _clean_text(getattr(entry, "title", "")),
                        "link": _clean_text(getattr(entry, "link", "")),
                        "published": published,
                        "source": source_title,
                        "summary": _clean_text(getattr(entry, "summary", "")),
                        "query": q,
                    }
                )
        except Exception:
            continue

    if out:
        return out

    # Fallback: some environments block Google News RSS. Try trusted direct feeds.
    for source_name, url in DIRECT_TRUSTED_RSS:
        try:
            feed = feedparser.parse(url)
            entries = getattr(feed, "entries", [])[: max(2, max_per_query // 2)]
            for entry in entries:
                dt = _entry_datetime(entry)
                published = dt.isoformat() if dt != datetime.min.replace(tzinfo=timezone.utc) else ""
                out.append(
                    {
                        "title": _clean_text(getattr(entry, "title", "")),
                        "link": _clean_text(getattr(entry, "link", "")),
                        "published": published,
                        "source": source_name,
                        "summary": _clean_text(getattr(entry, "summary", "")),
                        "query": "trusted_rss_fallback",
                    }
                )
        except Exception:
            continue

    return out


def normalize_articles(raw_articles: list[dict], lookback_days: int = 2) -> list[dict]:
    """Normalize fields, enrich source metadata, and keep trusted+unknown sources."""
    if not raw_articles:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, int(lookback_days)))
    normalized: list[dict] = []

    for item in raw_articles:
        title = _clean_text(item.get("title", ""))
        if not title:
            continue

        published_raw = _clean_text(item.get("published", ""))
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

        article = {
            "title": title,
            "link": _clean_text(item.get("link", "")),
            "published": published_dt.isoformat() if published_dt != datetime.min.replace(tzinfo=timezone.utc) else "",
            "summary": _clean_text(item.get("summary", "")),
            "source": _clean_text(item.get("source", "")),
            "query": _clean_text(item.get("query", "")),
        }

        article = enrich_source_metadata(article)
        normalized.append(article)

    normalized.sort(key=lambda x: x.get("published", ""), reverse=True)
    return normalized


def deduplicate_articles(articles: list[dict]) -> list[dict]:
    """Title-based deduplication for Beta 1.0."""
    seen: set[str] = set()
    out: list[dict] = []
    for article in articles:
        key = (article.get("title", "").strip().lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(article)
    return out


def _rule_group_score(text: str, terms: list[str]) -> int:
    return sum(1 for t in terms if t in text)


def classify_article(article: dict) -> tuple[str, dict[str, float]]:
    """Classify article using hierarchical rule groups and return score map."""
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    score_map: dict[str, float] = {}

    for category, rules in CATEGORY_RULES.items():
        core_hits = _rule_group_score(text, rules.get("core", []))
        actor_hits = _rule_group_score(text, rules.get("actor", []))
        impact_hits = _rule_group_score(text, rules.get("impact", []))

        score = (1.0 * core_hits) + (0.7 * actor_hits) + (0.9 * impact_hits)
        group_matched = int(core_hits > 0) + int(actor_hits > 0) + int(impact_hits > 0)
        if group_matched >= 2:
            score += 1.0
        if group_matched == 3:
            score += 1.0
        score_map[category] = round(score, 3)

    best_category = "OTHER"
    best_score = 0.0
    for category, score in score_map.items():
        if score > best_score:
            best_category = category
            best_score = score

    if best_score <= 0:
        return "OTHER", score_map
    return best_category, score_map


def extract_dynamic_keywords(articles: list[dict]) -> dict:
    """Extract token and bigram frequency from titles/summaries."""
    tokens: list[str] = []
    bigrams: list[str] = []

    for article in articles:
        text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
        words = re.findall(r"[a-z][a-z0-9\-]{2,}", text)
        words = [w for w in words if w not in STOPWORDS and len(w) >= 3]
        tokens.extend(words)
        for i in range(len(words) - 1):
            bg = f"{words[i]} {words[i+1]}"
            if words[i] not in STOPWORDS and words[i + 1] not in STOPWORDS:
                bigrams.append(bg)

    token_counts = Counter(tokens)
    bigram_counts = Counter(bigrams)
    return {
        "dominant_terms": [w for w, c in token_counts.most_common(12) if c >= 2][:8],
        "dominant_bigrams": [w for w, c in bigram_counts.most_common(10) if c >= 2][:6],
    }


def cluster_themes(articles: list[dict]) -> dict:
    """Lightweight theme clustering via recurring terms and bigrams."""
    extracted = extract_dynamic_keywords(articles)
    terms = extracted.get("dominant_terms", [])
    bigrams = extracted.get("dominant_bigrams", [])

    theme_labels = []
    joined = " ".join(terms + bigrams)
    if any(k in joined for k in ["fed", "powell", "fomc", "rate"]):
        theme_labels.append("연준/금리")
    if any(k in joined for k in ["yield", "treasury", "bond"]):
        theme_labels.append("국채금리")
    if any(k in joined for k in ["inflation", "cpi", "pce", "ppi"]):
        theme_labels.append("인플레이션")
    if any(k in joined for k in ["ai", "nvidia", "semiconductor", "chip", "cloud"]):
        theme_labels.append("AI/기술")
    if any(k in joined for k in ["oil", "crude", "opec", "shipping"]):
        theme_labels.append("에너지")
    if any(k in joined for k in ["war", "tariff", "sanction", "china"]):
        theme_labels.append("지정학")
    if any(k in joined for k in ["volatility", "selloff", "vix", "risk-off"]):
        theme_labels.append("시장 스트레스")

    return {
        "dominant_terms": terms,
        "dominant_bigrams": bigrams,
        "theme_labels": theme_labels[:5],
    }


def _compute_sentiment(text: str) -> float:
    pos = sum(1 for w in POSITIVE_PHRASES if w in text)
    neg = sum(1 for w in NEGATIVE_PHRASES if w in text)
    if pos == 0 and neg == 0:
        return 0.0
    score = (pos - neg) / max(1, pos + neg)
    return round(max(-1.0, min(1.0, score)), 3)


def score_article_impact(article: dict, pattern_score: float) -> tuple[float, float]:
    """Source-aware impact score with supportive sentiment."""
    text = f"{article.get('title', '')} {article.get('summary', '')}".lower()
    sentiment = _compute_sentiment(text)

    category = article.get("category", "OTHER")
    category_weight = CATEGORY_WEIGHTS.get(category, CATEGORY_WEIGHTS["OTHER"])
    source_weight = float(article.get("source_weight", 0.0))

    impact = pattern_score * category_weight * max(0.1, source_weight)
    impact *= 1.0 + (0.15 * abs(sentiment))
    return round(impact, 3), sentiment


def aggregate_macro_signals(articles: list[dict], theme_info: dict) -> dict:
    """Aggregate category signals with core/secondary consensus logic."""
    if not articles:
        return {
            "sentiment_score": 0.0,
            "risk_level": "MODERATE",
            "risk_level_label": "보통",
            "macro_drivers": ["핵심 매체 보도 신호가 부족합니다."],
            "dominant_categories": ["OTHER"],
            "category_scores": {},
            "core_article_count": 0,
            "secondary_article_count": 0,
        }

    sentiments = [float(a.get("sentiment", 0.0)) for a in articles]
    avg_sentiment = round(sum(sentiments) / len(sentiments), 3)

    if avg_sentiment <= -0.5:
        risk_level = "HIGH"
    elif avg_sentiment <= 0.2:
        risk_level = "MODERATE"
    else:
        risk_level = "LOW"

    category_scores: dict[str, dict[str, float]] = {}
    for article in articles:
        cat = article.get("category", "OTHER")
        impact = float(article.get("impact_score", 0.0))
        tier = article.get("source_tier", "unknown")

        if cat not in category_scores:
            category_scores[cat] = {"core_theme_score": 0.0, "secondary_theme_score": 0.0, "total_theme_score": 0.0}

        if tier == "core":
            category_scores[cat]["core_theme_score"] += impact
        elif tier == "secondary":
            category_scores[cat]["secondary_theme_score"] += impact

    for cat, sc in category_scores.items():
        sc["total_theme_score"] = round(sc["core_theme_score"] + (0.8 * sc["secondary_theme_score"]), 3)

    dominant_categories = [
        c for c, _ in sorted(category_scores.items(), key=lambda kv: kv[1]["total_theme_score"], reverse=True)
    ][:4]

    label_map = {
        "POLICY_RATE_RISK": "금리 경로 리스크",
        "YIELD_PRESSURE": "장기금리 압력",
        "INFLATION_PRESSURE": "인플레이션 압력",
        "LABOR_SOFTNESS": "고용 둔화",
        "GROWTH_SLOWDOWN": "성장 둔화",
        "TECH_AI_SUPPORT": "AI/기술 모멘텀",
        "GEOPOLITICAL_CONFLICT": "지정학 갈등",
        "ENERGY_SUPPLY_RISK": "에너지 공급 리스크",
        "MARKET_STRESS": "시장 스트레스",
        "OTHER": "기타 이슈",
    }

    macro_drivers = []
    for cat in dominant_categories[:3]:
        score = category_scores.get(cat, {})
        core_score = score.get("core_theme_score", 0.0)
        sec_score = score.get("secondary_theme_score", 0.0)
        if core_score > 0 and core_score >= sec_score:
            macro_drivers.append(f"핵심 매체 합의 기준으로 '{label_map.get(cat, cat)}' 이슈가 주요 변수로 부각됩니다.")
        else:
            macro_drivers.append(f"보조 매체 중심으로 '{label_map.get(cat, cat)}' 이슈가 보완 신호로 확인됩니다.")

    if theme_info.get("theme_labels"):
        macro_drivers.append(f"반복 테마: {', '.join(theme_info['theme_labels'][:3])}")

    core_article_count = sum(1 for a in articles if a.get("source_tier") == "core")
    secondary_article_count = sum(1 for a in articles if a.get("source_tier") == "secondary")

    return {
        "sentiment_score": avg_sentiment,
        "risk_level": risk_level,
        "risk_level_label": _risk_level_label(risk_level),
        "macro_drivers": macro_drivers[:4],
        "dominant_categories": dominant_categories,
        "category_scores": category_scores,
        "core_article_count": core_article_count,
        "secondary_article_count": secondary_article_count,
    }


def build_portfolio_implication(aggregated_signals: dict, asset_focus: str = "growth") -> str:
    """Generate portfolio-aware practical implication."""
    dom = aggregated_signals.get("dominant_categories", [])
    risk = aggregated_signals.get("risk_level", "MODERATE")

    lines = []
    if "YIELD_PRESSURE" in dom or "POLICY_RATE_RISK" in dom:
        lines.append("금리 및 장기금리 압력으로 성장주 밸류에이션 부담이 커질 수 있습니다.")
    if "MARKET_STRESS" in dom or risk == "HIGH":
        lines.append("변동성 관리 강도를 높이고 현금성 자산 비중 점검이 필요합니다.")
    if "INFLATION_PRESSURE" in dom or "ENERGY_SUPPLY_RISK" in dom:
        lines.append("인플레이션 재가열 가능성에 대비해 공격적 추격매수는 신중한 접근이 바람직합니다.")
    if "TECH_AI_SUPPORT" in dom:
        lines.append("AI/기술 뉴스 흐름은 심리 지지 요인이지만 거시 역풍과 함께 확인해야 합니다.")

    if not lines:
        lines.append("뉴스 신호가 혼재되어 있어 기존 전략 신호 중심의 단계적 대응이 유효합니다.")

    if (asset_focus or "").lower() == "growth" and all("성장주" not in s for s in lines):
        lines.insert(0, "성장주 중심 포트폴리오는 금리와 변동성 변화에 민감하므로 리스크 관리 우선이 필요합니다.")

    return " ".join(lines[:3])


def generate_korean_macro_brief(articles: list[dict], aggregated_signals: dict, theme_info: dict, asset_focus: str = "growth") -> dict:
    """Generate final Korean dashboard-facing briefing texts."""
    if not articles:
        return {
            "headline_summary": "핵심 매체 뉴스 데이터가 부족해 지표 기반 해석을 우선 적용합니다.",
            "market_implication": "현재는 단기 변동성 확대 여부를 우선 점검하는 보수적 접근이 유효합니다.",
            "portfolio_implication": "전략 신호와 현금성 비중을 기준으로 단계적으로 대응하세요.",
            "asset_implications": {
                "QQQM": "성장주 밸류에이션은 금리와 변동성 민감도가 높습니다.",
                "SCHD": "배당/퀄리티 특성은 방어 완충 역할을 기대할 수 있습니다.",
                "IAU": "실질금리 하락 또는 위험회피 국면에서 상대적 방어성이 부각됩니다.",
                "SGOV": "현금성 자산으로 변동성 확대 구간의 완충 역할이 가능합니다.",
            },
            "watch_points": ["미국 10년물 금리 방향", "VIX 재상승 여부", "연준 발언 및 금리 경로 변화"],
        }

    top = articles[:5]
    lead = top[0]
    lead_title = lead.get("title", "대표 뉴스")
    lead_source = lead.get("source", "핵심 매체")

    drivers = aggregated_signals.get("macro_drivers", [])
    headline_summary = (
        "핵심 매체 보도 기준으로 "
        f"{drivers[0] if drivers else '주요 거시 변수'} "
        f"대표 뉴스({lead_source}) '{lead_title}'가 오늘 시장 심리에 영향을 줄 수 있습니다."
    )

    risk_level = aggregated_signals.get("risk_level", "MODERATE")
    if risk_level == "HIGH":
        market_implication = "단기적으로 위험자산 변동성 확대 가능성이 높아 방어적 포지셔닝 점검이 필요합니다."
    elif risk_level == "LOW":
        market_implication = "핵심 뉴스 심리는 상대적으로 안정적이나, 금리 및 변동성 재반등 가능성은 계속 점검해야 합니다."
    else:
        market_implication = "시장 심리는 혼재되어 있어 뉴스 신호와 지표 흐름을 함께 확인하는 중립적 대응이 적절합니다."

    portfolio_implication = build_portfolio_implication(aggregated_signals, asset_focus=asset_focus)

    asset_implications = {
        "QQQM": "장기금리와 실적 기대의 균형이 핵심이며 변동성 확대 시 밸류에이션 압력을 점검해야 합니다.",
        "SCHD": "현금흐름/배당 안정성이 상대 방어 요소이나 경기 둔화 시 이익 가이던스 확인이 필요합니다.",
        "IAU": "실질금리와 달러 방향, 위험회피 수요에 따라 헤지 효율이 달라질 수 있습니다.",
        "SGOV": "단기 금리 구간의 캐리와 대기자금 기능으로 포트폴리오 완충에 유리합니다.",
    }

    watch_points = ["미국 10년물 금리 방향", "VIX 재상승 여부", "연준 발언 및 금리 경로 변화", "브렌트유와 에너지 가격 흐름"]
    if theme_info.get("theme_labels"):
        watch_points.insert(0, f"반복 테마: {', '.join(theme_info['theme_labels'][:2])}")

    dedup = []
    for w in watch_points:
        if w not in dedup:
            dedup.append(w)

    return {
        "headline_summary": headline_summary,
        "market_implication": market_implication,
        "portfolio_implication": portfolio_implication,
        "asset_implications": asset_implications,
        "watch_points": dedup[:4],
    }


def get_news_brief(lookback_days=2, max_articles=20, region="US", asset_focus="growth") -> dict:
    """Public API for TEAM FIRE 25 news-based macro briefing."""
    try:
        queries = list(DEFAULT_QUERIES)
        if (asset_focus or "").lower() == "growth":
            queries.append("Nasdaq large cap growth stocks")

        raw_articles = fetch_news_articles(queries=queries, region=region, max_per_query=8)
        if not raw_articles:
            return _fallback_output("RSS 뉴스 수집 실패")

        normalized = normalize_articles(raw_articles, lookback_days=lookback_days)
        deduped = deduplicate_articles(normalized)
        articles = deduped[: max(1, int(max_articles))]
        if not articles:
            return _fallback_output("신뢰 가능한 뉴스가 부족합니다")

        enriched = []
        for article in articles:
            category, score_map = classify_article(article)
            pattern_score = max(score_map.values()) if score_map else 0.0

            item = dict(article)
            item["category"] = category
            impact, sentiment = score_article_impact(item, pattern_score=pattern_score)
            item["impact_score"] = impact
            item["sentiment"] = sentiment
            enriched.append(item)

        theme_info = cluster_themes(enriched)
        aggregated = aggregate_macro_signals(enriched, theme_info)
        briefing = generate_korean_macro_brief(enriched, aggregated, theme_info, asset_focus=asset_focus)

        output = {
            "status": "ok",
            "as_of": _now_str(),
            "article_count": len(enriched),
            "headline_summary": briefing["headline_summary"],
            "macro_drivers": aggregated.get("macro_drivers", []),
            "market_implication": briefing["market_implication"],
            "portfolio_implication": briefing["portfolio_implication"],
            "asset_implications": briefing.get("asset_implications", {}),
            "watch_points": briefing["watch_points"],
            "sentiment_score": aggregated.get("sentiment_score", 0.0),
            "risk_level": aggregated.get("risk_level", "MODERATE"),
            "risk_level_label": aggregated.get("risk_level_label", "보통"),
            "dominant_terms": theme_info.get("dominant_terms", []),
            "dominant_bigrams": theme_info.get("dominant_bigrams", []),
            "raw_article_count": len(raw_articles),
            "normalized_article_count": len(normalized),
            "matched_core_count": sum(1 for a in normalized if a.get("source_tier") == "core"),
            "matched_secondary_count": sum(1 for a in normalized if a.get("source_tier") == "secondary"),
            "matched_unknown_count": sum(1 for a in normalized if a.get("source_tier") == "unknown"),
            "core_article_count": aggregated.get("core_article_count", 0),
            "secondary_article_count": aggregated.get("secondary_article_count", 0),
            "articles": enriched,
            "brief_source": "rule_based",
        }

        gemini_payload = build_gemini_payload(enriched, aggregated, theme_info, asset_focus=asset_focus)
        ai_output = try_generate_gemini_brief(gemini_payload)
        if ai_output:
            # Narrative fields only: preserve raw analytics from deterministic layer.
            output["headline_summary"] = ai_output.get("headline_summary", output["headline_summary"])
            output["market_implication"] = ai_output.get("market_implication", output["market_implication"])
            output["portfolio_implication"] = ai_output.get("portfolio_implication", output["portfolio_implication"])
            output["asset_implications"] = ai_output.get("asset_implications", output.get("asset_implications", {}))
            output["watch_points"] = ai_output.get("watch_points", output["watch_points"])
            output["risk_level_label"] = ai_output.get("risk_level_label", output["risk_level_label"])
            output["brief_source"] = "gemini"

        return output
    except Exception:
        return _fallback_output("뉴스 엔진 처리 중 예외가 발생했습니다")


def get_macro_market_news(limit: int = 8) -> list[dict]:
    """Backward-compatible helper for existing dashboard code."""
    try:
        brief = get_news_brief(lookback_days=2, max_articles=max(8, limit), region="US", asset_focus="growth")
        return (brief.get("articles") or [])[: max(1, limit)]
    except Exception:
        return []


def build_news_macro_brief(news_items: list[dict]) -> dict:
    """Backward-compatible compact briefing for legacy call sites."""
    if not news_items:
        return {
            "headline_summary": [
                "최근 핵심 뉴스 신호가 제한적이라 지표 기반 해석을 우선 적용합니다.",
                "단기적으로는 금리와 변동성 흐름을 중심으로 시장을 점검할 필요가 있습니다.",
                "연준 발언과 장기금리 변화를 함께 확인하는 접근이 바람직합니다.",
            ],
            "watchpoints": ["미국 10년물 금리", "VIX 방향성"],
            "dominant_topics": ["OTHER"],
        }

    enriched = []
    for article in news_items[:5]:
        item = enrich_source_metadata(article)
        category, score_map = classify_article(item)
        item["category"] = category
        impact, sentiment = score_article_impact(item, pattern_score=max(score_map.values()) if score_map else 0.0)
        item["impact_score"] = impact
        item["sentiment"] = sentiment
        enriched.append(item)

    theme_info = cluster_themes(enriched)
    aggregated = aggregate_macro_signals(enriched, theme_info)
    briefing = generate_korean_macro_brief(enriched, aggregated, theme_info, asset_focus="growth")

    return {
        "headline_summary": [
            briefing.get("headline_summary", ""),
            *(aggregated.get("macro_drivers", [])[:2]),
        ][:3],
        "watchpoints": briefing.get("watch_points", [])[:2],
        "dominant_topics": aggregated.get("dominant_categories", ["OTHER"]),
    }
