from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import requests


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


def _parse_pub_datetime(value: str) -> datetime:
    """Parse RSS pubDate into timezone-aware datetime."""
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def get_google_news_rss(query: str, limit: int = 5) -> list[dict]:
    """Fetch Google News RSS headlines for a query without API key."""
    if not query:
        return []

    url = (
        f"{GOOGLE_NEWS_RSS}?q={quote_plus(query)}"
        "&hl=en-US&gl=US&ceid=US:en"
    )

    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return []

        root = ET.fromstring(resp.content)
        out: list[dict] = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            if not title:
                continue

            source = (item.findtext("source") or "Google News").strip()
            published = (item.findtext("pubDate") or "").strip()
            out.append(
                {
                    "title": title,
                    "source": source,
                    "published": published,
                    "query": query,
                }
            )
            if len(out) >= max(1, limit):
                break
        return out
    except Exception:
        return []


def get_macro_market_news(limit: int = 8) -> list[dict]:
    """Collect and merge macro-relevant market headlines from Google News RSS."""
    queries = [
        "Federal Reserve stock market",
        "US economy inflation",
        "Nasdaq AI stocks",
        "Treasury yields market",
        "China economy markets",
    ]

    per_query = max(3, min(6, limit))
    merged: list[dict] = []
    for q in queries:
        merged.extend(get_google_news_rss(q, limit=per_query))

    seen: set[str] = set()
    unique_items: list[dict] = []
    for item in merged:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_items.append(item)

    unique_items.sort(
        key=lambda x: _parse_pub_datetime(x.get("published", "")),
        reverse=True,
    )
    return unique_items[: max(1, limit)]


def classify_news_topic(title: str) -> str:
    """Classify a headline into a simple macro topic bucket."""
    text = (title or "").lower()

    topic_rules = [
        ("FED", ["fed", "powell", "fomc", "rate", "rates", "federal reserve", "hawkish", "dovish"]),
        ("INFLATION", ["inflation", "cpi", "pce", "consumer prices", "price pressure"]),
        ("AI", ["ai", "artificial intelligence", "nvidia", "chip", "chips", "semiconductor"]),
        ("BOND", ["treasury", "yield", "yields", "bond", "bonds", "10-year"]),
        ("CHINA", ["china", "beijing", "chinese", "yuan"]),
        ("ENERGY", ["oil", "crude", "opec", "energy", "gas"]),
    ]

    for topic, keywords in topic_rules:
        if any(k in text for k in keywords):
            return topic
    return "GENERAL"


def _topic_label_ko(topic: str) -> str:
    mapping = {
        "FED": "연준/금리",
        "INFLATION": "인플레이션",
        "AI": "AI/반도체",
        "BOND": "국채금리",
        "CHINA": "중국 경기",
        "ENERGY": "에너지",
        "GENERAL": "거시 일반",
    }
    return mapping.get(topic, "거시 일반")


def _build_watchpoints(dominant_topics: list[str]) -> list[str]:
    watch = []

    if "FED" in dominant_topics or "INFLATION" in dominant_topics:
        watch.append("미국 물가 지표(CPI/PCE)와 연준 인사 발언의 톤 변화를 확인할 필요가 있습니다.")
    if "BOND" in dominant_topics:
        watch.append("미국 10년물 금리와 VIX의 동반 상승 여부를 유심히 볼 필요가 있습니다.")
    if "AI" in dominant_topics:
        watch.append("AI/반도체 대형주의 실적 가이던스가 나스닥 심리를 좌우할 수 있습니다.")
    if "CHINA" in dominant_topics:
        watch.append("중국 경기 지표와 정책 부양 강도가 원자재 및 위험자산 심리에 영향을 줄 수 있습니다.")
    if "ENERGY" in dominant_topics:
        watch.append("유가 급등 여부가 기대 인플레이션과 장기금리 재상승 압력으로 이어지는지 점검이 필요합니다.")

    if not watch:
        watch = [
            "단기적으로는 VIX 방향성과 나스닥 추세의 동행 여부를 확인할 필요가 있습니다.",
            "거시 이벤트 발표 전후 금리 변동성이 확대되는지 점검하는 것이 좋습니다.",
        ]

    return watch[:2]


def build_news_macro_brief(news_items: list[dict]) -> dict:
    """Build deterministic Korean macro briefing from headlines."""
    if not news_items:
        return {
            "headline_summary": [
                "최근 뚜렷한 매크로 헤드라인 유입이 제한적이라 지표 중심 해석이 유효합니다.",
                "단기적으로는 변동성 지표와 금리 흐름이 시장 심리를 좌우할 가능성이 큽니다.",
                "앞으로는 주요 경제지표 발표 구간에서 위험선호 변화 여부를 확인할 필요가 있습니다.",
            ],
            "watchpoints": [
                "VIX와 장기금리의 동반 상승 여부를 우선 점검하세요.",
                "나스닥 추세와 거래대금 회복 여부를 함께 확인하세요.",
            ],
            "dominant_topics": ["GENERAL"],
        }

    top_items = news_items[:5]
    topics = [classify_news_topic(item.get("title", "")) for item in top_items]
    counts = Counter(topics)
    dominant_topics = [k for k, _ in counts.most_common(3)]

    dominant_ko = [_topic_label_ko(t) for t in dominant_topics]
    first_title = (top_items[0].get("title") or "").strip()
    first_source = (top_items[0].get("source") or "주요 외신").strip()

    headline_summary = [
        f"최근 {', '.join(dominant_ko)} 이슈가 동시에 부각되며 단기 매크로 변동성이 커지는 분위기입니다.",
        f"대표 헤드라인(출처: {first_source})은 '{first_title}'로, 위험선호 심리에 직접적인 영향을 줄 수 있습니다.",
    ]

    if "AI" in dominant_topics:
        headline_summary.append("특히 AI/반도체 관련 뉴스는 기술주 심리와 나스닥 방향성에 민감하게 작용할 수 있습니다.")
    elif "FED" in dominant_topics or "INFLATION" in dominant_topics:
        headline_summary.append("금리 경로 불확실성이 다시 부각되면서 성장주와 장기채의 변동성 확대 가능성을 경계할 필요가 있습니다.")
    elif "BOND" in dominant_topics:
        headline_summary.append("장기금리 뉴스 흐름이 밸류에이션 부담으로 연결될 수 있어 멀티플 민감 업종 변동성에 유의해야 합니다.")
    elif "CHINA" in dominant_topics:
        headline_summary.append("중국 경기 관련 뉴스는 글로벌 수요 기대를 통해 원자재 및 경기민감주 심리에 파급될 수 있습니다.")
    else:
        headline_summary.append("당분간은 개별 뉴스보다 금리·변동성 같은 핵심 매크로 축의 방향을 우선 점검하는 접근이 유효합니다.")

    watchpoints = _build_watchpoints(dominant_topics)

    return {
        "headline_summary": headline_summary[:3],
        "watchpoints": watchpoints[:2],
        "dominant_topics": dominant_topics,
    }
