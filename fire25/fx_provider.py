from __future__ import annotations

from typing import Dict

DEFAULT_KRW_PER_USD = 1300.0
_LAST_FX_RATES: Dict[str, float] = {"KRWUSD": DEFAULT_KRW_PER_USD}


def get_fx_rate(pair: str = "KRWUSD") -> float:
    """Return FX quote as KRW per USD with cache/fallback safety.

    Data source uses yfinance symbol `KRWUSD=X` (USD per KRW), then inverts
    to KRW per USD for stable portfolio normalization semantics.
    """
    if pair != "KRWUSD":
        raise ValueError(f"Unsupported FX pair: {pair}")

    try:
        import yfinance as yf

        df = yf.Ticker("KRWUSD=X").history(period="5d")
        if df is None or df.empty:
            raise ValueError("empty fx data")

        raw_usd_per_krw = float(df["Close"].dropna().iloc[-1])
        if raw_usd_per_krw <= 0:
            raise ValueError("invalid fx quote")

        krw_per_usd = 1.0 / raw_usd_per_krw
        _LAST_FX_RATES[pair] = float(krw_per_usd)
    except Exception:
        return float(_LAST_FX_RATES.get(pair, DEFAULT_KRW_PER_USD))

    return float(_LAST_FX_RATES[pair])


def convert_to_usd(value: float, currency: str) -> float:
    """Normalize amount to USD base currency."""
    if currency == "USD":
        return float(value)
    if currency == "KRW":
        krw_per_usd = get_fx_rate("KRWUSD")
        return float(value) / float(krw_per_usd)
    raise ValueError(f"Unsupported currency: {currency}")
