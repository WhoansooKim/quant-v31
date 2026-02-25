"""
V3.1 Phase 2 — ④ Volatility Targeting 오버레이
Harvey et al. (2018) 기반. 포트폴리오 전체 변동성을 목표치에 맞춤.
"""
import numpy as np
import logging

logger = logging.getLogger(__name__)


class VolatilityTargeting:
    """Vol-Targeting 오버레이
    
    논리:
    1. 포트폴리오 실현 변동성 측정 (21일)
    2. 목표 변동성(15%)과 비교
    3. 스케일 팩터 = target_vol / realized_vol
    4. 전체 익스포저를 스케일 팩터로 조절
    
    레짐 연동:
    - Bull:     max_leverage 1.3x까지 허용
    - Sideways: max_leverage 1.0x (레버리지 없음)
    - Bear:     min_exposure 0.3x (현금 비중 높임)
    
    학술 근거: Harvey et al., "The Impact of Volatility Targeting", JPM 2018
    """
    
    def __init__(self, target_vol: float = 0.15,
                 max_leverage: float = 1.3,
                 min_exposure: float = 0.3,
                 lookback: int = 21):
        self.target_vol = target_vol
        self.max_leverage = max_leverage
        self.min_exposure = min_exposure
        self.lookback = lookback
    
    def calculate_scale(self, portfolio_returns: np.ndarray,
                        regime: str = "bull") -> float:
        """Vol-Targeting 스케일 팩터 계산
        
        Args:
            portfolio_returns: 포트폴리오 일수익률 배열 (최소 lookback일)
            regime: 현재 레짐
            
        Returns:
            스케일 팩터 (0.3 ~ 1.3)
        """
        if len(portfolio_returns) < self.lookback:
            logger.warning(f"수익률 데이터 부족: {len(portfolio_returns)}/{self.lookback}일")
            return 1.0
        
        # 실현 변동성 (연간화)
        recent = portfolio_returns[-self.lookback:]
        realized_vol = float(np.std(recent) * np.sqrt(252))
        
        if realized_vol < 0.001:
            return 1.0
        
        # 스케일 팩터
        raw_scale = self.target_vol / realized_vol
        
        # 레짐별 제한
        regime_limits = {
            "bull":     (self.min_exposure, self.max_leverage),   # 0.3 ~ 1.3
            "sideways": (self.min_exposure, 1.0),                # 0.3 ~ 1.0
            "bear":     (self.min_exposure, 0.7),                # 0.3 ~ 0.7
        }
        
        min_exp, max_exp = regime_limits.get(regime, (0.3, 1.0))
        scale = float(np.clip(raw_scale, min_exp, max_exp))
        
        logger.debug(f"Vol-Target: realized={realized_vol:.1%}, "
                    f"scale={raw_scale:.2f} → clamped={scale:.2f} ({regime})")
        
        return scale
    
    def apply_to_weights(self, weights: dict[str, float],
                         portfolio_returns: np.ndarray,
                         regime: str = "bull") -> dict[str, float]:
        """기존 포지션 비중에 Vol-Targeting 적용
        
        Args:
            weights: {symbol: weight} 포지션 비중
            portfolio_returns: 포트폴리오 일수익률
            regime: 현재 레짐
            
        Returns:
            조정된 비중 dict
        """
        scale = self.calculate_scale(portfolio_returns, regime)
        
        adjusted = {sym: w * scale for sym, w in weights.items()}
        
        # 조정 후 총 비중
        total = sum(adjusted.values())
        cash = max(1.0 - total, 0.0)
        
        logger.info(f"Vol-Targeting: scale={scale:.2f}, "
                   f"total_exposure={total:.1%}, cash={cash:.1%}")
        
        return adjusted
    
    def get_info(self, portfolio_returns: np.ndarray, regime: str) -> dict:
        """현재 상태 정보"""
        if len(portfolio_returns) < self.lookback:
            return {"scale": 1.0, "realized_vol": 0, "target_vol": self.target_vol}
        
        realized = float(np.std(portfolio_returns[-self.lookback:]) * np.sqrt(252))
        scale = self.calculate_scale(portfolio_returns, regime)
        
        return {
            "scale": scale,
            "realized_vol": realized,
            "target_vol": self.target_vol,
            "regime": regime,
        }
