"""Daily post-market analysis orchestrator.

Scheduled at 06:05 KST (after US market close + 1h buffer).
Pipeline:
  1. Refresh MFE/MAE for all positions (open + closed today)
  2. Run event study for any positions missing β
  3. News attribution for today's closed + currently open positions
  4. Compute rolling decision metrics (win rate / expectancy / SQN / IC)
  5. Brinson decomposition (market vs selection vs residual)
  6. Persist to swing_daily_report
  7. Send Telegram digest
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, time as dtime, timedelta
from typing import Any

from engine_v4.analysis.counterfactual import (
    aggregate_counterfactuals, backfill_counterfactuals_all,
)
from engine_v4.analysis.event_study import (
    backfill_event_study_all, compute_event_study,
    update_postmortem_with_event_study,
)
from engine_v4.analysis.llm_narrative import (
    generate_daily_narrative, generate_trade_narrative,
    update_daily_with_narrative, update_postmortem_with_narrative,
)
from engine_v4.analysis.mfe_mae import backfill_all as mfe_backfill_all
from engine_v4.analysis.news_attribution import attribute_news_for_position
from engine_v4.data.storage import PostgresStore
from engine_v4.notify.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


def _today_us_session_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return [session_open, session_close] of US session that just ended (UTC).

    US regular session = 13:30 UTC ~ 20:00 UTC (DST: 13:30 ~ 20:00 EDT = 17:30 ~ 24:00 UTC)
    Run at 06:00 KST = 21:00 UTC, so the session that just ended is yesterday's UTC date.
    """
    if now is None:
        now = datetime.utcnow()
    # Find the most recent trading day relative to UTC
    today_utc = now.date()
    # If it's before 13:30 UTC, the most recent session is yesterday
    if now.time() < dtime(13, 30):
        sess_date = today_utc - timedelta(days=1)
    else:
        sess_date = today_utc
    # Skip weekends
    while sess_date.weekday() >= 5:
        sess_date -= timedelta(days=1)
    open_dt = datetime.combine(sess_date, dtime(13, 30))
    close_dt = datetime.combine(sess_date, dtime(20, 0))
    return open_dt, close_dt


def _rolling_decision_metrics(pg: PostgresStore, n: int = 30) -> dict[str, Any]:
    """Compute rolling-N-trade decision quality metrics from postmortems.

    Returns IC (Spearman), AUC (binary win/loss), expectancy in R, SQN (Tharp), win rate.
    """
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.position_id, p.realized_pct, p.r_multiple, s.composite_score
            FROM swing_trade_postmortem p
            LEFT JOIN swing_positions pp ON pp.position_id = p.position_id
            LEFT JOIN swing_signals s ON s.signal_id = pp.signal_id
            WHERE p.exit_time IS NOT NULL AND p.realized_pct IS NOT NULL
            ORDER BY p.exit_time DESC
            LIMIT %s
            """,
            (n,),
        ).fetchall()

    rows = [dict(r) for r in rows]
    if not rows:
        return {"n": 0}

    n_used = len(rows)
    returns = [float(r["realized_pct"] or 0) for r in rows]
    r_mults = [float(r["r_multiple"] or 0) for r in rows if r["r_multiple"] is not None]
    scores = [(float(r["composite_score"]), float(r["realized_pct"] or 0))
              for r in rows if r["composite_score"] is not None]

    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x <= 0]
    win_rate = len(wins) / n_used

    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    # SQN (Tharp) = (mean(R) / std(R)) * sqrt(N)
    sqn = None
    if r_mults and len(r_mults) >= 2:
        m = sum(r_mults) / len(r_mults)
        variance = sum((x - m) ** 2 for x in r_mults) / (len(r_mults) - 1)
        sd = math.sqrt(variance) if variance > 0 else 0
        if sd > 0:
            sqn = (m / sd) * math.sqrt(len(r_mults))

    # Information Coefficient — Spearman ρ between composite_score and realized return
    ic = None
    if len(scores) >= 5:
        ic = _spearman_rho([s for s, _ in scores], [r for _, r in scores])

    # AUC: how well does composite_score separate winners from losers
    auc = None
    if len(scores) >= 5:
        wins_scored = [s for s, r in scores if r > 0]
        loss_scored = [s for s, r in scores if r <= 0]
        if wins_scored and loss_scored:
            # Pairwise comparison AUC (Wilcoxon-Mann-Whitney)
            n_correct = 0
            n_total = 0
            for w in wins_scored:
                for l in loss_scored:
                    n_total += 1
                    if w > l:
                        n_correct += 1
                    elif w == l:
                        n_correct += 0.5
            auc = n_correct / n_total if n_total else None

    return {
        "n": n_used,
        "win_rate": round(win_rate, 4),
        "expectancy_pct": round(expectancy * 100, 4),
        "avg_win_pct": round(avg_win * 100, 4),
        "avg_loss_pct": round(avg_loss * 100, 4),
        "sqn": round(sqn, 3) if sqn is not None else None,
        "information_coefficient": round(ic, 4) if ic is not None else None,
        "auc": round(auc, 4) if auc is not None else None,
    }


def _spearman_rho(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation."""
    n = len(xs)
    if n < 2:
        return 0.0

    def rank(arr: list[float]) -> list[float]:
        # Average ranks (deal with ties)
        s = sorted(enumerate(arr), key=lambda t: t[1])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and s[j + 1][1] == s[i][1]:
                j += 1
            avg = (i + j + 2) / 2  # 1-indexed
            for k in range(i, j + 1):
                ranks[s[k][0]] = avg
            i = j + 1
        return ranks

    rx, ry = rank(xs), rank(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    sx2 = sum((rx[i] - mx) ** 2 for i in range(n))
    sy2 = sum((ry[i] - my) ** 2 for i in range(n))
    den = math.sqrt(sx2 * sy2)
    return cov / den if den > 1e-12 else 0.0


def _brinson_decomposition(pg: PostgresStore, report_date: date) -> dict[str, float]:
    """Lightweight Brinson — split realized P&L of trades closed on report_date
    into market(β·R_m) + idiosyncratic AR + residual.

    Uses already-computed beta/cumulative_ar/market_explained from postmortem.
    """
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT realized_pct, market_explained_pct, news_explained_pct, residual_pct
            FROM swing_trade_postmortem
            WHERE exit_time::date = %s
            """,
            (report_date,),
        ).fetchall()
    if not rows:
        return {"market": 0.0, "selection": 0.0, "residual": 0.0}
    market = sum(float(r["market_explained_pct"] or 0) for r in rows) / len(rows)
    selection = sum(float(r["news_explained_pct"] or 0) for r in rows) / len(rows)
    residual = sum(float(r["residual_pct"] or 0) for r in rows) / len(rows)
    return {
        "market": round(market, 6),
        "selection": round(selection, 6),
        "residual": round(residual, 6),
    }


def _get_snapshot_summary(pg: PostgresStore, report_date: date) -> dict[str, Any]:
    """Latest snapshot for the day."""
    with pg.get_conn() as conn:
        snap = conn.execute(
            """
            SELECT total_value_usd, cash_usd, invested_usd, daily_pnl_usd,
                   daily_return, cumulative_return, max_drawdown, trading_pnl
            FROM swing_snapshots
            WHERE time::date <= %s
            ORDER BY time DESC LIMIT 1
            """,
            (report_date,),
        ).fetchone()
    return dict(snap) if snap else {}


def _get_macro_summary(pg: PostgresStore, report_date: date) -> dict[str, Any]:
    """Most recent macro snapshot for the day."""
    with pg.get_conn() as conn:
        macro = conn.execute(
            """
            SELECT time, macro_score AS score, regime, vix, dxy,
                   risk_off_score, yield_curve_score, btc_momentum_20d
            FROM swing_macro_snapshots
            WHERE time::date <= %s
            ORDER BY time DESC LIMIT 1
            """,
            (report_date,),
        ).fetchone()
    return dict(macro) if macro else {}


def generate_daily_report(
    pg: PostgresStore,
    report_date: date | None = None,
    refresh_data: bool = True,
) -> dict[str, Any]:
    """Generate post-market daily report and persist to swing_daily_report.

    If refresh_data=True (default), recompute MFE/MAE/event_study/news for
    all positions before aggregating.
    """
    if report_date is None:
        report_date = date.today()

    # 1. Refresh post-mortem data
    if refresh_data:
        try:
            mfe_result = mfe_backfill_all(pg, include_open=True)
            logger.info(f"MFE refresh: {mfe_result}")
            es_result = backfill_event_study_all(pg)
            logger.info(f"Event study refresh: {es_result}")
            cf_result = backfill_counterfactuals_all(pg)
            logger.info(f"Counterfactual refresh: {cf_result}")
        except Exception as e:
            logger.warning(f"Refresh step failed (continuing): {e}")

    # 2. Closed today
    with pg.get_conn() as conn:
        closed_today = conn.execute(
            """
            SELECT position_id, symbol, realized_pnl, realized_pct, hold_days, exit_reason
            FROM swing_positions
            WHERE status='closed' AND exit_time::date = %s
            ORDER BY exit_time
            """,
            (report_date,),
        ).fetchall()
        open_pos = conn.execute(
            """
            SELECT position_id, symbol, qty, entry_price, current_price, unrealized_pct
            FROM swing_positions WHERE status='open'
            """,
        ).fetchall()

    closed_today = [dict(r) for r in closed_today]
    open_pos = [dict(r) for r in open_pos]

    # 3. News attribution for today's closed + open
    for p in closed_today + open_pos:
        try:
            attribute_news_for_position(pg, p["position_id"])
        except Exception as e:
            logger.warning(f"News attribution failed for {p['position_id']}: {e}")

    # 4. Metrics
    metrics = _rolling_decision_metrics(pg, n=30)
    brinson = _brinson_decomposition(pg, report_date)
    snap = _get_snapshot_summary(pg, report_date)
    macro = _get_macro_summary(pg, report_date)

    closed_pnl = sum(float(r["realized_pnl"] or 0) for r in closed_today)

    # 5. Top news today (all attribution rows with publish_date == report_date)
    with pg.get_conn() as conn:
        top_news = conn.execute(
            """
            SELECT n.position_id, n.symbol, n.news_headline, n.news_source,
                   n.news_published_at, n.relevance, n.sentiment, n.sec_8k_item
            FROM swing_news_attribution n
            WHERE n.news_published_at::date = %s
            ORDER BY n.relevance DESC
            LIMIT 10
            """,
            (report_date,),
        ).fetchall()
    top_news = [dict(r) for r in top_news]

    # 6. Persist
    import json as _json

    with pg.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO swing_daily_report (
                report_date, daily_pnl, cumulative_return, drawdown_from_peak,
                regime, macro_score, vix,
                closed_count, closed_pnl, closed_position_ids,
                open_count, open_position_ids,
                rolling_30_trades, rolling_30_win_rate, rolling_30_expectancy_pct,
                rolling_30_sqn, rolling_30_information_coefficient, rolling_30_auc,
                brinson_market, brinson_sector, brinson_selection, brinson_residual,
                top_news_today, generated_at
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s::jsonb, NOW()
            )
            ON CONFLICT (report_date) DO UPDATE SET
                daily_pnl = EXCLUDED.daily_pnl,
                cumulative_return = EXCLUDED.cumulative_return,
                drawdown_from_peak = EXCLUDED.drawdown_from_peak,
                regime = EXCLUDED.regime,
                macro_score = EXCLUDED.macro_score,
                vix = EXCLUDED.vix,
                closed_count = EXCLUDED.closed_count,
                closed_pnl = EXCLUDED.closed_pnl,
                closed_position_ids = EXCLUDED.closed_position_ids,
                open_count = EXCLUDED.open_count,
                open_position_ids = EXCLUDED.open_position_ids,
                rolling_30_trades = EXCLUDED.rolling_30_trades,
                rolling_30_win_rate = EXCLUDED.rolling_30_win_rate,
                rolling_30_expectancy_pct = EXCLUDED.rolling_30_expectancy_pct,
                rolling_30_sqn = EXCLUDED.rolling_30_sqn,
                rolling_30_information_coefficient = EXCLUDED.rolling_30_information_coefficient,
                rolling_30_auc = EXCLUDED.rolling_30_auc,
                brinson_market = EXCLUDED.brinson_market,
                brinson_selection = EXCLUDED.brinson_selection,
                brinson_residual = EXCLUDED.brinson_residual,
                top_news_today = EXCLUDED.top_news_today,
                generated_at = NOW()
            """,
            (
                report_date,
                float(snap.get("daily_pnl_usd") or 0),
                float(snap.get("cumulative_return") or 0),
                float(snap.get("max_drawdown") or 0),
                macro.get("regime"),
                float(macro.get("score") or 0) if macro else None,
                float(macro.get("vix") or 0) if macro else None,
                len(closed_today),
                closed_pnl,
                [p["position_id"] for p in closed_today],
                len(open_pos),
                [p["position_id"] for p in open_pos],
                metrics.get("n"),
                metrics.get("win_rate"),
                metrics.get("expectancy_pct"),
                metrics.get("sqn"),
                metrics.get("information_coefficient"),
                metrics.get("auc"),
                brinson["market"],
                0.0,  # sector (placeholder)
                brinson["selection"],
                brinson["residual"],
                _json.dumps(top_news, default=str),
            ),
        )
        conn.commit()

    return {
        "report_date": report_date.isoformat(),
        "closed_count": len(closed_today),
        "closed_pnl": closed_pnl,
        "open_count": len(open_pos),
        "metrics": metrics,
        "brinson": brinson,
        "macro": macro,
        "snap": snap,
        "top_news_count": len(top_news),
    }


def format_telegram_digest(report: dict) -> str:
    """Format a concise Telegram message from generate_daily_report output."""
    m = report.get("metrics", {})
    b = report.get("brinson", {})
    macro = report.get("macro", {})

    lines = [
        f"📊 *Daily Post-Market Report — {report['report_date']}*",
        "",
        f"💰 Closed: {report['closed_count']} trades, P&L ${report['closed_pnl']:+.2f}",
        f"📂 Open positions: {report['open_count']}",
        "",
        "*Rolling 30-trade*",
        f"  Win rate: {(m.get('win_rate', 0) * 100):.1f}%",
        f"  Expectancy: {m.get('expectancy_pct', 0):+.2f}%",
        f"  SQN: {m.get('sqn') if m.get('sqn') is not None else '—'}",
        f"  IC (score→PnL): {m.get('information_coefficient') if m.get('information_coefficient') is not None else '—'}",
        f"  AUC: {m.get('auc') if m.get('auc') is not None else '—'}",
        "",
        "*P&L Attribution (avg per closed trade)*",
        f"  Market (β·Rm): {b.get('market', 0) * 100:+.2f}%",
        f"  Selection (AR): {b.get('selection', 0) * 100:+.2f}%",
        f"  Residual: {b.get('residual', 0) * 100:+.2f}%",
    ]

    if macro:
        lines.extend([
            "",
            "*Macro snapshot*",
            f"  Regime: {macro.get('regime', '—')}",
            f"  Score: {float(macro.get('score') or 0):.1f}, VIX: {float(macro.get('vix') or 0):.2f}",
        ])

    lines.append("")
    lines.append(f"News flagged today: {report['top_news_count']}")
    return "\n".join(lines)


def run_and_notify(
    pg: PostgresStore,
    notifier: TelegramNotifier,
    report_date: date | None = None,
    anthropic_key: str | None = None,
) -> dict:
    """Generate report + LLM narrative + Telegram digest. Used by scheduler."""
    import asyncio as _asyncio

    rep = generate_daily_report(pg, report_date=report_date, refresh_data=True)

    # LLM daily narrative
    try:
        cf_agg = aggregate_counterfactuals(pg)
        narr = generate_daily_narrative(anthropic_key, rep, cf_agg)
        update_daily_with_narrative(pg, rep["report_date"], narr)
        rep["llm_narrative"] = narr
    except Exception as e:
        logger.warning(f"Daily narrative failed: {e}")

    # LLM per-trade narratives for closed-today positions (only |R|>1 or hold>5d)
    if rep.get("closed_count", 0) > 0:
        try:
            with pg.get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM swing_trade_postmortem
                    WHERE exit_time::date = %s AND llm_narrative_at IS NULL
                    """,
                    (rep["report_date"] if isinstance(rep["report_date"], date)
                     else date.fromisoformat(rep["report_date"]),),
                ).fetchall()
            for r in rows:
                pm = dict(r)
                cf = pm.get("counterfactual_exits") or None
                narr = generate_trade_narrative(anthropic_key, pm, cf)
                update_postmortem_with_narrative(pg, pm["position_id"], narr)
        except Exception as e:
            logger.warning(f"Per-trade narrative failed: {e}")

    try:
        msg = format_telegram_digest(rep)
        # Append LLM narrative if available
        if rep.get("llm_narrative", {}).get("narrative"):
            msg += "\n\n*AI 분석*\n" + rep["llm_narrative"]["narrative"]
        _asyncio.run(notifier.send(msg))
    except Exception as e:
        logger.warning(f"Telegram digest send failed: {e}")
    return rep
