"""Strategy B — LLM Gate with Claude → Ollama → fallback chain.

Decision priority:
  1. Claude Haiku 4.5 (if ANTHROPIC_KEY set) — best quality, ~$0.005/eval
  2. Ollama local (qwen2.5:1.5b by default) — free, ~5-15s/eval on CPU
  3. Fallback APPROVE-all — when neither available

Ollama optimizations:
  - format=json for structured output (no regex parse needed)
  - keep_alive=30m to avoid model reload
  - temperature=0.1 + low num_predict for speed + consistency
  - num_thread = CPU count
  - Redis cache 1h TTL for identical (symbol, score, regime) tuples
  - Compact prompt (~400 tokens vs ~1200 in v1)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any

import requests

from engine_v4.data.storage import PostgresStore, RedisCache

logger = logging.getLogger(__name__)

try:
    import anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


DECISION_APPROVE = "APPROVE"
DECISION_REJECT = "REJECT"
DECISION_DEFER = "DEFER"

DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b"  # Faster than 3b, plenty for binary-ish gate
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DEFAULT_NUM_THREAD = int(os.getenv("OLLAMA_NUM_THREAD", str(os.cpu_count() or 4)))

CACHE_TTL_SECONDS = 3600  # 1h


def _gather_context(pg: PostgresStore, signal: dict) -> dict[str, Any]:
    """Compact context for LLM evaluation."""
    sym = signal["symbol"]
    ctx: dict[str, Any] = {}

    with pg.get_conn() as conn:
        macro = conn.execute(
            """
            SELECT macro_score, regime, vix
            FROM swing_macro_snapshots ORDER BY time DESC LIMIT 1
            """
        ).fetchone()
    ctx["macro"] = dict(macro) if macro else {}

    # Top 3 recent news only (was 5 — trim for speed)
    with pg.get_conn() as conn:
        news = conn.execute(
            """
            SELECT title, severity, event_type, created_at
            FROM swing_events
            WHERE symbol = %s AND created_at > NOW() - INTERVAL '7 days'
              AND event_type IN ('news', 'earnings', 'insider_activity', 'sec_filing',
                                  'price_surge', 'price_drop')
            ORDER BY severity DESC, created_at DESC LIMIT 3
            """,
            (sym,),
        ).fetchall()
    ctx["news"] = [dict(n) for n in news]

    # Portfolio + perf (single combined query)
    with pg.get_conn() as conn:
        portfolio = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM swing_positions WHERE status='open') AS open_count,
              (SELECT value::int FROM swing_config WHERE key='max_positions') AS max_positions,
              (SELECT COUNT(*) FROM swing_positions WHERE status='closed' AND exit_time > NOW() - INTERVAL '7 days') AS recent_n,
              (SELECT SUM(CASE WHEN realized_pct > 0 THEN 1 ELSE 0 END) FROM swing_positions WHERE status='closed' AND exit_time > NOW() - INTERVAL '7 days') AS recent_wins,
              (SELECT AVG(realized_pct) FROM swing_positions WHERE status='closed' AND exit_time > NOW() - INTERVAL '7 days') AS recent_avg
            """
        ).fetchone()
    ctx["portfolio"] = dict(portfolio) if portfolio else {}

    return ctx


def _format_prompt(signal: dict, ctx: dict) -> str:
    """Compact prompt optimized for fast Ollama inference."""
    sym = signal["symbol"]
    macro = ctx.get("macro", {}) or {}
    port = ctx.get("portfolio", {})

    news_str = ""
    for n in ctx.get("news", []):
        sev = (n.get("severity") or "info")[:4]
        news_str += f"  [{sev}] {(n.get('title') or '')[:100]}\n"
    if not news_str:
        news_str = "  (no news)\n"

    perf_str = "no recent trades"
    if port.get("recent_n"):
        recent_n = port["recent_n"]
        recent_wins = port.get("recent_wins") or 0
        recent_avg = float(port.get("recent_avg") or 0) * 100
        perf_str = f"{recent_n} trades, {recent_wins}W, avg {recent_avg:+.2f}%"

    return f"""You are a quant trading risk gate. Output JSON only.

SIGNAL: {sym} BUY @ ${float(signal.get('entry_price') or 0):.2f} SL=${float(signal.get('stop_loss') or 0):.2f} TP=${float(signal.get('take_profit') or 0):.2f}
Scores: composite={signal.get('composite_score','?')} tech={signal.get('technical_score','?')} sentiment={signal.get('sentiment_score','?')} flow={signal.get('flow_score','?')} quality={signal.get('quality_score','?')}

MARKET: {macro.get('regime','?')} (score={macro.get('macro_score','?')}, VIX={macro.get('vix','?')})

NEWS:
{news_str}
PORTFOLIO: {port.get('open_count',0)}/{port.get('max_positions',7)} open. Last 7d: {perf_str}

Decide: APPROVE (good entry), REJECT (clear risk), DEFER (wait/unclear).

Output JSON only, no other text:
{{"decision":"APPROVE|REJECT|DEFER","confidence":0.0-1.0,"reason":"30-word max"}}"""


def _cache_key(signal: dict, ctx: dict) -> str:
    """Cache key from signal symbol + score + regime + open count (1h dedup)."""
    parts = [
        signal.get("symbol", ""),
        f"{float(signal.get('composite_score') or 0):.0f}",
        ctx.get("macro", {}).get("regime", ""),
        str(ctx.get("portfolio", {}).get("open_count", 0)),
    ]
    raw = "|".join(parts)
    return f"llm_gate:{hashlib.md5(raw.encode()).hexdigest()[:16]}"


def _call_ollama(
    prompt: str,
    url: str = DEFAULT_OLLAMA_URL,
    model: str = DEFAULT_OLLAMA_MODEL,
    num_thread: int = DEFAULT_NUM_THREAD,
    timeout: int = 90,
) -> dict[str, Any]:
    """Call Ollama with optimized settings for fast structured JSON output."""
    t0 = time.time()
    try:
        resp = requests.post(
            f"{url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "format": "json",       # structured output, no regex parse
                "stream": False,
                "keep_alive": "30m",    # keep model loaded between calls
                "options": {
                    "temperature": 0.1,     # consistency
                    "top_p": 0.8,
                    "num_predict": 200,     # short output only
                    "num_ctx": 2048,        # tight context window
                    "num_thread": num_thread,
                    "repeat_penalty": 1.1,
                },
            },
            timeout=timeout,
        )
        elapsed_ms = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            return {
                "decision": DECISION_DEFER, "confidence": 0.0,
                "reason": f"ollama_http_{resp.status_code}",
                "mode": "ollama_error", "elapsed_ms": elapsed_ms,
            }
        body = resp.json()
        raw = body.get("response", "")
        try:
            parsed = json.loads(raw)
        except Exception:
            # Try extracting JSON
            m = re.search(r"\{[^{}]*\"decision\"[^{}]*\}", raw, re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                except Exception:
                    parsed = None
            else:
                parsed = None
        if not parsed:
            return {
                "decision": DECISION_DEFER, "confidence": 0.0,
                "reason": f"parse_fail: {raw[:80]}",
                "mode": "ollama_parse_fail", "elapsed_ms": elapsed_ms,
            }

        decision = (parsed.get("decision") or "").upper().strip()
        if decision not in (DECISION_APPROVE, DECISION_REJECT, DECISION_DEFER):
            decision = DECISION_DEFER

        return {
            "decision": decision,
            "confidence": float(parsed.get("confidence") or 0.5),
            "reason": str(parsed.get("reason") or "")[:300],
            "concerns": parsed.get("concerns") or [],
            "mode": "ollama",
            "elapsed_ms": elapsed_ms,
            "model": model,
        }
    except requests.Timeout:
        return {
            "decision": DECISION_DEFER, "confidence": 0.0,
            "reason": f"ollama_timeout_{timeout}s",
            "mode": "ollama_timeout", "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except Exception as e:
        return {
            "decision": DECISION_DEFER, "confidence": 0.0,
            "reason": f"ollama_error: {e}",
            "mode": "ollama_error", "elapsed_ms": int((time.time() - t0) * 1000),
        }


def _call_claude(
    anthropic_key: str,
    prompt: str,
    model: str = DEFAULT_CLAUDE_MODEL,
    timeout: int = 60,
) -> dict[str, Any]:
    """Call Claude Haiku for evaluation."""
    t0 = time.time()
    try:
        client = anthropic.Anthropic(api_key=anthropic_key, timeout=timeout)
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        elapsed_ms = int((time.time() - t0) * 1000)

        m = re.search(r"\{[^{}]*\"decision\".*?\}", text, re.DOTALL)
        if not m:
            return {
                "decision": DECISION_DEFER, "confidence": 0.0,
                "reason": f"claude_no_json: {text[:80]}",
                "mode": "claude_parse_fail", "elapsed_ms": elapsed_ms,
            }
        try:
            parsed = json.loads(m.group(0))
        except Exception as e:
            return {
                "decision": DECISION_DEFER, "confidence": 0.0,
                "reason": f"claude_json_err: {e}",
                "mode": "claude_parse_fail", "elapsed_ms": elapsed_ms,
            }

        decision = (parsed.get("decision") or "").upper().strip()
        if decision not in (DECISION_APPROVE, DECISION_REJECT, DECISION_DEFER):
            decision = DECISION_DEFER

        return {
            "decision": decision,
            "confidence": float(parsed.get("confidence") or 0.5),
            "reason": str(parsed.get("reason") or "")[:300],
            "concerns": parsed.get("concerns") or [],
            "mode": "claude",
            "elapsed_ms": elapsed_ms,
            "model": model,
        }
    except Exception as e:
        return {
            "decision": DECISION_DEFER, "confidence": 0.0,
            "reason": f"claude_error: {e}",
            "mode": "claude_error", "elapsed_ms": int((time.time() - t0) * 1000),
        }


def evaluate_signal(
    anthropic_key: str | None,
    pg: PostgresStore,
    signal: dict,
    cache: RedisCache | None = None,
    prefer_ollama: bool = False,
) -> dict[str, Any]:
    """Evaluate a signal. Returns decision dict.

    Priority chain (unless prefer_ollama=True):
      1. Cache hit (1h TTL on symbol+score+regime+open_count)
      2. Claude Haiku (if anthropic_key)
      3. Ollama qwen2.5:1.5b (always tried if Claude missing/failed)
      4. Fallback APPROVE (last resort)
    """
    ctx = _gather_context(pg, signal)
    prompt = _format_prompt(signal, ctx)

    # Cache lookup
    cache_key = _cache_key(signal, ctx)
    if cache is not None:
        cached = cache.get_json(cache_key)
        if cached:
            cached["mode"] = (cached.get("mode") or "") + "+cache"
            cached["elapsed_ms"] = 0
            return cached

    result = None

    # Strategy: Claude first (if available + not prefer_ollama), else Ollama, else fallback
    if not prefer_ollama and anthropic_key and _HAS_ANTHROPIC:
        result = _call_claude(anthropic_key, prompt)
        # If Claude failed badly (network/parse), try Ollama as fallback
        if result["mode"].startswith("claude_") and result["mode"] != "claude":
            logger.warning(f"Claude failed ({result['mode']}), falling back to Ollama")
            result = _call_ollama(prompt)

    if result is None:
        # No Claude key — try Ollama
        result = _call_ollama(prompt)

    # Final fallback if Ollama also failed
    if result["decision"] == DECISION_DEFER and result["mode"].startswith(("ollama_", "claude_error")):
        # All AI gates failed — pass through with low confidence, audit trail
        result = {
            "decision": DECISION_APPROVE,
            "confidence": 0.3,
            "reason": f"all_llm_failed: {result.get('reason', '')[:60]} — fallback APPROVE",
            "mode": "fallback_approve",
            "elapsed_ms": result.get("elapsed_ms", 0),
        }

    # Cache successful evaluations
    if cache is not None and result["decision"] in (DECISION_APPROVE, DECISION_REJECT, DECISION_DEFER) \
            and result["mode"] in ("claude", "ollama"):
        try:
            cache.set_json(cache_key, result, ttl=CACHE_TTL_SECONDS)
        except Exception:
            pass

    return result


def evaluate_signals_parallel(
    anthropic_key: str | None,
    pg: PostgresStore,
    signals: list[dict],
    cache: RedisCache | None = None,
    max_workers: int = 4,
) -> dict[int, dict[str, Any]]:
    """Parallel evaluation of multiple signals — saves time when multiple pending.

    Returns dict {signal_id: gate_result}.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict[int, dict[str, Any]] = {}
    if not signals:
        return results

    def _eval_one(sig):
        sid = sig["signal_id"]
        try:
            r = evaluate_signal(anthropic_key, pg, sig, cache=cache)
            return sid, r
        except Exception as e:
            return sid, {
                "decision": DECISION_DEFER, "confidence": 0.0,
                "reason": f"exception: {e}", "mode": "error", "elapsed_ms": 0,
            }

    workers = min(max_workers, len(signals))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_eval_one, s) for s in signals]
        for fut in as_completed(futures):
            sid, r = fut.result()
            results[sid] = r

    return results


def log_gate_decision(pg: PostgresStore, signal_id: int, gate_result: dict) -> None:
    """Append LLM gate decision to swing_signals.llm_analysis JSONB column."""
    payload = {
        "type": "llm_gate",
        "decision": gate_result.get("decision"),
        "confidence": gate_result.get("confidence"),
        "reason": gate_result.get("reason"),
        "concerns": gate_result.get("concerns"),
        "mode": gate_result.get("mode"),
        "elapsed_ms": gate_result.get("elapsed_ms"),
        "model": gate_result.get("model"),
        "evaluated_at": datetime.utcnow().isoformat(),
    }
    try:
        with pg.get_conn() as conn:
            conn.execute(
                """
                UPDATE swing_signals SET
                    llm_analysis = COALESCE(llm_analysis::text, '') || %s,
                    llm_analyzed_at = NOW()
                WHERE signal_id = %s
                """,
                (("\n---\n" + json.dumps(payload)), signal_id),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"log_gate_decision failed for {signal_id}: {e}")


def warm_up_ollama(url: str = DEFAULT_OLLAMA_URL, model: str = DEFAULT_OLLAMA_MODEL) -> bool:
    """Pre-load Ollama model into memory. Call at engine startup or before scheduled jobs."""
    try:
        resp = requests.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": "ok", "stream": False,
                  "keep_alive": "30m", "options": {"num_predict": 1}},
            timeout=120,
        )
        if resp.status_code == 200:
            logger.info(f"Ollama warm-up OK: {model}")
            return True
    except Exception as e:
        logger.warning(f"Ollama warm-up failed: {e}")
    return False
