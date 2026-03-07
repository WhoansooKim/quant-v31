"""Event models for real-time event system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    """이벤트 데이터 모델."""
    event_type: str          # price_surge, price_drop, news, earnings, insider, webhook
    symbol: str | None = None
    severity: str = "info"   # info, warning, critical
    title: str = ""
    detail: dict = field(default_factory=dict)
    llm_score: int | None = None
    action_taken: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
