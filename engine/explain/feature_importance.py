"""
V3.1 Phase 3.3 — SHAP Feature Importance
전략 시그널 설명 + 레짐 피처 분석
- explain_signal(): 개별 시그널의 SHAP Top-5 피처
- regime_feature_importance(): 레짐별 평균 팩터 상관
- strategy_feature_summary(): 전략별 피처 중요도 요약
"""
import logging
from typing import Any

import numpy as np

from engine.data.storage import PostgresStore

logger = logging.getLogger(__name__)

try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False
    logger.warning("shap not installed, explain features will be limited")


class FeatureExplainer:
    """SHAP 기반 포지션 설명"""

    def __init__(self, pg: PostgresStore):
        self.pg = pg

    def explain_signal(
        self,
        symbol: str,
        strategy_model: Any,
        feature_names: list[str],
    ) -> dict:
        """
        개별 시그널에 대한 SHAP 설명
        - strategy_model: fit된 모델 (LightGBM, XGBoost, RandomForest 등)
        - feature_names: 피처 이름 목록
        Returns: {symbol, top_features, base_value, prediction}
        """
        if not SHAP_AVAILABLE:
            return {"error": "shap not installed"}

        features = self._load_factor_features(symbol)
        if features is None:
            return {"error": f"no factor data for {symbol}"}

        X = np.array([features])

        try:
            # TreeExplainer: LightGBM, XGBoost, RandomForest 등
            explainer = shap.TreeExplainer(strategy_model)
            shap_values = explainer.shap_values(X)

            # 다중 클래스 → 첫 번째 클래스 사용
            if isinstance(shap_values, list):
                sv = shap_values[0][0]
            else:
                sv = shap_values[0]

            # Top 5 영향력 피처
            importance = sorted(
                zip(feature_names, sv),
                key=lambda x: abs(x[1]),
                reverse=True,
            )[:5]

            base = float(explainer.expected_value)
            if isinstance(explainer.expected_value, np.ndarray):
                base = float(explainer.expected_value[0])

            return {
                "symbol": symbol,
                "top_features": [
                    {"name": name, "impact": float(val)}
                    for name, val in importance
                ],
                "base_value": base,
                "prediction": base + float(sum(sv)),
            }
        except Exception as e:
            logger.error(f"SHAP explain_signal error for {symbol}: {e}")
            return {"error": str(e)}

    def regime_feature_importance(self) -> dict:
        """
        레짐별 평균 팩터 분석
        HMM은 SHAP 직접 적용 불가 → 레짐별 팩터 통계로 대체
        """
        try:
            with self.pg.get_conn() as conn:
                rows = conn.execute("""
                    WITH spy_returns AS (
                        SELECT
                            dp.time,
                            dp.close,
                            dp.volume,
                            dp.close / NULLIF(
                                LAG(dp.close) OVER (ORDER BY dp.time), 0
                            ) - 1 AS daily_ret
                        FROM daily_prices dp
                        WHERE dp.symbol = 'SPY'
                          AND dp.time > NOW() - INTERVAL '180 days'
                    ),
                    regime_joined AS (
                        SELECT
                            rh.regime,
                            sr.daily_ret,
                            sr.close,
                            sr.volume
                        FROM regime_history rh
                        JOIN spy_returns sr
                            ON DATE(rh.detected_at) = DATE(sr.time)
                    )
                    SELECT
                        regime,
                        STDDEV(daily_ret) AS avg_volatility,
                        AVG(daily_ret) AS avg_momentum,
                        AVG(volume) AS avg_volume
                    FROM regime_joined
                    GROUP BY regime
                    ORDER BY regime
                """).fetchall()

            if not rows:
                return {"regimes": [], "note": "no data"}

            return {
                "regimes": [
                    {
                        "regime": r["regime"],
                        "avg_volatility": float(r["avg_volatility"] or 0),
                        "avg_momentum": float(r["avg_momentum"] or 0),
                        "avg_volume": float(r["avg_volume"] or 0),
                    }
                    for r in rows
                ],
            }
        except Exception as e:
            logger.error(f"regime_feature_importance error: {e}")
            return {"error": str(e)}

    def strategy_feature_summary(self, strategy: str) -> dict:
        """
        전략별 시그널 강도 통계
        어떤 팩터가 시그널 강도에 가장 상관있는지 분석
        """
        try:
            with self.pg.get_conn() as conn:
                rows = conn.execute("""
                    SELECT
                        sl.direction,
                        COUNT(*) as count,
                        AVG(sl.strength) as avg_strength,
                        STDDEV(sl.strength) as std_strength,
                        sl.regime
                    FROM signal_log sl
                    WHERE sl.strategy = %s
                      AND sl.time > NOW() - INTERVAL '30 days'
                    GROUP BY sl.direction, sl.regime
                    ORDER BY count DESC
                """, (strategy,)).fetchall()

            if not rows:
                return {"strategy": strategy, "summary": [], "note": "no signals"}

            return {
                "strategy": strategy,
                "summary": [
                    {
                        "direction": r["direction"],
                        "regime": r["regime"],
                        "count": r["count"],
                        "avg_strength": float(r["avg_strength"] or 0),
                        "std_strength": float(r["std_strength"] or 0),
                    }
                    for r in rows
                ],
            }
        except Exception as e:
            logger.error(f"strategy_feature_summary error: {e}")
            return {"error": str(e)}

    # ─── Internal ───

    def _load_factor_features(self, symbol: str) -> list[float] | None:
        """
        심볼의 최신 팩터 데이터 로드
        Returns: [volatility, momentum, quality, value, volume_ratio, ...]
        """
        try:
            with self.pg.get_conn() as conn:
                row = conn.execute("""
                    WITH latest AS (
                        SELECT
                            symbol,
                            -- 20일 변동성
                            STDDEV(daily_ret) OVER w AS volatility,
                            -- 12개월 모멘텀 (252일)
                            (LAST_VALUE(close) OVER w_full /
                             FIRST_VALUE(close) OVER w_full) - 1 AS momentum,
                            -- 거래량 비율
                            volume::float / NULLIF(
                                AVG(volume) OVER (
                                    ORDER BY time
                                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                                ), 0) AS volume_ratio,
                            close,
                            time,
                            -- daily return
                            close / NULLIF(LAG(close) OVER (ORDER BY time), 0) - 1
                                AS daily_ret
                        FROM daily_prices
                        WHERE symbol = %s
                        ORDER BY time DESC
                        LIMIT 252
                        WINDOW
                            w AS (ORDER BY time ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
                            w_full AS (ORDER BY time ROWS BETWEEN 251 PRECEDING AND CURRENT ROW)
                    )
                    SELECT volatility, momentum, volume_ratio
                    FROM latest
                    ORDER BY time DESC
                    LIMIT 1
                """, (symbol,)).fetchone()

            if not row:
                return None

            return [
                float(row.get("volatility", 0) or 0),
                float(row.get("momentum", 0) or 0),
                float(row.get("volume_ratio", 0) or 0),
            ]
        except Exception as e:
            logger.error(f"_load_factor_features error for {symbol}: {e}")
            return None
