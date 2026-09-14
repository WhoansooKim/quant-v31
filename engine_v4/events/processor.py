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
        """이벤트 배치 처리. 최근에 본 것과 같은 이벤트는 건너뛴다.

        2026-09-14 (§22.AO-29): 이벤트 스캔을 스케줄 잡으로 돌리기 시작하면서 필요해졌다.
        수동 실행일 때는 드러나지 않았지만, EDGAR 는 매 실행마다 같은 RSS 창을 읽으므로
        **돌릴 때마다 같은 공시가 재삽입**된다(실측: 2회 실행에 C 종목 6건 → 12건).
        여기서 걸러내면 DB 중복·텔레그램 재알림·SSE 재방송이 한꺼번에 막힌다 —
        `results` 에 넣지 않는 것만으로 세 경로가 모두 정리된다.
        """
        window = int(self.pg.get_config_value("event_dedup_days", "7"))
        results, skipped = [], 0
        for event in events:
            try:
                if window > 0 and self._recent_duplicate_id(event, window) is not None:
                    skipped += 1
                    continue
                results.append(self.process(event))
            except Exception as e:
                logger.error(f"Event processing failed: {e}")
        if skipped:
            logger.info(f"Event dedup: {skipped} duplicates skipped (window {window}d)")
        return results

    def _recent_duplicate_id(self, event: Event, within_days: int) -> int | None:
        """같은 (유형·종목·제목) 이벤트가 최근 within_days 안에 있으면 그 event_id."""
        with self.pg.get_conn() as conn:
            row = conn.execute("""
                SELECT event_id FROM swing_events
                WHERE event_type = %s AND symbol = %s AND title = %s
                  AND created_at > now() - make_interval(days => %s)
                ORDER BY event_id DESC LIMIT 1
            """, (event.event_type, event.symbol, event.title, within_days)).fetchone()
        return row["event_id"] if row else None

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
