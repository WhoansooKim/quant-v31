"""EventProcessor — 이벤트 처리 + DB 저장 + 알림."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from engine_v4.data.storage import PostgresStore
from engine_v4.events.models import Event

logger = logging.getLogger(__name__)


class EventProcessor:
    """이벤트 처리기 — 규칙 엔진 + DB 저장."""

    def __init__(self, pg: PostgresStore):
        self.pg = pg
        self._subscribers: list = []  # SSE subscribers

    def process(self, event: Event) -> dict:
        """이벤트 처리: DB 저장 + 액션 결정."""
        # DB 저장
        event_id = self._save_event(event)

        # 액션 결정
        action = self._decide_action(event)
        if action:
            event.action_taken = action
            self._update_action(event_id, action)

        # SSE 브로드캐스트
        self._broadcast(event, event_id)

        return {
            "event_id": event_id,
            "type": event.event_type,
            "symbol": event.symbol,
            "severity": event.severity,
            "action": action,
        }

    def process_batch(self, events: list[Event]) -> list[dict]:
        """이벤트 배치 처리."""
        results = []
        for event in events:
            try:
                result = self.process(event)
                results.append(result)
            except Exception as e:
                logger.error(f"Event processing failed: {e}")
        return results

    def _decide_action(self, event: Event) -> str | None:
        """규칙 기반 액션 결정."""
        match event.event_type:
            case "price_surge":
                if event.severity == "warning":
                    return "alert_sent"
            case "price_drop":
                if event.severity == "critical":
                    return "exit_review"
            case "earnings_upcoming":
                days = event.detail.get("days_until", 99)
                if days <= 2:
                    return "exit_review"
                return "alert_sent"
            case "insider_activity":
                net = event.detail.get("net_shares", 0)
                if net < -100000:
                    return "exit_review"
                return "alert_sent"
            case "news":
                return "alert_sent"
            case "tradingview_alert":
                return "signal_review"
        return None

    def _save_event(self, event: Event) -> int:
        """이벤트 DB 저장."""
        with self.pg.get_conn() as conn:
            row = conn.execute("""
                INSERT INTO swing_events
                    (event_type, symbol, severity, title, detail,
                     llm_score, action_taken)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING event_id
            """, (event.event_type, event.symbol, event.severity,
                  event.title, json.dumps(event.detail, default=str),
                  event.llm_score, event.action_taken)).fetchone()
            conn.commit()
        return row["event_id"]

    def _update_action(self, event_id: int, action: str) -> None:
        with self.pg.get_conn() as conn:
            conn.execute("""
                UPDATE swing_events SET action_taken = %s
                WHERE event_id = %s
            """, (action, event_id))
            conn.commit()

    def _broadcast(self, event: Event, event_id: int) -> None:
        """SSE 구독자에게 브로드캐스트 (future use)."""
        # TODO: asyncio Queue로 SSE 구독자에게 push
        pass

    def get_events(self, limit: int = 50,
                   event_type: str | None = None,
                   symbol: str | None = None,
                   severity: str | None = None) -> list[dict]:
        """이벤트 목록 조회."""
        conditions = []
        params = []

        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type)
        if symbol:
            conditions.append("symbol = %s")
            params.append(symbol)
        if severity:
            conditions.append("severity = %s")
            params.append(severity)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        with self.pg.get_conn() as conn:
            rows = conn.execute(f"""
                SELECT event_id, event_type, symbol, severity, title,
                       detail, llm_score, action_taken, created_at
                FROM swing_events
                {where}
                ORDER BY created_at DESC LIMIT %s
            """, tuple(params)).fetchall()

        return [dict(r) for r in rows]
