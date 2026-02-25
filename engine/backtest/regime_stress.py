"""
V3.1 Phase 4 — Regime Transition Stress Test

4가지 스트레스 시나리오:
  1. COVID Crash (2020-02~04): Bull → Bear 4주 급락
  2. Rate Hike (2022-01~10): Bull → Bear 6개월 하락
  3. Recovery (2020-04~2021-01): Bear → Bull 회복
  4. VIX Spike (2018-02, 2020-03): 급격한 변동성 급등

검증 항목:
- 레짐 감지 정확도 / 탐지 지연
- Kill Switch 발동 여부 / 레벨
- 구간 수익률 / MDD
- HMM False Positive Rate (목표 < 15%)
"""
import json
import logging
from dataclasses import dataclass, asdict
from datetime import date

import numpy as np

from engine.config.settings import Settings
from engine.data.storage import PostgresStore
from engine.backtest.engine import BacktestEngine, BacktestStore, compute_metrics
from engine.risk.kill_switch import DrawdownKillSwitch, DefenseLevel

logger = logging.getLogger(__name__)

# ─── Stress Scenarios ───
STRESS_SCENARIOS = {
    "covid_crash": {
        "name": "COVID-19 Crash",
        "start": date(2020, 1, 15),
        "end": date(2020, 4, 30),
        "expected_regime": "bear",
        "description": "Bull→Bear in 4 weeks, SPY -34%",
    },
    "rate_hike": {
        "name": "2022 Rate Hike Bear",
        "start": date(2022, 1, 3),
        "end": date(2022, 10, 31),
        "expected_regime": "bear",
        "description": "Bull→Bear over 6 months, SPY -25%",
    },
    "recovery": {
        "name": "Post-COVID Recovery",
        "start": date(2020, 3, 23),
        "end": date(2021, 1, 31),
        "expected_regime": "bull",
        "description": "Bear→Bull recovery, SPY +70%",
    },
    "vix_spike": {
        "name": "VIX Spike (Volmageddon)",
        "start": date(2018, 1, 26),
        "end": date(2018, 4, 30),
        "expected_regime": "bear",
        "description": "Sudden vol spike, VIX 15→50",
    },
}


@dataclass
class StressTestResult:
    """단일 스트레스 시나리오 결과"""
    scenario: str
    name: str
    period_start: date
    period_end: date
    total_return: float
    max_drawdown: float
    sharpe: float
    kill_triggered: bool
    kill_level_reached: str
    recovery_days: int
    regime_accuracy: float
    false_positive_rate: float
    detection_lag_days: int
    passed: bool


class RegimeStressTester:
    """레짐 전환 스트레스 테스트"""

    def __init__(self, config: Settings = None):
        self.config = config or Settings()
        self.engine = BacktestEngine(self.config)
        self.store = BacktestStore(self.engine.pg)

    def run_all(self) -> dict:
        """4개 시나리오 전체 실행"""
        run_id = self.store.create_run(
            name="Regime Stress Test (4 scenarios)",
            run_type="regime_stress",
            config={"scenarios": list(STRESS_SCENARIOS.keys())},
        )

        results = []
        for scenario_key, scenario in STRESS_SCENARIOS.items():
            logger.info(f"Stress Test: {scenario['name']}")
            try:
                result = self.run_scenario(scenario_key)
                results.append(result)
                self._save_result(run_id, result)
            except Exception as e:
                logger.error(f"  {scenario_key} failed: {e}")

        # 요약
        n_passed = sum(1 for r in results if r.passed)
        avg_accuracy = np.mean([r.regime_accuracy for r in results]) if results else 0
        avg_fpr = np.mean([r.false_positive_rate for r in results]) if results else 1

        summary = {
            "scenarios_tested": len(results),
            "scenarios_passed": n_passed,
            "all_passed": n_passed == len(results),
            "avg_regime_accuracy": float(avg_accuracy),
            "avg_false_positive_rate": float(avg_fpr),
            "fpr_below_15pct": float(avg_fpr) < 0.15,
        }

        self.store.complete_run(run_id, summary)
        summary["results"] = [asdict(r) for r in results]
        summary["run_id"] = run_id

        logger.info(f"Stress Test: {n_passed}/{len(results)} passed, "
                    f"FPR={avg_fpr:.1%}")
        return summary

    def run_scenario(self, scenario_key: str) -> StressTestResult:
        """단일 시나리오 실행"""
        scenario = STRESS_SCENARIOS[scenario_key]
        start = scenario["start"]
        end = scenario["end"]
        expected = scenario["expected_regime"]

        # 백테스트 실행
        bt_result = self.engine.run(start, end)

        # 레짐 정확도 분석
        regime_arr = np.array(bt_result.regimes)
        if len(regime_arr) > 0:
            accuracy = float(np.mean(regime_arr == expected))
            # False Positive: Bear를 Bull로 잘못 분류
            if expected == "bear":
                fpr = float(np.mean(regime_arr == "bull"))
            else:
                fpr = float(np.mean(regime_arr == "bear"))
        else:
            accuracy = 0.0
            fpr = 1.0

        # 탐지 지연: 예상 레짐이 처음 감지된 시점
        lag_days = self._compute_detection_lag(
            bt_result.regimes, expected
        )

        # Kill Switch 분석
        kill_arr = bt_result.kill_levels
        kill_triggered = any(k != "NORMAL" for k in kill_arr)
        max_kill = "NORMAL"
        levels = ["NORMAL", "WARNING", "DEFENSIVE", "EMERGENCY"]
        for k in kill_arr:
            if k in levels and levels.index(k) > levels.index(max_kill):
                max_kill = k

        # 회복 기간 (MDD 후 고점 회복까지)
        recovery_days = self._compute_recovery_days(bt_result.equity_curve)

        # 통과 조건
        passed = (
            accuracy >= 0.5 and          # 50% 이상 정확
            fpr < 0.25 and               # FPR < 25%
            bt_result.metrics.max_drawdown > -0.30  # MDD < -30%
        )

        result = StressTestResult(
            scenario=scenario_key,
            name=scenario["name"],
            period_start=start,
            period_end=end,
            total_return=bt_result.metrics.total_return,
            max_drawdown=bt_result.metrics.max_drawdown,
            sharpe=bt_result.metrics.sharpe,
            kill_triggered=kill_triggered,
            kill_level_reached=max_kill,
            recovery_days=recovery_days,
            regime_accuracy=accuracy,
            false_positive_rate=fpr,
            detection_lag_days=lag_days,
            passed=passed,
        )

        logger.info(
            f"  {scenario_key}: ret={result.total_return:.1%} "
            f"mdd={result.max_drawdown:.1%} acc={accuracy:.0%} "
            f"fpr={fpr:.0%} kill={max_kill} "
            f"{'PASS' if passed else 'FAIL'}"
        )
        return result

    def _compute_detection_lag(
        self, regimes: list, expected: str
    ) -> int:
        """예상 레짐 최초 감지 지연 (일)"""
        for i, r in enumerate(regimes):
            if r == expected:
                return i
        return len(regimes)  # 미감지

    def _compute_recovery_days(self, equity: np.ndarray) -> int:
        """MDD 후 고점 회복까지 일수"""
        if len(equity) == 0:
            return 0
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak
        mdd_idx = np.argmin(dd)

        # MDD 이후 고점 회복 시점 찾기
        for i in range(mdd_idx, len(equity)):
            if equity[i] >= peak[mdd_idx]:
                return i - mdd_idx
        return len(equity) - mdd_idx  # 미회복

    def _save_result(self, run_id: int, result: StressTestResult):
        """DB 저장"""
        with self.engine.pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO regime_stress_results
                    (run_id, scenario, period_start, period_end,
                     total_return, max_drawdown, sharpe,
                     kill_triggered, kill_level_reached, recovery_days,
                     regime_accuracy, false_positive_rate, detection_lag_days)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                run_id, result.scenario, result.period_start, result.period_end,
                result.total_return, result.max_drawdown, result.sharpe,
                result.kill_triggered, result.kill_level_reached, result.recovery_days,
                result.regime_accuracy, result.false_positive_rate, result.detection_lag_days,
            ))
            conn.commit()
