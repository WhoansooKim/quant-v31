"""
V3.1 Phase 2 — 레짐별 전략 배분 매트릭스
Bull/Sideways/Bear 레짐에 따라 5대 전략의 자금 비중을 동적 조절
"""
from dataclasses import dataclass
from .regime import RegimeState


@dataclass
class AllocationResult:
    """전략별 배분 비중"""
    lowvol_quality: float     # ① Low-Vol + Quality
    vol_momentum: float       # ② Vol-Managed 모멘텀
    pairs_trading: float      # ③ 페어즈 트레이딩
    vol_targeting: float      # ④ Vol-Targeting (오버레이)
    sentiment: float          # ⑤ FinBERT 센티먼트
    cash: float               # 현금 비중
    regime: str
    confidence: float


# ─── 레짐별 배분 매트릭스 (Build Plan 기준) ───
REGIME_MATRIX = {
    "bull": {
        "lowvol_quality": 0.25,
        "vol_momentum":   0.30,
        "pairs_trading":  0.10,
        "vol_targeting":  0.20,
        "sentiment":      0.10,
        "cash":           0.05,
    },
    "sideways": {
        "lowvol_quality": 0.30,
        "vol_momentum":   0.15,
        "pairs_trading":  0.25,
        "vol_targeting":  0.15,
        "sentiment":      0.10,
        "cash":           0.05,
    },
    "bear": {
        "lowvol_quality": 0.35,
        "vol_momentum":   0.05,
        "pairs_trading":  0.20,
        "vol_targeting":  0.10,
        "sentiment":      0.05,
        "cash":           0.25,
    },
}


class RegimeAllocator:
    """레짐 기반 전략 배분기
    
    - 레짐에 따라 배분 매트릭스 적용
    - 신뢰도가 낮으면 레짐 간 보간 (부드러운 전환)
    - Kill Switch exposure limit 반영
    """
    
    def __init__(self, confidence_threshold: float = 0.6):
        self.confidence_threshold = confidence_threshold
        self.matrix = REGIME_MATRIX
    
    def get_allocation(self, regime: RegimeState, 
                       exposure_limit: float = 1.0) -> AllocationResult:
        """레짐 상태에 따른 전략 배분 계산
        
        Args:
            regime: 현재 레짐 상태
            exposure_limit: Kill Switch에서 제한하는 최대 익스포저 (0.0~1.0)
        """
        if regime.confidence >= self.confidence_threshold:
            # 신뢰도 높음 → 해당 레짐 배분 그대로
            alloc = self.matrix[regime.current].copy()
        else:
            # 신뢰도 낮음 → 확률 가중 블렌딩
            alloc = self._blend_allocations(regime)
        
        # Kill Switch exposure limit 적용
        if exposure_limit < 1.0:
            alloc = self._apply_exposure_limit(alloc, exposure_limit)
        
        return AllocationResult(
            lowvol_quality=alloc["lowvol_quality"],
            vol_momentum=alloc["vol_momentum"],
            pairs_trading=alloc["pairs_trading"],
            vol_targeting=alloc["vol_targeting"],
            sentiment=alloc["sentiment"],
            cash=alloc["cash"],
            regime=regime.current,
            confidence=regime.confidence,
        )
    
    def _blend_allocations(self, regime: RegimeState) -> dict:
        """확률 가중 블렌딩 (레짐 불확실 시)"""
        probs = {
            "bull": regime.bull_prob,
            "sideways": regime.sideways_prob,
            "bear": regime.bear_prob,
        }
        
        blended = {}
        for key in self.matrix["bull"].keys():
            blended[key] = sum(
                probs[r] * self.matrix[r][key]
                for r in probs
            )
        
        # 정규화
        total = sum(blended.values())
        if total > 0:
            blended = {k: v / total for k, v in blended.items()}
        
        return blended
    
    def _apply_exposure_limit(self, alloc: dict, limit: float) -> dict:
        """Kill Switch exposure limit 적용 → 초과분을 현금으로"""
        stock_keys = ["lowvol_quality", "vol_momentum", "pairs_trading",
                      "vol_targeting", "sentiment"]
        
        stock_total = sum(alloc[k] for k in stock_keys)
        
        if stock_total <= limit:
            return alloc
        
        # 주식 비중을 limit 이하로 축소, 차이를 현금에 추가
        scale = limit / stock_total if stock_total > 0 else 0
        result = {}
        for k in stock_keys:
            result[k] = alloc[k] * scale
        result["cash"] = 1.0 - sum(result.values())
        
        return result
    
    def get_allowed_strategies(self, regime: RegimeState) -> list[str]:
        """현재 레짐에서 허용되는 전략 목록"""
        alloc = self.matrix[regime.current]
        return [k for k, v in alloc.items() if k != "cash" and v > 0.05]
