"""Knowledge base — CRUD for swing_knowledge.

Stores external research (papers, blogs, forums, seed data) + LLM extractions.
Consumed by variant_generator and regime_switcher for strategy synthesis.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)


def add_knowledge(
    pg: PostgresStore,
    source_type: str,
    title: str,
    source_url: str | None = None,
    source_name: str | None = None,
    summary: str | None = None,
    key_insights: list | None = None,
    strategy_hypothesis: dict | None = None,
    applicability_score: int = 50,
    regime_relevance: str = "ALL",
    tags: list[str] | None = None,
    source_tier: float = 0.5,
    published_at: datetime | None = None,
) -> int:
    """Insert a knowledge row. Returns knowledge_id."""
    with pg.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO swing_knowledge (
                source_type, source_url, source_name, title, summary,
                key_insights, strategy_hypothesis, applicability_score,
                regime_relevance, tags, source_tier, published_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
            RETURNING knowledge_id
            """,
            (
                source_type, source_url, source_name, title, summary,
                json.dumps(key_insights or []),
                json.dumps(strategy_hypothesis or {}),
                applicability_score, regime_relevance,
                tags or [], source_tier, published_at,
            ),
        ).fetchone()
        conn.commit()
    return row["knowledge_id"] if row else 0


def list_knowledge(
    pg: PostgresStore,
    source_type: str | None = None,
    regime: str | None = None,
    min_applicability: int = 0,
    limit: int = 50,
) -> list[dict]:
    """List knowledge entries with filters."""
    where_parts = ["1=1"]
    params: list[Any] = []
    if source_type:
        where_parts.append("source_type = %s")
        params.append(source_type)
    if regime:
        where_parts.append("(regime_relevance = %s OR regime_relevance = 'ALL')")
        params.append(regime)
    if min_applicability > 0:
        where_parts.append("applicability_score >= %s")
        params.append(min_applicability)
    params.append(limit)

    with pg.get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT knowledge_id, source_type, source_url, source_name, title,
                   summary, key_insights, strategy_hypothesis, applicability_score,
                   regime_relevance, tags, source_tier, published_at, collected_at,
                   tested, backtest_run_id
            FROM swing_knowledge
            WHERE {' AND '.join(where_parts)}
            ORDER BY applicability_score DESC, collected_at DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def search_knowledge(pg: PostgresStore, query: str, limit: int = 20) -> list[dict]:
    """Simple text search across title + summary + insights."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT knowledge_id, source_type, source_name, title, summary,
                   applicability_score, regime_relevance, tags
            FROM swing_knowledge
            WHERE title ILIKE %s OR summary ILIKE %s OR key_insights::text ILIKE %s
            ORDER BY applicability_score DESC LIMIT %s
            """,
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_knowledge(pg: PostgresStore, knowledge_id: int) -> dict | None:
    with pg.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM swing_knowledge WHERE knowledge_id = %s", (knowledge_id,)
        ).fetchone()
    return dict(row) if row else None


def mark_tested(pg: PostgresStore, knowledge_id: int, backtest_run_id: int) -> None:
    with pg.get_conn() as conn:
        conn.execute(
            """
            UPDATE swing_knowledge SET tested = TRUE, backtest_run_id = %s
            WHERE knowledge_id = %s
            """,
            (backtest_run_id, knowledge_id),
        )
        conn.commit()


def log_action(
    pg: PostgresStore,
    action: str,
    status: str,
    details: dict | None = None,
    related_knowledge_id: int | None = None,
    related_variant_id: int | None = None,
    error_msg: str | None = None,
    elapsed_sec: float | None = None,
) -> None:
    """Audit log for any harness action."""
    with pg.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO swing_harness_log
            (action, status, details, related_knowledge_id, related_variant_id, error_msg, elapsed_sec)
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                action, status, json.dumps(details or {}),
                related_knowledge_id, related_variant_id, error_msg, elapsed_sec,
            ),
        )
        conn.commit()
