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
    volume_ratio_min: float = 1.5
    stop_loss_pct: float = -0.05
    take_profit_pct: float = 0.10
    max_positions: int = 4
    position_pct: float = 0.05
    max_daily_entries: int = 1
    price_range_min: float = 20.0
    price_range_max: float = 80.0


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

        # ── 2. 데이터 다운로드 ──
        logger.info(f"Downloading data for {len(universe_symbols)} symbols...")
        start_padded = pd.Timestamp(params.start_date) - pd.Timedelta(days=300)

        all_data = {}
        batch_size = 50
        for i in range(0, len(universe_symbols), batch_size):
            batch = universe_symbols[i:i + batch_size]
            try:
                data = yf.download(
                    " ".join(batch),
                    start=start_padded.strftime("%Y-%m-%d"),
                    end=params.end_date.isoformat(),
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )
                if data.empty:
                    continue
                for sym in batch:
                    try:
                        if len(batch) == 1:
                            df = data[["Open", "High", "Low", "Close", "Volume"]].copy()
                        else:
                            df = data[sym][["Open", "High", "Low", "Close", "Volume"]].copy()
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
            df["high_5d"] = close.shift(1).rolling(params.breakout_days).max()
            df["vol_avg_20"] = volume.rolling(20).mean()
            df["vol_ratio"] = volume / df["vol_avg_20"]
            df["trend"] = (close > df["sma_50"]) & (df["sma_50"] > df["sma_200"])
            df["breakout"] = close > df["high_5d"]
            df["vol_surge"] = df["vol_ratio"] > params.volume_ratio_min
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

                exit_reason = None
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

            # ── 진입 체크 ──
            if len(positions) < params.max_positions:
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
                        if day not in df.index:
                            continue
                        if sym in [p["symbol"] for p in positions]:
                            continue

                        close = float(df.loc[day, "Close"])
                        if close < params.price_range_min or close > params.price_range_max:
                            continue

                        rank = ranks.get(sym, 0)
                        trend = df.loc[day, "trend"]
                        breakout = df.loc[day, "breakout"]
                        vol_surge = df.loc[day, "vol_surge"]

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
                        positions.append({
                            "symbol": sym,
                            "qty": qty,
                            "entry_price": close,
                            "entry_date": day,
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
            pos_value = 0
            for pos in positions:
                sym = pos["symbol"]
                if sym in indicators and day in indicators[sym].index:
                    pos_value += float(indicators[sym].loc[day, "Close"]) * pos["qty"]

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
