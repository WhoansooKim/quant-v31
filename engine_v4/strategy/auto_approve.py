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
from dataclasses import dataclass
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


@dataclass
class EntryGateConfig:
    """진입 기본 게이트 설정 (§22.AO-37).

    **공용으로 둔 이유**: 2026-10-07 분석에서 진입 경로가 둘인데 기준이 달랐다 —
    `run_auto_approve` 는 전 게이트를 적용하고 `POST /signals/{id}/approve` 는
    `validate_entry` 하나만 했다. 실측 체결의 **87%가 후자**였고, 그 결과 좋은 필터
    (교집합: 거른 것 중앙 −2.29% vs 통과 +5.26%, p=0.002)가 체결에 적용되지 않았다.
    로직을 복제하면 반드시 갈라지므로(§22.AO-18) 두 경로가 **이 한 곳**을 쓴다.
    """
    score_min: float
    score_max: float
    macro_min: float
    isec_enabled: bool
    isec_mom_min: float
    isec_tech_min: float

    @classmethod
    def load(cls, pg: PostgresStore) -> "EntryGateConfig":
        g = pg.get_config_value
        return cls(
            score_min=float(g("auto_approve_score_min", "60")),
            score_max=float(g("auto_approve_score_max", "75")),
            macro_min=float(g("auto_approve_macro_min", "30")),
            isec_enabled=g("intersection_gate_enabled", "false").lower() in ("true", "1", "yes"),
            isec_mom_min=float(g("intersection_momentum_min", "0.70")),
            isec_tech_min=float(g("intersection_technical_min", "60")),
        )


def latest_macro_score(pg: PostgresStore, default: float = 50.0) -> tuple[float, str | None]:
    """최신 매크로 스냅샷의 (score, regime). 실패 시 중립값."""
    try:
        with pg.get_conn() as conn:
            row = conn.execute(
                "SELECT macro_score, regime FROM swing_macro_snapshots ORDER BY time DESC LIMIT 1"
            ).fetchone()
        if row:
            return float(row.get("macro_score") or default), row.get("regime")
    except Exception as e:
        logger.warning(f"Macro snapshot fetch failed: {e}")
    return default, None


def evaluate_basic_gates(sig: dict, cfg: EntryGateConfig, macro_score: float) -> list[str]:
    """진입 기본 게이트 평가. **빈 리스트면 통과**, 아니면 탈락 사유 목록.

    LLM 게이트는 여기 넣지 않는다 — 병렬 평가 비용이 크고(Ollama ~2min/signal),
    실측상 기각 이력이 0건(25건 전부 APPROVE)이라 거르는 역할을 하지 않았다(§22.AO-36).
    """
    reasons: list[str] = []
    comp = sig.get("composite_score")
    if comp is None:
        return ["no_composite_score"]
    comp = float(comp)
    if comp < cfg.score_min:
        reasons.append(f"composite_score={comp:.1f} < {cfg.score_min}")
    if comp > cfg.score_max:
        reasons.append(f"composite_score={comp:.1f} > {cfg.score_max} (crowded top)")
    if macro_score < cfg.macro_min:
        reasons.append(f"macro_score={macro_score:.1f} < {cfg.macro_min}")
    if cfg.isec_enabled:
        rank = sig.get("return_20d_rank")
        tech = sig.get("technical_score")
        rank_ok = rank is not None and float(rank) >= cfg.isec_mom_min
        tech_ok = tech is not None and float(tech) >= cfg.isec_tech_min
        if not (rank_ok and tech_ok):
            reasons.append(
                f"intersection: rank={float(rank):.2f}/{cfg.isec_mom_min} "
                f"tech={float(tech):.0f}/{cfg.isec_tech_min}"
                if rank is not None and tech is not None
                else "intersection: missing rank/technical")
    return reasons


def skip_category(reason: str) -> str:
    """기각 사유 문자열 → 범주 (§22.AO-38).

    사유 문자열을 만드는 `evaluate_basic_gates` 와 **같은 파일**에 둔다 —
    문구가 바뀌면 이 함수도 같이 눈에 들어와야 한다(떨어뜨려 두면 조용히 어긋난다).
    """
    r = reason or ""
    if "no_composite_score" in r:              return "no_score"
    if "crowded top" in r:                     return "score_max"
    if r.startswith("composite_score"):        return "score_min"
    if r.startswith("macro_score"):            return "macro"
    if r.startswith("intersection"):           return "intersection"
    if r.startswith("validate"):               return "validate"
    if "LLM REJECT" in r:                      return "llm_reject"
    if "LLM DEFER" in r:                       return "llm_defer"
    if "low_conf" in r:                        return "llm_low_confidence"
    return "other"


def summarize_skips(skipped: list[dict]) -> dict[str, int]:
    """기각 목록을 범주별 건수로 집계. 사유가 여러 개면(`;` 구분) 각각 센다."""
    out: dict[str, int] = {}
    for item in skipped or []:
        for part in str(item.get("reason", "")).split(";"):
            part = part.strip()
            if not part:
                continue
            k = skip_category(part)
            out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


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

    # ② 신호 교집합 게이트 (§22.AO-12) — Sobotka(2025) 교집합 알파 3배.
    # 실측: 모멘텀(rank>=0.70) + technical(>=60) 동시충족이 composite>=61 단독보다 우수
    # (승률 66.2%→76.4%, 검증구간 평균수익 +1.64%→+3.64%). 화면을 더 얹으면 오히려 희석됨.
    # 설정·판정은 EntryGateConfig / evaluate_basic_gates 로 일원화했다 (§22.AO-37).
    gate_cfg = EntryGateConfig.load(pg)
    llm_gate_enabled = pg.get_config_value("llm_gate_enabled", "false").lower() in ("true", "1", "yes")
    llm_min_confidence = float(pg.get_config_value("llm_gate_min_confidence", "0.5"))
    prefer_ollama = pg.get_config_value("llm_gate_prefer_ollama", "false").lower() in ("true", "1", "yes")

    pending = pg.get_signals(status="pending", limit=100)
    entries = [s for s in pending if s["signal_type"] == "ENTRY"]

    # Macro check (single check, applies to all) — read latest snapshot from DB
    macro_score, macro_regime = latest_macro_score(pg)

    approved = []
    executed = []
    skipped = []
    errors = []

    # ── PASS 1: basic gates (score / macro / validate) ──
    candidates: list[dict] = []  # signals that passed basic gates, ready for LLM eval
    for sig in entries:
        sid = sig["signal_id"]
        sym = sig["symbol"]

        gate_fails = evaluate_basic_gates(sig, gate_cfg, macro_score)
        if gate_fails:
            skipped.append({"signal_id": sid, "symbol": sym, "reason": "; ".join(gate_fails)})
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
            pg.approve_signal(sid, via="auto")
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
        "macro_ok": macro_score >= gate_cfg.macro_min,
        "thresholds": {"score_min": gate_cfg.score_min, "score_max": gate_cfg.score_max,
                       "macro_min": gate_cfg.macro_min,
                       "intersection_enabled": gate_cfg.isec_enabled,
                       "momentum_min": gate_cfg.isec_mom_min,
                       "technical_min": gate_cfg.isec_tech_min,
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
