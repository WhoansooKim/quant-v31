"""
V3.1 Phase 5 — Paper Trading Performance Tracker

Paper Trading 기간 동안 일일 성과를 추적하고
GO/STOP 판정 기준 대비 달성률을 모니터링

Features:
- 일일 포트폴리오 스냅샷 기록
- Running Sharpe, MDD, CAGR 계산
- GO/STOP 재평가 (Paper Trading 기준)
"""
import json
import logging
from datetime import date, datetime, timedelta

import numpy as np

from engine.config.settings import Settings
from engine.data.storage import PostgresStore
from engine.backtest.engine import compute_metrics

logger = logging.getLogger(__name__)


class PaperTradingTracker:
    """Paper Trading 성과 추적기"""

    def __init__(self, config: Settings = None):
        self.config = config or Settings()
        self.pg = PostgresStore(self.config.pg_dsn)

    def record_snapshot(
        self,
        portfolio_value: float,
        cash: float,
        positions_value: float,
        regime: str = "unknown",
        kill_level: str = "NORMAL",
    ):
        """일일 포트폴리오 스냅샷 기록"""
        # 이전 스냅샷에서 일일 수익률 계산
        prev = self._get_latest_snapshot()
        daily_return = 0.0
        cumulative_return = 0.0
        if prev and prev["total_value"] > 0:
            daily_return = (portfolio_value / float(prev["total_value"])) - 1
            # 첫 스냅샷 기준 누적 수익률
            first = self._get_first_snapshot()
            if first and first["total_value"] > 0:
                cumulative_return = (portfolio_value / float(first["total_value"])) - 1

        with self.pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO portfolio_snapshots
                    (time, total_value, cash_value, daily_return,
                     cumulative_return, regime, kill_level)
                VALUES (now(), %s, %s, %s, %s, %s, %s)
            """, (
                portfolio_value, cash, daily_return,
                cumulative_return, regime, kill_level,
            ))
            conn.commit()
        logger.info(
            f"Paper snapshot: ${portfolio_value:,.0f} "
            f"(cash=${cash:,.0f}, positions=${positions_value:,.0f}) "
            f"daily={daily_return:+.2%}"
        )

    def _get_latest_snapshot(self) -> dict | None:
        """가장 최근 스냅샷"""
        with self.pg.get_conn() as conn:
            row = conn.execute("""
                SELECT total_value FROM portfolio_snapshots
                ORDER BY time DESC LIMIT 1
            """).fetchone()
        return dict(row) if row else None

    def _get_first_snapshot(self) -> dict | None:
        """첫 번째 스냅샷"""
        with self.pg.get_conn() as conn:
            row = conn.execute("""
                SELECT total_value FROM portfolio_snapshots
                ORDER BY time ASC LIMIT 1
            """).fetchone()
        return dict(row) if row else None

    def get_performance(self) -> dict:
        """Paper Trading 누적 성과 계산"""
        with self.pg.get_conn() as conn:
            rows = conn.execute("""
                SELECT time, total_value
                FROM portfolio_snapshots
                ORDER BY time
            """).fetchall()

        if len(rows) < 2:
            return {
                "status": "insufficient_data",
                "days": len(rows),
                "message": "Need at least 2 snapshots for performance calculation",
            }

        values = np.array([float(r["total_value"]) for r in rows])
        daily_returns = np.diff(values) / values[:-1]

        metrics = compute_metrics(daily_returns)
        start_date = rows[0]["time"]
        end_date = rows[-1]["time"]
        days = (end_date - start_date).days
        months = days / 30.44

        return {
            "status": "active",
            "start_date": str(start_date.date()),
            "end_date": str(end_date.date()),
            "days": days,
            "months": round(months, 1),
            "initial_value": float(values[0]),
            "current_value": float(values[-1]),
            "total_return": metrics.total_return,
            "cagr": metrics.cagr,
            "sharpe": metrics.sharpe,
            "sortino": metrics.sortino,
            "max_drawdown": metrics.max_drawdown,
            "calmar": metrics.calmar,
            "volatility": metrics.volatility,
            "win_rate": metrics.win_rate,
            "n_trading_days": metrics.n_days,
        }

    def evaluate_paper_go_stop(self) -> dict:
        """
        Paper Trading 성과 기반 GO/STOP 재평가

        GO 조건:
        - Paper Trading >= 9개월
        - Paper Sharpe > 1.1
        - Paper MDD > -18%
        - DSR > 95% (가장 최근 백테스트 기준)
        """
        perf = self.get_performance()
        if perf["status"] != "active":
            return {
                "decision": "PENDING",
                "reason": perf.get("message", "Insufficient data"),
                "performance": perf,
            }

        months = perf["months"]
        sharpe = perf["sharpe"]
        mdd = perf["max_drawdown"]

        criteria = {
            "duration": {
                "value": months,
                "threshold": self.config.go_paper_months,
                "passed": months >= self.config.go_paper_months,
            },
            "sharpe": {
                "value": sharpe,
                "threshold": self.config.go_sharpe_min,
                "passed": sharpe >= self.config.go_sharpe_min,
            },
            "mdd": {
                "value": mdd,
                "threshold": self.config.go_mdd_max,
                "passed": mdd > self.config.go_mdd_max,
            },
        }

        all_passed = all(c["passed"] for c in criteria.values())

        # 3개월 연속 Sharpe < 0.8 체크 (STOP 조건)
        consecutive_low_sharpe = self._check_consecutive_low_sharpe()

        decision = "PENDING"
        if months < self.config.go_paper_months:
            decision = "PENDING"
            reason = f"Paper Trading {months:.1f}/{self.config.go_paper_months} months"
        elif all_passed and not consecutive_low_sharpe:
            decision = "GO"
            reason = "All paper trading criteria met"
        elif consecutive_low_sharpe:
            decision = "STOP"
            reason = "3 consecutive months Sharpe < 0.8"
        else:
            decision = "STOP"
            failed = [k for k, v in criteria.items() if not v["passed"]]
            reason = f"Failed: {', '.join(failed)}"

        # DB 기록
        with self.pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO go_stop_log (decision, criteria, notes, decided_by)
                VALUES (%s, %s, %s, %s)
            """, (
                decision,
                json.dumps({
                    "type": "paper_trading",
                    "criteria": criteria,
                    "consecutive_low_sharpe": consecutive_low_sharpe,
                }),
                reason,
                "paper_tracker",
            ))
            conn.commit()

        return {
            "decision": decision,
            "reason": reason,
            "criteria": criteria,
            "performance": perf,
        }

    def _check_consecutive_low_sharpe(self, threshold: float = 0.8) -> bool:
        """최근 3개월 연속 Sharpe < threshold 체크"""
        with self.pg.get_conn() as conn:
            rows = conn.execute("""
                SELECT time, total_value
                FROM portfolio_snapshots
                WHERE time > now() - interval '4 months'
                ORDER BY time
            """).fetchall()

        if len(rows) < 63:  # 3개월치 데이터 부족
            return False

        values = np.array([float(r["total_value"]) for r in rows])
        daily_returns = np.diff(values) / values[:-1]

        # 월별 Sharpe 계산 (최근 3개월)
        n = len(daily_returns)
        low_months = 0
        for i in range(3):
            start = max(0, n - 21 * (i + 1))
            end = n - 21 * i
            if end <= start:
                break
            month_rets = daily_returns[start:end]
            if len(month_rets) > 5 and np.std(month_rets) > 0:
                monthly_sharpe = (
                    np.mean(month_rets) / np.std(month_rets) * np.sqrt(252)
                )
                if monthly_sharpe < threshold:
                    low_months += 1

        return low_months >= 3
