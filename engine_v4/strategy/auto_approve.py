"""Auto-approval gate — Strategy A.

Reduces approval-to-execution latency by auto-approving pending ENTRY signals
that meet quality criteria. Runs at 22:00 KST (30min before US summer open).

Criteria (all must pass):
  - signal.status = 'pending' (not yet approved/rejected/expired)
  - signal.signal_type = 'ENTRY'
  - composite_score >= auto_approve_score_min (default 60)
  - macro_score >= auto_approve_macro_min (default 30)
  - pos_mgr.validate_entry() passes (slots available, no duplicate, etc.)

Signals not meeting criteria stay pending (user can still manually approve).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from engine_v4.data.storage import PostgresStore, RedisCache
from engine_v4.notify.telegram import TelegramNotifier
from engine_v4.risk.position_manager import PositionManager
from engine_v4.strategy.llm_gate import (
    DECISION_APPROVE, DECISION_DEFER, DECISION_REJECT,
    evaluate_signals_parallel, log_gate_decision, warm_up_ollama,
)

logger = logging.getLogger(__name__)


def _get_account_value_fallback(pg: PostgresStore, default: float = 2200.0) -> float:
    """Last-resort account value when KIS unavailable."""
    snap = pg.get_latest_snapshot()
    if snap and snap.get("total_value_usd"):
        return float(snap["total_value_usd"])
    return default


def run_auto_approve(
    pg: PostgresStore,
    pos_mgr: PositionManager,
    notifier: TelegramNotifier | None,
    kis_client: Any | None = None,
    macro_scorer: Any | None = None,
    anthropic_key: str | None = None,
    cache: RedisCache | None = None,
    check_label: str = "scheduled",
) -> dict[str, Any]:
    """Process all pending ENTRY signals, auto-approve those meeting criteria.

    Strategy A: composite_score + macro gate → execute.
    Strategy B (when llm_gate_enabled + anthropic_key): adds Claude evaluation
      between basic gates and execution. DEFER stays pending for next check.

    Returns summary: {evaluated, auto_approved, executed, skipped: [...], errors: [...]}
    """
    enabled = pg.get_config_value("auto_approve_enabled", "false")
    if enabled.lower() not in ("true", "1", "yes"):
        logger.info("Auto-approve disabled — skipping")
        return {"enabled": False, "evaluated": 0, "auto_approved": 0}

    score_min = float(pg.get_config_value("auto_approve_score_min", "60"))
    macro_min = float(pg.get_config_value("auto_approve_macro_min", "30"))
    llm_gate_enabled = pg.get_config_value("llm_gate_enabled", "false").lower() in ("true", "1", "yes")
    llm_min_confidence = float(pg.get_config_value("llm_gate_min_confidence", "0.5"))
    prefer_ollama = pg.get_config_value("llm_gate_prefer_ollama", "false").lower() in ("true", "1", "yes")

    pending = pg.get_signals(status="pending", limit=100)
    entries = [s for s in pending if s["signal_type"] == "ENTRY"]

    # Macro check (single check, applies to all) — read latest snapshot from DB
    macro_score = 50.0  # neutral default
    macro_regime = None
    try:
        with pg.get_conn() as conn:
            row = conn.execute(
                """
                SELECT macro_score, regime FROM swing_macro_snapshots
                ORDER BY time DESC LIMIT 1
                """
            ).fetchone()
        if row:
            macro_score = float(row.get("macro_score") or 50.0)
            macro_regime = row.get("regime")
    except Exception as e:
        logger.warning(f"Macro snapshot fetch failed: {e}")
    macro_ok = macro_score >= macro_min

    approved = []
    executed = []
    skipped = []
    errors = []

    # ── PASS 1: basic gates (score / macro / validate) ──
    candidates: list[dict] = []  # signals that passed basic gates, ready for LLM eval
    for sig in entries:
        sid = sig["signal_id"]
        sym = sig["symbol"]
        comp = sig.get("composite_score")

        if comp is None:
            skipped.append({"signal_id": sid, "symbol": sym, "reason": "no_composite_score"})
            continue
        if float(comp) < score_min:
            skipped.append({"signal_id": sid, "symbol": sym, "reason": f"composite_score={comp:.1f} < {score_min}"})
            continue
        if not macro_ok:
            skipped.append({"signal_id": sid, "symbol": sym, "reason": f"macro_score={macro_score:.1f} < {macro_min}"})
            continue
        try:
            entry_price = float(sig["entry_price"]) if sig.get("entry_price") else 0
            valid, reason = pos_mgr.validate_entry(sym, entry_price)
            if not valid:
                skipped.append({"signal_id": sid, "symbol": sym, "reason": f"validate: {reason}"})
                continue
        except Exception as e:
            errors.append({"signal_id": sid, "symbol": sym, "error": f"validate: {e}"})
            continue
        candidates.append(sig)

    # ── PASS 2: LLM gate (parallel) — only if Strategy B enabled ──
    gate_results: dict[int, dict] = {}
    if llm_gate_enabled and candidates:
        # Warm up Ollama once before parallel calls (preload model into memory)
        if not anthropic_key or prefer_ollama:
            warm_up_ollama()
        try:
            gate_results = evaluate_signals_parallel(
                anthropic_key if not prefer_ollama else None,
                pg, candidates, cache=cache, max_workers=4,
            )
            for sid, gate in gate_results.items():
                log_gate_decision(pg, sid, gate)
        except Exception as e:
            logger.warning(f"Parallel LLM evaluation failed: {e}")

    # ── PASS 3: process LLM results + execute approved ──
    for sig in candidates:
        sid = sig["signal_id"]
        sym = sig["symbol"]
        comp = sig.get("composite_score")
        entry_price = float(sig["entry_price"]) if sig.get("entry_price") else 0

        if llm_gate_enabled:
            gate = gate_results.get(sid)
            if not gate:
                errors.append({"signal_id": sid, "symbol": sym, "error": "llm_gate_no_result"})
                continue
            if gate["decision"] == DECISION_REJECT:
                pg.reject_signal(sid)
                skipped.append({"signal_id": sid, "symbol": sym,
                                "reason": f"LLM REJECT ({gate.get('confidence', 0):.2f}, {gate.get('mode')}): {gate.get('reason', '')[:80]}"})
                continue
            if gate["decision"] == DECISION_DEFER:
                skipped.append({"signal_id": sid, "symbol": sym,
                                "reason": f"LLM DEFER ({gate.get('confidence', 0):.2f}, {gate.get('mode')}): {gate.get('reason', '')[:80]}"})
                continue
            if float(gate.get("confidence") or 0) < llm_min_confidence:
                skipped.append({"signal_id": sid, "symbol": sym,
                                "reason": f"LLM APPROVE low_conf={gate.get('confidence', 0):.2f} < {llm_min_confidence} ({gate.get('mode')})"})
                continue

        # ── Auto-approve ──
        try:
            pg.approve_signal(sid)
            approved.append({"signal_id": sid, "symbol": sym, "composite_score": comp})

            # Execute
            if kis_client and kis_client.is_connected:
                account_value = kis_client.get_balance().total_value_usd or _get_account_value_fallback(pg)
            else:
                account_value = _get_account_value_fallback(pg)

            result = pos_mgr.execute_entry(sig, account_value)
            if not result:
                pg.reject_signal(sid)
                errors.append({"signal_id": sid, "symbol": sym, "error": "execute_entry returned None"})
                continue

            # KIS order (paper/live; paper returns SIM-* and is fine)
            if kis_client:
                try:
                    order = kis_client.buy(symbol=sym, qty=result["qty"], price=entry_price)
                    result["order_id"] = order.order_id
                    if kis_client.is_connected and not order.success:
                        errors.append({"signal_id": sid, "symbol": sym,
                                       "error": f"KIS BUY failed: {order.message}"})
                except Exception as e:
                    errors.append({"signal_id": sid, "symbol": sym, "error": f"KIS order exception: {e}"})

            executed.append({
                "signal_id": sid, "symbol": sym, "qty": result["qty"],
                "entry_price": entry_price, "amount": result.get("amount"),
                "composite_score": comp,
            })

            # Telegram
            if notifier:
                try:
                    asyncio.run(_notify_auto_approve(notifier, sig, result, comp, macro_score))
                except Exception as e:
                    logger.warning(f"Telegram auto-approve notify failed: {e}")

        except Exception as e:
            logger.exception(f"Auto-approve failed for signal {sid}: {e}")
            errors.append({"signal_id": sid, "symbol": sym, "error": str(e)})

    summary = {
        "enabled": True,
        "check_label": check_label,
        "llm_gate_enabled": llm_gate_enabled,
        "evaluated": len(entries),
        "auto_approved": len(approved),
        "executed": len(executed),
        "skipped": len(skipped),
        "errors_count": len(errors),
        "macro_score": macro_score,
        "macro_ok": macro_ok,
        "thresholds": {"score_min": score_min, "macro_min": macro_min,
                       "llm_min_confidence": llm_min_confidence},
        "approved_list": approved,
        "executed_list": executed,
        "skipped_list": skipped,
        "errors_list": errors,
    }
    logger.info(f"Auto-approve summary: evaluated={len(entries)}, approved={len(approved)}, "
                f"executed={len(executed)}, skipped={len(skipped)}, errors={len(errors)}")
    return summary


async def _notify_auto_approve(notifier: TelegramNotifier, sig: dict, result: dict,
                                comp_score: float, macro_score: float) -> None:
    """Telegram digest for auto-approved entries."""
    msg = (
        f"🤖 *Auto-Approved Entry*\n\n"
        f"Symbol: *{sig['symbol']}*\n"
        f"Side: BUY\n"
        f"Qty: {result.get('qty')}\n"
        f"Entry: ${float(sig.get('entry_price') or 0):.2f}\n"
        f"Amount: ${result.get('amount', 0):.2f}\n\n"
        f"Composite Score: {comp_score:.1f}\n"
        f"Macro Score: {macro_score:.1f}\n\n"
        f"Strategy A — Latency removed"
    )
    await notifier.send(msg)
