from __future__ import annotations


def _extract_macro_keywords(market_news: list[dict] | None) -> list[str]:
    """Extract lightweight macro tags from broad headlines."""
    if not market_news:
        return []

    text = " ".join([(n.get("title") or "") for n in market_news]).lower()
    tags = []
    keyword_map = {
        "유가": ["oil", "crude", "energy"],
        "인플레이션": ["inflation", "cpi", "pce"],
        "연준": ["fed", "fomc", "powell", "rate", "rates"],
        "국채금리": ["yield", "treasury"],
        "달러": ["dollar", "usd"],
        "고용": ["payroll", "employment", "jobs", "labor"],
        "지정학": ["geopolit", "war", "conflict", "sanction"],
    }
    for label, keys in keyword_map.items():
        if any(k in text for k in keys):
            tags.append(label)
    return tags[:3]


def summarize_macro_today(vix_data, fng_data, qqqm_data, sgov_data, market_news=None) -> dict:
    """Return a concise rule-based macro summary for dashboard display."""
    vix = float(vix_data.get("price", 0.0)) if vix_data else 0.0
    vix_chg = float(vix_data.get("change_pct", 0.0)) if vix_data else 0.0
    fng = int(fng_data.get("value", 50)) if fng_data and fng_data.get("value") is not None else 50
    rsi = float(qqqm_data.get("rsi", 50.0)) if qqqm_data else 50.0
    sgov_chg = float(sgov_data.get("change_pct", 0.0)) if sgov_data else 0.0

    risk_off_score = 0
    risk_on_score = 0
    bullets = []

    if vix >= 22 or vix_chg >= 5:
        risk_off_score += 2
        bullets.append(f"VIX {vix:.2f} / 변동성 {vix_chg:+.2f}%로 불확실성 압력이 높습니다.")
    elif vix <= 15 and vix_chg <= 0:
        risk_on_score += 1
        bullets.append(f"VIX {vix:.2f} 수준으로 단기 위험선호 환경이 유지됩니다.")

    if fng <= 25:
        risk_off_score += 1
        bullets.append(f"Fear & Greed {fng}로 공포 구간이며, 역발상 분할매수 여지도 있습니다.")
    elif fng >= 75 and rsi >= 65:
        risk_off_score += 1
        bullets.append(f"심리지표 {fng} + RSI {rsi:.1f} 조합은 단기 과열 경계 신호입니다.")
    elif 45 <= fng <= 65:
        bullets.append(f"Fear & Greed {fng}로 심리는 중립권에 가깝습니다.")

    if sgov_data is not None:
        bullets.append(f"SGOV 일변화 {sgov_chg:+.2f}%: 현금성 비중은 방어 캐리 수단으로 유효합니다.")

    macro_tags = _extract_macro_keywords(market_news)
    if macro_tags:
        bullets.append(f"헤드라인 키워드: {', '.join(macro_tags)}")

    news_brief = None
    if market_news:
        try:
            from fire25.news_engine import build_news_macro_brief

            news_brief = build_news_macro_brief(market_news)
        except Exception:
            news_brief = None

    if news_brief and news_brief.get("headline_summary"):
        for line in news_brief["headline_summary"][:2]:
            bullets.append(line)

        dominant_topics = news_brief.get("dominant_topics") or []
        if dominant_topics:
            topic_labels = {
                "FED": "연준/금리",
                "INFLATION": "인플레이션",
                "AI": "AI/반도체",
                "BOND": "국채금리",
                "CHINA": "중국 경기",
                "ENERGY": "에너지",
                "GENERAL": "거시 일반",
            }
            labels = [topic_labels.get(t, "거시 일반") for t in dominant_topics[:3]]
            bullets.append(f"뉴스 주도 이슈: {', '.join(labels)}")

    if risk_off_score >= 2:
        regime = "Risk-off"
        color = "#ef4444"
        implication = "방어 유지 + 분할 매수 대기"
    elif risk_on_score >= 1 and risk_off_score == 0:
        regime = "Risk-on"
        color = "#10b981"
        implication = "추세 추종 가능, 과열 신호는 별도 점검"
    else:
        regime = "Mixed"
        color = "#f59e0b"
        implication = "중립 운용, 신호 기반 분할 접근"

    if news_brief and news_brief.get("watchpoints"):
        implication = f"{implication}. {news_brief['watchpoints'][0]}"

    return {
        "title": "거시 환경은 변동성/심리/헤드라인의 합성 신호로 판단했습니다.",
        "bullets": bullets[:6],
        "regime_label": regime,
        "color": color,
        "implication": implication,
    }
