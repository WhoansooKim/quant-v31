"""
V3.1 Phase 2 — 3단계 Kill Switch
MDD 기반 자동 방어: WARNING → DEFENSIVE → EMERGENCY
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class DefenseLevel(Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"         # MDD -10%
    DEFENSIVE = "DEFENSIVE"     # MDD -15%
    EMERGENCY = "EMERGENCY"     # MDD -20%


@dataclass
class KillSwitchState:
    level: DefenseLevel
    current_mdd: float            # 현재 MDD (음수)
    peak_value: float             # 최고점
    current_value: float
    exposure_limit: float         # 최대 익스포저
    allowed_strategies: list[str]
    cooldown_until: datetime | None = None
    triggered_at: datetime | None = None


# ─── Kill Switch 설정 ───
KILL_CONFIG = {
    DefenseLevel.NORMAL: {
        "mdd_threshold": 0.0,
        "exposure_limit": 1.0,
        "allowed": ["all"],
        "action": "정상 운영",
    },
    DefenseLevel.WARNING: {
        "mdd_threshold": -0.10,   # MDD -10%
        "exposure_limit": 0.70,   # 70%로 축소
        "allowed": ["lowvol_quality", "pairs_trading", "vol_targeting"],
        "action": "모멘텀+센티먼트 중단, 익스포저 70%",
    },
    DefenseLevel.DEFENSIVE: {
        "mdd_threshold": -0.15,   # MDD -15%
        "exposure_limit": 0.40,   # 40%로 축소
        "allowed": ["lowvol_quality", "pairs_trading"],
        "action": "방어 전략만, 익스포저 40%",
    },
    DefenseLevel.EMERGENCY: {
        "mdd_threshold": -0.20,   # MDD -20%
        "exposure_limit": 0.0,    # 전량 청산
        "allowed": [],
        "action": "⚠️ 전량 청산 + 30일 쿨다운",
    },
}


class DrawdownKillSwitch:
    """3단계 Kill Switch
    
    포트폴리오 최고점 대비 하락률(MDD)에 따라 자동 방어:
    - NORMAL:     정상 운영 (MDD > -10%)
    - WARNING:    MDD -10% → 공격 전략 중단, 익스포저 70%
    - DEFENSIVE:  MDD -15% → 방어 전략만, 익스포저 40%  
    - EMERGENCY:  MDD -20% → 전량 청산 + 30일 쿨다운
    
    쿨다운 해제 후 NORMAL로 복귀 (MDD 리셋).
    """
    
    def __init__(self, initial_value: float = 100000.0,
                 cooldown_days: int = 30):
        self.peak_value = initial_value
        self.current_value = initial_value
        self.level = DefenseLevel.NORMAL
        self.cooldown_days = cooldown_days
        self.cooldown_until: datetime | None = None
        self._history: list[KillSwitchState] = []
    
    @property
    def current_mdd(self) -> float:
        """현재 최대 낙폭 (음수)"""
        if self.peak_value <= 0:
            return 0.0
        return (self.current_value / self.peak_value) - 1.0
    
    def update(self, portfolio_value: float) -> DefenseLevel:
        """포트폴리오 가치 업데이트 → Kill Switch 레벨 결정
        
        Returns:
            현재 DefenseLevel
        """
        self.current_value = portfolio_value
        
        # 쿨다운 중이면 EMERGENCY 유지
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            logger.info(f"🧊 쿨다운 중: {self.cooldown_until.strftime('%Y-%m-%d')}까지")
            return DefenseLevel.EMERGENCY
        
        # 쿨다운 해제 → NORMAL 복귀
        if self.cooldown_until and datetime.now() >= self.cooldown_until:
            logger.info("✅ 쿨다운 해제 → NORMAL 복귀")
            self.cooldown_until = None
            self.peak_value = portfolio_value  # 피크 리셋
            self.level = DefenseLevel.NORMAL
            return DefenseLevel.NORMAL
        
        # 신고점 갱신
        if portfolio_value > self.peak_value:
            self.peak_value = portfolio_value
        
        mdd = self.current_mdd
        prev_level = self.level
        
        # MDD 기준 레벨 결정 (단방향: 악화만, 자동 복귀 없음)
        if mdd <= KILL_CONFIG[DefenseLevel.EMERGENCY]["mdd_threshold"]:
            self.level = DefenseLevel.EMERGENCY
            self.cooldown_until = datetime.now() + timedelta(days=self.cooldown_days)
            logger.critical(f"🚨 EMERGENCY! MDD {mdd:.1%} → 전량 청산, "
                          f"쿨다운 {self.cooldown_days}일")
        elif mdd <= KILL_CONFIG[DefenseLevel.DEFENSIVE]["mdd_threshold"]:
            self.level = DefenseLevel.DEFENSIVE
        elif mdd <= KILL_CONFIG[DefenseLevel.WARNING]["mdd_threshold"]:
            self.level = DefenseLevel.WARNING
        else:
            # MDD가 회복되면 한 단계씩 복귀 (급격한 복귀 방지)
            if self.level == DefenseLevel.DEFENSIVE and mdd > -0.12:
                self.level = DefenseLevel.WARNING
            elif self.level == DefenseLevel.WARNING and mdd > -0.07:
                self.level = DefenseLevel.NORMAL
        
        # 레벨 변경 시 로그
        if self.level != prev_level:
            config = KILL_CONFIG[self.level]
            logger.warning(f"Kill Switch: {prev_level.value} → {self.level.value} | "
                         f"MDD: {mdd:.1%} | {config['action']}")
        
        return self.level
    
    def get_exposure_limit(self) -> float:
        """현재 레벨의 최대 익스포저"""
        return KILL_CONFIG[self.level]["exposure_limit"]
    
    def get_allowed_strategies(self) -> list[str]:
        """현재 레벨에서 허용되는 전략"""
        return KILL_CONFIG[self.level]["allowed"]
    
    def get_state(self) -> KillSwitchState:
        """현재 상태 스냅샷"""
        return KillSwitchState(
            level=self.level,
            current_mdd=self.current_mdd,
            peak_value=self.peak_value,
            current_value=self.current_value,
            exposure_limit=self.get_exposure_limit(),
            allowed_strategies=self.get_allowed_strategies(),
            cooldown_until=self.cooldown_until,
        )
    
    def record_to_db(self, pg_dsn: str):
        """Kill Switch 상태를 DB에 기록"""
        import psycopg
        state = self.get_state()
        with psycopg.connect(pg_dsn) as conn:
            conn.execute("""
                INSERT INTO kill_switch_log
                    (from_level, to_level, current_mdd, portfolio_value,
                     exposure_limit, cooldown_until)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (state.level.value, state.level.value, state.current_mdd,
                  state.current_value, state.exposure_limit, state.cooldown_until))
            conn.commit()
