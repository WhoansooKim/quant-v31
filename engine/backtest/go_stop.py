"""
V3.1 Phase 4 — GO/STOP Auto-Decision Logic

백테스트 결과를 종합하여 Paper Trading 진행 여부 자동 판정
결과를 go_stop_log 테이블에 기록

GO 기준 (DevPlan.jsx):
  - Paper Sharpe > 1.1  (Walk-Forward OOS avg)
  - MDD > -18%
  - DSR > 95%
  - HMM FPR < 15%      (Stress Test avg)
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from engine.config.settings import Settings
from engine.data.storage import PostgresStore


def _json_default(obj):
    """JSON 직렬화 헬퍼 (Decimal, datetime 등)"""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

logger = logging.getLogger(__name__)


@dataclass
class GoStopCriteria:
    """GO/STOP 판정 기준 및 결과"""
    # Walk-Forward
    wf_oos_sharpe: float = 0.0
    wf_passed: bool = False

    # DSR
    dsr_score: float = 0.0
    dsr_passed: bool = False

    # Stress Test
    stress_avg_fpr: float = 1.0
    stress_scenarios_passed: int = 0
    stress_total: int = 4
    stress_fpr_passed: bool = False

    # Base Backtest MDD
    base_mdd: float = -1.0
    mdd_passed: bool = False

    # Monte Carlo (informational)
    mc_prob_negative: float = 1.0
    mc_prob_mdd_over_20: float = 1.0
    mc_median_sharpe: float = 0.0

    # Granger (optional)
    granger_skipped: bool = True
    granger_passed: bool = False

    # Overall
    decision: str = "STOP"
    notes: str = ""


class GoStopDecider:
    """GO/STOP 자동 판정기"""

    def __init__(self, config: Settings = None):
        self.config = config or Settings()
        self.pg = PostgresStore(self.config.pg_dsn)

    def evaluate(self) -> GoStopCriteria:
        """
        DB에서 최신 백테스트 결과를 수집하고 GO/STOP 판정

        Returns:
            GoStopCriteria with decision
        """
        criteria = GoStopCriteria()

        # 1. Walk-Forward 결과
        wf = self._get_latest_run("walk_forward")
        if wf and wf.get("summary"):
            summary = wf["summary"] if isinstance(wf["summary"], dict) else json.loads(wf["summary"])
            criteria.wf_oos_sharpe = summary.get("oos_sharpe_avg", 0)
            criteria.wf_passed = criteria.wf_oos_sharpe >= self.config.go_sharpe_min

        # 2. DSR 결과
        dsr = self._get_latest_dsr()
        if dsr:
            criteria.dsr_score = dsr.get("dsr_score", 0)
            criteria.dsr_passed = criteria.dsr_score >= self.config.dsr_threshold

        # 3. Stress Test 결과
        stress = self._get_latest_run("regime_stress")
        if stress and stress.get("summary"):
            summary = stress["summary"] if isinstance(stress["summary"], dict) else json.loads(stress["summary"])
            criteria.stress_avg_fpr = summary.get("avg_false_positive_rate", 1.0)
            criteria.stress_scenarios_passed = summary.get("scenarios_passed", 0)
            criteria.stress_total = summary.get("scenarios_tested", 4)
            criteria.stress_fpr_passed = criteria.stress_avg_fpr < 0.15

        # 4. Base Backtest MDD (최근 full backtest에서)
        base_mdd = self._get_base_mdd()
        if base_mdd is not None:
            criteria.base_mdd = base_mdd
            criteria.mdd_passed = base_mdd > self.config.go_mdd_max  # -0.18

        # 5. Monte Carlo (informational)
        mc = self._get_latest_mc()
        if mc:
            criteria.mc_prob_negative = mc.get("prob_negative", 1.0)
            criteria.mc_prob_mdd_over_20 = mc.get("prob_mdd_over_20", 1.0)
            criteria.mc_median_sharpe = mc.get("median_sharpe", 0.0)

        # 6. Granger (optional)
        granger = self._get_latest_run("granger")
        if granger and granger.get("summary"):
            summary = granger["summary"] if isinstance(granger["summary"], dict) else json.loads(granger["summary"])
            if "error" not in summary:
                criteria.granger_skipped = False
                criteria.granger_passed = summary.get("passed", False)

        # GO/STOP 판정
        go_criteria = [
            criteria.wf_passed,
            criteria.dsr_passed,
            criteria.stress_fpr_passed,
            criteria.mdd_passed,
        ]

        n_passed = sum(go_criteria)
        n_total = len(go_criteria)

        if all(go_criteria):
            criteria.decision = "GO"
            criteria.notes = f"All {n_total} criteria passed. Paper Trading 진행 가능."
        else:
            criteria.decision = "STOP"
            failed = []
            if not criteria.wf_passed:
                failed.append(
                    f"WF OOS Sharpe={criteria.wf_oos_sharpe:.3f} < {self.config.go_sharpe_min}"
                )
            if not criteria.dsr_passed:
                failed.append(
                    f"DSR={criteria.dsr_score:.1%} < {self.config.dsr_threshold:.0%}"
                )
            if not criteria.stress_fpr_passed:
                failed.append(
                    f"Stress FPR={criteria.stress_avg_fpr:.1%} >= 15%"
                )
            if not criteria.mdd_passed:
                failed.append(
                    f"MDD={criteria.base_mdd:.1%} <= {self.config.go_mdd_max:.0%}"
                )
            criteria.notes = (
                f"{n_passed}/{n_total} criteria passed. "
                f"Failed: {'; '.join(failed)}"
            )

        logger.info(f"GO/STOP Decision: {criteria.decision}")
        logger.info(f"  {criteria.notes}")

        return criteria

    def evaluate_and_save(self) -> GoStopCriteria:
        """GO/STOP 판정 + DB 저장"""
        criteria = self.evaluate()

        criteria_json = {
            "walk_forward": {
                "oos_sharpe": criteria.wf_oos_sharpe,
                "threshold": self.config.go_sharpe_min,
                "passed": criteria.wf_passed,
            },
            "dsr": {
                "score": criteria.dsr_score,
                "threshold": self.config.dsr_threshold,
                "passed": criteria.dsr_passed,
            },
            "stress_test": {
                "avg_fpr": criteria.stress_avg_fpr,
                "scenarios_passed": criteria.stress_scenarios_passed,
                "scenarios_total": criteria.stress_total,
                "fpr_threshold": 0.15,
                "passed": criteria.stress_fpr_passed,
            },
            "mdd": {
                "value": criteria.base_mdd,
                "threshold": self.config.go_mdd_max,
                "passed": criteria.mdd_passed,
            },
            "monte_carlo": {
                "prob_negative": criteria.mc_prob_negative,
                "prob_mdd_over_20": criteria.mc_prob_mdd_over_20,
                "median_sharpe": criteria.mc_median_sharpe,
            },
            "granger": {
                "skipped": criteria.granger_skipped,
                "passed": criteria.granger_passed,
            },
        }

        with self.pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO go_stop_log (decision, criteria, notes, decided_by)
                VALUES (%s, %s, %s, %s)
            """, (
                criteria.decision,
                json.dumps(criteria_json, default=_json_default),
                criteria.notes,
                "system_auto",
            ))
            conn.commit()

        logger.info(f"  Decision saved to go_stop_log")
        return criteria

    # ─── DB 조회 헬퍼 ───

    def _get_latest_run(self, run_type: str) -> dict | None:
        """최신 완료된 backtest_run 조회"""
        with self.pg.get_conn() as conn:
            row = conn.execute("""
                SELECT run_id, summary
                FROM backtest_runs
                WHERE run_type = %s AND status = 'completed'
                ORDER BY finished_at DESC
                LIMIT 1
            """, (run_type,)).fetchone()
        return dict(row) if row else None

    def _get_latest_dsr(self) -> dict | None:
        """최신 DSR 결과 조회"""
        with self.pg.get_conn() as conn:
            row = conn.execute("""
                SELECT d.* FROM dsr_results d
                JOIN backtest_runs br ON d.run_id = br.run_id
                WHERE br.status = 'completed'
                ORDER BY br.finished_at DESC
                LIMIT 1
            """).fetchone()
        return self._to_float_dict(row) if row else None

    def _get_latest_mc(self) -> dict | None:
        """최신 Monte Carlo 결과 조회"""
        with self.pg.get_conn() as conn:
            row = conn.execute("""
                SELECT mc.* FROM monte_carlo_results mc
                JOIN backtest_runs br ON mc.run_id = br.run_id
                WHERE br.status = 'completed'
                ORDER BY br.finished_at DESC
                LIMIT 1
            """).fetchone()
        return self._to_float_dict(row) if row else None

    @staticmethod
    def _to_float_dict(row) -> dict:
        """DB row의 Decimal 값을 float으로 변환"""
        d = dict(row)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
        return d

    def _get_base_mdd(self) -> float | None:
        """최근 전체 백테스트의 MDD (Monte Carlo 기반)"""
        mc = self._get_latest_mc()
        if mc:
            return mc.get("median_mdd", None)
        return None
