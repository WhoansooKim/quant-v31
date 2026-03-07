"""EventCollector — Finnhub 기반 이벤트 수집.

보유 종목 + 관심 종목에 대해:
- 뉴스 변동 감지 (5분 간격 폴링)
- 실적 발표 근접 알림
- 내부자 대량 거래 감지
- 가격 급등/급락 감지 (yfinance)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from engine_v4.ai.data_feeds import FinnhubClient
from engine_v4.data.storage import PostgresStore
from engine_v4.events.models import Event

logger = logging.getLogger(__name__)


class EventCollector:
    """이벤트 수집기 — Finnhub REST polling 기반."""

    def __init__(self, pg: PostgresStore, finnhub: FinnhubClient):
        self.pg = pg
        self.finnhub = finnhub
        self._seen_news: set[str] = set()  # headline hash → dedup

    def scan_events(self) -> list[Event]:
        """보유 종목에 대한 전체 이벤트 스캔.

        Returns: list of Event objects
        """
        events: list[Event] = []

        positions = self.pg.get_open_positions()
        if not positions:
            return events

        symbols = list(set(p["symbol"] for p in positions))

        # 1) Price check (yfinance)
        price_events = self._check_prices(positions)
        events.extend(price_events)

        if not self.finnhub.is_available:
            return events

        # 2) News scan
        for sym in symbols:
            news_events = self._check_news(sym)
            events.extend(news_events)

        # 3) Earnings proximity
        for sym in symbols:
            earn_event = self._check_earnings(sym)
            if earn_event:
                events.append(earn_event)

        # 4) Insider transactions
        for sym in symbols:
            insider_event = self._check_insider(sym)
            if insider_event:
                events.append(insider_event)

        return events

    def _check_prices(self, positions: list[dict]) -> list[Event]:
        """가격 급등/급락 감지 (현재가 vs 진입가)."""
        import yfinance as yf

        events = []
        symbols = list(set(p["symbol"] for p in positions))

        try:
            data = yf.download(symbols, period="2d", progress=False)
            for pos in positions:
                sym = pos["symbol"]
                try:
                    if len(symbols) == 1:
                        closes = data["Close"].dropna()
                    else:
                        closes = data["Close"][sym].dropna()

                    if len(closes) < 2:
                        continue

                    prev = float(closes.iloc[-2])
                    curr = float(closes.iloc[-1])
                    day_change = (curr - prev) / prev

                    if day_change >= 0.05:
                        events.append(Event(
                            event_type="price_surge",
                            symbol=sym,
                            severity="warning",
                            title=f"{sym} surged {day_change:+.1%} today",
                            detail={"current": curr, "previous": prev,
                                    "change_pct": round(day_change, 4)},
                        ))
                    elif day_change <= -0.05:
                        events.append(Event(
                            event_type="price_drop",
                            symbol=sym,
                            severity="critical",
                            title=f"{sym} dropped {day_change:+.1%} today",
                            detail={"current": curr, "previous": prev,
                                    "change_pct": round(day_change, 4)},
                        ))
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Price check failed: {e}")

        return events

    def _check_news(self, symbol: str) -> list[Event]:
        """새로운 뉴스 감지."""
        events = []
        news = self.finnhub.get_company_news(symbol, days=1)

        for article in news[:5]:
            headline = article.get("headline", "")
            key = f"{symbol}:{headline[:50]}"
            if key in self._seen_news:
                continue
            self._seen_news.add(key)

            events.append(Event(
                event_type="news",
                symbol=symbol,
                severity="info",
                title=headline,
                detail={
                    "source": article.get("source", ""),
                    "summary": article.get("summary", "")[:200],
                    "url": article.get("url", ""),
                    "datetime": article.get("datetime", ""),
                },
            ))

        return events

    def _check_earnings(self, symbol: str) -> Event | None:
        """실적 발표 근접 알림 (7일 이내)."""
        earnings = self.finnhub.get_upcoming_earnings(symbol)
        if not earnings:
            return None

        days_until = earnings.get("days_until")
        if days_until is not None and 0 <= days_until <= 7:
            severity = "critical" if days_until <= 2 else "warning"
            return Event(
                event_type="earnings_upcoming",
                symbol=symbol,
                severity=severity,
                title=f"{symbol} earnings in {days_until} days ({earnings.get('date', '')})",
                detail=earnings,
            )
        return None

    def _check_insider(self, symbol: str) -> Event | None:
        """내부자 대량 거래 감지."""
        insider = self.finnhub.get_insider_transactions(symbol)
        net = insider.get("net_shares", 0)

        if abs(net) >= 50000:
            direction = "buying" if net > 0 else "selling"
            severity = "warning" if net < -50000 else "info"
            return Event(
                event_type="insider_activity",
                symbol=symbol,
                severity=severity,
                title=f"{symbol} insider net {direction}: {abs(net):,} shares",
                detail=insider,
            )
        return None
