from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

STANDARD_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
TZ_SEOUL = "Asia/Seoul"


def detect_asset_type(symbol: str) -> str:
    """Detect asset class routing key for the symbol."""
    if symbol.startswith("KRW-"):
        return "CRYPTO"
    if symbol.endswith(".KS") or symbol.isdigit():
        return "KR_EQUITY"
    return "US_EQUITY"


def _period_to_days(period: str) -> int:
    p = (period or "1y").strip().lower()
    if p == "max":
        return 365 * 30
    if p.endswith("y"):
        return max(int(p[:-1]), 1) * 252
    if p.endswith("mo"):
        return max(int(p[:-2]), 1) * 21
    if p.endswith("m") and p[:-1].isdigit():
        return max(int(p[:-1]), 1) * 21
    if p.endswith("d"):
        return max(int(p[:-1]), 1)
    return 252


def _period_to_upbit_count(period: str) -> int:
    # pyupbit count is candle count; keep a practical cap while reflecting period intent.
    days = _period_to_days(period)
    return min(max(days, 30), 1000)


def _normalize_index(df: pd.DataFrame, source: str) -> pd.DataFrame:
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))

    if source == "US_EQUITY":
        if idx.tz is None:
            try:
                idx = idx.tz_localize("America/New_York")
            except Exception:
                idx = idx.tz_localize("UTC")
        idx = idx.tz_convert(TZ_SEOUL)
    else:
        if idx.tz is None:
            idx = idx.tz_localize(TZ_SEOUL)
        else:
            idx = idx.tz_convert(TZ_SEOUL)

    df = df.copy()
    df.index = idx
    df.index.name = "Date"
    return df


def _standardize_ohlcv(df: pd.DataFrame, source: str) -> pd.DataFrame:
    renamed = df.copy()

    # Korean source columns (PyKRX)
    renamed = renamed.rename(
        columns={
            "시가": "Open",
            "고가": "High",
            "저가": "Low",
            "종가": "Close",
            "거래량": "Volume",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )

    missing = [c for c in STANDARD_COLUMNS if c not in renamed.columns]
    if missing:
        raise ValueError(f"missing OHLCV columns: {missing}")

    out = renamed[STANDARD_COLUMNS].copy()
    out.index = pd.to_datetime(out.index)
    out = _normalize_index(out, source=source)

    for col in STANDARD_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna()
    if out.empty:
        raise ValueError("empty OHLCV after cleaning")

    return out


def _fetch_kr_equity(symbol: str, period: str) -> pd.DataFrame:
    try:
        from pykrx import stock
    except Exception as exc:
        raise ValueError("PyKRX is not available") from exc

    ticker = symbol[:-3] if symbol.endswith(".KS") else symbol
    if not ticker.isdigit():
        raise ValueError(f"invalid Korean ticker: {symbol}")

    end = pd.Timestamp.now(tz=TZ_SEOUL).normalize()
    start = end - timedelta(days=_period_to_days(period))

    raw = stock.get_market_ohlcv_by_date(
        start.strftime("%Y%m%d"),
        end.strftime("%Y%m%d"),
        ticker,
    )
    if raw is None or raw.empty:
        raise ValueError("empty PyKRX response")

    return _standardize_ohlcv(raw, source="KR_EQUITY")


def _fetch_crypto(symbol: str, period: str, interval: str = "day") -> pd.DataFrame:
    try:
        import pyupbit
    except Exception as exc:
        raise ValueError("pyupbit is not available") from exc

    valid_intervals = {"day", "minute60", "minute240"}
    if interval not in valid_intervals:
        raise ValueError(f"unsupported crypto interval: {interval}")

    count = _period_to_upbit_count(period)
    raw = pyupbit.get_ohlcv(symbol, interval=interval, count=count)
    if raw is None or raw.empty:
        raise ValueError("empty pyupbit response")

    return _standardize_ohlcv(raw, source="CRYPTO")


def _fetch_us_equity(symbol: str, period: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except Exception as exc:
        raise ValueError("yfinance is not available") from exc

    raw = yf.Ticker(symbol).history(period=period)
    if raw is None or raw.empty:
        raise ValueError("empty yfinance response")

    return _standardize_ohlcv(raw, source="US_EQUITY")


def get_market_data(
    symbol: str,
    period: str = "1y",
    interval: str = "day",
    with_metadata: bool = True,
) -> dict[str, Any] | pd.DataFrame:
    """Unified market data provider with standardized OHLCV output.

    Returns metadata by default; set with_metadata=False for legacy DataFrame-only behavior.
    """
    asset_type = detect_asset_type(symbol)

    try:
        if asset_type == "KR_EQUITY":
            df = _fetch_kr_equity(symbol, period)
            currency = "KRW"
        elif asset_type == "CRYPTO":
            df = _fetch_crypto(symbol, period, interval=interval)
            currency = "KRW"
        else:
            df = _fetch_us_equity(symbol, period)
            currency = "USD"

        if with_metadata:
            return {
                "df": df,
                "currency": currency,
                "asset_type": asset_type,
            }
        return df
    except Exception as exc:
        raise ValueError(f"Unable to fetch data for {symbol}") from exc
