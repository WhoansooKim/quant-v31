"""News attribution — per-news relevance scoring + 8-K item parser + price attribution.

Implements the algorithm from research:
  relevance(news, ticker) =
        40 × (ticker ∈ news.tickers)
      + 20 × mention_density (clipped)
      + 15 × source_tier
      + 10 × contains_numbers
      + 10 × fundamentals_focus
      +  5 × recency_decay (half-life 8h)

8-K item classification per Da et al. (Notre Dame):
  1.03 Bankruptcy        → CRITICAL
  2.02 Earnings result   → HIGH (AR ≈ 6.6%)
  2.05 Restructuring     → HIGH
  4.02 Restatement       → CRITICAL
  5.02 Officer change    → MEDIUM-HIGH
  7.01 Reg FD            → MEDIUM
  8.01 Other             → LOW-MEDIUM
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import Any

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)


SOURCE_TIER = {
    "reuters": 1.0,
    "bloomberg": 1.0,
    "wsj": 1.0,
    "ft": 1.0,
    "financial times": 1.0,
    "sec": 1.0,
    "sec edgar": 1.0,
    "edgar": 1.0,
    "businesswire": 0.85,
    "prnewswire": 0.85,
    "marketwatch": 0.8,
    "cnbc": 0.8,
    "barron's": 0.85,
    "barrons": 0.85,
    "finnhub": 0.6,
    "yahoo": 0.6,
    "seeking alpha": 0.55,
    "stocktwits": 0.3,
    "reddit": 0.3,
}

FUNDAMENTAL_KEYWORDS = [
    "earnings", "revenue", "guidance", "forecast", "outlook", "results",
    "merger", "acquisition", "m&a", "buyout", "spinoff", "split",
    "ceo", "cfo", "resign", "appoint", "officer",
    "dividend", "buyback", "repurchase",
    "lawsuit", "settlement", "fine", "penalty",
    "fda", "approval", "trial", "drug",
    "downgrade", "upgrade", "raised", "lowered",
    "8-k", "10-q", "10-k", "filing", "regulatory",
    "restructur", "layoff", "bankrupt", "restat",
]

CRITICAL_8K_ITEMS = {"1.03", "4.02"}
HIGH_8K_ITEMS = {"2.02", "2.05", "5.02"}
MEDIUM_8K_ITEMS = {"7.01", "5.07"}


def parse_8k_item(text: str | None) -> str | None:
    """Extract 8-K item code like '2.02' from text."""
    if not text:
        return None
    m = re.search(r"\bitem\s*([0-9]\.[0-9]{1,2})\b", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"\b8-K\b.*?([0-9]\.[0-9]{1,2})", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def get_8k_salience(item_code: str | None) -> str:
    """Return salience class for 8-K item."""
    if not item_code:
        return "UNKNOWN"
    if item_code in CRITICAL_8K_ITEMS:
        return "CRITICAL"
    if item_code in HIGH_8K_ITEMS:
        return "HIGH"
    if item_code in MEDIUM_8K_ITEMS:
        return "MEDIUM"
    return "LOW"


def compute_relevance(
    headline: str,
    description: str,
    tickers: list[str],
    target_ticker: str,
    source: str,
    published_at: datetime,
    ref_time: datetime,
) -> dict[str, Any]:
    """Compute relevance score 0-100 for one news item × target ticker.

    Returns {relevance, fundamentals_focus, source_tier, mention_density, recency_decay}.
    """
    text = f"{headline or ''} {description or ''}".lower()
    ticker_l = target_ticker.lower()

    # Component 1: ticker in news.tickers list (40)
    in_list = target_ticker.upper() in {t.upper() for t in (tickers or [])}
    score = 40.0 if in_list else 0.0

    # Component 2: mention density (20)
    words = re.findall(r"\b\w+\b", text)
    n_words = max(1, len(words))
    n_mentions = sum(1 for w in words if w == ticker_l)
    density = min(0.05, n_mentions / n_words)
    score += 20.0 * (density / 0.05)  # 0~20

    # Component 3: source tier (15)
    src_lower = (source or "").lower()
    tier = 0.5  # default unknown source
    for k, v in SOURCE_TIER.items():
        if k in src_lower:
            tier = v
            break
    score += 15.0 * tier

    # Component 4: contains numbers (10)
    has_num = bool(re.search(r"\$|\d[\d,]*", text))
    score += 10.0 if has_num else 0.0

    # Component 5: fundamentals focus (10)
    fund_focus = any(kw in text for kw in FUNDAMENTAL_KEYWORDS)
    score += 10.0 if fund_focus else 0.0

    # Component 6: recency decay half-life 8h (5)
    hours_old = max(0, (ref_time - published_at).total_seconds() / 3600)
    decay = 0.5 ** (hours_old / 8)
    score += 5.0 * decay

    return {
        "relevance": round(min(100.0, score), 2),
        "fundamentals_focus": fund_focus,
        "source_tier": tier,
        "mention_density": round(density, 4),
        "recency_decay": round(decay, 3),
    }


def simple_sentiment(text: str) -> float:
    """Naive sentiment: positive/negative word ratio. Range [-1, +1].

    Used as fallback when LLM sentiment not available.
    """
    pos_words = {
        "beat", "exceeded", "raised", "growth", "profit", "surge", "soar", "rally",
        "upgrade", "buy", "strong", "record", "outperform", "boost", "gain",
        "positive", "expand", "win", "approval", "success",
    }
    neg_words = {
        "miss", "missed", "downgrade", "loss", "fall", "drop", "plunge", "crash",
        "decline", "weak", "underperform", "cut", "sell", "negative", "concern",
        "warn", "risk", "lawsuit", "investigation", "bankrupt", "default",
    }
    text_l = (text or "").lower()
    words = re.findall(r"\b\w+\b", text_l)
    if not words:
        return 0.0
    p = sum(1 for w in words if w in pos_words)
    n = sum(1 for w in words if w in neg_words)
    if p + n == 0:
        return 0.0
    return (p - n) / (p + n)


def attribute_news_for_position(pg: PostgresStore, position_id: int) -> dict[str, Any]:
    """For one position, pull news (swing_events) during hold and compute attribution.

    Updates swing_news_attribution + top_news JSONB in swing_trade_postmortem.
    """
    with pg.get_conn() as conn:
        pos = conn.execute(
            """
            SELECT position_id, symbol, entry_time, exit_time, status
            FROM swing_positions WHERE position_id = %s
            """,
            (position_id,),
        ).fetchone()
        if not pos:
            return {"ok": False, "reason": "position not found"}

        # Pull news events for symbol during hold (with -1 day buffer on entry)
        sym = pos["symbol"]
        end_t = pos["exit_time"] or datetime.utcnow()
        start_t = pos["entry_time"] - timedelta(days=1)

        events = conn.execute(
            """
            SELECT event_id, event_type, symbol, severity, title, detail, created_at
            FROM swing_events
            WHERE symbol = %s
              AND created_at >= %s AND created_at <= %s
              AND event_type IN ('news', 'earnings', 'insider_activity', 'sec_filing',
                                 'price_surge', 'price_drop', 'tradingview_alert')
            ORDER BY created_at
            """,
            (sym, start_t, end_t + timedelta(days=1)),
        ).fetchall()

    if not events:
        return {"ok": True, "position_id": position_id, "news_count": 0, "attributed": []}

    # Clear previous attributions for this position (idempotent)
    with pg.get_conn() as conn:
        conn.execute(
            "DELETE FROM swing_news_attribution WHERE position_id = %s",
            (position_id,),
        )
        conn.commit()

    attributed = []
    ref_time = end_t if end_t else datetime.utcnow()

    for e in events:
        title = e.get("title") or ""
        detail = e.get("detail") or {}
        if not isinstance(detail, dict):
            try:
                import json as _json
                detail = _json.loads(detail)
            except Exception:
                detail = {}

        # description-like fields live in detail JSONB
        desc = " ".join(str(v) for v in [
            detail.get("summary", ""),
            detail.get("description", ""),
            detail.get("headline", ""),
        ] if v)

        # source
        source = detail.get("source") or detail.get("publisher")
        url = detail.get("url") or detail.get("source_url") or ""
        if not source:
            if "sec.gov" in url:
                source = "SEC"
            elif "finnhub" in url:
                source = "Finnhub"
            elif e["event_type"] == "sec_filing":
                source = "SEC"
            elif e["event_type"] == "earnings":
                source = "Finnhub"
            elif e["event_type"] == "insider_activity":
                source = "Finnhub"
            else:
                source = e.get("event_type") or "unknown"

        published_at = e["created_at"]
        rel_info = compute_relevance(
            title, desc, [sym], sym, source, published_at, ref_time,
        )
        relevance = rel_info["relevance"]
        if relevance < 50:
            continue

        # 8-K item parse
        item_code = parse_8k_item(f"{title} {desc}") if e["event_type"] == "sec_filing" else None

        # Sentiment (naive — LLM upgrade later in Phase 2E)
        sentiment = simple_sentiment(f"{title} {desc}")

        # Insert attribution row (AR fields left null — populated by event_study integration)
        with pg.get_conn() as conn:
            conn.execute(
                """
                INSERT INTO swing_news_attribution (
                    position_id, event_id, symbol,
                    news_url, news_headline, news_source, news_published_at,
                    relevance, sentiment, fundamentals_focus, sec_8k_item
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    position_id, e["event_id"], sym,
                    url or None, title, source, published_at,
                    relevance, sentiment, rel_info["fundamentals_focus"], item_code,
                ),
            )
            conn.commit()

        attributed.append({
            "event_id": e["event_id"],
            "date": published_at.date().isoformat() if hasattr(published_at, "date") else str(published_at)[:10],
            "headline": title[:120],
            "source": source,
            "relevance": relevance,
            "sentiment": round(sentiment, 3),
            "sec_8k_item": item_code,
            "salience_8k": get_8k_salience(item_code) if item_code else None,
        })

    # Update postmortem with top news + news_count
    top5 = sorted(attributed, key=lambda x: x["relevance"], reverse=True)[:5]

    import json as _json
    with pg.get_conn() as conn:
        conn.execute(
            """
            UPDATE swing_trade_postmortem SET
                news_count = %s,
                top_news = %s::jsonb,
                computed_at = NOW()
            WHERE position_id = %s
            """,
            (len(attributed), _json.dumps(top5), position_id),
        )
        conn.commit()

    return {
        "ok": True,
        "position_id": position_id,
        "news_count": len(attributed),
        "top_news": top5,
    }


def backfill_news_all(pg: PostgresStore) -> dict[str, int]:
    """Run news attribution for all postmortems."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            "SELECT position_id FROM swing_trade_postmortem ORDER BY entry_time"
        ).fetchall()

    ok = 0
    failed = 0
    for r in rows:
        try:
            attribute_news_for_position(pg, r["position_id"])
            ok += 1
        except Exception as e:
            logger.warning(f"News attribution failed for {r['position_id']}: {e}")
            failed += 1

    return {"ok": ok, "failed": failed, "total": len(rows)}
