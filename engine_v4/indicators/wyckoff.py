"""Wyckoff Volume Spread Analysis (VSA) — detect institutional footprints.

Key patterns detected:
  - Spring: false breakdown below recent low, then close back inside range
  - Upthrust: false breakout above recent high, then close back inside
  - No Demand: up bar but narrow spread + low volume = weak rally
  - No Supply: down bar but narrow spread + low volume = bottoming
  - Effort vs Result: high volume but narrow range = absorption

References:
  Wyckoff 1931 — Stock Market Course
  Anna Coulling — A Complete Guide to Volume Price Analysis (2013)
"""

from __future__ import annotations

import pandas as pd


def wyckoff_signals(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
                     lookback: int = 20) -> dict:
    if len(high) < lookback + 1:
        return {}

    # Recent window for range
    recent_high = high.iloc[-(lookback + 1):-1].max()
    recent_low = low.iloc[-(lookback + 1):-1].min()
    avg_volume = volume.iloc[-(lookback + 1):-1].mean()
    avg_range = (high - low).iloc[-(lookback + 1):-1].mean()

    h = float(high.iloc[-1])
    l = float(low.iloc[-1])
    c = float(close.iloc[-1])
    o_today_range = h - l
    v = float(volume.iloc[-1])

    rh = float(recent_high)
    rl = float(recent_low)
    av = float(avg_volume)
    ar = float(avg_range) if avg_range > 0 else 1

    # Spring: low broke below recent low, but close back in range (>50% of bar)
    spring = (l < rl) and (c > rl) and ((c - l) / max(o_today_range, 0.01) > 0.5) and (v > av)

    # Upthrust: high broke above recent high, but close back in range
    upthrust = (h > rh) and (c < rh) and ((h - c) / max(o_today_range, 0.01) > 0.5) and (v > av)

    # No Demand: up day, narrow spread, low volume → weak rally
    up_day = c > float(close.iloc[-2])
    narrow_spread = o_today_range < ar * 0.7
    low_volume = v < av * 0.8
    no_demand = up_day and narrow_spread and low_volume

    # No Supply: down day, narrow spread, low volume → exhausted decline
    down_day = c < float(close.iloc[-2])
    no_supply = down_day and narrow_spread and low_volume

    # Effort vs Result: high volume + narrow spread = absorption
    high_volume = v > av * 1.5
    absorption = high_volume and narrow_spread

    return {
        "wyckoff_spring": spring,
        "wyckoff_upthrust": upthrust,
        "wyckoff_no_demand": no_demand,
        "wyckoff_no_supply": no_supply,
        "wyckoff_absorption": absorption,
        "wyckoff_volume_ratio": v / av if av > 0 else 1.0,
        "wyckoff_range_ratio": o_today_range / ar if ar > 0 else 1.0,
    }
