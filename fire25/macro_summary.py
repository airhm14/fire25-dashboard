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


def summarize_macro_today(vix_data, fng_data, qqqm_data, sgov_data, market_news=None, news_brief=None) -> dict:
    """Return a concise macro summary blended with optional news signals."""
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
        bullets.append(f"VIX {vix:.2f}, 변동성 {vix_chg:+.2f}%로 단기 불확실성 압력이 높습니다.")
    elif vix <= 15 and vix_chg <= 0:
        risk_on_score += 1
        bullets.append(f"VIX {vix:.2f} 수준으로 단기 위험선호 환경이 유지됩니다.")

    if fng <= 25:
        risk_off_score += 1
        bullets.append(f"Fear & Greed {fng}로 공포 구간이며, 역발상 분할 접근 여지가 있습니다.")
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

    local_news_brief = news_brief
    if local_news_brief is None and market_news:
        try:
            from fire25.news_engine import build_news_macro_brief

            local_news_brief = build_news_macro_brief(market_news)
        except Exception:
            local_news_brief = None

    if local_news_brief:
        engine = local_news_brief.get("brief_source", "rule_based")
        if engine == "gemini":
            bullets.append("Gemini 해석 레이어를 결합한 뉴스 요약을 반영했습니다.")

        if isinstance(local_news_brief.get("headline_summary"), str):
            bullets.append(local_news_brief["headline_summary"])
        elif isinstance(local_news_brief.get("headline_summary"), list):
            for line in local_news_brief["headline_summary"][:2]:
                bullets.append(str(line))

        if local_news_brief.get("macro_drivers"):
            for line in local_news_brief["macro_drivers"][:2]:
                bullets.append(str(line))

        if local_news_brief.get("dominant_topics"):
            labels = [str(x) for x in local_news_brief["dominant_topics"][:3]]
            bullets.append(f"뉴스 주도 이슈: {', '.join(labels)}")

        asset_notes = local_news_brief.get("asset_implications")
        if isinstance(asset_notes, dict):
            qqqm_note = str(asset_notes.get("QQQM", "")).strip()
            if qqqm_note:
                bullets.append(f"QQQM 관점: {qqqm_note}")

    if risk_off_score >= 2:
        regime = "방어 우위"
        color = "#ef4444"
        implication = "방어 유지 + 분할 매수 대기"
    elif risk_on_score >= 1 and risk_off_score == 0:
        regime = "위험선호"
        color = "#10b981"
        implication = "추세 추종 가능, 과열 신호는 별도 점검"
    else:
        regime = "혼조"
        color = "#f59e0b"
        implication = "중립 운용, 신호 기반 분할 접근"

    if local_news_brief and local_news_brief.get("market_implication"):
        implication = f"{implication}. {local_news_brief['market_implication']}"
    if local_news_brief and local_news_brief.get("portfolio_implication"):
        implication = f"{implication}. {local_news_brief['portfolio_implication']}"
    elif local_news_brief and local_news_brief.get("watchpoints"):
        implication = f"{implication}. {local_news_brief['watchpoints'][0]}"

    title = "거시 환경은 변동성/심리/헤드라인의 합성 신호로 판단했습니다."
    if local_news_brief and local_news_brief.get("status") == "ok":
        title = "시장 지표와 핵심 뉴스 신호를 결합해 오늘의 거시 환경을 요약했습니다."

    return {
        "title": title,
        "bullets": bullets[:6],
        "regime_label": regime,
        "color": color,
        "implication": implication,
    }
