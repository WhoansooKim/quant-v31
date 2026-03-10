"""Watchlist Backtest — 24-indicator weighted category scoring 기반 히스토리컬 백테스트.

워치리스트 종목에 대해 가중 스코어링 시스템을 과거 데이터에 적용하여
매수/매도 시뮬레이션을 수행합니다.

Entry: weighted_score >= buy_threshold (default +0.12)
Exit:  weighted_score <= sell_threshold (default -0.12) OR trailing stop OR max hold days
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class WatchlistBacktestParams:
    start_date: date = date(2025, 1, 1)
    end_date: date = date(2025, 12, 31)
    initial_capital: float = 1000.0
    position_pct: float = 0.20
    max_positions: int = 3
    buy_threshold: float = 0.12
    sell_threshold: float = -0.12
    trailing_stop_pct: float = 0.05      # 5% trailing stop
    max_hold_days: int = 30              # max holding period
    slippage_pct: float = 0.001          # 0.1% slippage per trade


@dataclass
class WatchlistBacktestResult:
    total_return: float = 0.0
    cagr: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    avg_hold_days: float = 0.0
    final_value: float = 0.0
    equity_curve: list = field(default_factory=list)
    trades_log: list = field(default_factory=list)
    score_series: dict = field(default_factory=dict)  # {symbol: [{date, score, direction}]}


# ─── Indicator helpers (vectorized, same logic as _analyze_watchlist) ───

def _ema_arr(arr, period):
    out = np.empty_like(arr, dtype=float)
    out[0] = float(arr[0])
    m = 2.0 / (period + 1)
    for i in range(1, len(arr)):
        out[i] = (float(arr[i]) - out[i - 1]) * m + out[i - 1]
    return out


def _sma_arr(arr, period):
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = np.mean(arr[i - period + 1:i + 1])
    return out


def _rsi_series(arr, period=14):
    d = np.diff(arr)
    g = np.where(d > 0, d, 0.0)
    l = np.where(d < 0, -d, 0.0)
    avg_g = np.empty(len(d))
    avg_l = np.empty(len(d))
    avg_g[0] = g[0]
    avg_l[0] = max(l[0], 1e-10)
    for i in range(1, len(d)):
        avg_g[i] = (avg_g[i - 1] * (period - 1) + g[i]) / period
        avg_l[i] = (avg_l[i - 1] * (period - 1) + l[i]) / period
    rs = avg_g / np.maximum(avg_l, 1e-10)
    return 100.0 - 100.0 / (1.0 + rs)


def _stoch(high, low, close, k_period=14, d_period=3):
    k_arr = np.full(len(close), np.nan)
    for i in range(k_period - 1, len(close)):
        hh = np.max(high[i - k_period + 1:i + 1])
        ll = np.min(low[i - k_period + 1:i + 1])
        k_arr[i] = ((close[i] - ll) / max(hh - ll, 1e-10)) * 100
    return k_arr


def _williams_r(high, low, close, period=14):
    out = np.full(len(close), np.nan)
    for i in range(period - 1, len(close)):
        hh = np.max(high[i - period + 1:i + 1])
        ll = np.min(low[i - period + 1:i + 1])
        out[i] = ((hh - close[i]) / max(hh - ll, 1e-10)) * -100
    return out


def _cci(high, low, close, period=20):
    tp = (high + low + close) / 3.0
    out = np.full(len(close), np.nan)
    for i in range(period - 1, len(close)):
        window = tp[i - period + 1:i + 1]
        sma = np.mean(window)
        md = np.mean(np.abs(window - sma))
        out[i] = (tp[i] - sma) / max(md * 0.015, 1e-10)
    return out


def _adx(high, low, close, period=14):
    n = len(close)
    if n < period * 2:
        return np.full(n, np.nan)
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    up = high[1:] - high[:-1]
    dn = low[:-1] - low[1:]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_s = _ema_arr(tr, period)
    pdm_s = _ema_arr(pdm, period)
    ndm_s = _ema_arr(ndm, period)
    pdi = 100 * pdm_s / np.maximum(atr_s, 1e-10)
    ndi = 100 * ndm_s / np.maximum(atr_s, 1e-10)
    dx = 100 * np.abs(pdi - ndi) / np.maximum(pdi + ndi, 1e-10)
    adx_arr = _ema_arr(dx, period)
    out = np.full(n, np.nan)
    out[1:] = adx_arr
    return out


def _ultimate_osc(high, low, close, p1=7, p2=14, p3=28):
    bp = close[1:] - np.minimum(low[1:], close[:-1])
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    n = len(bp)
    out = np.full(len(close), np.nan)
    for i in range(max(p1, p2, p3) - 1, n):
        a1 = np.sum(bp[i - p1 + 1:i + 1]) / max(np.sum(tr[i - p1 + 1:i + 1]), 1e-10)
        a2 = np.sum(bp[i - p2 + 1:i + 1]) / max(np.sum(tr[i - p2 + 1:i + 1]), 1e-10)
        a3 = np.sum(bp[i - p3 + 1:i + 1]) / max(np.sum(tr[i - p3 + 1:i + 1]), 1e-10)
        out[i + 1] = 100 * (4 * a1 + 2 * a2 + a3) / 7.0
    return out


def _roc(close, period=12):
    out = np.full(len(close), np.nan)
    for i in range(period, len(close)):
        out[i] = ((close[i] - close[i - period]) / max(abs(close[i - period]), 1e-10)) * 100
    return out


def _sig_score(signals: list[str]) -> float:
    if not signals:
        return 0.0
    total = sum(1 if s == "BUY" else -1 if s == "SELL" else 0 for s in signals)
    return total / len(signals)


def compute_daily_scores(close, high, low, volume) -> list[dict]:
    """Compute weighted category score for every bar.

    Returns list of {index, score, direction, regime} for each valid bar.
    Requires at least 200 bars of lookback; scoring starts from bar 200.
    """
    n = len(close)
    min_bars = 200
    if n < min_bars + 50:
        return []

    # Pre-compute full indicator arrays
    rsi_arr = _rsi_series(close, 14)
    stoch_k = _stoch(high, low, close, 14, 3)
    wr_arr = _williams_r(high, low, close, 14)
    cci_arr = _cci(high, low, close, 20)
    adx_arr = _adx(high, low, close, 14)
    uo_arr = _ultimate_osc(high, low, close)
    roc_arr = _roc(close, 12)
    ema12 = _ema_arr(close, 12)
    ema26 = _ema_arr(close, 26)
    macd_line = ema12 - ema26
    signal_line = _ema_arr(macd_line, 9)
    bull_ema13 = _ema_arr(close, 13)
    bull_power = high - bull_ema13
    bear_power = low - bull_ema13

    # EMA arrays for all MA periods
    ema_arrays = {p: _ema_arr(close, p) for p in [5, 10, 20, 50, 100, 200]}

    results = []

    for i in range(min_bars, n):
        c = close[i]

        # ── Oscillator signals ──
        osc_signals = {}

        # RSI
        rv = float(rsi_arr[i - 1]) if i - 1 < len(rsi_arr) else 50
        osc_signals["RSI"] = "BUY" if rv < 30 else ("SELL" if rv > 70 else "NEUTRAL")

        # Stochastic
        sk = float(stoch_k[i]) if not np.isnan(stoch_k[i]) else 50
        osc_signals["STOCH"] = "BUY" if sk < 20 else ("SELL" if sk > 80 else "NEUTRAL")

        # StochRSI
        rsi_window = rsi_arr[max(0, i - 15):i]
        if len(rsi_window) >= 14:
            rsi_h, rsi_l = np.max(rsi_window), np.min(rsi_window)
            srsi = ((rv - rsi_l) / max(rsi_h - rsi_l, 1e-10)) * 100
        else:
            srsi = 50
        osc_signals["StochRSI"] = "BUY" if srsi < 20 else ("SELL" if srsi > 80 else "NEUTRAL")

        # MACD histogram
        mhist = float(macd_line[i] - signal_line[i])
        osc_signals["MACD"] = "BUY" if mhist > 0 else ("SELL" if mhist < 0 else "NEUTRAL")

        # ADX
        adx_v = float(adx_arr[i]) if not np.isnan(adx_arr[i]) else 25
        if adx_v > 25:
            sma20 = float(np.mean(close[max(0, i - 19):i + 1]))
            osc_signals["ADX"] = "BUY" if c > sma20 else "SELL"
        else:
            osc_signals["ADX"] = "NEUTRAL"

        # Williams %R
        wv = float(wr_arr[i]) if not np.isnan(wr_arr[i]) else -50
        osc_signals["WR"] = "BUY" if wv < -80 else ("SELL" if wv > -20 else "NEUTRAL")

        # CCI
        cv = float(cci_arr[i]) if not np.isnan(cci_arr[i]) else 0
        osc_signals["CCI"] = "BUY" if cv < -100 else ("SELL" if cv > 100 else "NEUTRAL")

        # ATR - always neutral
        osc_signals["ATR"] = "NEUTRAL"

        # Highs/Lows 14d
        h14 = float(np.max(high[max(0, i - 13):i + 1]))
        l14 = float(np.min(low[max(0, i - 13):i + 1]))
        hl_mid = (h14 + l14) / 2
        osc_signals["HL"] = "BUY" if c > hl_mid else ("SELL" if c < hl_mid else "NEUTRAL")

        # Ultimate Oscillator
        uv = float(uo_arr[i]) if not np.isnan(uo_arr[i]) else 50
        osc_signals["UO"] = "BUY" if uv < 30 else ("SELL" if uv > 70 else "NEUTRAL")

        # ROC
        rcv = float(roc_arr[i]) if not np.isnan(roc_arr[i]) else 0
        osc_signals["ROC"] = "BUY" if rcv > 0 else ("SELL" if rcv < 0 else "NEUTRAL")

        # Bull/Bear Power
        bp = float(bull_power[i] + bear_power[i])
        osc_signals["BP"] = "BUY" if bp > 0 else ("SELL" if bp < 0 else "NEUTRAL")

        # ── Moving Average signals ──
        ma_buy = 0
        ma_sell = 0
        for p in [5, 10, 20, 50, 100, 200]:
            if i >= p:
                sma_v = float(np.mean(close[i - p + 1:i + 1]))
                ema_v = float(ema_arrays[p][i])
                if c > sma_v:
                    ma_buy += 1
                else:
                    ma_sell += 1
                if c > ema_v:
                    ma_buy += 1
                else:
                    ma_sell += 1

        # ── Weighted Category Scoring ──
        # Category 1: Trend
        ma_total = max(ma_buy + ma_sell, 1)
        ma_score = (ma_buy - ma_sell) / ma_total
        trend_osc = [osc_signals["ADX"], osc_signals["HL"]]
        trend_score = 0.6 * ma_score + 0.4 * _sig_score(trend_osc)

        # Category 2: Momentum
        momentum_score = _sig_score([osc_signals[k] for k in ["RSI", "ROC", "UO", "BP"]])

        # Category 3: MACD
        macd_score = _sig_score([osc_signals["MACD"]])

        # Category 4: Mean-Reversion
        meanrev_score = _sig_score([osc_signals[k] for k in ["STOCH", "StochRSI", "WR", "CCI"]])

        # Category 5: Volume
        if i >= 20:
            vr = float(np.mean(volume[max(0, i - 4):i + 1])) / max(float(np.mean(volume[max(0, i - 19):i + 1])), 1)
        else:
            vr = 1.0
        vol_score = 1.0 if vr >= 2.0 else (0.5 if vr >= 1.5 else (0.0 if vr >= 1.0 else -0.5))

        # Regime detection via ADX
        if adx_v > 25:
            regime = "TRENDING"
            w_trend, w_mom, w_macd, w_mr, w_vol = 0.40, 0.25, 0.15, 0.10, 0.10
        elif adx_v < 20:
            regime = "SIDEWAYS"
            w_trend, w_mom, w_macd, w_mr, w_vol = 0.15, 0.20, 0.20, 0.30, 0.15
        else:
            regime = "MIXED"
            w_trend, w_mom, w_macd, w_mr, w_vol = 0.30, 0.25, 0.20, 0.15, 0.10

        weighted_raw = (
            w_trend * trend_score +
            w_mom * momentum_score +
            w_macd * macd_score +
            w_mr * meanrev_score +
            w_vol * vol_score
        )

        # Volume confirmation dampening
        vol_factor = 1.0 if vr >= 1.5 else 0.5
        score = weighted_raw * vol_factor

        # Direction
        if score >= 0.35:
            direction = "STRONG_BUY"
        elif score >= 0.12:
            direction = "BUY"
        elif score <= -0.35:
            direction = "STRONG_SELL"
        elif score <= -0.12:
            direction = "SELL"
        else:
            direction = "NEUTRAL"

        results.append({
            "index": i,
            "score": round(score, 4),
            "direction": direction,
            "regime": regime,
        })

    return results


class WatchlistBacktester:
    """Run backtest using watchlist weighted scoring signals."""

    def run(self, symbols: list[str], params: WatchlistBacktestParams) -> WatchlistBacktestResult:
        logger.info(f"Watchlist backtest: {symbols}, {params.start_date}~{params.end_date}")

        # 200-day lookback padding for indicator warm-up
        pad_start = pd.Timestamp(params.start_date) - pd.Timedelta(days=350)

        try:
            data = yf.download(
                symbols,
                start=pad_start.strftime("%Y-%m-%d"),
                end=(pd.Timestamp(params.end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                progress=False,
            )
        except Exception as e:
            logger.error(f"yfinance download failed: {e}")
            return WatchlistBacktestResult()

        if data.empty:
            logger.warning("No data downloaded")
            return WatchlistBacktestResult()

        single = len(symbols) == 1

        def _col(col, sym):
            if single:
                return data[col].dropna().values
            if sym in data[col].columns:
                return data[col][sym].dropna().values
            return np.array([])

        def _dates(sym):
            if single:
                return data[data["Close"].notna()].index
            if sym in data["Close"].columns:
                return data[data["Close"][sym].notna()].index
            return pd.DatetimeIndex([])

        # ── Compute daily scores for each symbol ──
        symbol_data = {}
        score_series_out = {}

        for sym in symbols:
            close = _col("Close", sym)
            high = _col("High", sym)
            low = _col("Low", sym)
            vol = _col("Volume", sym)
            dates = _dates(sym)

            if len(close) < 250:
                logger.warning(f"{sym}: insufficient data ({len(close)} bars)")
                continue

            scores = compute_daily_scores(close, high, low, vol)
            if not scores:
                continue

            # Map scores back to dates
            scored = []
            for s in scores:
                idx = s["index"]
                if idx < len(dates):
                    dt = dates[idx]
                    if pd.Timestamp(params.start_date) <= dt <= pd.Timestamp(params.end_date):
                        scored.append({
                            "date": dt,
                            "close": float(close[idx]),
                            "score": s["score"],
                            "direction": s["direction"],
                            "regime": s["regime"],
                        })

            if scored:
                symbol_data[sym] = scored
                score_series_out[sym] = [
                    {"date": s["date"].strftime("%Y-%m-%d"), "score": s["score"], "direction": s["direction"]}
                    for s in scored
                ]

        if not symbol_data:
            logger.warning("No symbols with sufficient data for backtest")
            return WatchlistBacktestResult()

        # ── Simulation ──
        result = self._simulate(symbol_data, params)
        result.score_series = score_series_out
        return result

    def _simulate(self, symbol_data: dict, params: WatchlistBacktestParams) -> WatchlistBacktestResult:
        """Day-by-day portfolio simulation."""
        cash = params.initial_capital
        positions = {}   # sym -> {qty, entry_price, entry_date, high_water}
        trades = []
        equity_curve = []

        # Collect all unique dates across symbols, sorted
        all_dates = sorted(set(
            s["date"] for scored in symbol_data.values() for s in scored
        ))

        # Build lookup: {sym: {date: {close, score, direction}}}
        lookup = {}
        for sym, scored in symbol_data.items():
            lookup[sym] = {s["date"]: s for s in scored}

        for day in all_dates:
            # ── Check exits first ──
            to_close = []
            for sym, pos in list(positions.items()):
                if sym not in lookup or day not in lookup[sym]:
                    continue
                bar = lookup[sym][day]
                price = bar["close"]
                hold_days = (day - pos["entry_date"]).days

                # Update high water mark
                if price > pos["high_water"]:
                    pos["high_water"] = price

                # Exit conditions
                reason = None

                # 1) Score reversal
                if bar["score"] <= params.sell_threshold:
                    reason = "score_reversal"

                # 2) Trailing stop
                elif pos["high_water"] > 0:
                    dd = (price - pos["high_water"]) / pos["high_water"]
                    if dd <= -params.trailing_stop_pct:
                        reason = "trailing_stop"

                # 3) Max hold days
                elif hold_days >= params.max_hold_days:
                    reason = "max_hold"

                if reason:
                    to_close.append((sym, price, reason, hold_days, day))

            for sym, price, reason, hold_days, day in to_close:
                pos = positions.pop(sym)
                sell_price = price * (1 - params.slippage_pct)
                pnl = (sell_price - pos["entry_price"]) * pos["qty"]
                pnl_pct = (sell_price / pos["entry_price"] - 1) * 100
                cash += sell_price * pos["qty"]
                trades.append({
                    "symbol": sym,
                    "side": "SELL",
                    "entry_date": pos["entry_date"].strftime("%Y-%m-%d"),
                    "exit_date": day.strftime("%Y-%m-%d"),
                    "entry_price": round(pos["entry_price"], 2),
                    "exit_price": round(sell_price, 2),
                    "qty": pos["qty"],
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "hold_days": hold_days,
                    "reason": reason,
                })

            # ── Check entries ──
            candidates = []
            for sym in symbol_data:
                if sym in positions:
                    continue
                if sym not in lookup or day not in lookup[sym]:
                    continue
                bar = lookup[sym][day]
                if bar["score"] >= params.buy_threshold:
                    candidates.append((sym, bar))

            # Sort by score descending (strongest signals first)
            candidates.sort(key=lambda x: x[1]["score"], reverse=True)

            for sym, bar in candidates:
                if len(positions) >= params.max_positions:
                    break

                price = bar["close"]
                buy_price = price * (1 + params.slippage_pct)
                alloc = cash * params.position_pct
                if alloc < buy_price:
                    continue

                qty = int(alloc / buy_price)
                if qty < 1:
                    continue

                cost = buy_price * qty
                if cost > cash:
                    continue

                cash -= cost
                positions[sym] = {
                    "qty": qty,
                    "entry_price": buy_price,
                    "entry_date": day,
                    "high_water": buy_price,
                }

            # ── Record equity ──
            invested = 0.0
            for sym, pos in positions.items():
                if sym in lookup and day in lookup[sym]:
                    invested += lookup[sym][day]["close"] * pos["qty"]
                else:
                    invested += pos["entry_price"] * pos["qty"]

            total_value = cash + invested
            equity_curve.append({
                "date": day.strftime("%Y-%m-%d"),
                "value": round(total_value, 2),
                "cash": round(cash, 2),
                "invested": round(invested, 2),
                "positions": len(positions),
            })

        # ── Force-close remaining positions at last date ──
        if positions and all_dates:
            last_day = all_dates[-1]
            for sym, pos in list(positions.items()):
                if sym in lookup and last_day in lookup[sym]:
                    price = lookup[sym][last_day]["close"]
                else:
                    price = pos["entry_price"]
                sell_price = price * (1 - params.slippage_pct)
                pnl = (sell_price - pos["entry_price"]) * pos["qty"]
                pnl_pct = (sell_price / pos["entry_price"] - 1) * 100
                hold_days = (last_day - pos["entry_date"]).days
                cash += sell_price * pos["qty"]
                trades.append({
                    "symbol": sym,
                    "side": "SELL",
                    "entry_date": pos["entry_date"].strftime("%Y-%m-%d"),
                    "exit_date": last_day.strftime("%Y-%m-%d"),
                    "entry_price": round(pos["entry_price"], 2),
                    "exit_price": round(sell_price, 2),
                    "qty": pos["qty"],
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "hold_days": hold_days,
                    "reason": "end_of_period",
                })

        # ── Calculate metrics ──
        return self._calc_metrics(equity_curve, trades, params)

    def _calc_metrics(self, equity_curve, trades, params) -> WatchlistBacktestResult:
        result = WatchlistBacktestResult()
        result.equity_curve = equity_curve[-500:] if len(equity_curve) > 500 else equity_curve
        result.trades_log = trades[-200:] if len(trades) > 200 else trades
        result.total_trades = len(trades)

        if not equity_curve:
            result.final_value = params.initial_capital
            return result

        initial = params.initial_capital
        final = equity_curve[-1]["value"]
        result.final_value = round(final, 2)
        result.total_return = round((final / initial - 1) * 100, 2)

        # CAGR
        if len(equity_curve) >= 2:
            days = (pd.Timestamp(equity_curve[-1]["date"]) - pd.Timestamp(equity_curve[0]["date"])).days
            years = max(days / 365.25, 0.01)
            if final > 0 and initial > 0:
                result.cagr = round(((final / initial) ** (1 / years) - 1) * 100, 2)

        # Max Drawdown
        values = [e["value"] for e in equity_curve]
        peak = values[0]
        worst_dd = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (v - peak) / peak
            if dd < worst_dd:
                worst_dd = dd
        result.max_drawdown = round(worst_dd * 100, 2)

        # Sharpe Ratio
        if len(values) > 1:
            returns = np.diff(values) / np.array(values[:-1])
            if np.std(returns) > 0:
                result.sharpe_ratio = round(np.mean(returns) / np.std(returns) * np.sqrt(252), 2)

        # Trade stats
        if trades:
            wins = [t for t in trades if t["pnl"] > 0]
            losses = [t for t in trades if t["pnl"] <= 0]
            result.win_rate = round(len(wins) / len(trades) * 100, 1)

            gross_profit = sum(t["pnl"] for t in wins)
            gross_loss = abs(sum(t["pnl"] for t in losses))
            result.profit_factor = round(gross_profit / max(gross_loss, 0.01), 2)

            result.avg_hold_days = round(np.mean([t["hold_days"] for t in trades]), 1)

        return result
