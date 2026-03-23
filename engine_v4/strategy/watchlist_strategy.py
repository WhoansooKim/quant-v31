"""WatchlistStrategy — 5-Layer Tactical Quality Momentum.

기술우량주(대형 기술주) 워치리스트 전용 전략.
기존 Connors RSI(2) 단기 평균회귀 → 월 2회 중기 매매 최적화.

연구 기반:
  Layer 1: 레짐 필터 — Faber 10-month SMA (2007), Antonacci Dual Momentum (2014)
  Layer 2: 종목 랭킹 — IBD RS Rating (O'Neil), AQR Quality-Momentum (2014)
  Layer 3: 진입 타이밍 — BB/KC Squeeze (Carter TTM), PEAD (Bernard & Thomas 1989), RSI(2) 변형
  Layer 4: 포지션 사이징 — Quarter-Kelly (Thorp 2006), ATR 기반 (Carver 2015)
  Layer 5: 매도 — ATR Trailing, KAMA 이탈 (Kaufman 2013), Graduated Drawdown (Grossman-Zhou 1993)
"""

from __future__ import annotations

import logging
import calendar
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
#  Technical Indicator Helpers (vectorized NumPy)
# ═══════════════════════════════════════════════════════════

def _ema_arr(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.empty_like(arr, dtype=float)
    out[0] = float(arr[0])
    m = 2.0 / (period + 1)
    for i in range(1, len(arr)):
        out[i] = (float(arr[i]) - out[i - 1]) * m + out[i - 1]
    return out


def _sma_arr(arr: np.ndarray, period: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        out[i] = np.mean(arr[i - period + 1:i + 1])
    return out


def _rsi_series(arr: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI (Wilder smoothing)."""
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    rsi = np.full(len(arr), 50.0)
    if avg_loss == 0:
        rsi[period] = 100.0
    else:
        rsi[period] = 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rsi[i + 1] = 100 - 100 / (1 + avg_gain / avg_loss)
    return rsi


def _stoch(high, low, close, k_period=5, d_period=3):
    k_values = np.full(len(close), 50.0)
    for i in range(k_period - 1, len(close)):
        hh = np.max(high[i - k_period + 1:i + 1])
        ll = np.min(low[i - k_period + 1:i + 1])
        if hh != ll:
            k_values[i] = ((close[i] - ll) / (hh - ll)) * 100
    d_values = _sma_arr(k_values, d_period)
    return k_values[-1], d_values[-1] if not np.isnan(d_values[-1]) else k_values[-1]


def _adx(high, low, close, period=14):
    n = len(close)
    if n < period + 1:
        return 20.0
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, hc, lc)
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0
    atr = _ema_arr(tr[1:], period)
    pdi = _ema_arr(plus_dm[1:], period) / np.maximum(atr, 1e-10) * 100
    mdi = _ema_arr(minus_dm[1:], period) / np.maximum(atr, 1e-10) * 100
    dx = np.abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-10) * 100
    adx_val = _ema_arr(dx, period)
    return float(adx_val[-1])


def _mfi(high, low, close, volume, period=14):
    tp = (high + low + close) / 3
    mf = tp * volume
    pos_mf = np.zeros(len(tp))
    neg_mf = np.zeros(len(tp))
    for i in range(1, len(tp)):
        if tp[i] > tp[i - 1]:
            pos_mf[i] = mf[i]
        else:
            neg_mf[i] = mf[i]
    if len(tp) < period + 1:
        return 50.0
    pos_sum = np.sum(pos_mf[-period:])
    neg_sum = np.sum(neg_mf[-period:])
    if neg_sum == 0:
        return 100.0
    return 100 - 100 / (1 + pos_sum / neg_sum)


def _kama(arr: np.ndarray, period: int = 10, fast: int = 2, slow: int = 30) -> np.ndarray:
    """Kaufman Adaptive Moving Average."""
    fast_sc = 2.0 / (fast + 1)
    slow_sc = 2.0 / (slow + 1)
    kama = np.full(len(arr), np.nan)
    if len(arr) < period + 1:
        return kama
    kama[period] = float(arr[period])
    for i in range(period + 1, len(arr)):
        direction = abs(float(arr[i]) - float(arr[i - period]))
        volatility = sum(abs(float(arr[j]) - float(arr[j - 1])) for j in range(i - period + 1, i + 1))
        if volatility == 0:
            er = 0
        else:
            er = direction / volatility
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        kama[i] = kama[i - 1] + sc * (float(arr[i]) - kama[i - 1])
    return kama


def _is_opex_week() -> bool:
    """현재 주가 OPEX 주간(미국 옵션 만기 = 매월 셋째 금요일 포함 주)인지."""
    today = date.today()
    cal = calendar.Calendar(firstweekday=0)
    fridays = [d for d in cal.itermonthdays2(today.year, today.month)
               if d[0] != 0 and d[1] == 4]
    if len(fridays) >= 3:
        third_friday = date(today.year, today.month, fridays[2][0])
        week_start = third_friday - timedelta(days=third_friday.weekday())
        week_end = week_start + timedelta(days=6)
        return week_start <= today <= week_end
    return False


# ═══════════════════════════════════════════════════════════
#  Main Strategy Class
# ═══════════════════════════════════════════════════════════

class WatchlistStrategy:
    """5-Layer Tactical Quality Momentum for Large-Cap Tech.

    기존 Connors RSI(2) 단기 전략과 병행:
    - 기존 출력 형식 100% 호환 (Dashboard 하위 호환)
    - 새 5-Layer 시그널 추가 (layer_* 필드)
    """

    # Layer 1 — Regime thresholds
    REGIME_SMA_PERIOD = 200  # ≈10개월
    VIX_NO_ENTRY = 30
    VIX_HALF_SIZE = 25

    # Layer 2 — Ranking
    RS_LOOKBACK_3M = 63     # trading days
    RS_LOOKBACK_6M = 126
    RS_LOOKBACK_9M = 189
    RS_LOOKBACK_12M = 252

    # Layer 3 — Entry
    BB_PERIOD = 20
    BB_STD = 2.0
    KC_PERIOD = 20
    KC_ATR_MULT = 1.5
    RSI2_ENTRY = 10
    RSI2_STRONG_ENTRY = 5

    # Layer 5 — Exit
    KAMA_PERIOD = 10
    KAMA_FAST = 2
    KAMA_SLOW = 30

    def __init__(self, finnhub_client=None):
        self.finnhub = finnhub_client

    def analyze(self, items: list[dict], price_data, vix_data=None) -> list[dict]:
        """전체 워치리스트 분석.

        Args:
            items: pg.get_watchlist() 결과
            price_data: yfinance download result (symbols + QQQ + ^VIX)
            vix_data: optional separate VIX data

        Returns:
            list of result dicts (기존 형식 호환 + layer 필드 추가)
        """
        symbols = [w["symbol"] for w in items]
        results = []

        # ── Layer 1: 레짐 필터 (Market-level) ──
        regime_info = self._check_regime(price_data, symbols)

        # ── QQQ 벤치마크 데이터 ──
        qqq_close = self._get_col(price_data, "Close", "QQQ", symbols)

        for item in items:
            sym = item["symbol"]
            try:
                result = self._analyze_symbol(
                    sym, item, price_data, symbols,
                    qqq_close, regime_info
                )
                if result:
                    results.append(result)
            except Exception as e:
                logger.warning(f"Watchlist analysis failed for {sym}: {e}")
                continue

        return results

    def _get_col(self, data, col: str, sym: str, symbols: list) -> np.ndarray:
        """yfinance multi-symbol DataFrame에서 컬럼 추출."""
        try:
            if len(symbols) == 1 and sym not in ["QQQ", "^VIX"]:
                if "QQQ" not in symbols and "^VIX" not in symbols:
                    return data[col].dropna().values
            return data[col][sym].dropna().values
        except Exception:
            return np.array([])

    # ─────────────────────────────────────────────────────
    #  Layer 1: Regime Filter
    # ─────────────────────────────────────────────────────

    def _check_regime(self, data, symbols: list) -> dict:
        """시장 레짐 판별 (QQQ + VIX)."""
        qqq = self._get_col(data, "Close", "QQQ", symbols)
        vix = self._get_col(data, "Close", "^VIX", symbols)

        regime = {
            "market_trend": "UNKNOWN",
            "qqq_above_sma200": False,
            "qqq_above_sma50": False,
            "qqq_momentum_3m": 0.0,
            "qqq_momentum_6m": 0.0,
            "vix_level": 0.0,
            "regime_score": 50,  # 0-100
            "entry_allowed": True,
            "size_factor": 1.0,
        }

        if len(qqq) < 210:
            return regime

        sma200 = np.mean(qqq[-200:])
        sma50 = np.mean(qqq[-50:])
        current = float(qqq[-1])

        regime["qqq_above_sma200"] = current > sma200
        regime["qqq_above_sma50"] = current > sma50

        # 3M / 6M absolute momentum
        if len(qqq) >= 63:
            regime["qqq_momentum_3m"] = (current / float(qqq[-63]) - 1) * 100
        if len(qqq) >= 126:
            regime["qqq_momentum_6m"] = (current / float(qqq[-126]) - 1) * 100

        # VIX
        if len(vix) > 0:
            regime["vix_level"] = float(vix[-1])

        # Market trend determination
        if current > sma200 and sma50 > sma200:
            regime["market_trend"] = "BULLISH"
        elif current > sma200:
            regime["market_trend"] = "CAUTIOUS"
        elif current > sma50:
            regime["market_trend"] = "WEAKENING"
        else:
            regime["market_trend"] = "BEARISH"

        # Regime score (0=worst, 100=best)
        score = 50
        if regime["qqq_above_sma200"]:
            score += 20
        if regime["qqq_above_sma50"]:
            score += 10
        if regime["qqq_momentum_3m"] > 0:
            score += 10
        if regime["qqq_momentum_6m"] > 0:
            score += 10
        # VIX penalty
        if regime["vix_level"] > 30:
            score -= 30
        elif regime["vix_level"] > 25:
            score -= 15
        elif regime["vix_level"] < 15:
            score += 10
        regime["regime_score"] = max(0, min(100, score))

        # Entry / sizing decisions
        if regime["vix_level"] >= self.VIX_NO_ENTRY:
            regime["entry_allowed"] = False
            regime["size_factor"] = 0.0
        elif regime["vix_level"] >= self.VIX_HALF_SIZE:
            regime["size_factor"] = 0.5
        elif regime["market_trend"] == "BEARISH":
            regime["entry_allowed"] = False
            regime["size_factor"] = 0.0
        elif regime["market_trend"] == "WEAKENING":
            regime["size_factor"] = 0.5

        return regime

    # ─────────────────────────────────────────────────────
    #  Per-Symbol Analysis
    # ─────────────────────────────────────────────────────

    def _analyze_symbol(self, sym: str, item: dict, data,
                        symbols: list, qqq_close: np.ndarray,
                        regime: dict) -> Optional[dict]:
        close = self._get_col(data, "Close", sym, symbols)
        high = self._get_col(data, "High", sym, symbols)
        low = self._get_col(data, "Low", sym, symbols)
        volume = self._get_col(data, "Volume", sym, symbols)

        if len(close) < 60:
            return None

        current_price = round(float(close[-1]), 2)
        avg_cost = float(item.get("avg_cost") or 0)
        pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 2) if avg_cost > 0 else None

        # ── 기본 지표 계산 ──
        atr_14 = self._calc_atr(high, low, close, 14)
        rsi2 = _rsi_series(close, 2)[-1]
        rsi14 = _rsi_series(close, 14)[-1]
        cum_rsi2 = _rsi_series(close, 2)[-1] + _rsi_series(close, 2)[-2] if len(close) > 3 else rsi2
        adx_val = _adx(high, low, close, 14)

        sma5 = np.mean(close[-5:]) if len(close) >= 5 else current_price
        sma20 = np.mean(close[-20:]) if len(close) >= 20 else current_price
        sma50 = np.mean(close[-50:]) if len(close) >= 50 else current_price
        sma200 = np.mean(close[-200:]) if len(close) >= 200 else current_price

        # KAMA
        kama_vals = _kama(close, self.KAMA_PERIOD, self.KAMA_FAST, self.KAMA_SLOW)
        kama_current = float(kama_vals[-1]) if not np.isnan(kama_vals[-1]) else current_price
        kama_prev = float(kama_vals[-2]) if len(kama_vals) > 1 and not np.isnan(kama_vals[-2]) else kama_current
        kama_slope = kama_current - kama_prev

        # ── Layer 2: 종목 랭킹 ──
        layer2 = self._calc_layer2_ranking(sym, close, qqq_close, high, low, volume)

        # ── Layer 3: 진입 타이밍 ──
        layer3 = self._calc_layer3_entry(close, high, low, volume, rsi2, adx_val, sma200, current_price)

        # ── Quality Score (Finnhub) ──
        quality_info = self._calc_quality_score(sym)

        # ── 기존 Connors RSI(2) 호환 지표 ──
        stoch_k, stoch_d = _stoch(high, low, close, 5, 3)
        ema12 = _ema_arr(close, 12)
        ema26 = _ema_arr(close, 26)
        macd_line = ema12[-1] - ema26[-1]
        signal_line = _ema_arr(ema12 - ema26, 9)[-1]
        macd_hist = macd_line - signal_line
        mfi_val = _mfi(high, low, close, volume, 14)

        # Volume ratio
        vol_sma20 = np.mean(volume[-20:]) if len(volume) >= 20 else 1
        vol_ratio = float(volume[-1]) / vol_sma20 if vol_sma20 > 0 else 1.0

        # QQQ relative strength
        rel_str_5d = 0.0
        rel_str_20d = 0.0
        if len(close) >= 5 and len(qqq_close) >= 5:
            sym_ret5 = float(close[-1] / close[-5] - 1)
            qqq_ret5 = float(qqq_close[-1] / qqq_close[-5] - 1)
            rel_str_5d = sym_ret5 - qqq_ret5
        if len(close) >= 20 and len(qqq_close) >= 20:
            sym_ret20 = float(close[-1] / close[-20] - 1)
            qqq_ret20 = float(qqq_close[-1] / qqq_close[-20] - 1)
            rel_str_20d = sym_ret20 - qqq_ret20

        # Connors exit / OPEX
        connors_exit = bool(current_price > sma5)
        opex_week = _is_opex_week()

        # BB Squeeze (from Layer 3)
        bb_squeeze = layer3["bb_squeeze"]

        # ── Pre-market volume boost ──
        pre_vol_boost = 0.0

        # ── Regime (ADX-based for indicator weights) ──
        if adx_val > 25:
            ind_regime = "TRENDING"
        elif adx_val < 20:
            ind_regime = "SIDEWAYS"
        else:
            ind_regime = "MIXED"

        # ═══ 5-LAYER COMPOSITE SCORING ═══

        # --- Category scores (기존 호환) ---
        rsi2_score = self._calc_rsi2_reversion_score(rsi2, cum_rsi2)
        trend_score = self._calc_trend_score(close, sma50, sma200, adx_val, current_price)
        vol_score = self._calc_volume_score(vol_ratio, mfi_val, volume)
        rs_score = self._calc_rs_score(rel_str_5d, rel_str_20d)
        volatility_score = self._calc_volatility_score(bb_squeeze, atr_14, current_price, opex_week)

        # --- 새 Layer 점수 (0-100 스케일) ---
        # Layer 1: Regime (0-100)
        layer1_score = regime["regime_score"]

        # Layer 2: RS + Quality Ranking (0-100)
        layer2_score = layer2["composite_rank"]

        # Layer 3: Entry Timing (0-100)
        layer3_score = layer3["timing_score"]

        # Layer Quality (0-100)
        quality_score = quality_info["quality_score"]

        # ── 최종 복합 스코어 (새 전략) ──
        # 6-factor weighted: Regime 15%, RS Ranking 20%, Quality 20%, Timing 25%, Trend 10%, Momentum 10%
        composite_100 = (
            layer1_score * 0.15 +
            layer2_score * 0.20 +
            quality_score * 0.20 +
            layer3_score * 0.25 +
            (50 + trend_score * 50) * 0.10 +  # convert -1~1 → 0~100
            (50 + rs_score * 50) * 0.10
        )
        composite_100 = max(0, min(100, composite_100))

        # ── 기존 가중 점수 (Connors 호환 -1~+1) ──
        if ind_regime == "TRENDING":
            w_rsi2, w_trend, w_vol, w_rs, w_volat = 0.30, 0.30, 0.15, 0.15, 0.10
        elif ind_regime == "SIDEWAYS":
            w_rsi2, w_trend, w_vol, w_rs, w_volat = 0.40, 0.15, 0.15, 0.15, 0.15
        else:
            w_rsi2, w_trend, w_vol, w_rs, w_volat = 0.35, 0.25, 0.15, 0.15, 0.10

        weighted_raw = (
            w_rsi2 * rsi2_score +
            w_trend * trend_score +
            w_vol * vol_score +
            w_rs * rs_score +
            w_volat * volatility_score
        )

        # SMA200 damping
        if len(close) >= 200 and current_price < sma200 and weighted_raw > 0:
            weighted_raw *= 0.3

        # Volume damping
        vol_factor = 1.0 if vol_ratio >= 1.0 else 0.5
        weighted_final = weighted_raw * vol_factor

        # ── Direction 결정 (5-Layer 통합) ──
        direction, confidence = self._determine_direction(
            weighted_final, rsi2, connors_exit, opex_week,
            regime, layer2, layer3, quality_score, composite_100
        )

        # ── Target / Stop (ATR 기반) ──
        if "BUY" in direction:
            target_price = round(current_price + 2.5 * atr_14, 2)
            stop_price = round(current_price - 1.5 * atr_14, 2)
        elif "SELL" in direction:
            target_price = round(current_price - 2.5 * atr_14, 2)
            stop_price = round(current_price + 1.5 * atr_14, 2)
        else:
            target_price = round(current_price + 2.5 * atr_14, 2)
            stop_price = round(current_price - 1.5 * atr_14, 2)

        # ── Oscillator / MA counts (기존 Dashboard 호환) ──
        ind_list, ma_list = self._build_indicator_lists(
            rsi2, rsi14, stoch_k, macd_hist, mfi_val, adx_val,
            current_price, sma5, sma20, sma50, sma200,
            _ema_arr(close, 9)[-1], _ema_arr(close, 21)[-1]
        )
        osc_buy = sum(1 for i in ind_list if i["signal"] == "BUY")
        osc_sell = sum(1 for i in ind_list if i["signal"] == "SELL")
        osc_neutral = sum(1 for i in ind_list if i["signal"] == "NEUTRAL")
        ma_buy = sum(1 for i in ma_list if i["signal"] == "BUY")
        ma_sell = sum(1 for i in ma_list if i["signal"] == "SELL")
        ma_neutral = sum(1 for i in ma_list if i["signal"] == "NEUTRAL")

        return {
            "symbol": sym,
            "company_name": item.get("company_name", ""),
            "current_price": current_price,
            "avg_cost": avg_cost,
            "qty": float(item.get("qty") or 0),
            "pnl_pct": pnl_pct,
            "direction": direction,
            "confidence": confidence,
            # Oscillator / MA (기존 호환)
            "osc_buy": osc_buy, "osc_sell": osc_sell, "osc_neutral": osc_neutral,
            "indicators": ind_list,
            "ma_buy": ma_buy, "ma_sell": ma_sell, "ma_neutral": ma_neutral,
            "moving_averages": ma_list,
            "total_buy": osc_buy + ma_buy,
            "total_sell": osc_sell + ma_sell,
            "total_neutral": osc_neutral + ma_neutral,
            # Category scores (기존 호환)
            "regime": ind_regime,
            "vol_factor": vol_factor,
            "weighted_score": round(weighted_final, 3),
            "category_scores": {
                "rsi2_reversion": round(rsi2_score, 3),
                "trend": round(trend_score, 3),
                "volume": round(vol_score, 3),
                "rel_strength": round(rs_score, 3),
                "volatility": round(volatility_score, 3),
            },
            "category_weights": {
                "rsi2_reversion": w_rsi2, "trend": w_trend,
                "volume": w_vol, "rel_strength": w_rs, "volatility": w_volat,
            },
            # Pricing
            "target_price": target_price,
            "stop_price": stop_price,
            "atr": round(atr_14, 2),
            "vol_ratio": round(vol_ratio, 2),
            "pre_vol_boost": pre_vol_boost,
            # Connors 호환 필드
            "rsi2": round(rsi2, 1),
            "cum_rsi2": round(cum_rsi2, 1),
            "connors_exit": connors_exit,
            "opex_week": opex_week,
            "rel_str_5d": round(rel_str_5d * 100, 2),
            "rel_str_20d": round(rel_str_20d * 100, 2),
            "bb_squeeze": bb_squeeze,
            # ═══ NEW: 5-Layer 시그널 ═══
            "composite_score": round(composite_100, 1),
            "layer1_regime": {
                "score": layer1_score,
                "market_trend": regime["market_trend"],
                "qqq_above_sma200": regime["qqq_above_sma200"],
                "vix": round(regime["vix_level"], 1),
                "momentum_3m": round(regime["qqq_momentum_3m"], 1),
                "entry_allowed": regime["entry_allowed"],
                "size_factor": regime["size_factor"],
            },
            "layer2_ranking": {
                "score": round(layer2_score, 1),
                "rs_rating": round(layer2["rs_rating"], 1),
                "momentum_6m": round(layer2["momentum_6m"], 2),
                "stage": layer2["weinstein_stage"],
            },
            "layer3_entry": {
                "score": round(layer3_score, 1),
                "bb_squeeze": layer3["bb_squeeze"],
                "squeeze_fired": layer3["squeeze_fired"],
                "momentum_positive": layer3["momentum_positive"],
                "rsi2_oversold": rsi2 < self.RSI2_ENTRY,
                "pead_signal": layer3.get("pead_signal", "NONE"),
            },
            "layer4_sizing": {
                "regime_factor": regime["size_factor"],
                "seasonal": self._seasonal_factor(),
                "suggested_pct": round(regime["size_factor"] * self._seasonal_factor() * 15, 1),
            },
            "layer5_exit": {
                "kama": round(kama_current, 2),
                "kama_slope": round(kama_slope, 2),
                "kama_exit": current_price < kama_current and kama_slope < 0,
                "connors_exit": connors_exit,
                "atr_stop": stop_price,
                "atr_target": target_price,
            },
            "quality": {
                "score": round(quality_score, 1),
                "gp_assets": quality_info.get("gp_assets"),
                "roe": quality_info.get("roe"),
                "debt_equity": quality_info.get("debt_equity"),
                "margin": quality_info.get("gross_margin"),
            },
        }

    # ─────────────────────────────────────────────────────
    #  Layer 2: RS Rating + Weinstein Stage
    # ─────────────────────────────────────────────────────

    def _calc_layer2_ranking(self, sym: str, close: np.ndarray,
                             qqq_close: np.ndarray,
                             high: np.ndarray, low: np.ndarray,
                             volume: np.ndarray) -> dict:
        """IBD-style Relative Strength + Weinstein Stage Analysis."""
        result = {
            "rs_rating": 50.0,
            "momentum_3m": 0.0,
            "momentum_6m": 0.0,
            "momentum_12m": 0.0,
            "weinstein_stage": "UNKNOWN",
            "composite_rank": 50.0,
        }

        n = len(close)
        if n < 63:
            return result

        # IBD RS Rating formula: 0.4*3M + 0.2*6M + 0.2*9M + 0.2*12M
        roc_3m = (float(close[-1]) / float(close[-min(63, n)]) - 1) * 100 if n >= 63 else 0
        roc_6m = (float(close[-1]) / float(close[-min(126, n)]) - 1) * 100 if n >= 126 else roc_3m
        roc_9m = (float(close[-1]) / float(close[-min(189, n)]) - 1) * 100 if n >= 189 else roc_6m
        roc_12m = (float(close[-1]) / float(close[-min(252, n)]) - 1) * 100 if n >= 252 else roc_9m

        rs_factor = 0.4 * roc_3m + 0.2 * roc_6m + 0.2 * roc_9m + 0.2 * roc_12m
        # Normalize to 0-100 (heuristic: ±50% range)
        rs_rating = max(0, min(100, 50 + rs_factor))

        result["rs_rating"] = rs_rating
        result["momentum_3m"] = roc_3m
        result["momentum_6m"] = roc_6m
        result["momentum_12m"] = roc_12m

        # Weinstein Stage Analysis (30-week ≈ 150-day SMA)
        if n >= 200:
            sma150 = _sma_arr(close, 150)
            current = float(close[-1])
            sma150_now = float(sma150[-1]) if not np.isnan(sma150[-1]) else current
            sma150_prev = float(sma150[-20]) if not np.isnan(sma150[-20]) else sma150_now

            sma150_slope = sma150_now - sma150_prev

            # 52-week range position
            high_52w = float(np.max(close[-252:])) if n >= 252 else float(np.max(close))
            low_52w = float(np.min(close[-252:])) if n >= 252 else float(np.min(close))
            range_52w = high_52w - low_52w if high_52w != low_52w else 1
            pct_from_low = (current - low_52w) / range_52w * 100
            pct_from_high = (high_52w - current) / range_52w * 100

            if current > sma150_now and sma150_slope > 0 and pct_from_low > 25:
                result["weinstein_stage"] = "STAGE_2"  # Advancing
            elif current > sma150_now and sma150_slope <= 0:
                result["weinstein_stage"] = "STAGE_3"  # Topping
            elif current < sma150_now and sma150_slope < 0:
                result["weinstein_stage"] = "STAGE_4"  # Declining
            else:
                result["weinstein_stage"] = "STAGE_1"  # Basing

        # Composite rank (0-100)
        stage_bonus = {"STAGE_2": 20, "STAGE_1": 5, "STAGE_3": -10, "STAGE_4": -25}.get(
            result["weinstein_stage"], 0
        )
        result["composite_rank"] = max(0, min(100, rs_rating + stage_bonus))

        return result

    # ─────────────────────────────────────────────────────
    #  Layer 3: Entry Timing (BB Squeeze + RSI2 + PEAD)
    # ─────────────────────────────────────────────────────

    def _calc_layer3_entry(self, close: np.ndarray, high: np.ndarray,
                           low: np.ndarray, volume: np.ndarray,
                           rsi2: float, adx_val: float,
                           sma200: float, current_price: float) -> dict:
        """BB/KC Squeeze detection + momentum + RSI2 timing."""
        result = {
            "timing_score": 50,
            "bb_squeeze": False,
            "squeeze_fired": False,
            "momentum_positive": False,
            "pead_signal": "NONE",
        }

        n = len(close)
        if n < 30:
            return result

        # Bollinger Bands (20, 2.0)
        sma20 = _sma_arr(close, self.BB_PERIOD)
        std20 = np.full(len(close), np.nan)
        for i in range(self.BB_PERIOD - 1, len(close)):
            std20[i] = np.std(close[i - self.BB_PERIOD + 1:i + 1])

        bb_upper = sma20 + self.BB_STD * std20
        bb_lower = sma20 - self.BB_STD * std20
        bb_width = (bb_upper - bb_lower) / np.maximum(sma20, 0.01)

        # Keltner Channel (20, 1.5×ATR)
        ema20 = _ema_arr(close, self.KC_PERIOD)
        atr_arr = np.zeros(len(close))
        for i in range(1, len(close)):
            tr = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
            atr_arr[i] = tr
        atr_ema = _ema_arr(atr_arr[1:], self.KC_PERIOD)
        # Pad to match length
        atr_smooth = np.concatenate([[atr_ema[0]], atr_ema])

        kc_upper = ema20 + self.KC_ATR_MULT * atr_smooth
        kc_lower = ema20 - self.KC_ATR_MULT * atr_smooth

        # Squeeze detection: BB inside KC
        squeeze_on = False
        squeeze_fired = False
        if not np.isnan(bb_upper[-1]) and not np.isnan(kc_upper[-1]):
            was_squeeze = (bb_upper[-2] < kc_upper[-2] and bb_lower[-2] > kc_lower[-2]) if n > 1 else False
            is_squeeze = bb_upper[-1] < kc_upper[-1] and bb_lower[-1] > kc_lower[-1]
            squeeze_on = is_squeeze
            squeeze_fired = was_squeeze and not is_squeeze  # BB just expanded outside KC

        # BB Width percentile (120-day)
        bw_valid = bb_width[-120:]
        bw_valid = bw_valid[~np.isnan(bw_valid)]
        bb_squeeze_hist = False
        if len(bw_valid) > 10 and not np.isnan(bb_width[-1]):
            bb_squeeze_hist = bool(bb_width[-1] <= np.percentile(bw_valid, 10))

        result["bb_squeeze"] = squeeze_on or bb_squeeze_hist

        # Momentum direction (linear regression slope of close over 12 periods)
        if n >= 12:
            x = np.arange(12)
            y = close[-12:]
            slope = np.polyfit(x, y, 1)[0]
            result["momentum_positive"] = slope > 0

        result["squeeze_fired"] = squeeze_fired

        # ── Timing Score (0-100) ──
        score = 50

        # BB Squeeze 해소 + 모멘텀 양수 = 최강 진입 시그널 (+30)
        if squeeze_fired and result["momentum_positive"]:
            score += 30
        elif squeeze_fired:
            score += 15
        elif squeeze_on:
            score += 5  # 에너지 축적 중

        # RSI(2) 과매도 = 평균회귀 매수 기회 (+20)
        if rsi2 < 5:
            score += 20
        elif rsi2 < 10:
            score += 12
        elif rsi2 > 90:
            score -= 15
        elif rsi2 > 95:
            score -= 20

        # SMA200 위 = 장기 추세 확인 (+10)
        if len(close) >= 200 and current_price > sma200:
            score += 10
        elif len(close) >= 200:
            score -= 10

        # Volume surge (+5)
        vol_sma = np.mean(volume[-20:]) if len(volume) >= 20 else 1
        if len(volume) > 0 and float(volume[-1]) > vol_sma * 1.5:
            score += 5

        result["timing_score"] = max(0, min(100, score))
        return result

    # ─────────────────────────────────────────────────────
    #  Quality Score (Finnhub fundamentals → GP/Assets)
    # ─────────────────────────────────────────────────────

    def _calc_quality_score(self, symbol: str) -> dict:
        """AQR-style Quality score (GP/Assets, ROE, margins, leverage)."""
        result = {
            "quality_score": 50,
            "gp_assets": None,
            "roe": None,
            "debt_equity": None,
            "gross_margin": None,
        }

        if not self.finnhub or not self.finnhub.is_available:
            return result

        try:
            fin = self.finnhub.get_basic_financials(symbol)
            if not fin:
                return result

            score = 50
            roe = fin.get("roe")
            gm = fin.get("gross_margin")
            de = fin.get("debt_equity")
            om = fin.get("operating_margin")

            result["roe"] = roe
            result["gross_margin"] = gm
            result["debt_equity"] = de

            # ROE scoring (Novy-Marx 2013: profitability is strongest quality signal)
            if roe is not None:
                if roe > 25:
                    score += 15
                elif roe > 15:
                    score += 10
                elif roe > 8:
                    score += 5
                elif roe < 0:
                    score -= 15

            # Gross Margin (GP/Assets proxy — higher is better for tech)
            if gm is not None:
                result["gp_assets"] = gm  # Simplified proxy
                if gm > 60:
                    score += 15
                elif gm > 40:
                    score += 10
                elif gm > 25:
                    score += 5
                elif gm < 15:
                    score -= 10

            # Debt/Equity (lower is better)
            if de is not None:
                if de < 0.3:
                    score += 10
                elif de < 0.7:
                    score += 5
                elif de > 1.5:
                    score -= 10
                elif de > 2.5:
                    score -= 15

            # Operating Margin
            if om is not None:
                if om > 30:
                    score += 10
                elif om > 15:
                    score += 5
                elif om < 0:
                    score -= 10

            result["quality_score"] = max(0, min(100, score))

        except Exception as e:
            logger.debug(f"Quality score failed for {symbol}: {e}")

        return result

    # ─────────────────────────────────────────────────────
    #  Direction Determination (5-Layer 통합)
    # ─────────────────────────────────────────────────────

    def _determine_direction(self, weighted_final: float, rsi2: float,
                             connors_exit: bool, opex_week: bool,
                             regime: dict, layer2: dict, layer3: dict,
                             quality_score: float, composite_100: float) -> tuple[str, int]:
        """5-Layer 통합 매매 판정.

        기존 Connors 로직 유지하되, 5-Layer 시그널로 보강:
        - Regime BEARISH → BUY 억제
        - Stage 4 → BUY 억제
        - Squeeze fired + momentum + → BUY 부스트
        - Quality < 30 → BUY 감쇠
        """
        # 기존 Connors 기본 방향
        if weighted_final >= 0.40:
            direction = "STRONG_BUY"
        elif weighted_final >= 0.15:
            direction = "BUY"
        elif weighted_final <= -0.40:
            direction = "STRONG_SELL"
        elif weighted_final <= -0.15:
            direction = "SELL"
        elif connors_exit and rsi2 > 50:
            direction = "SELL"
        else:
            direction = "NEUTRAL"

        # 5-Layer overrides
        # Override 1: Regime BEARISH → suppress BUY
        if not regime["entry_allowed"] and "BUY" in direction:
            direction = "NEUTRAL"

        # Override 2: Stage 4 (declining) → suppress BUY
        if layer2["weinstein_stage"] == "STAGE_4" and "BUY" in direction:
            direction = "NEUTRAL"

        # Override 3: Squeeze fired with positive momentum → boost to BUY
        if layer3["squeeze_fired"] and layer3["momentum_positive"]:
            if direction == "NEUTRAL" and composite_100 >= 55:
                direction = "BUY"
            elif direction == "BUY":
                direction = "STRONG_BUY"

        # Override 4: Very low quality → dampen BUY
        if quality_score < 30 and direction == "STRONG_BUY":
            direction = "BUY"

        # Override 5: OPEX week → suppress BUY (기존 로직 유지)
        if opex_week and "BUY" in direction:
            direction = "NEUTRAL"

        # Confidence (0-100)
        base_conf = int(abs(weighted_final) * 120 + 40)
        # Boost from composite score
        if composite_100 >= 70:
            base_conf = min(99, base_conf + 10)
        elif composite_100 <= 30:
            base_conf = max(10, base_conf - 10)
        confidence = max(10, min(99, base_conf))

        return direction, confidence

    # ─────────────────────────────────────────────────────
    #  Graduated Drawdown Defense (Layer 5 helper)
    # ─────────────────────────────────────────────────────

    @staticmethod
    def check_drawdown_defense(current_equity: float, peak_equity: float) -> dict:
        """Grossman-Zhou inspired 4-tier graduated drawdown defense.

        Returns action recommendations based on current drawdown level.
        """
        if peak_equity <= 0:
            return {"tier": 0, "action": "NORMAL", "size_mult": 1.0, "message": "Normal operations"}

        dd_pct = (peak_equity - current_equity) / peak_equity * 100

        if dd_pct < 5:
            return {"tier": 0, "action": "NORMAL", "size_mult": 1.0,
                    "drawdown_pct": round(dd_pct, 1),
                    "message": "Normal operations"}
        elif dd_pct < 8:
            return {"tier": 1, "action": "CAUTION", "size_mult": 0.7,
                    "drawdown_pct": round(dd_pct, 1),
                    "message": "No new entries, tighten stops to 1.5×ATR"}
        elif dd_pct < 12:
            return {"tier": 2, "action": "DEFENSIVE", "size_mult": 0.5,
                    "drawdown_pct": round(dd_pct, 1),
                    "message": "Reduce positions 50%, stops to 1.0×ATR"}
        else:
            return {"tier": 3, "action": "EMERGENCY", "size_mult": 0.2,
                    "drawdown_pct": round(dd_pct, 1),
                    "message": "Liquidate to 80% cash, keep only strongest"}

    # ─────────────────────────────────────────────────────
    #  Helper Calculators
    # ─────────────────────────────────────────────────────

    @staticmethod
    def _calc_atr(high, low, close, period=14) -> float:
        n = len(close)
        if n < 2:
            return 0.0
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(high[i] - low[i], abs(high[i] - close[i-1]), abs(low[i] - close[i-1]))
        if n <= period:
            return float(np.mean(tr[1:]))
        atr = float(np.mean(tr[1:period+1]))
        for i in range(period + 1, n):
            atr = (atr * (period - 1) + tr[i]) / period
        return atr

    @staticmethod
    def _seasonal_factor() -> float:
        """Bouman & Jacobsen (2002): Nov-Apr full size, May-Oct 70%."""
        month = date.today().month
        return 1.0 if month in (11, 12, 1, 2, 3, 4) else 0.7

    @staticmethod
    def _calc_rsi2_reversion_score(rsi2: float, cum_rsi2: float) -> float:
        """RSI(2) 평균회귀 점수 (-1 ~ +1)."""
        score = 0.0
        if rsi2 < 5:
            score += 0.8
        elif rsi2 < 10:
            score += 0.5
        elif rsi2 < 20:
            score += 0.2
        elif rsi2 > 95:
            score -= 0.8
        elif rsi2 > 90:
            score -= 0.5
        elif rsi2 > 80:
            score -= 0.2

        if cum_rsi2 < 10:
            score += 0.2
        elif cum_rsi2 > 190:
            score -= 0.2

        return max(-1, min(1, score))

    @staticmethod
    def _calc_trend_score(close, sma50, sma200, adx_val, current_price) -> float:
        """추세 점수 (-1 ~ +1)."""
        score = 0.0
        if len(close) >= 200:
            if current_price > sma50 > sma200:
                score += 0.5
            elif current_price > sma200:
                score += 0.2
            elif current_price < sma50 < sma200:
                score -= 0.5
            else:
                score -= 0.2

        if adx_val > 30:
            score *= 1.3
        elif adx_val < 15:
            score *= 0.5

        return max(-1, min(1, score))

    @staticmethod
    def _calc_volume_score(vol_ratio: float, mfi_val: float, volume: np.ndarray) -> float:
        """거래량 점수 (-1 ~ +1)."""
        score = 0.0
        if vol_ratio >= 2.0:
            score += 0.4
        elif vol_ratio >= 1.5:
            score += 0.2
        elif vol_ratio < 0.5:
            score -= 0.3

        if mfi_val < 20:
            score += 0.3
        elif mfi_val < 30:
            score += 0.15
        elif mfi_val > 80:
            score -= 0.3
        elif mfi_val > 70:
            score -= 0.15

        # OBV trend (simplified)
        if len(volume) >= 20:
            obv_recent = np.mean(volume[-5:])
            obv_older = np.mean(volume[-20:-5]) if len(volume) >= 20 else obv_recent
            if obv_recent > obv_older * 1.2:
                score += 0.15
            elif obv_recent < obv_older * 0.8:
                score -= 0.15

        return max(-1, min(1, score))

    @staticmethod
    def _calc_rs_score(rel_str_5d: float, rel_str_20d: float) -> float:
        """상대강도 점수 (-1 ~ +1)."""
        score = 0.0
        if rel_str_5d > 0.03:
            score += 0.3
        elif rel_str_5d > 0.01:
            score += 0.15
        elif rel_str_5d < -0.03:
            score -= 0.3
        elif rel_str_5d < -0.01:
            score -= 0.15

        if rel_str_20d > 0.05:
            score += 0.3
        elif rel_str_20d > 0.02:
            score += 0.15
        elif rel_str_20d < -0.05:
            score -= 0.3
        elif rel_str_20d < -0.02:
            score -= 0.15

        return max(-1, min(1, score))

    @staticmethod
    def _calc_volatility_score(bb_squeeze: bool, atr_val: float,
                               current_price: float, opex_week: bool) -> float:
        """변동성 점수 (-1 ~ +1)."""
        score = 0.0
        if bb_squeeze:
            score += 0.3  # 에너지 축적
        atr_pct = (atr_val / current_price * 100) if current_price > 0 else 0
        if atr_pct < 1.5:
            score += 0.2  # 저변동
        elif atr_pct > 4:
            score -= 0.3  # 고변동
        if opex_week:
            score -= 0.2
        return max(-1, min(1, score))

    @staticmethod
    def _build_indicator_lists(rsi2, rsi14, stoch_k, macd_hist, mfi_val, adx_val,
                               current_price, sma5, sma20, sma50, sma200,
                               ema9, ema21):
        """기존 Dashboard 호환 indicator/MA 리스트 생성."""
        def _sig(val, buy_thresh, sell_thresh, invert=False):
            if invert:
                return "BUY" if val > sell_thresh else ("SELL" if val < buy_thresh else "NEUTRAL")
            return "BUY" if val < buy_thresh else ("SELL" if val > sell_thresh else "NEUTRAL")

        ind_list = [
            {"name": "RSI(2)", "value": round(rsi2, 1), "signal": _sig(rsi2, 10, 90)},
            {"name": "RSI(14)", "value": round(rsi14, 1), "signal": _sig(rsi14, 30, 70)},
            {"name": "Stoch(5,3)", "value": round(stoch_k, 1), "signal": _sig(stoch_k, 20, 80)},
            {"name": "MACD Hist", "value": round(macd_hist, 3),
             "signal": "BUY" if macd_hist > 0 else "SELL"},
            {"name": "MFI(14)", "value": round(mfi_val, 1), "signal": _sig(mfi_val, 30, 70)},
            {"name": "ADX(14)", "value": round(adx_val, 1), "signal": "NEUTRAL"},
        ]

        ma_list = [
            {"name": "SMA(5)", "value": round(sma5, 2),
             "signal": "BUY" if current_price > sma5 else "SELL"},
            {"name": "SMA(20)", "value": round(sma20, 2),
             "signal": "BUY" if current_price > sma20 else "SELL"},
            {"name": "SMA(50)", "value": round(sma50, 2),
             "signal": "BUY" if current_price > sma50 else "SELL"},
            {"name": "SMA(200)", "value": round(sma200, 2),
             "signal": "BUY" if current_price > sma200 else "SELL"},
            {"name": "EMA(9)", "value": round(ema9, 2),
             "signal": "BUY" if current_price > ema9 else "SELL"},
            {"name": "EMA(21)", "value": round(ema21, 2),
             "signal": "BUY" if current_price > ema21 else "SELL"},
        ]

        return ind_list, ma_list
