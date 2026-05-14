"""Sweeney (1997) Maximum Favorable / Adverse Excursion + R-multiple computation.

For each closed (or open) swing_position, replay daily_prices over the holding
window and record:
  - mfe_pct  = max favorable excursion (long: (max_high - entry) / entry)
  - mae_pct  = max adverse excursion (long: (min_low - entry) / entry)
  - capture_ratio = realized_pct / mfe_pct          [Sweeney 1997]
  - exit_difficulty = (mfe_pct - realized_pct) / mfe_pct
  - r_multiple = realized_pnl / (entry - stop_loss) / qty  [Tharp]

Capture ratio < 0.40 → "noise-driven exit" (early). > 0.70 → excellent discipline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)


def compute_mfe_mae(pg: PostgresStore, position_id: int) -> dict[str, Any] | None:
    """Compute MFE/MAE for a single position. Returns None if data insufficient."""
    with pg.get_conn() as conn:
        pos = conn.execute(
            """
            SELECT position_id, symbol, side, qty, entry_price, entry_time,
                   exit_price, exit_time, status, stop_loss,
                   realized_pnl, realized_pct, hold_days, exit_reason
            FROM swing_positions WHERE position_id = %s
            """,
            (position_id,),
        ).fetchone()

        if not pos:
            return None

        is_open = pos["status"] == "open"
        end_time = pos["exit_time"] if not is_open else datetime.utcnow()

        prices = conn.execute(
            """
            SELECT time, high, low, close
            FROM daily_prices
            WHERE symbol = %s
              AND time >= %s::date
              AND time <= %s::date
            ORDER BY time
            """,
            (pos["symbol"], pos["entry_time"], end_time + timedelta(days=1)),
        ).fetchall()

    if len(prices) < 1:
        logger.warning(f"No prices for position {position_id} ({pos['symbol']})")
        return None

    entry = float(pos["entry_price"])
    qty = float(pos["qty"])
    side = pos.get("side", "BUY") or "BUY"
    is_long = side.upper() in ("BUY", "LONG")

    # MFE/MAE traversal
    if is_long:
        mfe_row = max(prices, key=lambda r: float(r["high"]))
        mae_row = min(prices, key=lambda r: float(r["low"]))
        mfe_price = float(mfe_row["high"])
        mae_price = float(mae_row["low"])
    else:  # short — invert
        mfe_row = min(prices, key=lambda r: float(r["low"]))
        mae_row = max(prices, key=lambda r: float(r["high"]))
        mfe_price = float(mfe_row["low"])
        mae_price = float(mae_row["high"])

    # MFE = best unrealized gain during hold (always positive when good)
    # MAE = worst unrealized drawdown (always negative or zero)
    if is_long:
        mfe_pct = (mfe_price - entry) / entry
        mae_pct = (mae_price - entry) / entry
    else:
        mfe_pct = (entry - mfe_price) / entry
        mae_pct = (entry - mae_price) / entry

    realized_pct = float(pos["realized_pct"]) if pos["realized_pct"] is not None else 0.0
    realized_pnl = float(pos["realized_pnl"]) if pos["realized_pnl"] is not None else 0.0

    # Capture ratio — only meaningful when mfe > 0 (the trade had favorable movement)
    capture_ratio = (realized_pct / mfe_pct) if mfe_pct > 0.001 else None
    exit_difficulty = ((mfe_pct - realized_pct) / mfe_pct) if mfe_pct > 0.001 else None

    # R-multiple (Tharp) — only when stop_loss is recorded
    initial_risk_per_share = None
    r_multiple = None
    if pos["stop_loss"] is not None:
        sl = float(pos["stop_loss"])
        if is_long:
            initial_risk_per_share = entry - sl
        else:
            initial_risk_per_share = sl - entry
        if initial_risk_per_share > 0:
            r_multiple = realized_pnl / (initial_risk_per_share * qty)

    return {
        "position_id": position_id,
        "symbol": pos["symbol"],
        "is_open": is_open,
        "entry_time": pos["entry_time"],
        "exit_time": pos["exit_time"],
        "entry_price": entry,
        "exit_price": float(pos["exit_price"]) if pos["exit_price"] else None,
        "qty": qty,
        "realized_pct": realized_pct,
        "realized_pnl": realized_pnl,
        "hold_days": pos["hold_days"],
        "mfe_pct": round(mfe_pct, 6),
        "mfe_date": mfe_row["time"].date() if hasattr(mfe_row["time"], "date") else mfe_row["time"],
        "mae_pct": round(mae_pct, 6),
        "mae_date": mae_row["time"].date() if hasattr(mae_row["time"], "date") else mae_row["time"],
        "capture_ratio": round(capture_ratio, 4) if capture_ratio is not None else None,
        "exit_difficulty": round(exit_difficulty, 4) if exit_difficulty is not None else None,
        "initial_risk": round(initial_risk_per_share, 4) if initial_risk_per_share else None,
        "r_multiple": round(r_multiple, 3) if r_multiple is not None else None,
        "exit_reason": pos["exit_reason"],
    }


def upsert_postmortem(pg: PostgresStore, mfe: dict) -> None:
    """Insert or update swing_trade_postmortem with MFE/MAE fields.

    Doesn't touch event_study/news fields — those stay null until Phase 2B runs.
    """
    from engine_v4.analysis.period_summary import _classify_layer

    exit_layer = _classify_layer(mfe.get("exit_reason"))

    with pg.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO swing_trade_postmortem (
                position_id, symbol, entry_time, exit_time, entry_price, exit_price, qty,
                realized_pct, realized_pnl, hold_days,
                mfe_pct, mfe_date, mae_pct, mae_date,
                capture_ratio, exit_difficulty,
                initial_risk, r_multiple,
                exit_layer, exit_reason,
                is_open, computed_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                %s, NOW()
            )
            ON CONFLICT (position_id) DO UPDATE SET
                exit_time = EXCLUDED.exit_time,
                exit_price = EXCLUDED.exit_price,
                realized_pct = EXCLUDED.realized_pct,
                realized_pnl = EXCLUDED.realized_pnl,
                hold_days = EXCLUDED.hold_days,
                mfe_pct = EXCLUDED.mfe_pct,
                mfe_date = EXCLUDED.mfe_date,
                mae_pct = EXCLUDED.mae_pct,
                mae_date = EXCLUDED.mae_date,
                capture_ratio = EXCLUDED.capture_ratio,
                exit_difficulty = EXCLUDED.exit_difficulty,
                initial_risk = EXCLUDED.initial_risk,
                r_multiple = EXCLUDED.r_multiple,
                exit_layer = EXCLUDED.exit_layer,
                exit_reason = EXCLUDED.exit_reason,
                is_open = EXCLUDED.is_open,
                computed_at = NOW()
            """,
            (
                mfe["position_id"], mfe["symbol"], mfe["entry_time"], mfe["exit_time"],
                mfe["entry_price"], mfe["exit_price"], mfe["qty"],
                mfe["realized_pct"], mfe["realized_pnl"], mfe["hold_days"],
                mfe["mfe_pct"], mfe["mfe_date"], mfe["mae_pct"], mfe["mae_date"],
                mfe["capture_ratio"], mfe["exit_difficulty"],
                mfe["initial_risk"], mfe["r_multiple"],
                exit_layer, mfe["exit_reason"],
                mfe["is_open"],
            ),
        )
        conn.commit()


def backfill_all(pg: PostgresStore, include_open: bool = True) -> dict[str, int]:
    """Compute MFE/MAE for all positions (closed + optionally open). Idempotent.

    Returns counts.
    """
    with pg.get_conn() as conn:
        if include_open:
            rows = conn.execute(
                "SELECT position_id FROM swing_positions ORDER BY entry_time"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT position_id FROM swing_positions WHERE status='closed' ORDER BY entry_time"
            ).fetchall()

    ok = 0
    skipped = 0
    failed = 0
    for r in rows:
        try:
            mfe = compute_mfe_mae(pg, r["position_id"])
            if mfe is None:
                skipped += 1
                continue
            upsert_postmortem(pg, mfe)
            ok += 1
        except Exception as e:
            logger.warning(f"MFE backfill failed for position {r['position_id']}: {e}")
            failed += 1

    return {"ok": ok, "skipped": skipped, "failed": failed, "total": len(rows)}


def get_postmortems(pg: PostgresStore, limit: int = 100, only_closed: bool = True) -> list[dict]:
    """Read post-mortem rows for dashboard."""
    where = "WHERE NOT is_open" if only_closed else ""
    with pg.get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM swing_trade_postmortem
            {where}
            ORDER BY exit_time DESC NULLS LAST, computed_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
