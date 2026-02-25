"""
V3.1 Phase 4 — Granger Causality Test
FinBERT 센티먼트 → 가격 선행성 검증

검증: 센티먼트 시그널이 가격 변동을 Granger-cause 하는지
statsmodels.tsa.stattools.grangercausalitytests 사용
"""
import json
import logging
from dataclasses import dataclass, asdict
from datetime import date, timedelta

import numpy as np

from engine.config.settings import Settings
from engine.data.storage import PostgresStore
from engine.backtest.engine import BacktestStore

logger = logging.getLogger(__name__)

try:
    from statsmodels.tsa.stattools import grangercausalitytests
    GRANGER_AVAILABLE = True
except ImportError:
    GRANGER_AVAILABLE = False


@dataclass
class GrangerResult:
    """단일 심볼 Granger 검정 결과"""
    symbol: str
    lag_days: int
    f_statistic: float
    p_value: float
    is_significant: bool   # p < 0.05
    direction: str         # sentiment_leads_price, price_leads_sentiment, none


class GrangerCausalityTester:
    """
    FinBERT 센티먼트 → 가격 Granger Causality 검증

    H0: 센티먼트가 가격 변동을 예측하지 못함
    H1: 센티먼트가 가격 변동을 Granger-cause 함
    """

    def __init__(self, config: Settings = None):
        self.config = config or Settings()
        self.pg = PostgresStore(self.config.pg_dsn)
        self.store = BacktestStore(self.pg)

    def run(
        self,
        symbols: list[str] = None,
        max_lag: int = 5,
        lookback_days: int = 180,
    ) -> dict:
        """
        Granger Causality 테스트 실행

        Args:
            symbols: 테스트 대상 종목 (None이면 sentiment_scores에서 로드)
            max_lag: 최대 시차 (일)
            lookback_days: 분석 기간
        """
        if not GRANGER_AVAILABLE:
            return {"error": "statsmodels not installed"}

        run_id = self.store.create_run(
            name=f"Granger Causality (lag={max_lag})",
            run_type="granger",
            config={"max_lag": max_lag, "lookback_days": lookback_days},
        )

        # 심볼 목록 로드
        if symbols is None:
            symbols = self._get_sentiment_symbols(lookback_days)
        if not symbols:
            self.store.fail_run(run_id, "No sentiment data found")
            return {"error": "no sentiment data", "run_id": run_id}

        logger.info(f"Granger Test: {len(symbols)} symbols, lag={max_lag}")

        results = []
        for symbol in symbols:
            try:
                result = self._test_symbol(symbol, max_lag, lookback_days)
                if result:
                    results.append(result)
                    self._save_result(run_id, result)
            except Exception as e:
                logger.warning(f"  {symbol} failed: {e}")

        # 요약
        significant = [r for r in results if r.is_significant]
        sentiment_leads = [r for r in results
                           if r.direction == "sentiment_leads_price"]

        summary = {
            "symbols_tested": len(results),
            "significant_count": len(significant),
            "significant_pct": len(significant) / max(len(results), 1),
            "sentiment_leads_count": len(sentiment_leads),
            "avg_p_value": float(np.mean([r.p_value for r in results])) if results else 1.0,
            "avg_lag": float(np.mean([r.lag_days for r in results])) if results else 0,
            "passed": len(significant) >= max(len(results) * 0.3, 1),
        }

        self.store.complete_run(run_id, summary)
        summary["results"] = [asdict(r) for r in results]
        summary["run_id"] = run_id

        logger.info(
            f"Granger: {len(significant)}/{len(results)} significant "
            f"(avg_p={summary['avg_p_value']:.4f})"
        )
        return summary

    def _test_symbol(
        self, symbol: str, max_lag: int, lookback_days: int,
    ) -> GrangerResult | None:
        """단일 심볼 Granger 검정"""
        # 센티먼트 + 가격 데이터 로드
        data = self._load_sentiment_price(symbol, lookback_days)
        if data is None or len(data) < max_lag * 3:
            return None

        sentiment = np.array([d["sentiment"] for d in data])
        returns = np.array([d["daily_return"] for d in data])

        # NaN 제거
        valid = ~(np.isnan(sentiment) | np.isnan(returns))
        sentiment = sentiment[valid]
        returns = returns[valid]

        if len(sentiment) < max_lag * 3:
            return None

        # Granger 검정: 센티먼트 → 가격
        try:
            test_data = np.column_stack([returns, sentiment])
            gc_result = grangercausalitytests(
                test_data, maxlag=max_lag, verbose=False
            )

            # 최소 p-value인 lag 선택
            best_lag = 1
            best_p = 1.0
            best_f = 0.0

            for lag in range(1, max_lag + 1):
                f_test = gc_result[lag][0]["ssr_ftest"]
                p_val = f_test[1]
                f_stat = f_test[0]
                if p_val < best_p:
                    best_p = p_val
                    best_f = f_stat
                    best_lag = lag

            is_significant = best_p < 0.05

            # 역방향 테스트: 가격 → 센티먼트
            reverse_data = np.column_stack([sentiment, returns])
            gc_reverse = grangercausalitytests(
                reverse_data, maxlag=max_lag, verbose=False
            )
            reverse_p = min(
                gc_reverse[lag][0]["ssr_ftest"][1]
                for lag in range(1, max_lag + 1)
            )

            # 방향 결정
            if is_significant and best_p < reverse_p:
                direction = "sentiment_leads_price"
            elif reverse_p < 0.05 and reverse_p < best_p:
                direction = "price_leads_sentiment"
            else:
                direction = "none"

            return GrangerResult(
                symbol=symbol,
                lag_days=best_lag,
                f_statistic=float(best_f),
                p_value=float(best_p),
                is_significant=is_significant,
                direction=direction,
            )
        except Exception as e:
            logger.debug(f"  Granger test failed for {symbol}: {e}")
            return None

    def _get_sentiment_symbols(self, lookback_days: int) -> list[str]:
        """sentiment_scores에서 활성 심볼 목록"""
        with self.pg.get_conn() as conn:
            rows = conn.execute("""
                SELECT DISTINCT symbol
                FROM sentiment_scores
                WHERE time > now() - interval '%s days'
                  AND symbol IS NOT NULL
                ORDER BY symbol
            """, (lookback_days,)).fetchall()
        return [r["symbol"] for r in rows]

    def _load_sentiment_price(
        self, symbol: str, lookback_days: int,
    ) -> list[dict] | None:
        """센티먼트 + 가격 데이터 일별 조인"""
        with self.pg.get_conn() as conn:
            rows = conn.execute("""
                WITH daily_sent AS (
                    SELECT DATE(time) AS day,
                           AVG(hybrid_score) AS sentiment
                    FROM sentiment_scores
                    WHERE symbol = %s
                      AND time > now() - interval '%s days'
                    GROUP BY DATE(time)
                ),
                daily_ret AS (
                    SELECT DATE(time) AS day,
                           (close / LAG(close) OVER (ORDER BY time) - 1)
                               AS daily_return
                    FROM daily_prices
                    WHERE symbol = %s
                      AND time > now() - interval '%s days'
                )
                SELECT ds.day, ds.sentiment, dr.daily_return
                FROM daily_sent ds
                JOIN daily_ret dr ON ds.day = dr.day
                WHERE dr.daily_return IS NOT NULL
                ORDER BY ds.day
            """, (symbol, lookback_days, symbol, lookback_days)).fetchall()

        if not rows or len(rows) < 10:
            return None
        return [dict(r) for r in rows]

    def _save_result(self, run_id: int, result: GrangerResult):
        """DB 저장"""
        with self.pg.get_conn() as conn:
            conn.execute("""
                INSERT INTO granger_results
                    (run_id, symbol, lag_days, f_statistic,
                     p_value, is_significant, direction)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                run_id, result.symbol, result.lag_days,
                result.f_statistic, result.p_value,
                result.is_significant, result.direction,
            ))
            conn.commit()
