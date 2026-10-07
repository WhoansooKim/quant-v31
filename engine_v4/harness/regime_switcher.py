"""Phase 3F — Macro-Adaptive Strategy Switcher.

Reads latest macro_score from swing_macro_snapshots, classifies regime,
and applies a config preset when the regime changes. Audit-logged.

Regime presets (paper mode only — Live changes require user manual approval):

  RISK_ON (macro_score > 70):
    position_pct = 0.20, max_positions = 5
    auto_approve_score_min = 58 (looser entry) — 기본 비활성, §22.AO-35
    take_profit_pct = 0.25
    atr_trailing_multiplier = 3.0 (wider trail in trending regime)

  NEUTRAL (30 <= macro_score <= 70):
    position_pct = 0.14, max_positions = 7
    auto_approve_score_min = 61
    take_profit_pct = 0.20
    atr_trailing_multiplier = 2.5

  RISK_OFF (macro_score < 30):
    position_pct = 0.05, max_positions = 3
    auto_approve_score_min = 70 (stricter — only high-conviction)
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


# NOTE: max_positions / take_profit_pct / position_pct 는 프리셋에서 제외 (2026-07-28).
#   - max_positions: 사용자 지정 고정(20). 레짐 스위치가 덮어쓰지 않음.
#   - take_profit_pct: ①번 손익비 개선(백테스트 검증, 0.50=트레일링 지배) 보호.
#   - position_pct: 사용자 지정 고정(0.05, 20개 분산). 레짐 무관.
#   레짐 적응은 진입 엄격도(auto_approve_score_min) + 트레일 폭(atr_trailing_multiplier)만 담당.
#   ⚠️ 2026-10-07 현재 **둘 다 실효가 없다** — 전자는 기본 비활성(§22.AO-35),
#      후자는 브레이크이븐이 먼저 발동해 미사용(§22.AO-26-C).
#   위기(RISK_OFF) 방어 = 진입 score 70 + 좁은 트레일 2.0 으로 유지(포지션 크기 축소는 제외).
# 🔴 2026-10-07 (§22.AO-35): 키 이름이 틀려서 **레짐 적응이 통째로 무효**였다.
#   여기서 `composite_score_min` 을 썼지만 진입 경로(auto_approve)가 읽는 것은
#   `auto_approve_score_min` 이고, `composite_score_min` 을 **읽는 코드는 하나도 없었다**.
#   증거: auto_approve_score_min 의 최종 수정이 2026-05-14 — 그 뒤 레짐이 여러 번 바뀌었는데
#   진입 엄격도는 5개월간 61 로 고정이었다.
#   (나머지 한 레버 atr_trailing_multiplier 도 브레이크이븐이 먼저 발동해 무효였다 — §22.AO-26-C.
#    즉 Phase 3F 의 두 레버가 둘 다 죽어 있었다.)
#
# ⚠️ 키를 고치면 잠들어 있던 기능이 **깨어난다**. 그래서 기본값은 끈 상태로 둔다
#   (`regime_entry_strictness_enabled`, 기본 false → 지금까지와 동일하게 61 고정).
#   켜기 전에 알아야 할 실측(2026-09-25, h=20d 선행수익률 밴드별 중앙값):
#     <60  중앙 −2.97% (승률 41.9%)  ← RISK_ON 프리셋 58 이 들어가는 구간. **최악이다.**
#     60-65 중앙 +0.50%             65-70 중앙 +7.60% (승률 76.9%)  ← 스윗스팟
#     70-75 중앙 +1.83%             75+   중앙 +6.46%
#   즉 RISK_ON 에서 58 로 **완화**하면 가장 나쁜 구간으로 진입을 넓히게 된다.
#   활성화는 별도 판단 사항이며, 밴드 기반 재설계(§SESSION_PICKUP ③)와 함께 봐야 한다.
ENTRY_STRICTNESS_KEY = "auto_approve_score_min"

REGIME_PRESETS: dict[str, dict[str, str]] = {
    "RISK_ON": {
        # 2026-06-03 IC 보정: 55 → 58 (60일 분석 결과 sweet spot 65-70)
        ENTRY_STRICTNESS_KEY: "58",
        "atr_trailing_multiplier": "3.0",
    },
    "NEUTRAL": {
        # 2026-06-03 IC 보정: 60 → 63
        # 2026-06-04 절충 완화: 63 → 61 (시그널 0건 회복, 1주 관찰)
        ENTRY_STRICTNESS_KEY: "61",
        "atr_trailing_multiplier": "2.5",
    },
    "RISK_OFF": {
        ENTRY_STRICTNESS_KEY: "70",
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
    # 진입 엄격도는 기본적으로 레짐이 건드리지 않는다 (§22.AO-35 머리말 참조).
    # 켜려면 swing_config.regime_entry_strictness_enabled = true.
    if pg.get_config_value("regime_entry_strictness_enabled", "false").lower() \
            not in ("true", "1", "yes"):
        updates.pop(ENTRY_STRICTNESS_KEY, None)
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
