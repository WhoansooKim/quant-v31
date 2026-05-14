"""Period analysis aggregator — KPI / exit layers / holding days / score bins / symbol ranking.

Query swing_positions (closed) joined with swing_signals for composite_score.
Returns a single dict consumed by GET /analysis endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from engine_v4.data.storage import PostgresStore


# Exit-reason → 5-Layer Auto-Sell label mapping.
# Aligns DB free-form strings with documented framework labels.
EXIT_LAYER_MAP = {
    "trailing_stop": "L1_TRAIL",
    "trailing": "L1_TRAIL",
    "atr_trail": "L1_TRAIL",
    "hard_stop": "L2_HARD_STOP",
    "stop_loss": "L2_HARD_STOP",
    "time_stop": "L3_TIME",
    "rsi2_overbought": "L4_RSI",
    "rsi_exit": "L4_RSI",
    "regime_change": "L5_REGIME",
    "regime": "L5_REGIME",
    "take_profit": "TAKE_PROFIT",
    "partial_exit": "PARTIAL",
    "manual": "MANUAL",
}


def _classify_layer(reason: str | None) -> str:
    if not reason:
        return "UNKNOWN"
    return EXIT_LAYER_MAP.get(reason.lower(), reason.upper())


def _hold_bucket(days: int | None) -> str:
    if days is None:
        return "?"
    if days <= 1:
        return "1d"
    if days <= 5:
        return "2-5d"
    if days <= 10:
        return "6-10d"
    if days <= 15:
        return "11-15d"
    return "16d+"


def _score_bin(score: float | None) -> str:
    if score is None:
        return "no_score"
    if score < 50:
        return "<50"
    if score < 60:
        return "50-60"
    if score < 70:
        return "60-70"
    if score < 80:
        return "70-80"
    return "80+"


def analyze_period(
    pg: PostgresStore,
    start: date,
    end: date,
    mode: str = "all",
) -> dict[str, Any]:
    """Period analysis. Returns dict suitable for JSON response.

    mode: "paper" | "live" | "all"
    """
    # End is inclusive — extend to end-of-day
    end_dt = datetime.combine(end, datetime.max.time())
    start_dt = datetime.combine(start, datetime.min.time())

    mode_clause = ""
    params: list[Any] = [start_dt, end_dt]
    if mode == "paper":
        mode_clause = " AND p.is_paper = true"
    elif mode == "live":
        mode_clause = " AND p.is_paper = false"

    with pg.get_conn() as conn:
        # ── Closed positions in range ──
        rows = conn.execute(
            f"""
            SELECT
              p.position_id, p.symbol, p.entry_price, p.exit_price,
              p.realized_pnl, p.realized_pct, p.exit_reason, p.hold_days,
              p.entry_time, p.exit_time, p.signal_id, p.is_paper,
              s.composite_score, s.technical_score, s.sentiment_score,
              s.flow_score, s.quality_score, s.value_score, s.macro_score
            FROM swing_positions p
            LEFT JOIN swing_signals s ON s.signal_id = p.signal_id
            WHERE p.status = 'closed'
              AND p.exit_time >= %s AND p.exit_time <= %s
              {mode_clause}
            ORDER BY p.exit_time DESC
            """,
            params,
        ).fetchall()

    trades = [dict(r) for r in rows]

    return {
        "range": {"from": start.isoformat(), "to": end.isoformat(), "mode": mode},
        "kpi": _compute_kpi(trades),
        "exit_layers": _compute_exit_layers(trades),
        "hold_days": _compute_hold_buckets(trades),
        "score_bins": _compute_score_bins(trades),
        "symbols": _compute_symbol_ranking(trades),
        "trades_sample": trades[:30],
    }


def _f(x) -> float:
    """Decimal/None-safe float."""
    if x is None:
        return 0.0
    return float(x)


def _compute_kpi(trades: list[dict]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "avg_win_pct": 0.0, "avg_loss_pct": 0.0, "expectancy_pct": 0.0,
            "profit_factor": 0.0, "total_pnl": 0.0,
            "avg_hold_days": 0.0, "best_pct": 0.0, "worst_pct": 0.0,
        }

    pnls = [_f(t["realized_pct"]) for t in trades]
    pnl_dollars = [_f(t["realized_pnl"]) for t in trades]
    holds = [int(t["hold_days"]) if t["hold_days"] is not None else 0 for t in trades]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_win = sum(_f(t["realized_pnl"]) for t in trades if _f(t["realized_pct"]) > 0)
    gross_loss = sum(_f(t["realized_pnl"]) for t in trades if _f(t["realized_pct"]) <= 0)
    pf = (gross_win / abs(gross_loss)) if gross_loss < 0 else (float("inf") if gross_win > 0 else 0.0)

    win_rate = len(wins) / n
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "avg_win_pct": round(avg_win * 100, 4),  # 0.05 → 5.00
        "avg_loss_pct": round(avg_loss * 100, 4),
        "expectancy_pct": round(expectancy * 100, 4),
        "profit_factor": round(pf, 3) if pf != float("inf") else None,
        "total_pnl": round(sum(pnl_dollars), 2),
        "avg_hold_days": round(sum(holds) / len(holds), 2) if holds else 0.0,
        "best_pct": round(max(pnls) * 100, 2) if pnls else 0.0,
        "worst_pct": round(min(pnls) * 100, 2) if pnls else 0.0,
    }


def _compute_exit_layers(trades: list[dict]) -> list[dict]:
    by_layer: dict[str, list[dict]] = {}
    for t in trades:
        layer = _classify_layer(t.get("exit_reason"))
        by_layer.setdefault(layer, []).append(t)

    result = []
    for layer, ts in by_layer.items():
        pnls = [_f(t["realized_pct"]) for t in ts]
        wins = sum(1 for p in pnls if p > 0)
        result.append({
            "layer": layer,
            "raw_reason": ts[0].get("exit_reason"),
            "count": len(ts),
            "win_rate": round(wins / len(ts), 4) if ts else 0.0,
            "avg_pnl_pct": round(sum(pnls) / len(pnls) * 100, 4) if pnls else 0.0,
            "total_pnl": round(sum(_f(t["realized_pnl"]) for t in ts), 2),
            "avg_hold_days": round(
                sum(int(t["hold_days"]) for t in ts if t["hold_days"] is not None) / len(ts),
                2,
            ) if ts else 0.0,
        })
    result.sort(key=lambda x: x["count"], reverse=True)
    return result


def _compute_hold_buckets(trades: list[dict]) -> list[dict]:
    by_bucket: dict[str, list[dict]] = {}
    for t in trades:
        bucket = _hold_bucket(t.get("hold_days"))
        by_bucket.setdefault(bucket, []).append(t)

    order = ["1d", "2-5d", "6-10d", "11-15d", "16d+", "?"]
    result = []
    for bucket in order:
        ts = by_bucket.get(bucket, [])
        if not ts:
            continue
        pnls = [_f(t["realized_pct"]) for t in ts]
        wins = sum(1 for p in pnls if p > 0)
        result.append({
            "bucket": bucket,
            "count": len(ts),
            "win_rate": round(wins / len(ts), 4),
            "avg_pnl_pct": round(sum(pnls) / len(pnls) * 100, 4) if pnls else 0.0,
            "total_pnl": round(sum(_f(t["realized_pnl"]) for t in ts), 2),
        })
    return result


def _compute_score_bins(trades: list[dict]) -> list[dict]:
    """Composite score predictive validation: does higher score → higher win rate?"""
    by_bin: dict[str, list[dict]] = {}
    for t in trades:
        bin_name = _score_bin(t.get("composite_score"))
        by_bin.setdefault(bin_name, []).append(t)

    order = ["<50", "50-60", "60-70", "70-80", "80+", "no_score"]
    result = []
    for bin_name in order:
        ts = by_bin.get(bin_name, [])
        if not ts:
            continue
        pnls = [_f(t["realized_pct"]) for t in ts]
        wins = sum(1 for p in pnls if p > 0)
        scores = [_f(t["composite_score"]) for t in ts if t.get("composite_score") is not None]
        result.append({
            "bin": bin_name,
            "count": len(ts),
            "win_rate": round(wins / len(ts), 4),
            "avg_pnl_pct": round(sum(pnls) / len(pnls) * 100, 4) if pnls else 0.0,
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
        })
    return result


def _compute_symbol_ranking(trades: list[dict], top_n: int = 5) -> dict[str, list[dict]]:
    by_symbol: dict[str, list[dict]] = {}
    for t in trades:
        by_symbol.setdefault(t["symbol"], []).append(t)

    rows = []
    for sym, ts in by_symbol.items():
        pnls_pct = [_f(t["realized_pct"]) for t in ts]
        pnl_dollars = sum(_f(t["realized_pnl"]) for t in ts)
        wins = sum(1 for p in pnls_pct if p > 0)
        rows.append({
            "symbol": sym,
            "trades": len(ts),
            "total_pnl": round(pnl_dollars, 2),
            "avg_pnl_pct": round(sum(pnls_pct) / len(pnls_pct) * 100, 4) if pnls_pct else 0.0,
            "win_rate": round(wins / len(ts), 4),
        })

    rows.sort(key=lambda r: r["total_pnl"], reverse=True)
    return {
        "top": rows[:top_n],
        "bottom": rows[-top_n:][::-1] if len(rows) > top_n else [],
    }
