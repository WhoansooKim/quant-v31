"""
V3.1 Phase 2 — ① Low-Vol + Quality 전략
저변동성 + 퀄리티 팩터 결합. SQL CTE로 팩터 계산.
"""
import numpy as np
import logging
from .base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class LowVolQuality(BaseStrategy):
    """저변동성 + 퀄리티 전략
    
    논리:
    1. 유니버스에서 252일 변동성 하위 30% 필터
    2. 퀄리티 z-score (ROE, 부채비율 역수, FCF) 상위 필터
    3. 복합 스코어 = 0.5 * Vol순위 + 0.5 * Quality순위
    4. 레짐별 종목 수 조절: Bull 15, Sideways 20, Bear 25
    
    레짐 적응:
    - Bull: 상위 15종목 (집중 투자)
    - Sideways: 상위 20종목 (분산 강화)
    - Bear: 상위 25종목 (최대 분산 + 방어적)
    """
    
    def __init__(self, pg_dsn: str, config: dict | None = None):
        super().__init__(pg_dsn, config)
        self.vol_percentile = config.get("vol_percentile", 0.30) if config else 0.30
        self.lookback_days = config.get("lookback_days", 252) if config else 252
    
    def generate_signals(self, regime: str,
                         regime_conf: float) -> list[Signal]:
        """Low-Vol + Quality 시그널 생성"""
        logger.info(f"[{self.name}] 시그널 생성 시작 (regime={regime})")
        
        # 1. 변동성 계산 (SQL로 일괄)
        vol_data = self._calculate_volatilities()
        if not vol_data:
            logger.warning(f"[{self.name}] 변동성 데이터 없음")
            return []
        
        # 2. 저변동성 필터 (하위 30%)
        vols = {r["symbol"]: r["volatility"] for r in vol_data}
        vol_threshold = np.percentile(list(vols.values()), self.vol_percentile * 100)
        low_vol_symbols = {s for s, v in vols.items() if v <= vol_threshold}
        logger.info(f"  저변동성 필터: {len(low_vol_symbols)}종목 (임계값 {vol_threshold:.1%})")
        
        # 3. 퀄리티 스코어 계산
        quality_data = self._calculate_quality_scores(list(low_vol_symbols))
        if not quality_data:
            # 퀄리티 데이터 없으면 변동성만으로 시그널
            logger.info(f"  퀄리티 데이터 없음 → 변동성 기반 시그널")
            return self._fallback_vol_only(vols, low_vol_symbols, regime)
        
        # 4. 복합 스코어 계산
        candidates = self._compute_composite(vols, quality_data, low_vol_symbols)
        
        # 5. 레짐별 종목 수
        n = {"bull": 15, "sideways": 20, "bear": 25}.get(regime, 20)
        top = sorted(candidates, key=lambda x: x["composite"], reverse=True)[:n]
        
        # 6. 시그널 생성
        signals = []
        for c in top:
            signals.append(Signal(
                symbol=c["symbol"],
                direction="long",
                strength=float(c["composite"]),
                strategy=self.name,
                regime=regime,
                factors={
                    "volatility": c.get("volatility", 0),
                    "quality_z": c.get("quality_z", 0),
                    "vol_rank": c.get("vol_rank", 0),
                },
            ))
        
        logger.info(f"  [{self.name}] {len(signals)}개 시그널 생성 (regime={regime})")
        return signals
    
    def _calculate_volatilities(self) -> list[dict]:
        """SQL로 전 종목 252일 변동성 일괄 계산"""
        sql = """
            WITH daily_returns AS (
                SELECT symbol,
                    (close - lag(close) OVER (PARTITION BY symbol ORDER BY time))
                    / NULLIF(lag(close) OVER (PARTITION BY symbol ORDER BY time), 0) AS ret
                FROM daily_prices
                WHERE time > now() - interval '%s days'
            )
            SELECT symbol,
                stddev(ret) * sqrt(252) AS volatility,
                count(ret) AS obs
            FROM daily_returns
            WHERE ret IS NOT NULL
            GROUP BY symbol
            HAVING count(ret) >= 126
            ORDER BY volatility
        """
        return self.batch_query(sql, (self.lookback_days + 30,))
    
    def _calculate_quality_scores(self, symbols: list[str]) -> list[dict]:
        """퀄리티 팩터 z-score (DB에 fundamentals 있을 때)"""
        if not symbols:
            return []
        
        try:
            sql = """
                SELECT f.ticker AS symbol,
                    f.roe,
                    f.debt_to_equity,
                    f.free_cashflow,
                    f.gross_margin,
                    -- Z-score 계산
                    (f.roe - avg(f.roe) OVER()) 
                        / NULLIF(stddev(f.roe) OVER(), 0) AS roe_z,
                    (avg(f.debt_to_equity) OVER() - f.debt_to_equity) 
                        / NULLIF(stddev(f.debt_to_equity) OVER(), 0) AS debt_z,
                    (f.free_cashflow - avg(f.free_cashflow) OVER()) 
                        / NULLIF(stddev(f.free_cashflow) OVER(), 0) AS fcf_z,
                    (f.gross_margin - avg(f.gross_margin) OVER()) 
                        / NULLIF(stddev(f.gross_margin) OVER(), 0) AS margin_z
                FROM fundamentals f
                WHERE f.ticker = ANY(%s)
                  AND f.report_date = (
                      SELECT max(report_date) FROM fundamentals WHERE ticker = f.ticker
                  )
            """
            rows = self.batch_query(sql, (symbols,))
            
            # 복합 퀄리티 z-score
            for r in rows:
                scores = [r.get("roe_z", 0) or 0,
                          r.get("debt_z", 0) or 0,
                          r.get("fcf_z", 0) or 0,
                          r.get("margin_z", 0) or 0]
                r["quality_z"] = sum(s for s in scores) / max(len([s for s in scores if s != 0]), 1)
            
            return rows
        except Exception as e:
            logger.debug(f"  퀄리티 쿼리 실패 (fundamentals 테이블 미구축): {e}")
            return []
    
    def _compute_composite(self, vols: dict, quality_data: list,
                           low_vol_symbols: set) -> list[dict]:
        """변동성 순위 + 퀄리티 순위 → 복합 스코어"""
        quality_map = {r["symbol"]: r for r in quality_data}
        
        # 변동성 순위 (낮을수록 좋음 → 역순위)
        vol_items = [(s, v) for s, v in vols.items() if s in low_vol_symbols]
        vol_sorted = sorted(vol_items, key=lambda x: x[1])
        vol_rank = {s: i / max(len(vol_sorted) - 1, 1) 
                    for i, (s, _) in enumerate(vol_sorted)}
        
        candidates = []
        for sym in low_vol_symbols:
            vol_r = 1.0 - vol_rank.get(sym, 0.5)  # 역순위 (낮은 변동성 = 높은 점수)
            
            q = quality_map.get(sym)
            qual_z = q["quality_z"] if q else 0.0
            
            # 정규화된 복합 스코어
            composite = 0.5 * vol_r + 0.5 * (qual_z + 2) / 4  # qual_z를 0~1로 대략 변환
            
            candidates.append({
                "symbol": sym,
                "volatility": vols.get(sym, 0),
                "quality_z": qual_z,
                "vol_rank": vol_r,
                "composite": composite,
            })
        
        return candidates
    
    def _fallback_vol_only(self, vols: dict, low_vol_symbols: set,
                           regime: str) -> list[Signal]:
        """퀄리티 데이터 없을 때 변동성만으로 시그널"""
        vol_items = [(s, v) for s, v in vols.items() if s in low_vol_symbols]
        vol_sorted = sorted(vol_items, key=lambda x: x[1])  # 저변동성 우선
        
        n = {"bull": 15, "sideways": 20, "bear": 25}.get(regime, 20)
        
        signals = []
        for i, (sym, vol) in enumerate(vol_sorted[:n]):
            strength = 1.0 - (i / max(n - 1, 1))  # 1위=1.0, 마지막=0.0
            signals.append(Signal(
                symbol=sym, direction="long", strength=strength,
                strategy=self.name, regime=regime,
                factors={"volatility": vol, "vol_rank": i + 1},
            ))
        
        return signals
