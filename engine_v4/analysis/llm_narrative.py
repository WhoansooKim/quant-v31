"""LLM narrative generation (Claude Haiku batch).

Two kinds of narratives:
  1. Per-closed-trade post-mortem narrative — only for |R|>1.0 or hold>5d.
     Cost: ~$0.02/trade × ~3/week = $0.25/month.
  2. Daily session narrative — 200 words, summarizes daily report.
     Cost: ~$0.05/day = $1.50/month.

Cost-controlled: skips when no anthropic_key, or falls back to deterministic summary.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Anthropic client is optional — only imported when key is present
try:
    import anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False


def _format_trade_prompt(postmortem: dict, counterfactuals: dict | None) -> str:
    cf_section = ""
    if counterfactuals:
        cf_lines = []
        for layer, info in counterfactuals.items():
            pnl = info.get("pnl_pct")
            if pnl is not None:
                cf_lines.append(f"  - {layer}: {pnl:+.2f}% (would have exited day {info.get('days_to_exit')})")
        if cf_lines:
            cf_section = "\nCounterfactual exits (what other layers would have produced):\n" + "\n".join(cf_lines)

    news_section = ""
    if postmortem.get("top_news"):
        items = postmortem["top_news"]
        if isinstance(items, list) and items:
            lines = [f"  - {it.get('headline', '')[:100]} ({it.get('source', '')}, rel={it.get('relevance', 0)})"
                     for it in items[:3]]
            news_section = "\nTop news during hold:\n" + "\n".join(lines)

    return f"""You are analyzing a closed swing trade for a quant trader.

Position: {postmortem.get('symbol')} | Entry ${postmortem.get('entry_price')} → Exit ${postmortem.get('exit_price')}
Hold: {postmortem.get('hold_days')}d
Realized: {(postmortem.get('realized_pct') or 0) * 100:+.2f}% (${postmortem.get('realized_pnl', 0):+.2f})
MFE: {(postmortem.get('mfe_pct') or 0) * 100:+.2f}% on {postmortem.get('mfe_date')}
MAE: {(postmortem.get('mae_pct') or 0) * 100:+.2f}% on {postmortem.get('mae_date')}
Capture Ratio: {postmortem.get('capture_ratio')}
R-multiple: {postmortem.get('r_multiple')}
Exit Layer: {postmortem.get('exit_layer')} ({postmortem.get('exit_reason')})
β (market sensitivity): {postmortem.get('beta')}
Cumulative AR: {(postmortem.get('cumulative_ar') or 0) * 100:+.2f}%
{cf_section}{news_section}

Write a concise post-mortem in Korean (3 bullets, under 100 words total):
1. 한 줄 평가 (예: "RSI(2) 조기청산, 추세 놓침")
2. 무엇이 잘 됐나 / 못 됐나
3. 시스템 개선 제안 (구체적 파라미터)
"""


def _format_daily_prompt(report: dict, counterfactual_agg: dict | None = None) -> str:
    m = report.get("metrics", {}) or {}
    cf_summary = ""
    if counterfactual_agg and counterfactual_agg.get("layers"):
        top_layers = counterfactual_agg["layers"][:3]
        cf_summary = "\nCounterfactual (vs actual): " + ", ".join(
            f"{l['layer']}=+{l['avg_delta_pct']:.1f}%" for l in top_layers
        )

    return f"""You are writing the daily post-market report for a quant trader.

Date: {report.get('report_date')}
Closed today: {report.get('closed_count')} (P&L ${report.get('closed_pnl', 0):+.2f})
Open positions: {report.get('open_count')}

Rolling 30-trade:
  Win rate: {(m.get('win_rate') or 0) * 100:.1f}%
  Expectancy: {m.get('expectancy_pct', 0):+.2f}%
  SQN: {m.get('sqn')}
  IC (score→PnL Spearman): {m.get('information_coefficient')}
  AUC (score binary): {m.get('auc')}

P&L attribution (avg per trade):
  Market (β·Rm): {(report.get('brinson', {}).get('market', 0)) * 100:+.2f}%
  Selection (AR): {(report.get('brinson', {}).get('selection', 0)) * 100:+.2f}%
  Residual: {(report.get('brinson', {}).get('residual', 0)) * 100:+.2f}%

Regime: {report.get('macro', {}).get('regime')} | Macro Score: {report.get('macro', {}).get('score')}
News flagged: {report.get('top_news_count')}
{cf_summary}

Write a 150-word Korean daily briefing covering:
1. 오늘 거래 평가 (성과 vs 기대)
2. 시그널 품질 진단 (IC/AUC/Calibration이 시사하는 바)
3. 내일 주의사항 (regime, news, open positions)
"""


def generate_trade_narrative(
    anthropic_key: str | None,
    postmortem: dict,
    counterfactuals: dict | None = None,
    max_tokens: int = 250,
) -> dict[str, Any]:
    """Generate per-trade narrative via Claude Haiku.

    Returns {narrative, one_liner, mode, error}.
    """
    # Skip threshold: |R| < 1 AND hold ≤ 5 → not worth LLM call
    r = postmortem.get("r_multiple") or 0
    hold = postmortem.get("hold_days") or 0
    if abs(r) < 1.0 and hold <= 5:
        return _fallback_trade_narrative(postmortem, counterfactuals, reason="skip_threshold")

    if not anthropic_key or not _HAS_ANTHROPIC:
        return _fallback_trade_narrative(postmortem, counterfactuals, reason="no_anthropic")

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        prompt = _format_trade_prompt(postmortem, counterfactuals)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        # one_liner: first line, strip bullets
        first = next((l.strip("- •*0123456789. ").strip() for l in text.split("\n") if l.strip()), "")
        return {
            "narrative": text,
            "one_liner": first[:200],
            "mode": "claude",
        }
    except Exception as e:
        logger.warning(f"Claude trade narrative failed: {e}")
        return _fallback_trade_narrative(postmortem, counterfactuals, reason=f"error: {e}")


def _fallback_trade_narrative(
    postmortem: dict,
    counterfactuals: dict | None,
    reason: str = "fallback",
) -> dict[str, Any]:
    realized = (postmortem.get("realized_pct") or 0) * 100
    mfe = (postmortem.get("mfe_pct") or 0) * 100
    capture = postmortem.get("capture_ratio") or 0
    layer = postmortem.get("exit_layer") or "?"
    sym = postmortem.get("symbol", "?")
    hold = postmortem.get("hold_days") or 0

    if capture and capture < 0.4 and mfe > 5:
        one_liner = f"{sym}: 조기청산({layer}), 가능했던 {mfe:.1f}% 중 {realized:.1f}% (capture {capture:.2f})"
    elif realized < 0:
        one_liner = f"{sym}: 손실 마감 {realized:.2f}% via {layer} (보유 {hold}d)"
    else:
        one_liner = f"{sym}: +{realized:.2f}% via {layer} (보유 {hold}d, capture {capture})"

    narrative = f"- {one_liner}\n- 진입 후 MFE {mfe:.1f}%, capture ratio {capture}\n- 시스템: {reason}"
    return {
        "narrative": narrative,
        "one_liner": one_liner,
        "mode": "fallback",
    }


def generate_daily_narrative(
    anthropic_key: str | None,
    report: dict,
    counterfactual_agg: dict | None = None,
    max_tokens: int = 400,
) -> dict[str, Any]:
    """Generate daily session narrative.

    Returns {narrative, mode}.
    """
    if not anthropic_key or not _HAS_ANTHROPIC:
        return _fallback_daily_narrative(report, counterfactual_agg)

    try:
        client = anthropic.Anthropic(api_key=anthropic_key)
        prompt = _format_daily_prompt(report, counterfactual_agg)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else ""
        return {"narrative": text, "mode": "claude"}
    except Exception as e:
        logger.warning(f"Claude daily narrative failed: {e}")
        return _fallback_daily_narrative(report, counterfactual_agg)


def _fallback_daily_narrative(report: dict, counterfactual_agg: dict | None) -> dict:
    m = report.get("metrics", {}) or {}
    parts = [
        f"오늘 청산: {report.get('closed_count')}건, P&L ${report.get('closed_pnl', 0):+.2f}",
        f"오픈 포지션: {report.get('open_count')}",
        f"Rolling 30 — 승률 {(m.get('win_rate') or 0) * 100:.1f}%, expectancy {m.get('expectancy_pct', 0):+.2f}%, SQN {m.get('sqn')}",
    ]
    ic = m.get("information_coefficient")
    if ic is not None and ic < 0:
        parts.append(f"⚠️ IC {ic} — composite_score가 결과와 음의 상관 (점수 시스템 재검토 필요)")
    if counterfactual_agg and counterfactual_agg.get("layers"):
        best = counterfactual_agg["layers"][0]
        parts.append(f"Counterfactual: {best['layer']} 청산 시 평균 +{best['avg_delta_pct']:.1f}% 추가 수익 가능")
    return {"narrative": "\n".join(parts), "mode": "fallback"}


def update_postmortem_with_narrative(pg, position_id: int, narr: dict) -> None:
    with pg.get_conn() as conn:
        conn.execute(
            """
            UPDATE swing_trade_postmortem SET
                llm_narrative = %s, llm_one_liner = %s, llm_narrative_at = NOW()
            WHERE position_id = %s
            """,
            (narr["narrative"], narr["one_liner"], position_id),
        )
        conn.commit()


def update_daily_with_narrative(pg, report_date, narr: dict) -> None:
    with pg.get_conn() as conn:
        conn.execute(
            """
            UPDATE swing_daily_report SET
                llm_narrative = %s, llm_narrative_at = NOW()
            WHERE report_date = %s
            """,
            (narr["narrative"], report_date),
        )
        conn.commit()
