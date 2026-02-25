"""
V3.1 Phase 2 — 전략 베이스 클래스
모든 전략이 상속하는 추상 클래스. PostgreSQL 직접 연동.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import psycopg
import numpy as np
import logging

logger = logging.getLogger(__name__)


@dataclass
class Signal:
    """트레이딩 시그널"""
    symbol: str
    direction: str        # "long", "short", "close"
    strength: float       # -1.0 ~ 1.0
    strategy: str
    regime: str
    factors: dict = field(default_factory=dict)  # 팩터 스코어 상세
    timestamp: datetime = field(default_factory=datetime.now)


class BaseStrategy(ABC):
    """V3.1 전략 기본 클래스
    
    모든 전략은 이 클래스를 상속하고 generate_signals()를 구현.
    PostgreSQL에서 직접 데이터를 읽어 시그널을 생성.
    """
    
    def __init__(self, pg_dsn: str, config: dict | None = None):
        self.pg_dsn = pg_dsn
        self.config = config or {}
        self.name = self.__class__.__name__
    
    def _get_conn(self):
        return psycopg.connect(self.pg_dsn)
    
    @abstractmethod
    def generate_signals(self, regime: str,
                         regime_conf: float) -> list[Signal]:
        """시그널 생성 (각 전략에서 구현)"""
        pass
    
    # ─── 공통 데이터 조회 메서드 ───
    
    def get_universe(self, min_mcap: float = 0, max_mcap: float = 1e15) -> list[str]:
        """유니버스 종목 조회"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT ticker FROM symbols
                WHERE is_active = true
                ORDER BY ticker
            """).fetchall()
        return [r[0] for r in rows]
    
    def get_prices(self, symbol: str, days: int = 504) -> list[dict]:
        """종목 OHLCV 조회 (최근 N일)"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT time, open, high, low, close, volume
                FROM daily_prices
                WHERE symbol = %s
                ORDER BY time DESC
                LIMIT %s
            """, (symbol, days)).fetchall()
        return [{"time": r[0], "open": float(r[1]), "high": float(r[2]),
                 "low": float(r[3]), "close": float(r[4]), "volume": int(r[5])}
                for r in reversed(rows)]
    
    def get_prices_np(self, symbol: str, days: int = 504) -> dict[str, np.ndarray]:
        """종목 OHLCV → NumPy 배열"""
        rows = self.get_prices(symbol, days)
        if not rows:
            return {}
        return {
            "close": np.array([r["close"] for r in rows]),
            "high": np.array([r["high"] for r in rows]),
            "low": np.array([r["low"] for r in rows]),
            "open": np.array([r["open"] for r in rows]),
            "volume": np.array([r["volume"] for r in rows]),
        }
    
    def get_returns(self, symbol: str, days: int = 504) -> np.ndarray:
        """일수익률 배열"""
        data = self.get_prices_np(symbol, days)
        if "close" not in data or len(data["close"]) < 2:
            return np.array([])
        return np.diff(data["close"]) / data["close"][:-1]
    
    def get_volatility(self, symbol: str, window: int = 21) -> float:
        """연간화 변동성"""
        ret = self.get_returns(symbol, window + 30)
        if len(ret) < window:
            return 0.0
        return float(np.std(ret[-window:]) * np.sqrt(252))
    
    def batch_query(self, sql: str, params: tuple = ()) -> list[dict]:
        """범용 SQL 쿼리 (dict 결과)"""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                columns = [desc.name for desc in cur.description]
                rows = cur.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    
    # ─── 시그널 기록 ───
    
    def record_signals(self, signals: list[Signal]):
        """시그널을 DB에 기록"""
        with self._get_conn() as conn:
            for s in signals:
                conn.execute("""
                    INSERT INTO signal_log
                        (symbol, direction, strength, strategy, regime)
                    VALUES (%s, %s, %s, %s, %s)
                """, (s.symbol, s.direction, s.strength, s.strategy, s.regime))
            conn.commit()
        logger.info(f"  [{self.name}] {len(signals)}개 시그널 기록")
    
    # ─── 유틸리티 ───
    
    @staticmethod
    def zscore(values: np.ndarray) -> np.ndarray:
        """Z-Score 표준화"""
        mean = np.mean(values)
        std = np.std(values)
        if std == 0:
            return np.zeros_like(values)
        return (values - mean) / std
    
    @staticmethod
    def rank_percentile(values: np.ndarray) -> np.ndarray:
        """백분위 순위 (0~1)"""
        n = len(values)
        if n == 0:
            return np.array([])
        ranks = np.argsort(np.argsort(values))
        return ranks / (n - 1) if n > 1 else np.array([0.5])
