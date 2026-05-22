"""Phase 3E — Safe Variant Auto-Deployment + Rollback Monitor.

Workflow:
  1. Find validated variants (status='validated', not yet deployed)
  2. Apply config_diff to swing_config (paper mode only)
  3. Mark variant as 'deployed', record deployed_at
  4. Monitor next N trades — if rollback conditions met, revert + status='rolled_back'

Rollback conditions:
  - N consecutive losses (config: harness_rollback_consecutive_losses, default 5)
  - SQN drop >= threshold (config: harness_rollback_sqn_drop, default 0.5)

Safety:
  - NEVER auto-deploys in live mode (requires manual approval)
  - Only ONE variant active at a time (newer overrides older)
  - Full audit trail in swing_harness_log
  - Telegram notification on every deploy + rollback
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from datetime import datetime
from typing import Any

from engine_v4.data.storage import PostgresStore
from engine_v4.harness.knowledge import log_action
from engine_v4.notify.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


def _current_deployed_variant(pg: PostgresStore) -> dict | None:
    with pg.get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM swing_strategy_variants
            WHERE status = 'deployed' AND rollback_at IS NULL
            ORDER BY deployed_at DESC LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def _snapshot_baseline(pg: PostgresStore, keys: list[str]) -> dict[str, str]:
    """Record current values of keys before applying variant — used for rollback."""
    out = {}
    for k in keys:
        v = pg.get_config_value(k, None)
        if v is not None:
            out[k] = v
    return out


def _apply_diff(pg: PostgresStore, diff: dict) -> None:
    """Apply config_diff to swing_config."""
    with pg.get_conn() as conn:
        for k, v in diff.items():
            conn.execute(
                """
                INSERT INTO swing_config (key, value, category, updated_at)
                VALUES (%s, %s, 'variant', NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (k, str(v)),
            )
        conn.commit()


def _notify_deploy(notifier: TelegramNotifier, variant: dict, baseline_snapshot: dict) -> None:
    diff = variant.get("config_diff") or {}
    if not isinstance(diff, dict):
        try:
            diff = json.loads(diff)
        except Exception:
            diff = {}
    lines = [
        f"🚀 *Variant Deployed (paper)*",
        "",
        f"#{variant['variant_id']} {variant['name']}",
        f"{(variant.get('description') or '')[:200]}",
        "",
        "*Backtest results*",
        f"  Variant SQN: {variant.get('variant_sqn')}",
        f"  vs Baseline: {variant.get('baseline_sqn')}",
        f"  SQN Δ: {variant.get('sqn_delta'):+.3f}" if variant.get("sqn_delta") else "  SQN Δ: —",
        f"  Sharpe Δ: {variant.get('sharpe_delta'):+.3f}" if variant.get("sharpe_delta") else "  Sharpe Δ: —",
        "",
        "*Config changes applied*",
    ]
    for k, v in diff.items():
        base = baseline_snapshot.get(k, "?")
        lines.append(f"  {k}: {base} → {v}")
    lines.append("")
    lines.append("Auto-rollback if 5 consecutive losses or SQN drops 0.5")
    try:
        asyncio.run(notifier.send("\n".join(lines)))
    except Exception as e:
        logger.warning(f"Deploy notify failed: {e}")


def _notify_rollback(notifier: TelegramNotifier, variant: dict, reason: str) -> None:
    lines = [
        f"⏪ *Variant Rolled Back*",
        "",
        f"#{variant['variant_id']} {variant['name']}",
        "",
        f"Reason: {reason}",
        f"Trades under variant: {variant.get('trades_under_variant', 0)}",
        "",
        "Baseline config restored.",
    ]
    try:
        asyncio.run(notifier.send("\n".join(lines)))
    except Exception as e:
        logger.warning(f"Rollback notify failed: {e}")


def deploy_validated_variant(
    pg: PostgresStore, notifier: TelegramNotifier | None = None,
    force_variant_id: int | None = None,
) -> dict[str, Any]:
    """Deploy the highest-priority validated variant.

    Selection: highest sqn_delta among validated + not deployed.
    Or force_variant_id for explicit deploy.

    Safety: skips if any variant currently deployed (one-at-a-time policy).
    """
    enabled = pg.get_config_value("harness_auto_deploy_enabled", "false")
    if enabled.lower() not in ("true", "1", "yes"):
        return {"deployed": False, "reason": "harness_auto_deploy_enabled=false"}

    mode = pg.get_config_value("trading_mode", "paper")
    if mode == "live":
        log_action(pg, "auto_deploy", "skipped", details={"reason": "live_requires_manual"})
        return {"deployed": False, "reason": "live_requires_manual"}

    existing = _current_deployed_variant(pg)
    if existing and not force_variant_id:
        return {"deployed": False, "reason": "another_variant_deployed",
                "existing_variant_id": existing["variant_id"]}

    # Pick candidate
    with pg.get_conn() as conn:
        if force_variant_id:
            cand = conn.execute(
                "SELECT * FROM swing_strategy_variants WHERE variant_id = %s",
                (force_variant_id,),
            ).fetchone()
        else:
            cand = conn.execute(
                """
                SELECT * FROM swing_strategy_variants
                WHERE status = 'validated' AND deployed_at IS NULL
                ORDER BY sqn_delta DESC NULLS LAST, sharpe_delta DESC NULLS LAST
                LIMIT 1
                """
            ).fetchone()
    if not cand:
        return {"deployed": False, "reason": "no_validated_candidate"}

    variant = dict(cand)
    diff_raw = variant.get("config_diff") or {}
    diff = diff_raw if isinstance(diff_raw, dict) else json.loads(diff_raw)
    if not diff:
        return {"deployed": False, "reason": "empty_config_diff"}

    # Snapshot baseline for rollback
    baseline_snapshot = _snapshot_baseline(pg, list(diff.keys()))

    # Apply diff
    _apply_diff(pg, diff)

    # Mark deployed
    with pg.get_conn() as conn:
        conn.execute(
            """
            UPDATE swing_strategy_variants
            SET status = 'deployed', deployed_at = NOW(), trades_under_variant = 0
            WHERE variant_id = %s
            """,
            (variant["variant_id"],),
        )
        # Store baseline snapshot for rollback (in details of harness_log)
        conn.execute(
            """
            INSERT INTO swing_harness_log
            (action, status, details, related_variant_id)
            VALUES ('auto_deploy_baseline', 'completed', %s::jsonb, %s)
            """,
            (json.dumps({"baseline_snapshot": baseline_snapshot, "diff_applied": diff}),
             variant["variant_id"]),
        )
        conn.commit()

    log_action(pg, "auto_deploy", "completed", details={
        "variant_id": variant["variant_id"],
        "diff": diff,
        "baseline_snapshot": baseline_snapshot,
    }, related_variant_id=variant["variant_id"])

    logger.info(f"Variant {variant['variant_id']} deployed: {diff}")
    if notifier:
        _notify_deploy(notifier, variant, baseline_snapshot)

    return {
        "deployed": True,
        "variant_id": variant["variant_id"],
        "name": variant["name"],
        "diff_applied": diff,
        "baseline_snapshot": baseline_snapshot,
    }


def _get_baseline_snapshot(pg: PostgresStore, variant_id: int) -> dict | None:
    """Recover the baseline snapshot from harness log."""
    with pg.get_conn() as conn:
        row = conn.execute(
            """
            SELECT details FROM swing_harness_log
            WHERE action = 'auto_deploy_baseline' AND related_variant_id = %s
            ORDER BY created_at DESC LIMIT 1
            """,
            (variant_id,),
        ).fetchone()
    if not row:
        return None
    details = row.get("details") or {}
    if not isinstance(details, dict):
        try:
            details = json.loads(details)
        except Exception:
            return None
    return details.get("baseline_snapshot")


def rollback_variant(pg: PostgresStore, notifier: TelegramNotifier | None = None,
                       reason: str = "manual") -> dict[str, Any]:
    """Roll back currently deployed variant. Restores baseline config."""
    existing = _current_deployed_variant(pg)
    if not existing:
        return {"rolled_back": False, "reason": "no_deployed_variant"}

    snapshot = _get_baseline_snapshot(pg, existing["variant_id"])
    if not snapshot:
        return {"rolled_back": False, "reason": "no_baseline_snapshot"}

    # Restore baseline
    _apply_diff(pg, snapshot)

    # Mark rolled back
    with pg.get_conn() as conn:
        conn.execute(
            """
            UPDATE swing_strategy_variants SET
                status = 'rolled_back',
                rollback_at = NOW(),
                rollback_reason = %s
            WHERE variant_id = %s
            """,
            (reason, existing["variant_id"]),
        )
        conn.commit()

    log_action(pg, "auto_rollback", "completed",
               details={"variant_id": existing["variant_id"], "reason": reason,
                        "restored_config": snapshot},
               related_variant_id=existing["variant_id"])

    logger.info(f"Variant {existing['variant_id']} rolled back: {reason}")
    if notifier:
        _notify_rollback(notifier, existing, reason)

    return {"rolled_back": True, "variant_id": existing["variant_id"], "reason": reason}


def check_rollback_conditions(pg: PostgresStore,
                                notifier: TelegramNotifier | None = None) -> dict[str, Any]:
    """Monitor active variant — auto-rollback if conditions met.

    Conditions:
      - N consecutive losses since deployed_at
      - SQN drop >= threshold vs baseline
    """
    existing = _current_deployed_variant(pg)
    if not existing:
        return {"checked": False, "reason": "no_deployed_variant"}

    consecutive_losses_max = int(pg.get_config_value("harness_rollback_consecutive_losses", "5"))
    sqn_drop_max = float(pg.get_config_value("harness_rollback_sqn_drop", "0.5"))

    # Trades since deploy
    deployed_at = existing.get("deployed_at")
    if not deployed_at:
        return {"checked": False, "reason": "no_deployed_at"}

    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT position_id, realized_pct, exit_time
            FROM swing_positions
            WHERE status = 'closed' AND exit_time >= %s
            ORDER BY exit_time
            """,
            (deployed_at,),
        ).fetchall()
    closed = [dict(r) for r in rows]

    # Update trades_under_variant
    with pg.get_conn() as conn:
        conn.execute(
            "UPDATE swing_strategy_variants SET trades_under_variant = %s WHERE variant_id = %s",
            (len(closed), existing["variant_id"]),
        )
        conn.commit()

    # Consecutive losses check
    if len(closed) >= consecutive_losses_max:
        last_n = closed[-consecutive_losses_max:]
        if all(float(t["realized_pct"] or 0) < 0 for t in last_n):
            reason = f"{consecutive_losses_max}_consecutive_losses"
            result = rollback_variant(pg, notifier, reason=reason)
            return {"checked": True, "rolled_back": True, "reason": reason, "result": result}

    # SQN drop check (only if enough trades)
    if len(closed) >= 10:
        pnls = [float(t["realized_pct"] or 0) for t in closed]
        mean = sum(pnls) / len(pnls)
        var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1) if len(pnls) > 1 else 0
        sd = math.sqrt(var) if var > 0 else 0
        if sd > 0:
            current_sqn = (mean / sd) * math.sqrt(len(pnls))
            baseline_sqn = float(existing.get("baseline_sqn") or 0)
            if baseline_sqn > 0 and (baseline_sqn - current_sqn) >= sqn_drop_max:
                reason = f"sqn_dropped_{baseline_sqn:.2f}_to_{current_sqn:.2f}"
                result = rollback_variant(pg, notifier, reason=reason)
                return {"checked": True, "rolled_back": True, "reason": reason, "result": result}

    return {"checked": True, "rolled_back": False, "trades_under_variant": len(closed),
            "consecutive_losses_max": consecutive_losses_max}
