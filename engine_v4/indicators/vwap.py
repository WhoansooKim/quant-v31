"""VWAP — Volume Weighted Average Price.

For daily bars, computes a rolling-N-day VWAP (anchored VWAP requires intraday).

  Typical Price = (H + L + C) / 3
  VWAP_n = Σ(TP × Volume) / Σ(Volume) over last n bars

Use:
  Price > VWAP = institutional support, bullish bias
  Price < VWAP = institutional resistance, bearish bias
"""

from __future__ import annotations

import pandas as pd


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
          period: int = 20) -> pd.Series:
    typical = (high + low + close) / 3
    tp_vol = typical * volume
    return tp_vol.rolling(period, min_periods=period).sum() / volume.rolling(period, min_periods=period).sum()


def vwap_latest(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
                period: int = 20) -> dict:
    v = vwap(high, low, close, volume, period)
    if len(v) < period or pd.isna(v.iloc[-1]):
        return {}
    price = float(close.iloc[-1])
    vwap_now = float(v.iloc[-1])
    return {
        "vwap": vwap_now,
        "vwap_period": period,
        "price_vs_vwap_pct": (price - vwap_now) / vwap_now * 100,
        "price_above_vwap": price > vwap_now,
    }
