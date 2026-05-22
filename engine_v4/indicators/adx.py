"""ADX (Average Directional Index) + DI+ / DI- — trend strength.

  TR (True Range)  = max(H-L, |H-prev_close|, |L-prev_close|)
  +DM              = H_t - H_{t-1} if positive AND > L_{t-1} - L_t else 0
  -DM              = L_{t-1} - L_t if positive AND > H_t - H_{t-1} else 0
  +DI = 100 × EMA(+DM, n) / EMA(TR, n)
  -DI = 100 × EMA(-DM, n) / EMA(TR, n)
  DX  = 100 × |+DI - -DI| / (+DI + -DI)
  ADX = EMA(DX, n)

Interpretation:
  ADX > 25 = trending market
  +DI > -DI = uptrend, -DI > +DI = downtrend
  ADX rising = trend strengthening
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> dict[str, pd.Series]:
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_ema = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1.0 / period, adjust=False).mean() / tr_ema
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1.0 / period, adjust=False).mean() / tr_ema

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_line = dx.ewm(alpha=1.0 / period, adjust=False).mean()

    return {"adx": adx_line, "plus_di": plus_di, "minus_di": minus_di}


def adx_latest(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> dict:
    a = adx(high, low, close, period)
    if len(a["adx"]) < period * 2 or pd.isna(a["adx"].iloc[-1]):
        return {}
    adx_now = float(a["adx"].iloc[-1])
    adx_prev = float(a["adx"].iloc[-2]) if not pd.isna(a["adx"].iloc[-2]) else adx_now
    plus_now = float(a["plus_di"].iloc[-1])
    minus_now = float(a["minus_di"].iloc[-1])
    return {
        "adx": adx_now,
        "plus_di": plus_now,
        "minus_di": minus_now,
        "adx_trending": adx_now > 25,
        "adx_strong_trend": adx_now > 40,
        "adx_rising": adx_now > adx_prev,
        "uptrend": plus_now > minus_now,
        "trend_strength": "strong" if adx_now > 40 else ("trending" if adx_now > 25 else "weak"),
    }
