"""Phase 3F — Macro-Adaptive Strategy Switcher.

Reads latest macro_score from swing_macro_snapshots, classifies regime,
and applies a config preset when the regime changes. Audit-logged.

Regime presets (paper mode only — Live changes require user manual approval):

  RISK_ON (macro_score > 70):
    position_pct = 0.20, max_positions = 5
    composite_score_min = 55 (looser entry)
    take_profit_pct = 0.25
    atr_trailing_multiplier = 3.0 (wider trail in trending regime)

  NEUTRAL (30 <= macro_score <= 70):
    position_pct = 0.14, max_positions = 7
    composite_score_min = 60
    take_profit_pct = 0.20
    atr_trailing_multiplier = 2.5

  RISK_OFF (macro_score < 30):
    position_pct = 0.05, max_positions = 3
    composite_score_min = 70 (stricter — only high-conviction)
    take_profit_pct = 0.15 (take profits earlier)
    atr_trailing_multiplier = 2.0 (tighter trail in risky regime)

Switch only fires when regime label changes. Within-regime score changes
do not retune (avoids constant churn).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from engine_v4.data.storage import PostgresStore
from engine_v4.harness.knowledge import log_action
from engine_v4.notify.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


REGIME_PRESETS: dict[str, dict[str, str]] = {
    "RISK_ON": {
        "position_pct": "0.20",
        "max_positions": "5",
        "composite_score_min": "55",
        "take_profit_pct": "0.25",
        "atr_trailing_multiplier": "3.0",
    },
    "NEUTRAL": {
        "position_pct": "0.14",
        "max_positions": "7",
        "composite_score_min": "60",
        "take_profit_pct": "0.20",
        "atr_trailing_multiplier": "2.5",
    },
    "RISK_OFF": {
        "position_pct": "0.05",
        "max_positions": "3",
        "composite_score_min": "70",
        "take_profit_pct": "0.15",
        "atr_trailing_multiplier": "2.0",
    },
}


def _classify_regime(macro_score: float) -> str:
    """Map macro_score to regime label."""
    if macro_score > 70:
        return "RISK_ON"
    if macro_score < 30:
        return "RISK_OFF"
    return "NEUTRAL"


def _get_latest_macro(pg: PostgresStore) -> dict | None:
    with pg.get_conn() as conn:
        row = conn.execute(
            """
            SELECT macro_score, regime, time, vix, dxy
            FROM swing_macro_snapshots ORDER BY time DESC LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def _read_current_regime(pg: PostgresStore) -> str:
    """Read tracked regime from swing_config. Defaults to NEUTRAL if not set."""
    return pg.get_config_value("current_regime", "NEUTRAL")


def _set_config_atomic(pg: PostgresStore, updates: dict[str, str]) -> None:
    """Apply multiple config keys in one transaction."""
    with pg.get_conn() as conn:
        for k, v in updates.items():
            conn.execute(
                """
                INSERT INTO swing_config (key, value, category, updated_at)
                VALUES (%s, %s, 'regime', NOW())
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (k, v),
            )
        conn.commit()


def _telegram_regime_switch(notifier: TelegramNotifier, old: str, new: str,
                              macro_score: float, preset: dict[str, str],
                              triggers: dict[str, Any]) -> None:
    """Send Telegram alert on regime switch."""
    lines = [
        f"🔄 *Regime Switch: {old} → {new}*",
        "",
        f"Macro score: {macro_score:.1f}",
    ]
    if triggers.get("vix"):
        lines.append(f"VIX: {triggers['vix']:.2f}")
    if triggers.get("dxy"):
        lines.append(f"DXY: {triggers['dxy']:.2f}")
    lines.append("")
    lines.append("*Applied preset:*")
    for k, v in preset.items():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("_(paper mode only — Live changes require manual approval)_")
    try:
        asyncio.run(notifier.send("\n".join(lines)))
    except Exception as e:
        logger.warning(f"Regime switch telegram send failed: {e}")


def check_and_switch(
    pg: PostgresStore,
    notifier: TelegramNotifier | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Detect regime change and apply preset if needed.

    Returns: {old, new, switched, macro_score, applied_preset}
    """
    t0 = time.time()
    enabled = pg.get_config_value("harness_regime_switch_enabled", "false")
    if enabled.lower() not in ("true", "1", "yes") and not force:
        return {"switched": False, "reason": "harness_regime_switch_enabled=false"}

    # Live 모드는 자동 전환 금지 (사용자 명시 승인만)
    mode = pg.get_config_value("trading_mode", "paper")
    if mode == "live" and not force:
        log_action(pg, "regime_check", "skipped",
                   details={"reason": "live_mode_requires_manual"})
        return {"switched": False, "reason": "live_mode_requires_manual"}

    macro = _get_latest_macro(pg)
    if not macro:
        return {"switched": False, "reason": "no_macro_snapshot"}

    macro_score = float(macro.get("macro_score") or 50.0)
    new_regime = _classify_regime(macro_score)
    old_regime = _read_current_regime(pg)

    if new_regime == old_regime and not force:
        return {
            "switched": False,
            "old": old_regime, "new": new_regime,
            "macro_score": macro_score,
            "reason": "same_regime",
        }

    preset = REGIME_PRESETS.get(new_regime, REGIME_PRESETS["NEUTRAL"])

    # Apply preset
    updates = dict(preset)
    updates["current_regime"] = new_regime
    _set_config_atomic(pg, updates)

    triggers = {"vix": macro.get("vix"), "dxy": macro.get("dxy")}
    details = {
        "old": old_regime,
        "new": new_regime,
        "macro_score": macro_score,
        "preset_applied": preset,
        "triggers": triggers,
    }
    elapsed = time.time() - t0
    log_action(pg, "regime_switch", "completed", details=details, elapsed_sec=elapsed)
    logger.info(f"Regime switched: {old_regime} → {new_regime} (macro={macro_score:.1f})")

    if notifier:
        _telegram_regime_switch(notifier, old_regime, new_regime, macro_score, preset, triggers)

    return {
        "switched": True,
        "old": old_regime,
        "new": new_regime,
        "macro_score": macro_score,
        "applied_preset": preset,
        "elapsed_sec": elapsed,
    }


def regime_history(pg: PostgresStore, limit: int = 50) -> list[dict]:
    """Recent regime switches from harness log."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT log_id, details, created_at
            FROM swing_harness_log
            WHERE action = 'regime_switch' AND status = 'completed'
            ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
