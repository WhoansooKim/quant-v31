"""Orchestrator — compute all extended indicators for a single symbol.

Called by daily_pipeline (after existing swing_indicators).
Pulls OHLCV from daily_prices, computes MACD/BB/ADX/Ichimoku/VWAP/Wyckoff,
returns a flat dict suitable for persistence or JSON.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from engine_v4.data.storage import PostgresStore
from engine_v4.indicators.adx import adx_latest
from engine_v4.indicators.bollinger import bollinger_latest
from engine_v4.indicators.ichimoku import ichimoku_latest
from engine_v4.indicators.macd import macd_latest
from engine_v4.indicators.vwap import vwap_latest
from engine_v4.indicators.wyckoff import wyckoff_signals

logger = logging.getLogger(__name__)


def _load_ohlcv(pg: PostgresStore, symbol: str, days: int = 200) -> pd.DataFrame | None:
    """Pull last N days of OHLCV from daily_prices."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT time::date AS d, open, high, low, close, volume, adj_close
            FROM daily_prices
            WHERE symbol = %s AND time >= NOW() - INTERVAL '%s days'
            ORDER BY time
            """ % ("%s", days),
            (symbol,),
        ).fetchall()
    if not rows:
        return None
    df = pd.DataFrame([dict(r) for r in rows])
    df["d"] = pd.to_datetime(df["d"])
    df = df.set_index("d")
    df[["open", "high", "low", "close", "adj_close"]] = df[[
        "open", "high", "low", "close", "adj_close"]].astype(float)
    df["volume"] = df["volume"].fillna(0).astype(float)
    return df


def compute_all(pg: PostgresStore, symbol: str) -> dict[str, Any]:
    """Compute all extended indicators for symbol. Returns flat dict."""
    df = _load_ohlcv(pg, symbol)
    if df is None or len(df) < 60:
        return {"symbol": symbol, "error": "insufficient_data"}

    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]
    result: dict[str, Any] = {"symbol": symbol}

    try:
        result.update(macd_latest(close))
    except Exception as e:
        logger.warning(f"MACD {symbol}: {e}")
    try:
        result.update(bollinger_latest(close))
    except Exception as e:
        logger.warning(f"Bollinger {symbol}: {e}")
    try:
        result.update(adx_latest(high, low, close))
    except Exception as e:
        logger.warning(f"ADX {symbol}: {e}")
    try:
        result.update(ichimoku_latest(high, low, close))
    except Exception as e:
        logger.warning(f"Ichimoku {symbol}: {e}")
    try:
        result.update(vwap_latest(high, low, close, volume))
    except Exception as e:
        logger.warning(f"VWAP {symbol}: {e}")
    try:
        result.update(wyckoff_signals(high, low, close, volume))
    except Exception as e:
        logger.warning(f"Wyckoff {symbol}: {e}")

    return result


def compute_batch(pg: PostgresStore, symbols: list[str]) -> dict[str, dict]:
    """Compute for a batch of symbols. Returns {symbol: indicators}."""
    out = {}
    for s in symbols:
        try:
            out[s] = compute_all(pg, s)
        except Exception as e:
            logger.warning(f"Indicator compute failed for {s}: {e}")
            out[s] = {"symbol": s, "error": str(e)}
    return out


def detect_strong_signals(pg: PostgresStore, symbol: str) -> dict[str, Any]:
    """Combined signal strength assessment using all indicators.

    Returns score 0-100 + breakdown — alternative entry score that variant_generator can use.
    """
    ind = compute_all(pg, symbol)
    if ind.get("error"):
        return ind

    score = 0
    breakdown = {}

    # MACD bullish cross + above zero = +20
    if ind.get("bullish_cross"):
        score += 15
        breakdown["macd_bullish_cross"] = 15
    if ind.get("above_zero"):
        score += 5
        breakdown["macd_above_zero"] = 5
    if ind.get("histogram_growing"):
        score += 5
        breakdown["macd_momentum"] = 5

    # ADX trending = +15
    if ind.get("adx_trending") and ind.get("uptrend"):
        score += 15
        breakdown["adx_uptrend"] = 15

    # Ichimoku strong bull = +20
    if ind.get("ichimoku_strong_bull"):
        score += 20
        breakdown["ichimoku_strong_bull"] = 20
    elif ind.get("ichimoku_above_cloud"):
        score += 10
        breakdown["ichimoku_above_cloud"] = 10

    # BB breakout up + not extreme = +10
    if ind.get("bb_breakout_up"):
        score += 10
        breakdown["bb_breakout"] = 10
    if ind.get("bb_squeeze"):
        score += 5  # squeeze = pending breakout
        breakdown["bb_squeeze"] = 5

    # VWAP support = +5
    if ind.get("price_above_vwap"):
        score += 5
        breakdown["vwap_support"] = 5

    # Wyckoff spring = +15 (high-conviction reversal)
    if ind.get("wyckoff_spring"):
        score += 15
        breakdown["wyckoff_spring"] = 15

    # Wyckoff absorption = bullish if combined with other signals
    if ind.get("wyckoff_absorption") and score > 20:
        score += 5
        breakdown["wyckoff_absorption"] = 5

    return {
        "symbol": symbol,
        "extended_score": min(100, score),
        "breakdown": breakdown,
        "raw_indicators": ind,
    }
