"""Event Study (Fama-Fisher-Jensen-Roll 1969) — β estimation + Abnormal Return / CAR.

For each closed position:
  1. Estimate market model β from 252 trading days ending 3 days BEFORE entry
     (estimation window [-254, -3] to avoid contamination)
  2. For each trading day in [entry, exit], compute:
       AR_t = R_t - (α + β · R_market,t)
  3. Sum to get CAR (cumulative abnormal return) over the hold.

Used to attribute holding-period P&L to:
  - Market move (β · R_market) — explained by market
  - News/idiosyncratic (AR) — explained by news + residual
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

BENCHMARK = "SPY"
ESTIMATION_WINDOW_DAYS = 252
ESTIMATION_GAP_DAYS = 3


def _get_returns(pg: PostgresStore, symbol: str, start: date, end: date) -> list[dict]:
    """Daily adj_close returns from daily_prices. Returns [{date, ret}]."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT time::date AS d, adj_close, close
            FROM daily_prices
            WHERE symbol = %s AND time::date >= %s AND time::date <= %s
            ORDER BY time
            """,
            (symbol, start, end),
        ).fetchall()
    if len(rows) < 2:
        return []
    series = []
    for i in range(1, len(rows)):
        prev = float(rows[i - 1]["adj_close"] or rows[i - 1]["close"])
        curr = float(rows[i]["adj_close"] or rows[i]["close"])
        if prev > 0:
            series.append({"date": rows[i]["d"], "ret": (curr - prev) / prev})
    return series


def _yf_returns_fallback(symbol: str, start: date, end: date) -> list[dict]:
    """Fetch from yfinance when daily_prices has gap."""
    try:
        # yfinance end is exclusive; +1 day
        df = yf.download(
            symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return []
        # Handle MultiIndex columns (yfinance 0.2+ returns MultiIndex for single ticker too)
        if isinstance(df.columns, type(df.columns)) and hasattr(df.columns, "levels"):
            # Flatten MultiIndex
            try:
                closes = df["Close"][symbol] if (symbol,) in df["Close"] else df["Close"].iloc[:, 0]
            except Exception:
                closes = df.xs("Close", level=0, axis=1).iloc[:, 0]
        else:
            closes = df["Close"]
        rets = closes.pct_change().dropna()
        return [{"date": idx.date(), "ret": float(r)} for idx, r in rets.items()]
    except Exception as e:
        logger.warning(f"yfinance fallback for {symbol} failed: {e}")
        return []


def _get_benchmark_returns(pg: PostgresStore, start: date, end: date) -> dict[date, float]:
    """Benchmark (SPY) daily returns. Falls back to yfinance if DB has gap."""
    db_rets = _get_returns(pg, BENCHMARK, start, end)
    by_date = {r["date"]: r["ret"] for r in db_rets}

    # Check if we have data through `end` (within 5 trading days tolerance)
    max_db = max(by_date.keys()) if by_date else None
    if max_db is None or (end - max_db).days > 5:
        # Try yfinance fallback for gap
        gap_start = max_db + timedelta(days=1) if max_db else start
        yf_rets = _yf_returns_fallback(BENCHMARK, gap_start, end)
        for r in yf_rets:
            by_date[r["date"]] = r["ret"]
    return by_date


def _linear_regression(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """OLS y = α + β·x. Returns (α, β, r²)."""
    n = len(xs)
    if n < 30:
        return (0.0, 1.0, 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    var_x = sum((xs[i] - mx) ** 2 for i in range(n))
    if var_x < 1e-12:
        return (my, 0.0, 0.0)
    beta = cov / var_x
    alpha = my - beta * mx
    # r²
    ss_tot = sum((ys[i] - my) ** 2 for i in range(n))
    if ss_tot < 1e-12:
        return (alpha, beta, 0.0)
    ss_res = sum((ys[i] - (alpha + beta * xs[i])) ** 2 for i in range(n))
    r2 = max(0.0, 1.0 - ss_res / ss_tot)
    return (alpha, beta, r2)


def compute_event_study(pg: PostgresStore, position_id: int) -> dict[str, Any] | None:
    """Event study for a single position. Returns β, AR per day, CAR over hold.

    Returns None if insufficient data.
    """
    with pg.get_conn() as conn:
        pos = conn.execute(
            """
            SELECT position_id, symbol, entry_time, exit_time, status
            FROM swing_positions WHERE position_id = %s
            """,
            (position_id,),
        ).fetchone()
    if not pos:
        return None

    symbol = pos["symbol"]
    entry_date = pos["entry_time"].date() if hasattr(pos["entry_time"], "date") else pos["entry_time"]
    exit_date = (
        pos["exit_time"].date() if pos["exit_time"] and hasattr(pos["exit_time"], "date")
        else (pos["exit_time"] if pos["exit_time"] else date.today())
    )

    # Estimation window: 252 days ending 3 days before entry
    est_end = entry_date - timedelta(days=ESTIMATION_GAP_DAYS)
    est_start = est_end - timedelta(days=int(ESTIMATION_WINDOW_DAYS * 1.5))  # cal days vs trading days

    # Pull symbol + benchmark returns for both estimation + event windows
    sym_est = _get_returns(pg, symbol, est_start, est_end)
    bench_est_dict = _get_benchmark_returns(pg, est_start, est_end)

    if len(sym_est) < 60:
        logger.warning(f"Insufficient estimation data for position {position_id} ({symbol}): {len(sym_est)} days")
        return None

    # Align estimation
    xs, ys = [], []
    for r in sym_est:
        if r["date"] in bench_est_dict:
            xs.append(bench_est_dict[r["date"]])
            ys.append(r["ret"])

    if len(xs) < 60:
        logger.warning(f"Estimation overlap too small for position {position_id}: {len(xs)}")
        return None

    alpha, beta, r2 = _linear_regression(xs, ys)

    # Event window returns
    sym_event = _get_returns(pg, symbol, entry_date, exit_date)
    bench_event_dict = _get_benchmark_returns(pg, entry_date, exit_date)

    daily_ar = []
    cum_ar = 0.0
    cum_mkt_ret = 0.0
    entry_day_ar = None
    for r in sym_event:
        d = r["date"]
        if d not in bench_event_dict:
            continue
        bench_ret = bench_event_dict[d]
        expected = alpha + beta * bench_ret
        ar = r["ret"] - expected
        cum_ar += ar
        cum_mkt_ret += bench_ret * beta  # market explained
        if entry_day_ar is None and d >= entry_date:
            entry_day_ar = ar
        daily_ar.append({"date": d.isoformat(), "ret": r["ret"], "bench": bench_ret, "ar": ar})

    return {
        "position_id": position_id,
        "symbol": symbol,
        "beta": round(beta, 4),
        "alpha": round(alpha, 6),
        "r2": round(r2, 4),
        "estimation_days": len(xs),
        "entry_day_ar": round(entry_day_ar, 6) if entry_day_ar is not None else None,
        "cumulative_ar": round(cum_ar, 6),
        "market_return_during_hold": round(cum_mkt_ret, 6),
        "daily_ar": daily_ar,
    }


def update_postmortem_with_event_study(pg: PostgresStore, es: dict) -> None:
    """Patch swing_trade_postmortem with event study fields."""
    with pg.get_conn() as conn:
        # Get realized to compute attribution
        row = conn.execute(
            "SELECT realized_pct FROM swing_trade_postmortem WHERE position_id = %s",
            (es["position_id"],),
        ).fetchone()
        if not row:
            return

        realized = float(row["realized_pct"] or 0)
        market_pct = es["market_return_during_hold"]
        news_pct = es["cumulative_ar"]  # idiosyncratic = news + residual
        residual_pct = realized - market_pct - news_pct

        conn.execute(
            """
            UPDATE swing_trade_postmortem SET
                beta = %s,
                market_return_during_hold = %s,
                cumulative_ar = %s,
                entry_day_ar = %s,
                market_explained_pct = %s,
                news_explained_pct = %s,
                residual_pct = %s,
                computed_at = NOW()
            WHERE position_id = %s
            """,
            (
                es["beta"], market_pct, news_pct, es["entry_day_ar"],
                market_pct, news_pct, residual_pct,
                es["position_id"],
            ),
        )
        conn.commit()


def backfill_event_study_all(pg: PostgresStore) -> dict[str, int]:
    """Run event study for all positions in postmortem table."""
    with pg.get_conn() as conn:
        rows = conn.execute(
            "SELECT position_id FROM swing_trade_postmortem ORDER BY entry_time"
        ).fetchall()

    ok = 0
    failed = 0
    skipped = 0
    for r in rows:
        try:
            es = compute_event_study(pg, r["position_id"])
            if es is None:
                skipped += 1
                continue
            update_postmortem_with_event_study(pg, es)
            ok += 1
        except Exception as e:
            logger.warning(f"Event study failed for position {r['position_id']}: {e}")
            failed += 1

    return {"ok": ok, "skipped": skipped, "failed": failed, "total": len(rows)}
