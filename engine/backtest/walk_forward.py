"""
V3.1 Phase 4 — Walk-Forward Validation
36개월 학습 / 6개월 테스트 롤링 윈도우
OOS Sharpe, CAGR, MDD, Calmar 추적
"""
import json
import logging
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

import numpy as np

from engine.config.settings import Settings
from engine.backtest.engine import BacktestEngine, BacktestStore, compute_metrics

logger = logging.getLogger(__name__)


@dataclass
class WalkForwardFold:
    """Walk-Forward 단일 폴드 결과"""
    fold_num: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    is_sharpe: float
    is_cagr: float
    is_mdd: float
    oos_sharpe: float
    oos_cagr: float
    oos_mdd: float
    oos_calmar: float
    regime_bull_pct: float
    regime_sideways_pct: float
    regime_bear_pct: float


class WalkForwardValidator:
    """
    Walk-Forward 교차 검증

    36개월 학습 → 6개월 OOS 테스트 → 롤링
    전체 백테스트 기간에 걸쳐 폴드 생성
    """

    def __init__(self, config: Settings = None):
        self.config = config or Settings()
        self.engine = BacktestEngine(self.config)
        self.store = BacktestStore(self.engine.pg)
        self.train_months = self.config.walk_forward_train  # 36
        self.test_months = self.config.walk_forward_test    # 6

    def run(
        self,
        start_date: date = None,
        end_date: date = None,
    ) -> dict:
        """
        Walk-Forward 검증 실행

        Returns: {
            folds: [WalkForwardFold, ...],
            oos_sharpe_avg, oos_cagr_avg, oos_mdd_avg,
            degradation_ratio, passed
        }
        """
        if start_date is None:
            start_date = date.today() - timedelta(days=self.config.backtest_years * 365)
        if end_date is None:
            end_date = date.today()

        logger.info(f"Walk-Forward: {start_date} ~ {end_date}")
        logger.info(f"  Train={self.train_months}m, Test={self.test_months}m")

        # 백테스트 실행 기록
        run_id = self.store.create_run(
            name=f"WalkForward {start_date}~{end_date}",
            run_type="walk_forward",
            config={
                "train_months": self.train_months,
                "test_months": self.test_months,
                "start_date": str(start_date),
                "end_date": str(end_date),
            },
        )

        try:
            # 레짐 사전 추정 (전체 기간)
            regimes = self.engine._load_regimes(start_date, end_date)
            if not regimes:
                regimes = self.engine._estimate_regimes(start_date, end_date)

            # 폴드 생성
            folds = self._generate_folds(start_date, end_date)
            logger.info(f"  {len(folds)} folds generated")

            results = []
            for i, (train_s, train_e, test_s, test_e) in enumerate(folds):
                logger.info(f"  Fold {i + 1}: train={train_s}~{train_e} test={test_s}~{test_e}")

                # In-Sample 백테스트
                is_result = self.engine.run(train_s, train_e, regimes=regimes)

                # Out-of-Sample 백테스트
                oos_result = self.engine.run(test_s, test_e, regimes=regimes)

                # 레짐 분포 (OOS)
                regime_arr = np.array(oos_result.regimes) if oos_result.regimes else np.array([])
                bull_pct = float(np.mean(regime_arr == "bull")) if len(regime_arr) else 0
                side_pct = float(np.mean(regime_arr == "sideways")) if len(regime_arr) else 0
                bear_pct = float(np.mean(regime_arr == "bear")) if len(regime_arr) else 0

                fold = WalkForwardFold(
                    fold_num=i + 1,
                    train_start=train_s, train_end=train_e,
                    test_start=test_s, test_end=test_e,
                    is_sharpe=is_result.metrics.sharpe,
                    is_cagr=is_result.metrics.cagr,
                    is_mdd=is_result.metrics.max_drawdown,
                    oos_sharpe=oos_result.metrics.sharpe,
                    oos_cagr=oos_result.metrics.cagr,
                    oos_mdd=oos_result.metrics.max_drawdown,
                    oos_calmar=oos_result.metrics.calmar,
                    regime_bull_pct=bull_pct,
                    regime_sideways_pct=side_pct,
                    regime_bear_pct=bear_pct,
                )
                results.append(fold)

                # DB 기록
                self._save_fold(run_id, fold)

            # 요약
            if results:
                oos_sharpes = [f.oos_sharpe for f in results]
                is_sharpes = [f.is_sharpe for f in results]
                oos_cagrs = [f.oos_cagr for f in results]
                oos_mdds = [f.oos_mdd for f in results]

                avg_oos_sharpe = float(np.mean(oos_sharpes))
                avg_is_sharpe = float(np.mean(is_sharpes))
                degradation = avg_oos_sharpe / avg_is_sharpe if avg_is_sharpe != 0 else 0

                summary = {
                    "n_folds": len(results),
                    "oos_sharpe_avg": avg_oos_sharpe,
                    "oos_sharpe_std": float(np.std(oos_sharpes)),
                    "oos_cagr_avg": float(np.mean(oos_cagrs)),
                    "oos_mdd_avg": float(np.mean(oos_mdds)),
                    "oos_mdd_worst": float(np.min(oos_mdds)),
                    "degradation_ratio": degradation,
                    "passed": avg_oos_sharpe >= self.config.go_sharpe_min,
                }
            else:
                summary = {"n_folds": 0, "error": "no folds generated"}

            self.store.complete_run(run_id, summary)
            logger.info(f"  Walk-Forward complete: OOS Sharpe={summary.get('oos_sharpe_avg', 0):.2f}")
            summary["folds"] = [asdict(f) for f in results]
            summary["run_id"] = run_id
            return summary

        except Exception as e:
            self.store.fail_run(run_id, str(e))
            logger.error(f"Walk-Forward failed: {e}")
            raise

    def _generate_folds(
        self, start: date, end: date,
    ) -> list[tuple[date, date, date, date]]:
        """롤링 윈도우 폴드 생성"""
        folds = []
        current = start

        while True:
            train_start = current
            train_end = train_start + relativedelta(months=self.train_months)
            test_start = train_end + timedelta(days=1)
            test_end = test_start + relativedelta(months=self.test_months)

            if test_end > end:
                break

            folds.append((train_start, train_end, test_start, test_end))
            current += relativedelta(months=self.test_months)  # 롤링

        return folds

    def _save_fold(self, run_id: int, fold: WalkForwardFold):
        """DB에 폴드 결과 저장"""
        with self.engine.pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO walk_forward_results
                    (run_id, fold_num, train_start, train_end,
                     test_start, test_end,
                     is_sharpe, is_cagr, is_mdd,
                     oos_sharpe, oos_cagr, oos_mdd, oos_calmar,
                     regime_bull_pct, regime_sideways_pct, regime_bear_pct)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                run_id, fold.fold_num,
                fold.train_start, fold.train_end,
                fold.test_start, fold.test_end,
                fold.is_sharpe, fold.is_cagr, fold.is_mdd,
                fold.oos_sharpe, fold.oos_cagr, fold.oos_mdd, fold.oos_calmar,
                fold.regime_bull_pct, fold.regime_sideways_pct, fold.regime_bear_pct,
            ))
            conn.commit()
