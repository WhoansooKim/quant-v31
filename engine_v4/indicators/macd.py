"""MACD — Moving Average Convergence Divergence.

  MACD line     = EMA(12) - EMA(26)
  Signal line   = EMA(9) of MACD line
  Histogram     = MACD - Signal

Signals:
  - Bullish: MACD crosses above Signal AND > 0
  - Bearish: MACD crosses below Signal
  - Strength: |Histogram| growing = momentum increasing
"""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, pd.Series]:
    """Returns {macd, signal, histogram}."""
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return {"macd": macd_line, "signal": signal_line, "histogram": hist}


def macd_latest(close: pd.Series, **kwargs) -> dict:
    """Latest MACD values + crossover flags."""
    m = macd(close, **kwargs)
    if len(m["macd"]) < 2:
        return {}
    macd_now = float(m["macd"].iloc[-1])
    macd_prev = float(m["macd"].iloc[-2])
    sig_now = float(m["signal"].iloc[-1])
    sig_prev = float(m["signal"].iloc[-2])
    hist_now = float(m["histogram"].iloc[-1])
    hist_prev = float(m["histogram"].iloc[-2])
    return {
        "macd": macd_now,
        "signal": sig_now,
        "histogram": hist_now,
        "bullish_cross": macd_prev < sig_prev and macd_now > sig_now,
        "bearish_cross": macd_prev > sig_prev and macd_now < sig_now,
        "above_zero": macd_now > 0,
        "histogram_growing": hist_now > hist_prev,
    }
