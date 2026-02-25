"""
V3.1 Phase 4 — Monte Carlo Simulation
수익률 분포 기반 포트폴리오 경로 시뮬레이션

Features:
- 부트스트랩 + 정규 분포 + Block Bootstrap
- 파산 확률, MDD 분포, Sharpe 신뢰구간
- CAGR/MDD p5/p50/p95 보고
"""
import json
import logging
from dataclasses import dataclass

import numpy as np

from engine.config.settings import Settings
from engine.data.storage import PostgresStore
from engine.backtest.engine import BacktestStore, compute_metrics

logger = logging.getLogger(__name__)


@dataclass
class MonteCarloResult:
    """Monte Carlo 시뮬레이션 결과"""
    n_simulations: int
    # CAGR 분포
    median_cagr: float
    p5_cagr: float
    p95_cagr: float
    # Sharpe 분포
    median_sharpe: float
    p5_sharpe: float
    p95_sharpe: float
    # MDD 분포
    median_mdd: float
    p5_mdd: float        # 5th percentile (worst)
    p95_mdd: float       # 95th percentile (best)
    # Risk
    prob_negative: float      # 마이너스 수익 확률
    prob_mdd_over_20: float   # MDD > 20% 확률


class MonteCarloSimulator:
    """
    Monte Carlo 포트폴리오 시뮬레이션

    Method: Block Bootstrap
    - 원본 수익률을 블록 단위로 리샘플링
    - 자기상관 구조 보존
    """

    def __init__(self, config: Settings = None):
        self.config = config or Settings()
        self.pg = PostgresStore(self.config.pg_dsn)
        self.store = BacktestStore(self.pg)
        self.n_sims = self.config.monte_carlo_sims  # 10000

    def run(
        self,
        daily_returns: np.ndarray,
        n_sims: int = None,
        n_days: int = 252,
        block_size: int = 21,
        initial_capital: float = 100_000,
    ) -> MonteCarloResult:
        """
        Monte Carlo 시뮬레이션 실행

        Args:
            daily_returns: 원본 일별 수익률
            n_sims: 시뮬레이션 횟수
            n_days: 시뮬레이션 기간 (일)
            block_size: 블록 부트스트랩 크기 (21일 = 1개월)
            initial_capital: 초기 자본
        """
        if n_sims is None:
            n_sims = self.n_sims

        n_orig = len(daily_returns)
        if n_orig < 30:
            raise ValueError(f"Need 30+ days, got {n_orig}")

        logger.info(f"Monte Carlo: {n_sims} sims x {n_days} days (block={block_size})")

        # Block Bootstrap 시뮬레이션
        all_cagrs = np.zeros(n_sims)
        all_sharpes = np.zeros(n_sims)
        all_mdds = np.zeros(n_sims)
        all_finals = np.zeros(n_sims)

        rng = np.random.default_rng(42)

        for i in range(n_sims):
            # 블록 부트스트랩으로 수익률 경로 생성
            sim_returns = self._block_bootstrap(
                daily_returns, n_days, block_size, rng
            )

            # 자본 곡선
            equity = initial_capital * np.cumprod(1 + sim_returns)
            final_value = equity[-1]

            # CAGR
            years = n_days / 252
            cagr = (final_value / initial_capital) ** (1 / years) - 1 if years > 0 else 0

            # Sharpe
            if np.std(sim_returns) > 0:
                sharpe = np.mean(sim_returns) / np.std(sim_returns) * np.sqrt(252)
            else:
                sharpe = 0

            # MDD
            peak = np.maximum.accumulate(equity)
            dd = (equity - peak) / peak
            mdd = np.min(dd)

            all_cagrs[i] = cagr
            all_sharpes[i] = sharpe
            all_mdds[i] = mdd
            all_finals[i] = final_value

        # 통계 계산
        result = MonteCarloResult(
            n_simulations=n_sims,
            median_cagr=float(np.median(all_cagrs)),
            p5_cagr=float(np.percentile(all_cagrs, 5)),
            p95_cagr=float(np.percentile(all_cagrs, 95)),
            median_sharpe=float(np.median(all_sharpes)),
            p5_sharpe=float(np.percentile(all_sharpes, 5)),
            p95_sharpe=float(np.percentile(all_sharpes, 95)),
            median_mdd=float(np.median(all_mdds)),
            p5_mdd=float(np.percentile(all_mdds, 5)),
            p95_mdd=float(np.percentile(all_mdds, 95)),
            prob_negative=float(np.mean(all_finals < initial_capital)),
            prob_mdd_over_20=float(np.mean(all_mdds < -0.20)),
        )

        logger.info(
            f"  CAGR: {result.p5_cagr:.1%} / {result.median_cagr:.1%} / {result.p95_cagr:.1%}"
            f"  Sharpe: {result.p5_sharpe:.2f} / {result.median_sharpe:.2f} / {result.p95_sharpe:.2f}"
            f"  MDD: {result.p5_mdd:.1%} / {result.median_mdd:.1%}"
            f"  P(loss)={result.prob_negative:.1%}"
        )

        return result

    def run_and_save(
        self,
        daily_returns: np.ndarray,
        n_sims: int = None,
        n_days: int = 252,
    ) -> MonteCarloResult:
        """Monte Carlo + DB 저장"""
        run_id = self.store.create_run(
            name=f"MonteCarlo {n_sims or self.n_sims} sims",
            run_type="monte_carlo",
            config={"n_sims": n_sims or self.n_sims, "n_days": n_days},
        )

        try:
            result = self.run(daily_returns, n_sims, n_days)

            with self.pg.get_conn() as conn:
                conn.execute("""
                    INSERT INTO monte_carlo_results
                        (run_id, n_simulations,
                         median_cagr, p5_cagr, p95_cagr,
                         median_sharpe, p5_sharpe, p95_sharpe,
                         median_mdd, p5_mdd, p95_mdd,
                         prob_negative, prob_mdd_over_20)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    run_id, result.n_simulations,
                    result.median_cagr, result.p5_cagr, result.p95_cagr,
                    result.median_sharpe, result.p5_sharpe, result.p95_sharpe,
                    result.median_mdd, result.p5_mdd, result.p95_mdd,
                    result.prob_negative, result.prob_mdd_over_20,
                ))
                conn.commit()

            self.store.complete_run(run_id, {
                "median_cagr": result.median_cagr,
                "median_sharpe": result.median_sharpe,
                "prob_negative": result.prob_negative,
            })
            return result

        except Exception as e:
            self.store.fail_run(run_id, str(e))
            raise

    def _block_bootstrap(
        self,
        returns: np.ndarray,
        n_days: int,
        block_size: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        """블록 부트스트랩 리샘플링"""
        n = len(returns)
        result = np.empty(n_days)
        idx = 0

        while idx < n_days:
            # 랜덤 시작점
            start = rng.integers(0, n - block_size)
            end = min(start + block_size, n)
            block = returns[start:end]

            # 결과에 복사
            take = min(len(block), n_days - idx)
            result[idx:idx + take] = block[:take]
            idx += take

        return result
