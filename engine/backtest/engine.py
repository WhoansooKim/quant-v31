"""
V3.1 Phase 4 — Core Backtest Engine
PostgreSQL 데이터 기반 벡터화 백테스트

Features:
- 일별 포트폴리오 시뮬레이션 (PostgreSQL OHLCV)
- 레짐 적응형 배분 반영
- Kill Switch 시뮬레이션
- 슬리피지 + 수수료 모델
- 성과 메트릭 계산 (Sharpe, CAGR, MDD, Calmar)
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import numpy as np

from engine.config.settings import Settings
from engine.data.storage import PostgresStore
from engine.risk.regime import RegimeDetector
from engine.risk.regime_allocator import RegimeAllocator
from engine.risk.kill_switch import DrawdownKillSwitch, DefenseLevel

logger = logging.getLogger(__name__)


@dataclass
class BacktestMetrics:
    """백테스트 성과 메트릭"""
    total_return: float = 0.0
    cagr: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    max_drawdown: float = 0.0
    calmar: float = 0.0
    volatility: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    win_rate: float = 0.0
    n_days: int = 0
    n_trades: int = 0
    # Regime breakdown
    bull_return: float = 0.0
    sideways_return: float = 0.0
    bear_return: float = 0.0
    # Kill switch
    kill_events: int = 0
    max_kill_level: str = "NORMAL"


@dataclass
class BacktestResult:
    """백테스트 결과"""
    metrics: BacktestMetrics
    equity_curve: np.ndarray      # 일별 포트폴리오 가치
    daily_returns: np.ndarray     # 일별 수익률
    dates: list                   # 날짜 목록
    regimes: list                 # 일별 레짐
    kill_levels: list             # 일별 Kill Switch 레벨
    allocations: list             # 일별 배분
    drawdowns: np.ndarray         # 일별 MDD


def compute_metrics(
    daily_returns: np.ndarray,
    risk_free: float = 0.04,
    annual_factor: int = 252,
) -> BacktestMetrics:
    """일별 수익률 → 성과 메트릭 계산"""
    n = len(daily_returns)
    if n < 2:
        return BacktestMetrics(n_days=n)

    m = BacktestMetrics(n_days=n)

    # 누적 수익
    equity = np.cumprod(1 + daily_returns)
    m.total_return = float(equity[-1] - 1)

    # CAGR
    years = n / annual_factor
    if years > 0 and equity[-1] > 0:
        m.cagr = float(equity[-1] ** (1 / years) - 1)

    # Volatility
    m.volatility = float(np.std(daily_returns) * np.sqrt(annual_factor))

    # Sharpe
    if m.volatility > 0:
        excess = np.mean(daily_returns) - risk_free / annual_factor
        m.sharpe = float(excess / np.std(daily_returns) * np.sqrt(annual_factor))

    # Sortino
    downside = daily_returns[daily_returns < 0]
    if len(downside) > 0:
        downside_vol = np.std(downside) * np.sqrt(annual_factor)
        if downside_vol > 0:
            excess = np.mean(daily_returns) - risk_free / annual_factor
            m.sortino = float(excess / (np.std(downside) * np.sqrt(annual_factor)))

    # MDD
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    m.max_drawdown = float(np.min(dd))

    # Calmar
    if m.max_drawdown < 0:
        m.calmar = float(m.cagr / abs(m.max_drawdown))

    # Distribution
    m.skewness = float(_skewness(daily_returns))
    m.kurtosis = float(_kurtosis(daily_returns))

    # Win rate
    m.win_rate = float(np.mean(daily_returns > 0))

    return m


def _skewness(x: np.ndarray) -> float:
    n = len(x)
    if n < 3:
        return 0.0
    mean = np.mean(x)
    std = np.std(x, ddof=1)
    if std == 0:
        return 0.0
    return float(np.mean(((x - mean) / std) ** 3) * n / ((n - 1) * (n - 2) + 1e-10))


def _kurtosis(x: np.ndarray) -> float:
    n = len(x)
    if n < 4:
        return 0.0
    mean = np.mean(x)
    std = np.std(x, ddof=1)
    if std == 0:
        return 0.0
    return float(np.mean(((x - mean) / std) ** 4) - 3)


class BacktestEngine:
    """
    레짐 적응형 벡터화 백테스트 엔진
    PostgreSQL daily_prices 데이터 사용
    """

    def __init__(self, config: Optional[Settings] = None):
        self.config = config or Settings()
        self.pg = PostgresStore(self.config.pg_dsn)
        self.allocator = RegimeAllocator()
        self.slippage_bps = self.config.slippage_bps

    def run(
        self,
        start_date: date,
        end_date: date,
        initial_capital: float = 100_000,
        regimes: Optional[dict] = None,
    ) -> BacktestResult:
        """
        백테스트 실행

        Args:
            start_date: 시작일
            end_date: 종료일
            initial_capital: 초기 자본
            regimes: {date: regime_str} 사전 계산 레짐 (없으면 DB에서 로드)
        """
        logger.info(f"Backtest: {start_date} ~ {end_date}, ${initial_capital:,.0f}")

        # 1. SPY 데이터 로드 (벤치마크 + 포트폴리오 프록시)
        spy_data = self._load_prices("SPY", start_date, end_date)
        if not spy_data:
            raise ValueError("No SPY data for the given period")

        dates = [d["time"] for d in spy_data]
        closes = np.array([float(d["close"]) for d in spy_data])
        spy_returns = np.diff(closes) / closes[:-1]

        n_days = len(spy_returns)
        logger.info(f"  Loaded {n_days} trading days")

        # 2. 레짐 로드 (DB 또는 제공된 것)
        if regimes is None:
            regimes = self._load_regimes(start_date, end_date)

        # 3. 시뮬레이션
        equity = np.zeros(n_days + 1)
        equity[0] = initial_capital
        daily_rets = np.zeros(n_days)
        regime_list = []
        kill_list = []
        alloc_list = []

        kill_switch = DrawdownKillSwitch(initial_value=initial_capital)

        for i in range(n_days):
            d = dates[i + 1] if i + 1 < len(dates) else dates[-1]
            day = d.date() if hasattr(d, "date") else d

            # 레짐 결정
            regime = regimes.get(day, "sideways")
            regime_list.append(regime)

            # Kill Switch
            pv = equity[i]
            kill_level = kill_switch.update(pv)
            kill_list.append(kill_level.value)
            exposure_limit = kill_switch.get_exposure_limit()

            # 배분
            from engine.risk.regime_allocator import RegimeState as _RS
            mock_regime = type("R", (), {
                "current": regime,
                "confidence": 0.8,
                "bull_prob": 0.8 if regime == "bull" else 0.1,
                "sideways_prob": 0.8 if regime == "sideways" else 0.1,
                "bear_prob": 0.8 if regime == "bear" else 0.1,
            })()
            alloc = self.allocator.get_allocation(mock_regime, exposure_limit)
            total_equity_pct = 1.0 - alloc.cash
            alloc_list.append(total_equity_pct)

            # EMERGENCY → 현금
            if kill_level == DefenseLevel.EMERGENCY:
                daily_rets[i] = 0.0
            else:
                # 포트폴리오 수익률 = 시장 수익 * 투자비중 - 슬리피지
                market_ret = spy_returns[i]
                slippage = self.slippage_bps / 10000
                daily_rets[i] = market_ret * total_equity_pct - slippage

            equity[i + 1] = equity[i] * (1 + daily_rets[i])

        # 4. 메트릭 계산
        metrics = compute_metrics(daily_rets)

        # 레짐별 수익
        regime_arr = np.array(regime_list)
        for regime_name, attr in [("bull", "bull_return"), ("sideways", "sideways_return"), ("bear", "bear_return")]:
            mask = regime_arr == regime_name
            if mask.any():
                setattr(metrics, attr, float(np.sum(daily_rets[mask])))

        # Kill Switch 이벤트
        kill_events = sum(1 for i in range(1, len(kill_list))
                          if kill_list[i] != kill_list[i - 1])
        metrics.kill_events = kill_events
        if kill_list:
            levels = ["NORMAL", "WARNING", "DEFENSIVE", "EMERGENCY"]
            max_idx = max(levels.index(k) for k in kill_list if k in levels)
            metrics.max_kill_level = levels[max_idx]

        # Drawdowns
        eq_curve = equity[1:]
        peak = np.maximum.accumulate(eq_curve)
        drawdowns = (eq_curve - peak) / peak

        logger.info(f"  Sharpe={metrics.sharpe:.2f} CAGR={metrics.cagr:.1%} "
                    f"MDD={metrics.max_drawdown:.1%}")

        return BacktestResult(
            metrics=metrics,
            equity_curve=equity[1:],
            daily_returns=daily_rets,
            dates=dates[1:],
            regimes=regime_list,
            kill_levels=kill_list,
            allocations=alloc_list,
            drawdowns=drawdowns,
        )

    def _load_prices(self, symbol: str, start: date, end: date) -> list[dict]:
        """PostgreSQL에서 OHLCV 로드"""
        with self.pg.get_conn() as conn:
            return conn.execute("""
                SELECT time, open, high, low, close, volume
                FROM daily_prices
                WHERE symbol = %s AND time >= %s AND time <= %s
                ORDER BY time
            """, (symbol, start, end)).fetchall()

    def _load_regimes(self, start: date, end: date) -> dict:
        """DB regime_history에서 레짐 매핑 로드"""
        with self.pg.get_conn() as conn:
            rows = conn.execute("""
                SELECT DATE(detected_at) AS day, regime
                FROM regime_history
                WHERE detected_at >= %s AND detected_at <= %s
                ORDER BY detected_at
            """, (start, end)).fetchall()

        regime_map = {}
        last_regime = "sideways"
        for r in rows:
            regime_map[r["day"]] = r["regime"]
            last_regime = r["regime"]

        # DB에 없는 날짜는 HMM으로 추정
        if not regime_map:
            regime_map = self._estimate_regimes(start, end)

        return regime_map

    def _estimate_regimes(self, start: date, end: date) -> dict:
        """HMM으로 과거 레짐 추정 (regime_history가 없을 때)"""
        logger.info("  Estimating regimes via HMM...")
        try:
            detector = RegimeDetector(
                pg_dsn=self.config.pg_dsn,
                n_states=self.config.hmm_n_states,
                lookback=self.config.hmm_lookback_days,
            )
            detector.load()

            # SPY 데이터로 레짐 추정
            spy_data = self._load_prices("SPY", start, end)
            if not spy_data:
                return {}

            closes = np.array([float(d["close"]) for d in spy_data])
            returns = np.diff(np.log(closes)).reshape(-1, 1)

            if len(returns) < 20:
                return {}

            states = detector.model.predict(returns)

            # 상태 → 레짐 매핑 (평균 수익 기준)
            state_means = {}
            for s in range(detector.n_states):
                mask = states == s
                if mask.any():
                    state_means[s] = np.mean(returns[mask])

            sorted_states = sorted(state_means.keys(), key=lambda s: state_means[s])
            state_to_regime = {}
            if len(sorted_states) >= 3:
                state_to_regime[sorted_states[0]] = "bear"
                state_to_regime[sorted_states[1]] = "sideways"
                state_to_regime[sorted_states[2]] = "bull"
            elif len(sorted_states) == 2:
                state_to_regime[sorted_states[0]] = "bear"
                state_to_regime[sorted_states[1]] = "bull"

            regime_map = {}
            for i, state in enumerate(states):
                d = spy_data[i + 1]["time"]
                day = d.date() if hasattr(d, "date") else d
                regime_map[day] = state_to_regime.get(state, "sideways")

            logger.info(f"  Estimated {len(regime_map)} regime days")
            return regime_map

        except Exception as e:
            logger.warning(f"  Regime estimation failed: {e}, using sideways default")
            return {}


class BacktestStore:
    """백테스트 결과 저장소"""

    def __init__(self, pg: PostgresStore):
        self.pg = pg

    def create_run(self, name: str, run_type: str, config: dict) -> int:
        """백테스트 실행 생성 → run_id 반환"""
        import json
        with self.pg.get_conn() as conn:
            row = conn.execute("""
                INSERT INTO backtest_runs (name, run_type, config)
                VALUES (%s, %s, %s) RETURNING run_id
            """, (name, run_type, json.dumps(config))).fetchone()
            conn.commit()
            return row["run_id"]

    def complete_run(self, run_id: int, summary: dict):
        """백테스트 완료 업데이트"""
        import json
        with self.pg.get_conn() as conn:
            conn.execute("""
                UPDATE backtest_runs
                SET finished_at = now(), status = 'completed',
                    summary = %s
                WHERE run_id = %s
            """, (json.dumps(summary), run_id))
            conn.commit()

    def fail_run(self, run_id: int, error: str):
        """백테스트 실패 업데이트"""
        import json
        with self.pg.get_conn() as conn:
            conn.execute("""
                UPDATE backtest_runs
                SET finished_at = now(), status = 'failed',
                    summary = %s
                WHERE run_id = %s
            """, (json.dumps({"error": error}), run_id))
            conn.commit()
