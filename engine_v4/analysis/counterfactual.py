"""Counterfactual exit simulation.

For each closed position, replay daily prices to find what each of the 5 exit
layers would have produced if it had been the one to fire. Lets us answer:
"How much profit are we leaving on the table by always exiting via RSI(2)?"

Layers simulated:
  L1_TRAIL    — ATR trailing stop (activated after +1R favorable, multiplier 2.5)
  L2_HARD     — Hard stop at entry - 1.5 × ATR_entry
  L3_TIME     — Time stop at N days (config: time_stop_days)
  TAKE_PROFIT — Fixed +20% (config: take_profit_pct)
  PARTIAL_EXIT — +12% partial 50% out (config: partial_exit_threshold)
  HOLD_TO_END — No exit (peak hold)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)


def _read_config_float(pg: PostgresStore, key: str, default: float) -> float:
    val = pg.get_config_value(key, str(default))
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _get_atr14(pg: PostgresStore, position_id: int, symbol: str, on_date: date) -> float | None:
    """Get ATR(14) — try swing_positions.entry_atr first, else compute from daily_prices."""
    with pg.get_conn() as conn:
        row = conn.execute(
            """
            SELECT entry_atr, atr_14 FROM swing_positions WHERE position_id = %s
            """,
            (position_id,),
        ).fetchone()
        if row and row.get("entry_atr"):
            return float(row["entry_atr"])
        if row and row.get("atr_14"):
            return float(row["atr_14"])

        # Fallback: compute 14-day ATR from daily_prices ending at on_date
        prices = conn.execute(
            """
            SELECT high, low, close, LAG(close) OVER (ORDER BY time) AS prev_close
            FROM daily_prices
            WHERE symbol = %s AND time::date <= %s
            ORDER BY time DESC LIMIT 15
            """,
            (symbol, on_date),
        ).fetchall()
    if len(prices) < 2:
        return None
    trs = []
    for p in prices:
        if p.get("prev_close") is None:
            continue
        h, lo, pc = float(p["high"]), float(p["low"]), float(p["prev_close"])
        tr = max(h - lo, abs(h - pc), abs(lo - pc))
        trs.append(tr)
    if not trs:
        return None
    return sum(trs) / len(trs)


def _get_prices(pg: PostgresStore, symbol: str, start: date, end: date) -> list[dict]:
    """Daily OHLC for symbol between start and end inclusive."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT time::date AS d, open, high, low, close
            FROM daily_prices
            WHERE symbol = %s AND time::date >= %s AND time::date <= %s
            ORDER BY time
            """,
            (symbol, start, end),
        ).fetchall()
    return [dict(r) for r in rows]


def simulate_counterfactuals(pg: PostgresStore, position_id: int) -> dict[str, Any] | None:
    """For one closed position, simulate what each exit layer would have done.

    Returns a dict {layer_name: {exit_date, exit_price, pnl_pct, days_to_exit}}.
    """
    with pg.get_conn() as conn:
        pos = conn.execute(
            """
            SELECT position_id, symbol, side, entry_price, entry_time,
                   exit_price, exit_time, status, stop_loss, qty
            FROM swing_positions WHERE position_id = %s
            """,
            (position_id,),
        ).fetchone()
    if not pos:
        return None
    if pos["status"] != "closed":
        return None

    entry_price = float(pos["entry_price"])
    entry_date = pos["entry_time"].date() if hasattr(pos["entry_time"], "date") else pos["entry_time"]
    exit_date = pos["exit_time"].date() if hasattr(pos["exit_time"], "date") else pos["exit_time"]
    symbol = pos["symbol"]
    side = (pos.get("side") or "BUY").upper()
    is_long = side in ("BUY", "LONG")

    # Config params
    atr_trail_mult = _read_config_float(pg, "atr_trailing_multiplier", 2.5)
    atr_hard_mult = _read_config_float(pg, "atr_hard_stop_multiplier", 1.5)
    atr_activation_r = _read_config_float(pg, "atr_trailing_activation_r", 1.0)
    time_stop_days = int(_read_config_float(pg, "time_stop_days", 15))
    take_profit_pct = _read_config_float(pg, "take_profit_pct", 0.20)
    partial_exit_threshold = _read_config_float(pg, "partial_exit_threshold", 0.12)

    # Pull prices from entry through 30 days after exit (so we can see what would have happened later)
    end_window = exit_date + timedelta(days=30)
    prices = _get_prices(pg, symbol, entry_date, end_window)
    if len(prices) < 1:
        return None

    # ATR at entry
    atr_entry = _get_atr14(pg, position_id, symbol, entry_date)
    if atr_entry is None or atr_entry <= 0:
        # Fallback: 2% of entry price
        atr_entry = entry_price * 0.02

    initial_risk = atr_hard_mult * atr_entry  # 1R = 1.5×ATR

    def _ret(exit_p: float) -> float:
        if is_long:
            return (exit_p - entry_price) / entry_price
        return (entry_price - exit_p) / entry_price

    def _days(d: date) -> int:
        return (d - entry_date).days

    # ── Simulate each layer ──
    results: dict[str, Any] = {}

    # L1 — ATR Trailing (activated after +1R favorable move)
    activated = False
    trail_stop = None  # latest stop
    peak = entry_price if is_long else entry_price
    l1_exit = None
    for p in prices:
        high = float(p["high"])
        low = float(p["low"])
        close = float(p["close"])
        # Update peak
        if is_long:
            if high > peak:
                peak = high
        else:
            if low < peak:
                peak = low

        # Activation check
        if not activated:
            move = (peak - entry_price) if is_long else (entry_price - peak)
            if move >= atr_activation_r * initial_risk:
                activated = True
        if activated:
            # Trail stop
            if is_long:
                trail_stop = peak - atr_trail_mult * atr_entry
                if low <= trail_stop:
                    l1_exit = {"date": p["d"], "price": trail_stop}
                    break
            else:
                trail_stop = peak + atr_trail_mult * atr_entry
                if high >= trail_stop:
                    l1_exit = {"date": p["d"], "price": trail_stop}
                    break

    if l1_exit:
        results["L1_TRAIL"] = {
            "exit_date": l1_exit["date"].isoformat(),
            "exit_price": round(l1_exit["price"], 4),
            "pnl_pct": round(_ret(l1_exit["price"]) * 100, 4),
            "days_to_exit": _days(l1_exit["date"]),
        }
    else:
        results["L1_TRAIL"] = {"exit_date": None, "pnl_pct": None, "days_to_exit": None,
                                "note": "never activated or never hit"}

    # L2 — Hard Stop
    hard_stop = (entry_price - atr_hard_mult * atr_entry) if is_long else (entry_price + atr_hard_mult * atr_entry)
    l2_exit = None
    for p in prices:
        if is_long and float(p["low"]) <= hard_stop:
            l2_exit = {"date": p["d"], "price": hard_stop}
            break
        if not is_long and float(p["high"]) >= hard_stop:
            l2_exit = {"date": p["d"], "price": hard_stop}
            break
    if l2_exit:
        results["L2_HARD_STOP"] = {
            "exit_date": l2_exit["date"].isoformat(),
            "exit_price": round(l2_exit["price"], 4),
            "pnl_pct": round(_ret(l2_exit["price"]) * 100, 4),
            "days_to_exit": _days(l2_exit["date"]),
        }
    else:
        results["L2_HARD_STOP"] = {"exit_date": None, "pnl_pct": None, "days_to_exit": None,
                                    "note": "never hit"}

    # L3 — Time Stop
    if len(prices) > time_stop_days:
        ts = prices[time_stop_days]
        results["L3_TIME"] = {
            "exit_date": ts["d"].isoformat(),
            "exit_price": round(float(ts["close"]), 4),
            "pnl_pct": round(_ret(float(ts["close"])) * 100, 4),
            "days_to_exit": time_stop_days,
        }
    else:
        last = prices[-1]
        results["L3_TIME"] = {
            "exit_date": last["d"].isoformat(),
            "exit_price": round(float(last["close"]), 4),
            "pnl_pct": round(_ret(float(last["close"])) * 100, 4),
            "days_to_exit": _days(last["d"]),
            "note": "data ended before time stop",
        }

    # Take Profit @ +20%
    tp_price = entry_price * (1 + take_profit_pct) if is_long else entry_price * (1 - take_profit_pct)
    tp_exit = None
    for p in prices:
        if is_long and float(p["high"]) >= tp_price:
            tp_exit = {"date": p["d"], "price": tp_price}
            break
        if not is_long and float(p["low"]) <= tp_price:
            tp_exit = {"date": p["d"], "price": tp_price}
            break
    if tp_exit:
        results["TAKE_PROFIT"] = {
            "exit_date": tp_exit["date"].isoformat(),
            "exit_price": round(tp_exit["price"], 4),
            "pnl_pct": round(_ret(tp_exit["price"]) * 100, 4),
            "days_to_exit": _days(tp_exit["date"]),
        }
    else:
        results["TAKE_PROFIT"] = {"exit_date": None, "pnl_pct": None, "days_to_exit": None,
                                   "note": "never reached"}

    # HOLD_TO_END — peak unrealized capture
    if prices:
        if is_long:
            best = max(prices, key=lambda r: float(r["high"]))
            best_price = float(best["high"])
        else:
            best = min(prices, key=lambda r: float(r["low"]))
            best_price = float(best["low"])
        last = prices[-1]
        results["HOLD_PEAK"] = {
            "exit_date": best["d"].isoformat(),
            "exit_price": round(best_price, 4),
            "pnl_pct": round(_ret(best_price) * 100, 4),
            "days_to_exit": _days(best["d"]),
        }
        results["HOLD_TO_END"] = {
            "exit_date": last["d"].isoformat(),
            "exit_price": round(float(last["close"]), 4),
            "pnl_pct": round(_ret(float(last["close"])) * 100, 4),
            "days_to_exit": _days(last["d"]),
        }

    return {
        "position_id": position_id,
        "symbol": symbol,
        "entry_date": entry_date.isoformat(),
        "exit_date": exit_date.isoformat(),
        "entry_price": round(entry_price, 4),
        "actual_exit_price": float(pos["exit_price"]) if pos["exit_price"] else None,
        "actual_pnl_pct": round(_ret(float(pos["exit_price"])) * 100, 4) if pos["exit_price"] else None,
        "atr_entry": round(atr_entry, 4),
        "initial_risk": round(initial_risk, 4),
        "layers": results,
    }


def update_postmortem_with_counterfactuals(pg: PostgresStore, cf: dict) -> None:
    """Patch swing_trade_postmortem with counterfactual_exits JSON."""
    import json as _json
    with pg.get_conn() as conn:
        conn.execute(
            """
            UPDATE swing_trade_postmortem SET
                counterfactual_exits = %s::jsonb,
                computed_at = NOW()
            WHERE position_id = %s
            """,
            (_json.dumps(cf["layers"], default=str), cf["position_id"]),
        )
        conn.commit()


def backfill_counterfactuals_all(pg: PostgresStore) -> dict[str, int]:
    """Run counterfactual sim for all closed positions."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.position_id FROM swing_trade_postmortem p
            JOIN swing_positions pp ON pp.position_id = p.position_id
            WHERE pp.status = 'closed' ORDER BY pp.entry_time
            """
        ).fetchall()

    ok = 0
    failed = 0
    skipped = 0
    for r in rows:
        try:
            cf = simulate_counterfactuals(pg, r["position_id"])
            if cf is None:
                skipped += 1
                continue
            update_postmortem_with_counterfactuals(pg, cf)
            ok += 1
        except Exception as e:
            logger.warning(f"Counterfactual failed for {r['position_id']}: {e}")
            failed += 1

    return {"ok": ok, "skipped": skipped, "failed": failed, "total": len(rows)}


def aggregate_counterfactuals(pg: PostgresStore) -> dict[str, Any]:
    """Aggregate counterfactual results across all closed trades.

    For each layer: avg pnl_pct, avg days_to_exit, fire rate, comparison vs actual.
    This is the key insight: 'if you had held to take profit, you would have made X% on avg'.
    """
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT position_id, realized_pct, counterfactual_exits
            FROM swing_trade_postmortem
            WHERE counterfactual_exits IS NOT NULL
              AND exit_time IS NOT NULL
            """
        ).fetchall()

    rows = [dict(r) for r in rows]
    if not rows:
        return {"n": 0}

    layer_stats: dict[str, list[dict]] = {}
    for r in rows:
        cf = r["counterfactual_exits"]
        if not isinstance(cf, dict):
            continue
        actual = float(r["realized_pct"] or 0) * 100  # → %
        for layer, info in cf.items():
            if info.get("pnl_pct") is None:
                continue
            layer_stats.setdefault(layer, []).append({
                "pnl_pct": info["pnl_pct"],
                "days": info.get("days_to_exit") or 0,
                "actual": actual,
                "delta": info["pnl_pct"] - actual,
            })

    summary = []
    for layer, items in layer_stats.items():
        n = len(items)
        avg_pnl = sum(i["pnl_pct"] for i in items) / n
        avg_delta = sum(i["delta"] for i in items) / n  # avg improvement vs actual
        avg_days = sum(i["days"] for i in items) / n
        wins = sum(1 for i in items if i["pnl_pct"] > 0)
        summary.append({
            "layer": layer,
            "fire_rate": round(n / len(rows), 4),  # what fraction of trades would have fired
            "fired_count": n,
            "avg_pnl_pct": round(avg_pnl, 4),
            "avg_delta_pct": round(avg_delta, 4),  # vs actual realized
            "avg_days": round(avg_days, 2),
            "win_rate": round(wins / n, 4),
        })
    summary.sort(key=lambda s: s["avg_pnl_pct"], reverse=True)

    return {"n": len(rows), "layers": summary}


def get_calibration_data(pg: PostgresStore) -> list[dict]:
    """For calibration plot: bin composite_score → realized win rate.

    Returns 10 bins (0-10, 10-20, ..., 90-100) with actual hit rate.
    """
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.composite_score, p.realized_pct
            FROM swing_trade_postmortem p
            JOIN swing_positions pp ON pp.position_id = p.position_id
            JOIN swing_signals s ON s.signal_id = pp.signal_id
            WHERE p.realized_pct IS NOT NULL AND s.composite_score IS NOT NULL
            """
        ).fetchall()
    rows = [dict(r) for r in rows]
    if not rows:
        return []

    bins = [(i * 10, (i + 1) * 10) for i in range(10)]
    out = []
    for lo, hi in bins:
        items = [r for r in rows if lo <= float(r["composite_score"]) < hi]
        if not items:
            out.append({"bin": f"{lo}-{hi}", "n": 0, "win_rate": None, "avg_pnl_pct": None})
            continue
        wins = sum(1 for r in items if float(r["realized_pct"]) > 0)
        n = len(items)
        avg_pnl = sum(float(r["realized_pct"]) for r in items) / n
        out.append({
            "bin": f"{lo}-{hi}",
            "n": n,
            "win_rate": round(wins / n, 4),
            "avg_pnl_pct": round(avg_pnl * 100, 4),
            "expected_rate": round((lo + hi) / 200, 4),  # midpoint as predicted win rate
        })
    return out
