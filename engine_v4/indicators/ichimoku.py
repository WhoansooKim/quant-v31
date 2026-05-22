"""Ichimoku Cloud (Ichimoku Kinkō Hyō).

Five lines:
  Tenkan-sen (Conversion): (max_high(9) + min_low(9)) / 2
  Kijun-sen (Base):        (max_high(26) + min_low(26)) / 2
  Senkou A (Lead A):       (Tenkan + Kijun) / 2, plotted 26 ahead → forms cloud
  Senkou B (Lead B):       (max_high(52) + min_low(52)) / 2, plotted 26 ahead → forms cloud
  Chikou (Lagging):        close plotted 26 behind

Signals:
  - Price above cloud + cloud green (A > B) = strong bullish
  - Tenkan > Kijun = short-term bullish
  - Price below cloud + cloud red = strong bearish
"""

from __future__ import annotations

import pandas as pd


def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
              conv: int = 9, base: int = 26, lead_b: int = 52, lag: int = 26) -> dict[str, pd.Series]:
    tenkan = (high.rolling(conv).max() + low.rolling(conv).min()) / 2
    kijun = (high.rolling(base).max() + low.rolling(base).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(lag)
    senkou_b = ((high.rolling(lead_b).max() + low.rolling(lead_b).min()) / 2).shift(lag)
    chikou = close.shift(-lag)
    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "senkou_a": senkou_a,
        "senkou_b": senkou_b,
        "chikou": chikou,
    }


def ichimoku_latest(high: pd.Series, low: pd.Series, close: pd.Series) -> dict:
    i = ichimoku(high, low, close)
    if len(close) < 52 or pd.isna(i["senkou_a"].iloc[-1]) or pd.isna(i["senkou_b"].iloc[-1]):
        return {}

    price = float(close.iloc[-1])
    tenkan_now = float(i["tenkan"].iloc[-1])
    kijun_now = float(i["kijun"].iloc[-1])
    sa = float(i["senkou_a"].iloc[-1])
    sb = float(i["senkou_b"].iloc[-1])

    cloud_top = max(sa, sb)
    cloud_bottom = min(sa, sb)
    cloud_green = sa > sb  # bullish cloud

    return {
        "ichimoku_tenkan": tenkan_now,
        "ichimoku_kijun": kijun_now,
        "ichimoku_senkou_a": sa,
        "ichimoku_senkou_b": sb,
        "ichimoku_cloud_green": cloud_green,
        "ichimoku_above_cloud": price > cloud_top,
        "ichimoku_below_cloud": price < cloud_bottom,
        "ichimoku_in_cloud": cloud_bottom <= price <= cloud_top,
        "ichimoku_tk_cross_bull": tenkan_now > kijun_now,
        "ichimoku_strong_bull": price > cloud_top and cloud_green and tenkan_now > kijun_now,
        "ichimoku_strong_bear": price < cloud_bottom and not cloud_green and tenkan_now < kijun_now,
    }
