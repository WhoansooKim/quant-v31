"""
V3.1 Phase 2 — ② Vol-Managed 모멘텀
Barroso & Santa-Clara (2015) 기반. 12-1개월 모멘텀 × 변동성 스케일링.
"""
import numpy as np
import logging
from .base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class VolManagedMomentum(BaseStrategy):
    """Vol-Managed 모멘텀 전략
    
    논리:
    1. 12개월 수익률 - 최근 1개월 수익률 (12-1 모멘텀)
    2. 실현 변동성으로 스케일링: mom / realized_vol
    3. 레짐별 조절: Bear에서 비중 대폭 축소
    
    학술 근거: Barroso & Santa-Clara, "Momentum has its moments", JFE 2015
    """
    
    def __init__(self, pg_dsn: str, config: dict | None = None):
        super().__init__(pg_dsn, config)
        self.mom_long = config.get("mom_long", 252) if config else 252
        self.mom_skip = config.get("mom_skip", 21) if config else 21
        self.vol_window = config.get("vol_window", 63) if config else 63
        self.target_vol = config.get("target_vol", 0.15) if config else 0.15
    
    def generate_signals(self, regime: str,
                         regime_conf: float) -> list[Signal]:
        logger.info(f"[{self.name}] 시그널 생성 (regime={regime})")
        
        # Bear에서는 최소화
        if regime == "bear":
            logger.info(f"  [{self.name}] Bear 레짐 → 모멘텀 5종목 제한")
        
        # SQL로 12-1 모멘텀 + 변동성 일괄 계산
        mom_data = self._calculate_momentum()
        if not mom_data:
            return []
        
        # Vol-managed 스코어 계산
        for r in mom_data:
            realized_vol = r.get("realized_vol", 0)
            if realized_vol > 0.01:
                r["vol_managed"] = r["momentum"] / realized_vol
            else:
                r["vol_managed"] = 0.0
            
            # Vol-targeting 스케일
            r["vol_scale"] = min(self.target_vol / max(realized_vol, 0.05), 2.0)
        
        # 양의 모멘텀만, vol-managed 순위
        positive = [r for r in mom_data if r["momentum"] > 0 and r["vol_managed"] > 0]
        positive.sort(key=lambda x: x["vol_managed"], reverse=True)
        
        # 레짐별 종목 수
        n = {"bull": 20, "sideways": 15, "bear": 5}.get(regime, 15)
        top = positive[:n]
        
        signals = []
        for r in top:
            signals.append(Signal(
                symbol=r["symbol"], direction="long",
                strength=float(np.clip(r["vol_managed"] / 5, 0, 1)),
                strategy=self.name, regime=regime,
                factors={
                    "momentum_12_1": r["momentum"],
                    "realized_vol": r.get("realized_vol", 0),
                    "vol_managed": r["vol_managed"],
                    "vol_scale": r["vol_scale"],
                },
            ))
        
        logger.info(f"  [{self.name}] {len(signals)}개 시그널")
        return signals
    
    def _calculate_momentum(self) -> list[dict]:
        """SQL로 12-1 모멘텀 + 실현변동성 일괄 계산"""
        sql = """
            WITH price_endpoints AS (
                SELECT symbol,
                    last(close, time) AS latest_close,
                    first(close, time) AS first_close,
                    -- 1개월 전 종가 (skip momentum)
                    (SELECT close FROM daily_prices dp2
                     WHERE dp2.symbol = dp.symbol
                     ORDER BY time DESC
                     OFFSET %s LIMIT 1) AS skip_close
                FROM daily_prices dp
                WHERE time > now() - interval '%s days'
                GROUP BY symbol
                HAVING count(*) >= 200
            ),
            returns AS (
                SELECT symbol,
                    (close - lag(close) OVER (PARTITION BY symbol ORDER BY time))
                    / NULLIF(lag(close) OVER (PARTITION BY symbol ORDER BY time), 0) AS ret
                FROM daily_prices
                WHERE time > now() - interval '%s days'
            ),
            vols AS (
                SELECT symbol,
                    stddev(ret) * sqrt(252) AS realized_vol
                FROM returns
                WHERE ret IS NOT NULL
                GROUP BY symbol
                HAVING count(ret) >= 42
            )
            SELECT p.symbol,
                CASE WHEN p.skip_close > 0 THEN
                    (p.skip_close / NULLIF(p.first_close, 0)) - 1
                ELSE
                    (p.latest_close / NULLIF(p.first_close, 0)) - 1
                END AS momentum,
                v.realized_vol
            FROM price_endpoints p
            JOIN vols v ON p.symbol = v.symbol
            WHERE p.first_close > 0
            ORDER BY momentum DESC
        """
        try:
            return self.batch_query(sql, (self.mom_skip, self.mom_long + 30, self.vol_window + 10))
        except Exception as e:
            logger.warning(f"  모멘텀 SQL 실패, 폴백 사용: {e}")
            return self._fallback_momentum()
    
    def _fallback_momentum(self) -> list[dict]:
        """SQL 실패 시 Python 폴백"""
        universe = self.get_universe()
        results = []
        
        for sym in universe[:500]:  # 상위 500만
            try:
                data = self.get_prices_np(sym, self.mom_long + 30)
                if "close" not in data or len(data["close"]) < self.mom_long:
                    continue
                
                closes = data["close"]
                # 12-1 모멘텀
                mom = (closes[-self.mom_skip] / closes[0]) - 1
                # 실현 변동성
                ret = np.diff(closes[-self.vol_window:]) / closes[-self.vol_window:-1]
                vol = float(np.std(ret) * np.sqrt(252))
                
                results.append({
                    "symbol": sym,
                    "momentum": float(mom),
                    "realized_vol": vol,
                })
            except:
                continue
        
        return results
