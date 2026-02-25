"""
V3.1 Phase 4 — Deflated Sharpe Ratio (DSR)
Bailey & Lopez de Prado (2014) 구현

다중 전략 테스트 시 과적합 보정된 Sharpe Ratio
DSR > 95% → GO 조건 충족
"""
import json
import logging
from dataclasses import dataclass

import numpy as np
from scipy import stats

from engine.config.settings import Settings
from engine.data.storage import PostgresStore
from engine.backtest.engine import BacktestStore

logger = logging.getLogger(__name__)


@dataclass
class DSRResult:
    """DSR 계산 결과"""
    raw_sharpe: float        # 관측된 Sharpe Ratio
    dsr_score: float         # Deflated Sharpe Ratio (0~1)
    dsr_pvalue: float        # p-value
    t_stat: float            # t-통계량
    n_trials: int            # 테스트한 전략 변형 수
    skewness: float          # 수익률 왜도
    kurtosis: float          # 수익률 첨도 (초과)
    var_sharpe: float        # Sharpe의 분산
    passed: bool             # DSR > threshold?


class DeflatedSharpeRatio:
    """
    Deflated Sharpe Ratio 계산기

    Reference: Bailey & Lopez de Prado (2014)
    "The Deflated Sharpe Ratio: Correcting for Selection Bias,
     Backtest Overfitting, and Non-Normality"
    """

    def __init__(self, config: Settings = None):
        self.config = config or Settings()
        self.pg = PostgresStore(self.config.pg_dsn)
        self.store = BacktestStore(self.pg)
        self.threshold = self.config.dsr_threshold  # 0.95

    def compute(
        self,
        daily_returns: np.ndarray,
        n_trials: int = 1,
        risk_free: float = 0.04,
        annual_factor: int = 252,
    ) -> DSRResult:
        """
        DSR 계산

        Args:
            daily_returns: 일별 수익률 배열
            n_trials: 테스트한 전략 변형 수 (selection bias 보정)
            risk_free: 연간 무위험 이자율
            annual_factor: 연간 거래일 수
        """
        n = len(daily_returns)
        if n < 30:
            return DSRResult(
                raw_sharpe=0, dsr_score=0, dsr_pvalue=1,
                t_stat=0, n_trials=n_trials,
                skewness=0, kurtosis=0, var_sharpe=0, passed=False,
            )

        # 연간화 Sharpe
        excess = daily_returns - risk_free / annual_factor
        sr = float(np.mean(excess) / np.std(excess) * np.sqrt(annual_factor))

        # 수익률 분포 특성
        skew = float(stats.skew(daily_returns))
        kurt = float(stats.kurtosis(daily_returns))  # excess kurtosis

        # Sharpe Ratio의 분산 (비정규 분포 보정)
        # Var(SR) ≈ (1 - skew*SR + (kurt-1)/4 * SR^2) / (n-1)
        var_sr = (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n - 1)

        # Expected maximum Sharpe under null (selection bias)
        # E[max(SR)] ≈ sqrt(Var(SR)) * ((1-γ)*Φ^{-1}(1-1/N) + γ*Φ^{-1}(1-1/(N*e)))
        # Simplified: E[max(SR)] ≈ sqrt(2*ln(N)) * sqrt(Var(SR))
        if n_trials > 1:
            e_max_sr = np.sqrt(var_sr) * (
                (1 - np.euler_gamma) * stats.norm.ppf(1 - 1 / n_trials)
                + np.euler_gamma * stats.norm.ppf(1 - 1 / (n_trials * np.e))
            )
        else:
            e_max_sr = 0.0

        # DSR t-statistic
        if var_sr > 0:
            t_stat = (sr - e_max_sr) / np.sqrt(var_sr)
        else:
            t_stat = 0.0

        # DSR = P(SR > E[max(SR)])
        dsr_score = float(stats.norm.cdf(t_stat))
        dsr_pvalue = float(1 - dsr_score)

        passed = dsr_score >= self.threshold

        logger.info(
            f"DSR: raw_sharpe={sr:.3f} dsr={dsr_score:.3f} "
            f"n_trials={n_trials} skew={skew:.2f} kurt={kurt:.2f} "
            f"{'PASS' if passed else 'FAIL'}"
        )

        return DSRResult(
            raw_sharpe=sr,
            dsr_score=dsr_score,
            dsr_pvalue=dsr_pvalue,
            t_stat=float(t_stat),
            n_trials=n_trials,
            skewness=skew,
            kurtosis=kurt,
            var_sharpe=float(var_sr),
            passed=passed,
        )

    def run_and_save(
        self,
        daily_returns: np.ndarray,
        n_trials: int = 1,
    ) -> DSRResult:
        """DSR 계산 + DB 저장"""
        run_id = self.store.create_run(
            name=f"DSR (n_trials={n_trials})",
            run_type="dsr",
            config={"n_trials": n_trials, "threshold": self.threshold},
        )

        result = self.compute(daily_returns, n_trials)

        # DB 저장
        with self.pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO dsr_results
                    (run_id, raw_sharpe, dsr_score, dsr_pvalue,
                     n_trials, skewness, kurtosis, var_sharpe, t_stat, passed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                run_id, result.raw_sharpe, result.dsr_score,
                result.dsr_pvalue, result.n_trials,
                result.skewness, result.kurtosis,
                result.var_sharpe, result.t_stat, result.passed,
            ))
            conn.commit()

        summary = {
            "raw_sharpe": result.raw_sharpe,
            "dsr_score": result.dsr_score,
            "passed": result.passed,
        }
        self.store.complete_run(run_id, summary)

        return result
