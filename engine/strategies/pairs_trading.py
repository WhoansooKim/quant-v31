"""
V3.1 Phase 2 — ③ 페어즈 트레이딩
Gatev et al. (2006) 기반. 공적분 쌍 탐색 + 스프레드 z-score 매매.
"""
import numpy as np
from statsmodels.tsa.stattools import coint
import logging
from .base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class PairsTrading(BaseStrategy):
    """페어즈 트레이딩 전략
    
    논리:
    1. 동일 섹터 내 종목 쌍 공적분 검정
    2. p-value < 0.05인 쌍 선별
    3. 스프레드 z-score 계산
    4. |z| > 2 → 진입, |z| < 0.5 → 청산
    
    레짐 적응:
    - Bull: 약한 쌍 (p < 0.05), 넓은 진입 (z > 1.5)
    - Sideways: 중간 (p < 0.03, z > 2.0) ← 메인 환경
    - Bear: 강한 쌍만 (p < 0.01, z > 2.5)
    """
    
    def __init__(self, pg_dsn: str, config: dict | None = None):
        super().__init__(pg_dsn, config)
        self.lookback = config.get("lookback", 252) if config else 252
        self.entry_z = config.get("entry_z", 2.0) if config else 2.0
        self.exit_z = config.get("exit_z", 0.5) if config else 0.5
    
    def find_cointegrated_pairs(self, sector: str,
                                 max_pairs: int = 20) -> list[dict]:
        """섹터 내 공적분 쌍 탐색"""
        # 섹터 종목 조회
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT ticker FROM symbols
                WHERE sector = %s AND is_active = true
                ORDER BY ticker
            """, (sector,)).fetchall()
        
        symbols = [r[0] for r in rows]
        if len(symbols) < 2:
            return []
        
        # 종목별 종가 로드
        prices = {}
        for sym in symbols[:50]:  # 섹터당 50종목 제한
            data = self.get_prices_np(sym, self.lookback)
            if "close" in data and len(data["close"]) >= 200:
                prices[sym] = data["close"][-200:]
        
        if len(prices) < 2:
            return []
        
        # 쌍별 공적분 검정
        syms = list(prices.keys())
        pairs = []
        
        for i in range(len(syms)):
            for j in range(i + 1, len(syms)):
                s1, s2 = syms[i], syms[j]
                n = min(len(prices[s1]), len(prices[s2]))
                if n < 100:
                    continue
                
                try:
                    _, pvalue, _ = coint(prices[s1][-n:], prices[s2][-n:])
                    if pvalue < 0.05:
                        # 스프레드 z-score
                        spread = prices[s1][-n:] - prices[s2][-n:]
                        zscore = (spread[-1] - np.mean(spread)) / max(np.std(spread), 0.001)
                        
                        pairs.append({
                            "symbol1": s1,
                            "symbol2": s2,
                            "p_value": float(pvalue),
                            "zscore": float(zscore),
                            "sector": sector,
                        })
                except:
                    continue
        
        pairs.sort(key=lambda x: x["p_value"])
        return pairs[:max_pairs]
    
    def generate_signals(self, regime: str,
                         regime_conf: float) -> list[Signal]:
        logger.info(f"[{self.name}] 페어즈 시그널 생성 (regime={regime})")
        
        # 레짐별 파라미터
        params = {
            "bull":     {"p_threshold": 0.05, "entry_z": 1.5},
            "sideways": {"p_threshold": 0.03, "entry_z": 2.0},
            "bear":     {"p_threshold": 0.01, "entry_z": 2.5},
        }
        p = params.get(regime, params["sideways"])
        
        # 주요 섹터에서 쌍 탐색
        sectors = ["Technology", "Healthcare", "Financial Services",
                   "Industrials", "Consumer Cyclical"]
        
        all_pairs = []
        for sector in sectors:
            pairs = self.find_cointegrated_pairs(sector)
            valid = [pr for pr in pairs if pr["p_value"] < p["p_threshold"]]
            all_pairs.extend(valid)
        
        # DB에 쌍 기록
        self._save_pairs(all_pairs)
        
        # 시그널 생성 (|z| > entry_z)
        signals = []
        for pair in all_pairs:
            z = pair["zscore"]
            if abs(z) < p["entry_z"]:
                continue
            
            if z > p["entry_z"]:
                # 스프레드 높음 → s1 숏, s2 롱
                signals.append(Signal(
                    symbol=pair["symbol1"], direction="short",
                    strength=float(min(abs(z) / 3, 1.0)),
                    strategy=self.name, regime=regime,
                    factors={"pair": pair["symbol2"], "zscore": z, "p_value": pair["p_value"]},
                ))
                signals.append(Signal(
                    symbol=pair["symbol2"], direction="long",
                    strength=float(min(abs(z) / 3, 1.0)),
                    strategy=self.name, regime=regime,
                    factors={"pair": pair["symbol1"], "zscore": z, "p_value": pair["p_value"]},
                ))
            elif z < -p["entry_z"]:
                # 스프레드 낮음 → s1 롱, s2 숏
                signals.append(Signal(
                    symbol=pair["symbol1"], direction="long",
                    strength=float(min(abs(z) / 3, 1.0)),
                    strategy=self.name, regime=regime,
                    factors={"pair": pair["symbol2"], "zscore": z, "p_value": pair["p_value"]},
                ))
                signals.append(Signal(
                    symbol=pair["symbol2"], direction="short",
                    strength=float(min(abs(z) / 3, 1.0)),
                    strategy=self.name, regime=regime,
                    factors={"pair": pair["symbol1"], "zscore": z, "p_value": pair["p_value"]},
                ))
        
        logger.info(f"  [{self.name}] {len(all_pairs)}쌍 탐색, {len(signals)}개 시그널")
        return signals
    
    def _save_pairs(self, pairs: list[dict]):
        """공적분 쌍을 DB에 기록"""
        try:
            with self._get_conn() as conn:
                for p in pairs:
                    conn.execute("""
                        INSERT INTO cointegrated_pairs (symbol1, symbol2, p_value, spread_zscore)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (symbol1, symbol2) DO UPDATE SET
                            p_value = EXCLUDED.p_value,
                            spread_zscore = EXCLUDED.spread_zscore,
                            updated_at = now()
                    """, (p["symbol1"], p["symbol2"], p["p_value"], p["zscore"]))
                conn.commit()
        except Exception as e:
            logger.debug(f"쌍 DB 기록 실패: {e}")
