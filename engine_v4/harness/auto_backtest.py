"""Phase 3D — Automated Backtest Validator.

For each variant in swing_strategy_variants (status=pending), run multi-period
backtests (90/180/365d) and compare to baseline. Promote to 'validated' or
'rejected' based on configurable thresholds.

Pass criteria (configurable via swing_config):
  - SQN delta >= harness_sqn_delta_min (default +0.3)
  - OR Sharpe delta >= harness_sharpe_delta_min (default +0.2)
  - AND total trades >= harness_min_backtest_trades (default 30)
  - AND consistency across 3 periods (no period worse than baseline by 50%)
"""

from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from engine_v4.backtest.runner import BacktestParams, BacktestResult, BacktestRunner
from engine_v4.data.storage import PostgresStore
from engine_v4.harness.knowledge import log_action

logger = logging.getLogger(__name__)


def _make_params(base: dict, diff: dict, start: date, end: date,
                  initial_capital: float = 1000.0) -> BacktestParams:
    """Construct BacktestParams from baseline + diff. Only known fields applied."""
    merged = {**base, **diff}
    p = BacktestParams(start_date=start, end_date=end, initial_capital=initial_capital)
    # Map config keys -> BacktestParams attrs
    field_map = {
        "position_pct": "position_pct",
        "max_positions": "max_positions",
        "take_profit_pct": "take_profit_pct",
        "stop_loss_pct": "stop_loss_pct",
        "return_rank_min": "return_rank_min",
        "volume_ratio_min": "volume_ratio_min",
        "max_daily_entries": "max_daily_entries",
        "price_range_min": "price_range_min",
        "price_range_max": "price_range_max",
    }
    for cfg_key, attr in field_map.items():
        if cfg_key in merged:
            try:
                val = float(merged[cfg_key])
                if attr in ("max_positions", "max_daily_entries"):
                    val = int(val)
                setattr(p, attr, val)
            except (TypeError, ValueError):
                pass
    return p


def _baseline_config(pg: PostgresStore) -> dict:
    keys = ["position_pct", "max_positions", "take_profit_pct", "stop_loss_pct",
            "return_rank_min", "volume_ratio_min", "max_daily_entries",
            "price_range_min", "price_range_max"]
    out = {}
    for k in keys:
        v = pg.get_config_value(k, None)
        if v is not None:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = v
    return out


def _compute_sqn(trades_log: list, capital: float) -> float | None:
    """Tharp SQN from trade log."""
    if not trades_log:
        return None
    # Pull sell-side R-multiples (need entry+exit pair). Simpler: use pnl_pct as proxy.
    pnls = [t.get("pnl_pct", 0) for t in trades_log if t.get("side") == "SELL"]
    pnls = [p for p in pnls if p != 0]
    if len(pnls) < 5:
        return None
    mean = sum(pnls) / len(pnls)
    var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1) if len(pnls) > 1 else 0
    sd = math.sqrt(var) if var > 0 else 0
    if sd == 0:
        return None
    return round((mean / sd) * math.sqrt(len(pnls)), 3)


def _run_period(runner: BacktestRunner, base: dict, diff: dict,
                 start: date, end: date) -> tuple[BacktestResult, float | None]:
    """Run one backtest period and compute SQN."""
    params = _make_params(base, diff, start, end)
    result = runner.run(params)
    sqn = _compute_sqn(result.trades_log, params.initial_capital)
    return result, sqn


def _save_backtest(pg: PostgresStore, result: BacktestResult, params: BacktestParams,
                    label: str) -> int:
    """Save backtest result to swing_backtest_runs. Returns run_id."""
    with pg.get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO swing_backtest_runs
                (start_date, end_date, initial_capital, final_value, total_return,
                 cagr, max_drawdown, sharpe_ratio, win_rate, total_trades,
                 profit_factor, avg_hold_days, params)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING run_id
            """,
            (
                params.start_date, params.end_date, params.initial_capital,
                result.final_value, result.total_return, result.cagr,
                result.max_drawdown, result.sharpe_ratio, result.win_rate,
                result.total_trades, result.profit_factor, result.avg_hold_days,
                json.dumps({**asdict(params), "label": label}, default=str),
            ),
        ).fetchone()
        conn.commit()
    return row["run_id"]


def validate_variant(pg: PostgresStore, variant_id: int) -> dict[str, Any]:
    """Run multi-period backtests for a variant + compare to baseline. Update variant status."""
    t0 = time.time()
    log_action(pg, "variant_backtest", "started", related_variant_id=variant_id)

    # Load variant
    with pg.get_conn() as conn:
        v = conn.execute(
            "SELECT * FROM swing_strategy_variants WHERE variant_id = %s",
            (variant_id,),
        ).fetchone()
    if not v:
        return {"error": "variant_not_found"}

    diff_raw = v.get("config_diff") or {}
    diff = diff_raw if isinstance(diff_raw, dict) else json.loads(diff_raw)
    base = _baseline_config(pg)

    # Mark testing
    with pg.get_conn() as conn:
        conn.execute(
            "UPDATE swing_strategy_variants SET status = 'testing' WHERE variant_id = %s",
            (variant_id,),
        )
        conn.commit()

    # Multi-period
    runner = BacktestRunner(pg)
    today = date.today()
    periods = [
        ("90d", today - timedelta(days=90), today),
        ("180d", today - timedelta(days=180), today),
        ("365d", today - timedelta(days=365), today),
    ]

    baseline_results: dict[str, tuple[BacktestResult, float | None]] = {}
    variant_results: dict[str, tuple[BacktestResult, float | None]] = {}

    run_ids: dict[str, int] = {}

    for label, start, end in periods:
        try:
            br, b_sqn = _run_period(runner, base, {}, start, end)
            vr, v_sqn = _run_period(runner, base, diff, start, end)
            baseline_results[label] = (br, b_sqn)
            variant_results[label] = (vr, v_sqn)
            # Persist variant backtest result
            v_params = _make_params(base, diff, start, end)
            run_ids[label] = _save_backtest(pg, vr, v_params, f"variant_{variant_id}_{label}")
        except Exception as e:
            logger.warning(f"Backtest {label} failed for variant {variant_id}: {e}")

    if not variant_results:
        with pg.get_conn() as conn:
            conn.execute(
                """UPDATE swing_strategy_variants SET status='rejected',
                   rejection_reason='all_backtests_failed' WHERE variant_id = %s""",
                (variant_id,),
            )
            conn.commit()
        return {"variant_id": variant_id, "status": "rejected", "reason": "all_backtests_failed"}

    # Decision based on 90d (primary) + consistency
    primary_label = "90d" if "90d" in variant_results else next(iter(variant_results))
    b_result, b_sqn = baseline_results.get(primary_label, (None, None))
    v_result, v_sqn = variant_results[primary_label]

    sqn_delta = (v_sqn - b_sqn) if (v_sqn is not None and b_sqn is not None) else None
    sharpe_delta = (v_result.sharpe_ratio - b_result.sharpe_ratio) if b_result else None

    sqn_delta_min = float(pg.get_config_value("harness_sqn_delta_min", "0.3"))
    sharpe_delta_min = float(pg.get_config_value("harness_sharpe_delta_min", "0.2"))
    min_trades = int(pg.get_config_value("harness_min_backtest_trades", "30"))

    # Pass criteria
    passes_sqn = sqn_delta is not None and sqn_delta >= sqn_delta_min
    passes_sharpe = sharpe_delta is not None and sharpe_delta >= sharpe_delta_min
    enough_trades = v_result.total_trades >= min_trades

    # Consistency check — variant shouldn't be terrible in any period
    consistent = True
    for label, (vr, vs) in variant_results.items():
        br, bs = baseline_results.get(label, (None, None))
        if br and vr.total_return < br.total_return - 0.5:  # 50% worse
            consistent = False
            break

    new_status = "validated" if (passes_sqn or passes_sharpe) and enough_trades and consistent else "rejected"
    rejection_reason = None
    if new_status == "rejected":
        reasons = []
        if not enough_trades:
            reasons.append(f"trades={v_result.total_trades}<{min_trades}")
        if not (passes_sqn or passes_sharpe):
            reasons.append(f"sqn_delta={sqn_delta}, sharpe_delta={sharpe_delta}")
        if not consistent:
            reasons.append("inconsistent_across_periods")
        rejection_reason = "; ".join(reasons)

    # Update variant
    with pg.get_conn() as conn:
        conn.execute(
            """
            UPDATE swing_strategy_variants SET
                status = %s,
                backtest_90d_run_id = %s,
                backtest_180d_run_id = %s,
                backtest_365d_run_id = %s,
                baseline_sqn = %s, variant_sqn = %s,
                baseline_sharpe = %s, variant_sharpe = %s,
                sqn_delta = %s, sharpe_delta = %s,
                rejection_reason = %s
            WHERE variant_id = %s
            """,
            (
                new_status,
                run_ids.get("90d"), run_ids.get("180d"), run_ids.get("365d"),
                b_sqn, v_sqn,
                b_result.sharpe_ratio if b_result else None, v_result.sharpe_ratio,
                sqn_delta, sharpe_delta,
                rejection_reason,
                variant_id,
            ),
        )
        conn.commit()

    elapsed = time.time() - t0
    summary = {
        "variant_id": variant_id,
        "status": new_status,
        "baseline_sqn": b_sqn,
        "variant_sqn": v_sqn,
        "sqn_delta": sqn_delta,
        "sharpe_delta": sharpe_delta,
        "variant_trades": v_result.total_trades,
        "consistent": consistent,
        "rejection_reason": rejection_reason,
        "elapsed_sec": round(elapsed, 1),
    }
    log_action(pg, "variant_backtest", "completed", details=summary,
               related_variant_id=variant_id, elapsed_sec=elapsed)
    return summary


def validate_all_pending(pg: PostgresStore, max_per_run: int = 5) -> dict[str, Any]:
    """Run backtests for all pending variants. Capped to limit cost."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT variant_id FROM swing_strategy_variants
            WHERE status = 'pending' ORDER BY created_at LIMIT %s
            """,
            (max_per_run,),
        ).fetchall()

    results = []
    for r in rows:
        try:
            results.append(validate_variant(pg, r["variant_id"]))
        except Exception as e:
            logger.warning(f"Validate variant {r['variant_id']} failed: {e}")
            results.append({"variant_id": r["variant_id"], "error": str(e)})

    validated = sum(1 for r in results if r.get("status") == "validated")
    rejected = sum(1 for r in results if r.get("status") == "rejected")
    return {"total": len(results), "validated": validated, "rejected": rejected, "results": results}
