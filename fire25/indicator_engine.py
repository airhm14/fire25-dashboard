from __future__ import annotations

import pandas as pd


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add core trend/momentum indicators and return updated DataFrame."""
    out = df.copy()

    out["SMA_20"] = out["Close"].rolling(window=20).mean()
    out["SMA_50"] = out["Close"].rolling(window=50).mean()
    out["SMA_100"] = out["Close"].rolling(window=100).mean()
    out["SMA_200"] = out["Close"].rolling(window=200).mean()

    delta = out["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    out["RSI"] = 100 - (100 / (1 + rs))

    return out
