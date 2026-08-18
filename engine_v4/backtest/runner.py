"""Vectorized Backtest Runner — 스윙 전략 백테스트."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

import numpy as np
import pandas as pd
import yfinance as yf

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

# yfinance HTTP 타임아웃(초). 무응답 소켓이 백테스트 전체를 멈추지 못하게 한다.
YF_TIMEOUT_SEC = 30


@dataclass
class BacktestParams:
    """백테스트 파라미터."""
    start_date: date = date(2020, 1, 1)
    end_date: date = date(2025, 12, 31)
    initial_capital: float = 2200.0  # $2,200
    sma_short: int = 50
    sma_long: int = 200
    return_period: int = 20
    return_rank_min: float = 0.6
    breakout_days: int = 5
    breakout_margin: float = 0.0     # 근접 허용: close > high_Nd×(1−margin). 0=엄격 돌파
    require_breakout: bool = True     # False 시 브레이크아웃 조건 제외(추세+거래량만)
    # ── Tier 1 시장 트렌드 필터 (GEM/Faber): SPY < SMA면 신규 롱 중단(현금) ──
    use_market_filter: bool = False   # True 시 SPY가 시장SMA 아래면 진입 차단
    market_sma_days: int = 200         # 시장 추세 SMA (200일 ≈ Faber 10개월)
    volume_ratio_min: float = 1.5
    stop_loss_pct: float = -0.05
    take_profit_pct: float = 0.10
    max_positions: int = 4
    position_pct: float = 0.05
    max_daily_entries: int = 1
    price_range_min: float = 20.0
    price_range_max: float = 80.0
    # ── ①번 손익비 개선: ATR 트레일링 + 부분익절 (기본 off = 기존 고정 TP 동작 보존) ──
    use_atr_trailing: bool = False   # True 시 고정 take_profit 대신 ATR 트레일링으로 승자 추종
    atr_period: int = 14
    atr_trailing_mult: float = 2.5   # 트레일링 폭 = high_water − mult×ATR
    atr_activation_r: float = 1.0    # +activation_r × 초기리스크 도달 후 트레일링 개시
    partial_exit_r: float = 0.0      # >0 이면 +R 도달 시 partial_exit_pct 만큼 부분익절 (0=off)
    partial_exit_pct: float = 0.5
    # ── ②번 변동성 타깃팅 (Barroso&Santa-Clara): 포지션을 종목 ATR%의 역수로 스케일 ──
    use_vol_targeting: bool = False  # True 시 변동성 낮은 종목↑ / 높은 종목↓ 배분
    target_atr_pct: float = 0.03     # 목표 일일 ATR/price (3%) — 이 변동성 기준으로 정규화
    vol_mult_min: float = 0.5        # 사이즈 승수 하한
    vol_mult_max: float = 1.25       # 사이즈 승수 상한 (position_pct 0.20×1.25=0.25 → 라이브 캡 정합)
    # ── ③번 절대 모멘텀 필터 (Time Series Momentum, Moskowitz-Ooi-Pedersen 2012) ──
    use_abs_momentum: bool = False   # True 시 과거 abs_mom_period 수익>임계 종목만 진입
    abs_mom_period: int = 252        # 룩백 거래일 (252≈12개월)
    abs_mom_min: float = 0.0         # 절대모멘텀 최소치 (0 = 과거수익 양(+)만 롱)
    # ── 5-Layer Exit 정합 (2026-08-18 §22.AO-4): risk/exit_manager.py 와 동일 로직 ──
    # 라이브 청산 우선순위 L2(하드스탑) → L4(RSI2) → L3(시간청산) → L1(ATR 트레일링) 을 그대로 재현.
    # R 배수는 라이브와 같이 진입시점 ATR(entry_atr) 기준 — 당일 ATR 이 아니다.
    use_hard_stop: bool = False      # L2: entry − mult×entry_ATR 이탈 시 즉시 청산
    atr_hard_stop_mult: float = 1.5
    use_rsi2_exit: bool = False      # L4: RSI(2) > threshold (최소 R 도달 후에만)
    rsi2_period: int = 2
    rsi2_exit_threshold: float = 95.0
    rsi2_exit_min_r: float = 2.0     # 승자 과조기절단 방지 게이팅 (2026-07-01 교정치)
    use_time_stop: bool = False      # L3: 보유일 초과 시 청산
    time_stop_days: int = 15
    use_breakeven: bool = False      # +trigger_R 도달 시 손절을 본전(+버퍼)으로 상향
    breakeven_trigger_r: float = 1.0
    breakeven_buffer_pct: float = 0.002


@dataclass
class BacktestResult:
    """백테스트 결과."""
    total_return: float = 0.0
    cagr: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    payoff_ratio: float = 0.0   # 평균승/평균패 (손익비) — ①번 검증 핵심 지표
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_hold_days: float = 0.0
    final_value: float = 0.0
    equity_curve: list = field(default_factory=list)
    trades_log: list = field(default_factory=list)


class BacktestRunner:
    """벡터화 백테스트 실행기."""

    def __init__(self, pg: PostgresStore | None = None):
        self.pg = pg

    def run(self, params: BacktestParams,
            universe_symbols: list[str] | None = None) -> BacktestResult:
        """
        전체 백테스트 실행.
        1. 데이터 다운로드 (yfinance)
        2. 지표 계산
        3. 시뮬레이션
        4. 결과 계산
        """
        logger.info(f"Backtest: {params.start_date} ~ {params.end_date}, "
                     f"${params.initial_capital:,.0f}")

        # ── 1. 유니버스 결정 ──
        if not universe_symbols:
            if self.pg:
                uni = self.pg.get_universe()
                universe_symbols = [u["symbol"] for u in uni]
            if not universe_symbols:
                # 폴백: 대형주 50개
                universe_symbols = [
                    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
                    "BRK-B", "UNH", "JNJ", "V", "XOM", "JPM", "PG", "MA",
                    "HD", "CVX", "MRK", "ABBV", "LLY", "PEP", "KO", "COST",
                    "AVGO", "WMT", "MCD", "CSCO", "ACN", "ABT", "TMO",
                    "DHR", "NEE", "LIN", "PM", "TXN", "UNP", "RTX", "HON",
                    "LOW", "AMGN", "COP", "INTC", "AMD", "QCOM", "ADP",
                    "SBUX", "GILD", "ISRG", "BKNG", "ADI",
                ]

        # 시장 필터용 SPY 를 유니버스에 포함(진입 후보에선 제외)
        if params.use_market_filter and "SPY" not in universe_symbols:
            universe_symbols = universe_symbols + ["SPY"]

        # ── 2. 데이터 다운로드 ──
        logger.info(f"Downloading data for {len(universe_symbols)} symbols...")
        # 패딩: sma_long/abs_mom(≈252거래일) 워밍업 커버 (거래일 252 ≈ 캘린더 370일 → 여유롭게 500)
        pad_days = max(300, int(params.abs_mom_period * 1.6) + 120)
        start_padded = pd.Timestamp(params.start_date) - pd.Timedelta(days=pad_days)

        all_data = {}
        batch_size = 50
        for i in range(0, len(universe_symbols), batch_size):
            batch = universe_symbols[i:i + batch_size]
            try:
                # threads=False: yfinance 내부 스레드풀이 캐시 락에서 교착돼
                # 응답 없이 멈추는 사례가 있었다(2026-08-18 §22.AO). 배치 단위라
                # 직렬화해도 비용 차이가 작다. timeout 은 명시적으로 고정.
                data = yf.download(
                    " ".join(batch),
                    start=start_padded.strftime("%Y-%m-%d"),
                    end=params.end_date.isoformat(),
                    group_by="ticker",
                    threads=False,
                    progress=False,
                    timeout=YF_TIMEOUT_SEC,
                )
                if data.empty:
                    continue
                cols = ["Open", "High", "Low", "Close", "Volume"]
                for sym in batch:
                    try:
                        # group_by='ticker' 는 단일 배치도 MultiIndex(('SYM','Open')) 반환 →
                        # 항상 data[sym] 로 접근(단순컬럼이면 폴백). 단일배치 SPY 누락 버그 수정.
                        if isinstance(data.columns, pd.MultiIndex):
                            df = data[sym][cols].copy()
                        else:
                            df = data[cols].copy()
                        df = df.dropna(subset=["Close"])
                        if len(df) > params.sma_long:
                            all_data[sym] = df
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Download batch error: {e}")

        if not all_data:
            logger.error("No data downloaded for backtest")
            return BacktestResult()

        logger.info(f"Downloaded {len(all_data)} symbols with sufficient data")

        # ── 3. 지표 계산 ──
        indicators = {}
        for sym, df in all_data.items():
            close = df["Close"].astype(float)
            volume = df["Volume"].astype(float)
            df = df.copy()
            df["sma_50"] = close.rolling(params.sma_short).mean()
            df["sma_200"] = close.rolling(params.sma_long).mean()
            df["return_20d"] = close.pct_change(params.return_period)
            df["abs_mom"] = close.pct_change(params.abs_mom_period)  # 12개월 절대모멘텀
            df["high_5d"] = close.shift(1).rolling(params.breakout_days).max()
            df["vol_avg_20"] = volume.rolling(20).mean()
            df["vol_ratio"] = volume / df["vol_avg_20"]
            df["trend"] = (close > df["sma_50"]) & (df["sma_50"] > df["sma_200"])
            df["breakout"] = close > df["high_5d"] * (1 - params.breakout_margin)
            df["vol_surge"] = df["vol_ratio"] > params.volume_ratio_min
            # ATR (Wilder) — 트레일링 스톱용
            high = df["High"].astype(float)
            low = df["Low"].astype(float)
            prev_close = close.shift(1)
            tr = pd.concat([high - low, (high - prev_close).abs(),
                            (low - prev_close).abs()], axis=1).max(axis=1)
            df["atr"] = tr.ewm(alpha=1 / params.atr_period, adjust=False).mean()
            df["sma_market"] = close.rolling(params.market_sma_days).mean()  # 시장필터용

            # RSI(2) — 라이브 exit_manager.calc_rsi 와 동일한 단순평균 방식(Wilder 아님).
            # avg_loss == 0 이면 100 으로 고정하는 것까지 맞춘다.
            _delta = close.diff()
            _avg_gain = _delta.clip(lower=0).rolling(params.rsi2_period).mean()
            _avg_loss = (-_delta).clip(lower=0).rolling(params.rsi2_period).mean()
            _rs = _avg_gain / _avg_loss.replace(0, np.nan)
            df["rsi2"] = (100 - (100 / (1 + _rs))).where(_avg_loss != 0, 100.0)
            indicators[sym] = df

        # ── 4. 시뮬레이션 ──
        result = self._simulate(indicators, params)

        # ── 5. DB에 저장 (선택적) ──
        if self.pg:
            try:
                self.pg.insert_backtest_run({
                    "start_date": params.start_date.isoformat(),
                    "end_date": params.end_date.isoformat(),
                    "initial_capital": params.initial_capital,
                    "final_value": result.final_value,
                    "total_return": result.total_return,
                    "cagr": result.cagr,
                    "max_drawdown": result.max_drawdown,
                    "sharpe_ratio": result.sharpe_ratio,
                    "win_rate": result.win_rate,
                    "total_trades": result.total_trades,
                    "profit_factor": result.profit_factor,
                    "avg_hold_days": result.avg_hold_days,
                    "params": {
                        "sma_short": params.sma_short,
                        "sma_long": params.sma_long,
                        "stop_loss_pct": params.stop_loss_pct,
                        "take_profit_pct": params.take_profit_pct,
                        "max_positions": params.max_positions,
                        "position_pct": params.position_pct,
                    },
                    "equity_curve": result.equity_curve[-500:],  # 최근 500일
                    "trades_log": result.trades_log[-200:],       # 최근 200건
                })
            except Exception as e:
                logger.warning(f"Failed to save backtest: {e}")

        return result

    def _simulate(self, indicators: dict[str, pd.DataFrame],
                  params: BacktestParams) -> BacktestResult:
        """이벤트 드리븐 시뮬레이션."""
        cash = params.initial_capital
        positions: list[dict] = []
        trades_log: list[dict] = []
        equity_curve: list[dict] = []

        # 모든 날짜 합집합 (백테스트 기간만)
        all_dates = set()
        for df in indicators.values():
            dates = df.index[df.index >= pd.Timestamp(params.start_date)]
            all_dates.update(dates)
        all_dates = sorted(all_dates)

        if not all_dates:
            return BacktestResult(final_value=cash)

        peak_value = cash

        for day in all_dates:
            # ── 청산 체크 (먼저) ──
            closed_positions = []
            for pos in positions[:]:
                sym = pos["symbol"]
                if sym not in indicators:
                    continue
                df = indicators[sym]
                if day not in df.index:
                    continue

                current = float(df.loc[day, "Close"])
                entry = pos["entry_price"]
                pnl_pct = (current - entry) / entry

                # high_water_mark 갱신 (트레일링용)
                pos["high_water"] = max(pos.get("high_water", entry), current)

                exit_reason = None

                # ── 라이브 5-Layer 정합: L2 하드스탑 → L4 RSI(2) → L3 시간청산 ──
                entry_atr = float(pos.get("entry_atr") or 0)
                # R 배수 = (현재가 − 진입가) / 진입시점 ATR (라이브 exit_manager 와 동일)
                r_mult = (current - entry) / entry_atr if entry_atr > 0 else 0.0

                # L2: 하드 스톱 (entry − mult×entry_ATR, ATR 없으면 −5% 폴백)
                if params.use_hard_stop:
                    hard_stop = (entry - params.atr_hard_stop_mult * entry_atr
                                 if entry_atr > 0 else entry * 0.95)
                    if current <= hard_stop:
                        exit_reason = "hard_stop"

                # L4: RSI(2) 과매수 — 최소 R 도달 후에만 (승자 과조기절단 방지)
                if exit_reason is None and params.use_rsi2_exit:
                    rsi2_gate = (r_mult >= params.rsi2_exit_min_r if entry_atr > 0
                                 else pnl_pct >= 0.03)
                    if rsi2_gate:
                        _r2 = df.loc[day, "rsi2"]
                        if pd.notna(_r2) and float(_r2) > params.rsi2_exit_threshold:
                            exit_reason = "rsi2_overbought"

                # L3: 시간 청산
                if (exit_reason is None and params.use_time_stop
                        and (day - pos["entry_date"]).days >= params.time_stop_days):
                    exit_reason = "time_stop"

                if exit_reason is not None:
                    pass  # 상위 레이어에서 확정 — 아래 트레일링/고정 로직 건너뜀
                elif params.use_atr_trailing:
                    # ── L1: ATR 트레일링 + 브레이크이븐 + 부분익절 ──
                    # 라이브는 손절을 DB 에 누적 상향(래칫)하고 max(trail, old) 로 판정한다.
                    # 트레일 폭도 당일 ATR 이 아니라 진입시점 ATR 기준.
                    init_risk = (params.atr_hard_stop_mult * entry_atr if entry_atr > 0
                                 else entry - entry * (1 + params.stop_loss_pct))
                    gain = current - entry

                    # 부분익절: +partial_exit_r × 초기리스크 도달 시 1회 (일부 청산)
                    if (params.partial_exit_r > 0 and not pos.get("partial_done")
                            and init_risk > 0 and gain >= params.partial_exit_r * init_risk):
                        pexit_qty = int(pos["qty"] * params.partial_exit_pct)
                        if pexit_qty >= 1:
                            ppnl = (current - entry) * pexit_qty
                            cash += current * pexit_qty
                            pos["qty"] -= pexit_qty
                            pos["partial_done"] = True
                            trades_log.append({
                                "date": day.strftime("%Y-%m-%d"), "symbol": sym, "side": "SELL",
                                "qty": pexit_qty, "price": round(current, 2), "pnl": round(ppnl, 2),
                                "pnl_pct": round(pnl_pct, 4), "reason": "partial_exit",
                                "hold_days": (day - pos["entry_date"]).days,
                            })

                    if entry_atr > 0:
                        # 트레일링 활성화 (+activation_r × ATR 도달)
                        if r_mult >= params.atr_activation_r:
                            pos["trailing_active"] = True

                        # 브레이크이븐: +trigger_R 도달 시 손절을 본전(+버퍼)으로 상향.
                        # trail_sl 이 본전에 못 미치는 구간의 반전 손실을 막는다.
                        if params.use_breakeven and r_mult >= params.breakeven_trigger_r:
                            be_stop = entry * (1 + params.breakeven_buffer_pct)
                            if be_stop > pos["stop_loss"]:
                                pos["stop_loss"] = be_stop

                        # 트레일 손절 — 래칫(올리기만)
                        if pos["trailing_active"]:
                            trail_sl = pos["high_water"] - params.atr_trailing_mult * entry_atr
                            if trail_sl > pos["stop_loss"]:
                                pos["stop_loss"] = trail_sl
                            if current <= pos["stop_loss"]:
                                exit_reason = "atr_trailing_stop"

                    # 고정 %손절 — 라이브 exit_manager 처럼 L1 뒤의 '최종 폴백'으로 유지한다.
                    # (2026-08-18 1차 수정에서 하드스탑과 중복이라 판단해 제거했으나, 라이브는
                    #  지우지 않고 우선순위만 낮춘 구조였다. 제거 시 stop_loss_pct 가 측정 불가가
                    #  되어 변이 35/41/43 이 전부 Δ0.0 으로 나왔음 → 복원.)
                    if exit_reason is None and pnl_pct <= params.stop_loss_pct:
                        exit_reason = "stop_loss"
                    if exit_reason is None and not df.loc[day, "trend"]:
                        exit_reason = "trend_break"
                else:
                    # ── 기존(baseline): 고정 stop/take_profit/trend ──
                    if pnl_pct <= params.stop_loss_pct:
                        exit_reason = "stop_loss"
                    elif pnl_pct >= params.take_profit_pct:
                        exit_reason = "take_profit"
                    elif not df.loc[day, "trend"]:
                        exit_reason = "trend_break"

                if exit_reason:
                    pnl = (current - entry) * pos["qty"]
                    cash += current * pos["qty"]
                    trades_log.append({
                        "date": day.strftime("%Y-%m-%d"),
                        "symbol": sym,
                        "side": "SELL",
                        "qty": pos["qty"],
                        "price": round(current, 2),
                        "pnl": round(pnl, 2),
                        "pnl_pct": round(pnl_pct, 4),
                        "reason": exit_reason,
                        "hold_days": (day - pos["entry_date"]).days,
                    })
                    closed_positions.append(pos)

            for cp in closed_positions:
                positions.remove(cp)

            # ── Tier 1 시장 트렌드 필터: SPY < SMA면 신규 진입 차단(현금 보유) ──
            market_ok = True
            if params.use_market_filter and "SPY" in indicators:
                spy = indicators["SPY"]
                if day in spy.index:
                    sc = spy.loc[day, "Close"]
                    ss = spy.loc[day, "sma_market"]
                    if pd.notna(sc) and pd.notna(ss):
                        market_ok = float(sc) > float(ss)

            # ── 진입 체크 ──
            if market_ok and len(positions) < params.max_positions:
                # 일별 return_20d 랭크 계산
                day_returns = {}
                for sym, df in indicators.items():
                    if day in df.index and pd.notna(df.loc[day, "return_20d"]):
                        day_returns[sym] = float(df.loc[day, "return_20d"])

                if day_returns:
                    sorted_rets = sorted(day_returns.values())
                    n = len(sorted_rets)
                    ranks = {}
                    for sym, ret in day_returns.items():
                        ranks[sym] = sorted_rets.index(ret) / max(n - 1, 1)

                    entries_today = 0
                    candidates = []

                    for sym, df in indicators.items():
                        if sym == "SPY" and params.use_market_filter:
                            continue  # 시장필터용 벤치마크 — 진입 후보 제외
                        if day not in df.index:
                            continue
                        if sym in [p["symbol"] for p in positions]:
                            continue

                        close = float(df.loc[day, "Close"])
                        if close < params.price_range_min or close > params.price_range_max:
                            continue

                        rank = ranks.get(sym, 0)
                        trend = df.loc[day, "trend"]
                        breakout = df.loc[day, "breakout"] or (not params.require_breakout)
                        vol_surge = df.loc[day, "vol_surge"]

                        # ③번 절대 모멘텀 필터: 과거 12개월 수익 > 임계치인 종목만 롱
                        if params.use_abs_momentum:
                            am = df.loc[day, "abs_mom"]
                            if pd.isna(am) or float(am) < params.abs_mom_min:
                                continue

                        if (rank >= params.return_rank_min and trend
                                and breakout and vol_surge):
                            candidates.append((sym, close, rank))

                    # 랭크 높은 순 정렬
                    candidates.sort(key=lambda x: x[2], reverse=True)

                    for sym, close, rank in candidates:
                        if (len(positions) >= params.max_positions
                                or entries_today >= params.max_daily_entries):
                            break

                        target_amount = cash * params.position_pct / (1 - params.position_pct * len(positions) / max(len(positions) + 1, 1))
                        # 단순화: 전체 자산 대비 5%
                        total_val = cash + sum(
                            float(indicators[p["symbol"]].loc[day, "Close"]) * p["qty"]
                            for p in positions
                            if day in indicators[p["symbol"]].index
                        )
                        target_amount = total_val * params.position_pct
                        # ②번 변동성 타깃팅: 종목 ATR%의 역수로 사이즈 스케일 (승수 상/하한 clip)
                        if params.use_vol_targeting:
                            atr_v = float(df.loc[day, "atr"]) if pd.notna(df.loc[day, "atr"]) else 0.0
                            atr_pct = atr_v / close if close > 0 else 0.0
                            if atr_pct > 0:
                                mult = params.target_atr_pct / atr_pct
                                mult = max(params.vol_mult_min, min(params.vol_mult_max, mult))
                                target_amount *= mult
                        qty = int(target_amount / close)
                        if qty <= 0:
                            continue
                        cost = qty * close
                        if cost > cash:
                            qty = int(cash / close)
                            if qty <= 0:
                                continue
                            cost = qty * close

                        cash -= cost
                        _entry_atr = (float(df.loc[day, "atr"])
                                      if pd.notna(df.loc[day, "atr"]) else 0.0)
                        positions.append({
                            "symbol": sym,
                            "qty": qty,
                            "entry_price": close,
                            "entry_date": day,
                            # 라이브는 진입시점 ATR 을 고정 저장해 하드스탑·R배수 산정에 쓴다
                            "entry_atr": _entry_atr,
                            # 정적 하드스탑(절대 안 움직임) + 래칫 손절(올리기만) 을 분리 보관.
                            # 라이브 swing_positions.hard_stop / stop_loss 컬럼과 같은 역할.
                            "hard_stop": (close - params.atr_hard_stop_mult * _entry_atr
                                          if (params.use_hard_stop and _entry_atr > 0)
                                          else close * (1 + params.stop_loss_pct)),
                            "stop_loss": (close - params.atr_hard_stop_mult * _entry_atr
                                          if (params.use_hard_stop and _entry_atr > 0)
                                          else close * (1 + params.stop_loss_pct)),
                            "trailing_active": False,
                        })
                        trades_log.append({
                            "date": day.strftime("%Y-%m-%d"),
                            "symbol": sym,
                            "side": "BUY",
                            "qty": qty,
                            "price": round(close, 2),
                            "pnl": 0,
                            "pnl_pct": 0,
                            "reason": "entry",
                            "hold_days": 0,
                        })
                        entries_today += 1

            # ── 일말 자산 평가 ──
            # 해당 일자에 시세가 없는 종목(휴장/결측/상장폐지)은 마지막 확인가로 이월한다.
            # 이월하지 않으면 보유 포지션 평가액이 그날만 0 으로 사라져 자산이 급감했다가
            # 다음날 복구되는 유령 손실이 생긴다. 최종일에 걸리면 final_value 가 그대로
            # 깎여 수익률·MDD·Sharpe 가 전부 왜곡됨 (2026-08-18 발견, §22.AO-6).
            pos_value = 0
            for pos in positions:
                sym = pos["symbol"]
                if sym in indicators and day in indicators[sym].index:
                    px = float(indicators[sym].loc[day, "Close"])
                    pos["last_price"] = px
                else:
                    px = float(pos.get("last_price") or pos["entry_price"])
                pos_value += px * pos["qty"]

            total_value = cash + pos_value
            peak_value = max(peak_value, total_value)
            drawdown = (total_value - peak_value) / peak_value if peak_value > 0 else 0

            equity_curve.append({
                "date": day.strftime("%Y-%m-%d"),
                "value": round(total_value, 2),
                "cash": round(cash, 2),
                "drawdown": round(drawdown, 4),
                "positions": len(positions),
            })

        # ── 결과 계산 ──
        return self._calc_metrics(equity_curve, trades_log, params)

    def _calc_metrics(self, equity_curve: list[dict],
                      trades_log: list[dict],
                      params: BacktestParams) -> BacktestResult:
        """성과 지표 계산."""
        if not equity_curve:
            return BacktestResult()

        values = [e["value"] for e in equity_curve]
        initial = params.initial_capital
        final = values[-1]

        total_return = (final - initial) / initial
        days = len(values)
        years = days / 252
        cagr = (final / initial) ** (1 / years) - 1 if years > 0 else 0

        # MDD
        peak = initial
        max_dd = 0
        for v in values:
            peak = max(peak, v)
            dd = (v - peak) / peak
            max_dd = min(max_dd, dd)

        # 일별 수익률
        daily_returns = []
        for i in range(1, len(values)):
            r = (values[i] - values[i - 1]) / values[i - 1]
            daily_returns.append(r)

        # 샤프 비율
        if daily_returns:
            avg_r = np.mean(daily_returns)
            std_r = np.std(daily_returns) if len(daily_returns) > 1 else 1
            sharpe = (avg_r / std_r) * np.sqrt(252) if std_r > 0 else 0
        else:
            sharpe = 0

        # 거래 통계 (SELL 거래만)
        sells = [t for t in trades_log if t["side"] == "SELL"]
        total_trades = len(sells)
        wins = [t for t in sells if t["pnl"] > 0]
        losses = [t for t in sells if t["pnl"] <= 0]
        win_rate = len(wins) / total_trades if total_trades > 0 else 0

        gross_profit = sum(t["pnl"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # 손익비(payoff ratio) = 평균 승 수익% / 평균 패 손실% — ①번 핵심 지표
        avg_win_pct = np.mean([t["pnl_pct"] for t in wins]) if wins else 0
        avg_loss_pct = np.mean([t["pnl_pct"] for t in losses]) if losses else 0
        payoff_ratio = (avg_win_pct / abs(avg_loss_pct)) if avg_loss_pct < 0 else 0

        avg_hold = (np.mean([t["hold_days"] for t in sells])
                    if sells else 0)

        return BacktestResult(
            total_return=round(total_return, 4),
            cagr=round(cagr, 4),
            max_drawdown=round(max_dd, 4),
            sharpe_ratio=round(sharpe, 4),
            win_rate=round(win_rate, 4),
            total_trades=total_trades,
            profit_factor=round(profit_factor, 4),
            payoff_ratio=round(payoff_ratio, 3),
            avg_win_pct=round(avg_win_pct, 4),
            avg_loss_pct=round(avg_loss_pct, 4),
            avg_hold_days=round(avg_hold, 1),
            final_value=round(final, 2),
            equity_curve=equity_curve,
            trades_log=trades_log,
        )

    def run_spy_benchmark(self, params: BacktestParams) -> BacktestResult:
        """SPY Buy & Hold 벤치마크."""
        try:
            spy = yf.download(
                "SPY",
                start=params.start_date.isoformat(),
                end=params.end_date.isoformat(),
                progress=False,
                threads=False,
                timeout=YF_TIMEOUT_SEC,
            )
            if spy.empty:
                return BacktestResult()

            close = spy["Close"].astype(float)
            first = float(close.iloc[0])
            qty = int(params.initial_capital / first)
            remaining = params.initial_capital - qty * first

            equity = []
            peak = params.initial_capital
            for ts, price in close.items():
                val = qty * float(price) + remaining
                peak = max(peak, val)
                dd = (val - peak) / peak if peak > 0 else 0
                equity.append({
                    "date": ts.strftime("%Y-%m-%d"),
                    "value": round(val, 2),
                    "drawdown": round(dd, 4),
                })

            return self._calc_metrics(equity, [], params)
        except Exception as e:
            logger.error(f"SPY benchmark error: {e}")
            return BacktestResult()
