"""
V3.1 Phase 2 — 동적 포지션 사이저
ATR 기반 스톱 + Vol역가중 + Kelly Half + 집중 하이브리드
"""
import numpy as np
from dataclasses import dataclass


@dataclass
class PositionSize:
    """포지션 사이징 결과"""
    symbol: str
    shares: int
    weight: float              # 포트폴리오 비중 (0~1)
    dollar_amount: float
    stop_price: float          # ATR 기반 스톱 가격
    risk_amount: float         # 손실 허용액
    method: str                # 사용된 방법


class DynamicPositionSizer:
    """동적 포지션 사이저
    
    3가지 방법의 최솟값을 사용 (보수적):
    1. ATR 스톱 기반: risk_per_trade / (ATR * multiplier)
    2. Vol역가중: 저변동 종목에 더 많이 배분
    3. Kelly Half: 승률/손익비 기반 최적 비중의 절반
    
    + 집중도 제한: 종목당 10%, 섹터당 25%
    """
    
    def __init__(self, risk_per_trade: float = 0.02,
                 atr_multiplier: float = 2.0,
                 kelly_fraction: float = 0.5,
                 max_position_pct: float = 0.10,
                 max_sector_pct: float = 0.25):
        self.risk_per_trade = risk_per_trade
        self.atr_multiplier = atr_multiplier
        self.kelly_fraction = kelly_fraction
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct
    
    def calculate_atr(self, highs: np.ndarray, lows: np.ndarray,
                      closes: np.ndarray, period: int = 14) -> float:
        """Average True Range 계산"""
        if len(highs) < period + 1:
            return 0.0
        
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1])
            )
        )
        
        # EMA 방식 ATR
        atr = np.mean(tr[-period:])
        return float(atr)
    
    def size_by_atr(self, portfolio_value: float, current_price: float,
                    atr: float) -> tuple[float, float]:
        """ATR 기반 사이징
        
        Returns:
            (비중, 스톱가격)
        """
        if atr <= 0 or current_price <= 0:
            return 0.0, 0.0
        
        stop_distance = atr * self.atr_multiplier
        stop_price = current_price - stop_distance
        
        risk_amount = portfolio_value * self.risk_per_trade
        shares = risk_amount / stop_distance
        dollar_amount = shares * current_price
        weight = dollar_amount / portfolio_value
        
        return min(weight, self.max_position_pct), stop_price
    
    def size_by_vol_inverse(self, volatilities: dict[str, float],
                           target_symbol: str) -> float:
        """Vol역가중 사이징
        
        변동성이 낮을수록 더 많이 배분
        """
        if not volatilities or target_symbol not in volatilities:
            return 0.0
        
        inv_vols = {s: 1.0 / max(v, 0.01) for s, v in volatilities.items()}
        total_inv = sum(inv_vols.values())
        
        if total_inv <= 0:
            return 0.0
        
        weight = inv_vols[target_symbol] / total_inv
        return min(weight, self.max_position_pct)
    
    def size_by_kelly(self, win_rate: float, avg_win: float,
                      avg_loss: float) -> float:
        """Kelly Half 사이징
        
        Kelly% = W - (1-W)/R, 여기서 W=승률, R=손익비
        실전에서는 절반만 사용 (Half Kelly)
        """
        if avg_loss <= 0 or win_rate <= 0:
            return 0.0
        
        r = avg_win / abs(avg_loss)  # 손익비
        kelly = win_rate - (1 - win_rate) / r
        
        if kelly <= 0:
            return 0.0
        
        half_kelly = kelly * self.kelly_fraction
        return min(half_kelly, self.max_position_pct)
    
    def calculate(self, symbol: str, portfolio_value: float,
                  current_price: float, atr: float,
                  volatility: float = 0.0,
                  all_volatilities: dict[str, float] | None = None,
                  win_rate: float = 0.0,
                  avg_win: float = 0.0,
                  avg_loss: float = 0.0) -> PositionSize:
        """종합 포지션 사이즈 계산
        
        3가지 방법의 최솟값 (보수적 접근)
        """
        # 1. ATR 기반
        w_atr, stop_price = self.size_by_atr(portfolio_value, current_price, atr)
        
        # 2. Vol역가중 (데이터 있을 때만)
        w_vol = self.max_position_pct
        if all_volatilities and symbol in all_volatilities:
            w_vol = self.size_by_vol_inverse(all_volatilities, symbol)
        
        # 3. Kelly Half (데이터 있을 때만)
        w_kelly = self.max_position_pct
        if win_rate > 0 and avg_loss != 0:
            w_kelly = self.size_by_kelly(win_rate, avg_win, avg_loss)
        
        # 최솟값 선택 (보수적)
        weights = {"atr": w_atr, "vol_inv": w_vol, "kelly": w_kelly}
        min_method = min(weights, key=weights.get)
        final_weight = weights[min_method]
        
        # 최대 비중 제한
        final_weight = min(final_weight, self.max_position_pct)
        final_weight = max(final_weight, 0.0)
        
        dollar_amount = portfolio_value * final_weight
        shares = int(dollar_amount / current_price) if current_price > 0 else 0
        
        return PositionSize(
            symbol=symbol,
            shares=shares,
            weight=final_weight,
            dollar_amount=shares * current_price,
            stop_price=stop_price,
            risk_amount=portfolio_value * self.risk_per_trade,
            method=min_method,
        )
    
    def check_sector_limit(self, sector_weights: dict[str, float],
                           sector: str, new_weight: float) -> float:
        """섹터 집중도 제한"""
        current = sector_weights.get(sector, 0.0)
        remaining = self.max_sector_pct - current
        return min(new_weight, max(remaining, 0.0))
