"""Phase 3C — Strategy Variant Generator.

Monthly (or on-demand) Claude/Ollama-driven strategy variant proposal.

Inputs:
  - Current baseline config (swing_config)
  - Recent performance (Daily Reports — IC, SQN, expectancy, win_rate)
  - Counterfactual analysis (which layers leave money on table)
  - Top knowledge entries (swing_knowledge, ranked by applicability_score)

Output:
  - 3-10 strategy variants stored in swing_strategy_variants (status=pending)
  - Each variant has: name, description, config_diff, reasoning, based_on_knowledge_ids

Variant config_diff keys (subset of BacktestParams):
  position_pct, max_positions, composite_score_min, take_profit_pct,
  stop_loss_pct, return_rank_min, volume_ratio_min, atr_trailing_multiplier,
  atr_hard_stop_multiplier, time_stop_days, partial_exit_threshold, ...
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import requests

from engine_v4.data.storage import PostgresStore
from engine_v4.harness.knowledge import list_knowledge, log_action

logger = logging.getLogger(__name__)

try:
    import anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


# Tunable parameters that variants can change. Keep this list curated to
# prevent LLM from suggesting unsafe values.
TUNABLE_PARAMS = {
    "position_pct": (0.02, 0.25),
    "max_positions": (3, 10),
    "composite_score_min": (40, 80),
    "take_profit_pct": (0.10, 0.40),
    "stop_loss_pct": (-0.10, -0.02),
    "return_rank_min": (0.40, 0.85),
    "volume_ratio_min": (1.0, 3.0),
    "atr_trailing_multiplier": (1.5, 4.0),
    "atr_hard_stop_multiplier": (1.0, 2.5),
    "time_stop_days": (5, 30),
    "partial_exit_threshold": (0.05, 0.25),
    "partial_exit_pct": (0.25, 0.75),
    "atr_trailing_activation_r": (0.5, 2.0),
    "rsi2_exit_threshold": (60, 999),
    "factor_weight_technical": (0.10, 0.50),
    "factor_weight_sentiment": (0.10, 0.40),
    "factor_weight_flow": (0.05, 0.30),
    "factor_weight_quality": (0.05, 0.30),
    "factor_weight_value": (0.05, 0.30),
}


def _gather_performance(pg: PostgresStore) -> dict:
    """Snapshot of current performance from daily reports + counterfactual."""
    perf = {}
    with pg.get_conn() as conn:
        # Latest daily report
        row = conn.execute(
            """
            SELECT report_date, rolling_30_win_rate, rolling_30_expectancy_pct,
                   rolling_30_sqn, rolling_30_information_coefficient, rolling_30_auc,
                   brinson_market, brinson_selection, brinson_residual
            FROM swing_daily_report ORDER BY report_date DESC LIMIT 1
            """
        ).fetchone()
        if row:
            perf["daily_report"] = dict(row)

        # Counterfactual aggregate
        cf_rows = conn.execute(
            """
            SELECT realized_pct, counterfactual_exits
            FROM swing_trade_postmortem
            WHERE counterfactual_exits IS NOT NULL
              AND exit_time IS NOT NULL
            ORDER BY exit_time DESC LIMIT 50
            """
        ).fetchall()
        if cf_rows:
            cf_summary = {}
            for r in cf_rows:
                cf = r.get("counterfactual_exits") or {}
                if not isinstance(cf, dict):
                    continue
                for layer, info in cf.items():
                    if info.get("pnl_pct") is None:
                        continue
                    cf_summary.setdefault(layer, []).append(info["pnl_pct"])
            perf["counterfactual_avg"] = {
                layer: round(sum(vals) / len(vals), 2)
                for layer, vals in cf_summary.items() if vals
            }
    return perf


def _gather_baseline(pg: PostgresStore) -> dict:
    """Current swing_config values for tunable params."""
    baseline = {}
    for key in TUNABLE_PARAMS.keys():
        val = pg.get_config_value(key, None)
        if val is not None:
            try:
                baseline[key] = float(val)
            except (TypeError, ValueError):
                baseline[key] = val
    return baseline


def _gather_knowledge(pg: PostgresStore, top_n: int = 8) -> list[dict]:
    """Top-N knowledge entries by applicability."""
    return list_knowledge(pg, min_applicability=70, limit=top_n)


def _format_prompt(baseline: dict, perf: dict, knowledge: list[dict]) -> str:
    """Build the LLM prompt for variant generation."""
    perf_summary = ""
    daily = perf.get("daily_report") or {}
    if daily:
        perf_summary = (
            f"Win rate: {(daily.get('rolling_30_win_rate') or 0) * 100:.1f}%, "
            f"Expectancy: {daily.get('rolling_30_expectancy_pct', 0):.2f}%, "
            f"SQN: {daily.get('rolling_30_sqn', 0)}, "
            f"IC: {daily.get('rolling_30_information_coefficient', 0)}, "
            f"AUC: {daily.get('rolling_30_auc', 0)}"
        )

    cf = perf.get("counterfactual_avg") or {}
    cf_str = ", ".join(f"{k}={v:+.2f}%" for k, v in cf.items())

    kn_lines = []
    for k in knowledge:
        hint = ""
        if k.get("strategy_hypothesis"):
            sh = k["strategy_hypothesis"] if isinstance(k["strategy_hypothesis"], dict) \
                else json.loads(k["strategy_hypothesis"]) if isinstance(k["strategy_hypothesis"], str) else {}
            if sh:
                hint = " | " + " ".join(f"{kk}:{vv}" for kk, vv in list(sh.items())[:3])
        kn_lines.append(f"  [{k['applicability_score']}] {k['source_name'][:40]} — {k['title'][:60]}{hint}")
    kn_str = "\n".join(kn_lines) if kn_lines else "  (no knowledge entries)"

    baseline_str = ", ".join(f"{k}={v}" for k, v in baseline.items())
    tunable_str = "\n".join(
        f"  {k}: [{lo}, {hi}]" for k, (lo, hi) in TUNABLE_PARAMS.items()
    )

    return f"""You are a quant strategy designer. Propose 3-5 strategy variants for a momentum swing trading system.

CURRENT BASELINE CONFIG:
{baseline_str}

CURRENT PERFORMANCE (rolling 30 trades):
{perf_summary if perf_summary else '(no performance data yet)'}

COUNTERFACTUAL EXIT ANALYSIS (avg P&L if each layer had fired):
{cf_str if cf_str else '(no counterfactual data)'}

TOP STRATEGY KNOWLEDGE (from research):
{kn_str}

TUNABLE PARAMETERS (key: [min, max]):
{tunable_str}

DESIGN PRINCIPLES:
1. ONLY tune parameters in the TUNABLE list above
2. Each variant should change 2-5 parameters (not all at once — easier to attribute)
3. Variants should be MOTIVATED by the knowledge and performance data above
4. Avoid extreme values — stay within [min, max] ranges
5. Diversify: each variant should test a DIFFERENT hypothesis

OUTPUT JSON ONLY (array of variants):
{{
  "variants": [
    {{
      "name": "short name in Korean",
      "description": "one-sentence Korean description of hypothesis",
      "reasoning": "why this might improve over baseline (3 sentences)",
      "config_diff": {{"param1": value1, "param2": value2, ...}}
    }},
    ...
  ]
}}"""


def _ollama_generate(prompt: str, ollama_url: str = "http://localhost:11434",
                      model: str = "qwen2.5:3b", timeout: int = 120) -> dict:
    """Generate variants via Ollama."""
    try:
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": model, "prompt": prompt,
                "format": "json", "stream": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.5, "num_predict": 1500, "num_ctx": 4096, "num_thread": 4},
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return {}
        raw = resp.json().get("response", "")
        try:
            return json.loads(raw)
        except Exception:
            return {}
    except Exception as e:
        logger.warning(f"Ollama variant gen failed: {e}")
        return {}


def _claude_generate(anthropic_key: str, prompt: str,
                      model: str = "claude-haiku-4-5-20251001",
                      timeout: int = 60) -> dict:
    """Generate variants via Claude Haiku."""
    try:
        client = anthropic.Anthropic(api_key=anthropic_key, timeout=timeout)
        resp = client.messages.create(
            model=model, max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        m = re.search(r"\{.*\"variants\".*\}", text, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    except Exception as e:
        logger.warning(f"Claude variant gen failed: {e}")
        return {}


def _validate_variant(diff: dict) -> tuple[dict, list[str]]:
    """Clip variant values to safe ranges. Returns (sanitized, warnings)."""
    sanitized = {}
    warnings = []
    for k, v in diff.items():
        if k not in TUNABLE_PARAMS:
            warnings.append(f"unknown_param:{k}")
            continue
        lo, hi = TUNABLE_PARAMS[k]
        try:
            vv = float(v)
            if vv < lo:
                warnings.append(f"{k}_clipped_to_min")
                vv = lo
            elif vv > hi:
                warnings.append(f"{k}_clipped_to_max")
                vv = hi
            sanitized[k] = vv
        except (TypeError, ValueError):
            warnings.append(f"{k}_invalid_value")
    return sanitized, warnings


def generate_variants(
    pg: PostgresStore,
    anthropic_key: str | None = None,
    prefer_ollama: bool = True,
    max_variants: int = 5,
) -> dict[str, Any]:
    """Generate strategy variants. Returns summary dict."""
    t0 = time.time()
    log_action(pg, "variant_generate", "started")

    baseline = _gather_baseline(pg)
    perf = _gather_performance(pg)
    knowledge = _gather_knowledge(pg, top_n=8)
    prompt = _format_prompt(baseline, perf, knowledge)

    # Generation
    result = {}
    generated_by = "fallback"
    if not prefer_ollama and anthropic_key and _HAS_ANTHROPIC:
        result = _claude_generate(anthropic_key, prompt)
        generated_by = "claude"
    if not result:
        result = _ollama_generate(prompt)
        generated_by = "ollama"

    variants = result.get("variants") or []
    if not variants:
        log_action(pg, "variant_generate", "failed",
                   details={"reason": "no_variants_returned"},
                   elapsed_sec=time.time() - t0)
        return {"generated": 0, "error": "no_variants_returned"}

    # Persist variants
    inserted = []
    knowledge_ids = [k["knowledge_id"] for k in knowledge]
    with pg.get_conn() as conn:
        for v in variants[:max_variants]:
            name = (v.get("name") or "unnamed")[:100]
            description = v.get("description") or ""
            reasoning = v.get("reasoning") or ""
            raw_diff = v.get("config_diff") or {}
            sanitized, warnings = _validate_variant(raw_diff)
            if not sanitized:
                logger.warning(f"Variant '{name}' had no valid params, skipping")
                continue
            row = conn.execute(
                """
                INSERT INTO swing_strategy_variants
                (name, description, config_diff, based_on_knowledge_ids,
                 generated_by, generation_prompt, generation_reasoning, status)
                VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, 'pending')
                RETURNING variant_id
                """,
                (
                    name, description, json.dumps(sanitized),
                    knowledge_ids,
                    generated_by, prompt[:2000], reasoning,
                ),
            ).fetchone()
            conn.commit()
            inserted.append({
                "variant_id": row["variant_id"],
                "name": name,
                "config_diff": sanitized,
                "warnings": warnings,
            })

    elapsed = time.time() - t0
    summary = {
        "generated": len(inserted),
        "generated_by": generated_by,
        "elapsed_sec": round(elapsed, 1),
        "variants": inserted,
    }
    log_action(pg, "variant_generate", "completed", details=summary, elapsed_sec=elapsed)
    return summary


def list_variants(pg: PostgresStore, status: str | None = None, limit: int = 50) -> list[dict]:
    """List variants with optional status filter."""
    where = "WHERE status = %s" if status else "WHERE 1=1"
    params: list = [status] if status else []
    params.append(limit)
    with pg.get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT variant_id, name, description, config_diff, status, generated_by,
                   sqn_delta, sharpe_delta, baseline_sqn, variant_sqn,
                   trades_under_variant, deployed_at, rollback_at, rejection_reason,
                   created_at
            FROM swing_strategy_variants {where}
            ORDER BY created_at DESC LIMIT %s
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_variant(pg: PostgresStore, variant_id: int) -> dict | None:
    with pg.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM swing_strategy_variants WHERE variant_id = %s",
            (variant_id,),
        ).fetchone()
    return dict(row) if row else None
