"""
V3.1 Phase 3 — PostgreSQL + Redis 저장소
psycopg3 (dict_row) + Redis 캐시
오케스트레이터가 사용하는 모든 DB 메서드
"""
import json
import logging
from datetime import datetime
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
import redis

logger = logging.getLogger(__name__)


class PostgresStore:
    """PostgreSQL + TimescaleDB 저장소"""

    def __init__(self, dsn: str):
        # psycopg3는 postgresql:// 스킴 사용
        self.dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    @contextmanager
    def get_conn(self):
        """dict_row 커넥션 컨텍스트 매니저"""
        conn = psycopg.connect(self.dsn, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    # ─── OHLCV ───

    def get_ohlcv(self, symbol: str, days: int = 504) -> list[dict]:
        """종목 OHLCV 조회 (최근 N일, 시간순 정렬)"""
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT time, open, high, low, close, volume
                FROM daily_prices
                WHERE symbol = %s
                ORDER BY time DESC
                LIMIT %s
            """, (symbol, days)).fetchall()
        return list(reversed(rows))

    def get_latest_price(self, symbol: str) -> float:
        """최신 종가"""
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT close FROM daily_prices
                WHERE symbol = %s
                ORDER BY time DESC LIMIT 1
            """, (symbol,)).fetchone()
        return float(row["close"]) if row else 0.0

    def get_atr(self, symbol: str, period: int = 14) -> float:
        """ATR 계산 (TimescaleDB SQL)"""
        with self.get_conn() as conn:
            row = conn.execute("""
                WITH tr AS (
                    SELECT time,
                        GREATEST(
                            high - low,
                            ABS(high - LAG(close) OVER (ORDER BY time)),
                            ABS(low - LAG(close) OVER (ORDER BY time))
                        ) AS true_range
                    FROM daily_prices
                    WHERE symbol = %s
                    ORDER BY time DESC
                    LIMIT %s
                )
                SELECT AVG(true_range) AS atr
                FROM tr WHERE true_range IS NOT NULL
            """, (symbol, period + 1)).fetchone()
        return float(row["atr"]) if row and row["atr"] else 0.0

    # ─── 레짐 ───

    def insert_regime(self, state) -> None:
        """RegimeState를 regime_history에 기록"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO regime_history
                    (regime, bull_prob, sideways_prob, bear_prob,
                     confidence, previous_regime, is_transition)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (state.current, state.bull_prob, state.sideways_prob,
                  state.bear_prob, state.confidence,
                  state.previous, state.is_transition))
            conn.commit()

    def get_latest_regime(self) -> dict | None:
        """최신 레짐 상태"""
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT regime, bull_prob, sideways_prob, bear_prob,
                       confidence, previous_regime, is_transition, detected_at
                FROM regime_history
                ORDER BY detected_at DESC LIMIT 1
            """).fetchone()
        return dict(row) if row else None

    # ─── Kill Switch ───

    def insert_kill_switch_event(self, from_level: str, to_level: str,
                                  mdd: float, pv: float,
                                  exp_limit: float,
                                  cooldown_until=None) -> None:
        """Kill Switch 이벤트 기록"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO kill_switch_log
                    (from_level, to_level, current_mdd, portfolio_value,
                     exposure_limit, cooldown_until)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (from_level, to_level, mdd, pv, exp_limit, cooldown_until))
            conn.commit()

    # ─── 시그널 ───

    def insert_signal(self, symbol: str, direction: str,
                      strength: float, strategy: str, regime: str) -> None:
        """시그널 기록"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO signal_log
                    (symbol, direction, strength, strategy, regime)
                VALUES (%s, %s, %s, %s, %s)
            """, (symbol, direction, strength, strategy, regime))
            conn.commit()

    # ─── 거래 ───

    def insert_trade(self, trade: dict) -> None:
        """거래 기록"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO trades
                    (order_id, symbol, strategy, side, qty, price,
                     regime, kill_level, is_paper)
                VALUES (%(order_id)s, %(symbol)s, %(strategy)s,
                        %(side)s, %(qty)s, %(price)s,
                        %(regime)s, %(kill_level)s, %(is_paper)s)
            """, trade)
            conn.commit()

    # ─── 스냅샷 ───

    def insert_snapshot(self, value: float, regime: str,
                        regime_confidence: float, kill_level: str,
                        exposure_limit: float, vol_scale: float,
                        mdd: float) -> None:
        """포트폴리오 스냅샷 기록"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO portfolio_snapshots
                    (total_value, regime, regime_confidence,
                     kill_level, exposure_limit, vol_scale,
                     max_drawdown)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (value, regime, regime_confidence,
                  kill_level, exposure_limit, vol_scale, mdd))
            conn.commit()

    def get_latest_snapshot(self) -> dict | None:
        """최신 포트폴리오 스냅샷"""
        with self.get_conn() as conn:
            return conn.execute("""
                SELECT * FROM portfolio_snapshots
                ORDER BY time DESC LIMIT 1
            """).fetchone()

    # ─── 전략 성과 ───

    def insert_strategy_perf(self, strategy: str, daily_return: float,
                              allocation: float, regime: str,
                              signal_count: int) -> None:
        """전략별 성과 기록"""
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO strategy_performance
                    (strategy, daily_return, allocation, regime, signal_count)
                VALUES (%s, %s, %s, %s, %s)
            """, (strategy, daily_return, allocation, regime, signal_count))
            conn.commit()


class RedisCache:
    """Redis 캐시 (경량)"""

    def __init__(self, url: str = "redis://localhost:6379"):
        self.client = redis.from_url(url, decode_responses=True)
        self._prefix = "qv31:"

    def _key(self, name: str) -> str:
        return f"{self._prefix}{name}"

    # ─── 레짐 캐시 ───

    def set_regime(self, state) -> None:
        """현재 레짐 상태 캐시 (TTL 24h)"""
        data = {
            "current": state.current,
            "bull_prob": state.bull_prob,
            "sideways_prob": state.sideways_prob,
            "bear_prob": state.bear_prob,
            "confidence": state.confidence,
            "detected_at": state.detected_at.isoformat(),
        }
        self.client.setex(self._key("regime"), 86400, json.dumps(data))

    def get_regime(self) -> dict | None:
        """캐시된 레짐 상태"""
        raw = self.client.get(self._key("regime"))
        return json.loads(raw) if raw else None

    # ─── Kill Switch 캐시 ───

    def set_kill_switch(self, level: str, mdd: float,
                         exposure: float) -> None:
        data = {"level": level, "mdd": mdd, "exposure": exposure,
                "updated_at": datetime.now().isoformat()}
        self.client.setex(self._key("kill_switch"), 86400, json.dumps(data))

    def get_kill_switch(self) -> dict | None:
        raw = self.client.get(self._key("kill_switch"))
        return json.loads(raw) if raw else None

    # ─── 범용 ───

    def set_json(self, key: str, data: dict, ttl: int = 3600) -> None:
        self.client.setex(self._key(key), ttl, json.dumps(data))

    def get_json(self, key: str) -> dict | None:
        raw = self.client.get(self._key(key))
        return json.loads(raw) if raw else None

    def ping(self) -> bool:
        try:
            return self.client.ping()
        except Exception:
            return False
