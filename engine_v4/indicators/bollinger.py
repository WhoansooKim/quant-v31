"""Bollinger Bands + %B + Bandwidth.

  Mid     = SMA(20)
  Upper   = Mid + 2 × StdDev(20)
  Lower   = Mid - 2 × StdDev(20)
  %B      = (close - lower) / (upper - lower)   # 0 = lower band, 1 = upper
  BW      = (upper - lower) / mid               # squeeze indicator (low = squeeze)
"""

from __future__ import annotations

import pandas as pd


def bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> dict[str, pd.Series]:
    mid = close.rolling(period, min_periods=period).mean()
    sd = close.rolling(period, min_periods=period).std(ddof=0)
    upper = mid + std_mult * sd
    lower = mid - std_mult * sd
    bw = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower)
    return {"mid": mid, "upper": upper, "lower": lower, "bandwidth": bw, "pct_b": pct_b}


def bollinger_latest(close: pd.Series, **kwargs) -> dict:
    b = bollinger(close, **kwargs)
    if len(b["mid"]) < 2 or pd.isna(b["mid"].iloc[-1]):
        return {}
    bw_series = b["bandwidth"].dropna()
    bw_now = float(b["bandwidth"].iloc[-1])
    # Squeeze: bandwidth in lowest 20% of last 100d
    if len(bw_series) >= 20:
        bw_pctile = float((bw_series.iloc[-100:] <= bw_now).mean()) if len(bw_series) >= 20 else 0.5
    else:
        bw_pctile = 0.5
    return {
        "bb_mid": float(b["mid"].iloc[-1]),
        "bb_upper": float(b["upper"].iloc[-1]),
        "bb_lower": float(b["lower"].iloc[-1]),
        "bb_pct_b": float(b["pct_b"].iloc[-1]) if not pd.isna(b["pct_b"].iloc[-1]) else None,
        "bb_bandwidth": bw_now,
        "bb_squeeze": bw_pctile < 0.20,  # bandwidth in bottom 20% historically
        "bb_breakout_up": float(close.iloc[-1]) > float(b["upper"].iloc[-1]),
        "bb_breakout_down": float(close.iloc[-1]) < float(b["lower"].iloc[-1]),
    }
