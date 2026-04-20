"""PostgresStore + RedisCache — swing_ 테이블 전용 저장소."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import psycopg
import redis
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# PostgresStore
# ═══════════════════════════════════════════════════════════

class PostgresStore:
    """psycopg3 + dict_row 기반 swing 데이터 저장소."""

    def __init__(self, dsn: str):
        self.dsn = dsn.replace("postgresql+psycopg://", "postgresql://")

    @contextmanager
    def get_conn(self):
        conn = psycopg.connect(self.dsn, row_factory=dict_row)
        try:
            yield conn
        finally:
            conn.close()

    # ─── Universe ─────────────────────────────────────────

    def upsert_universe(self, symbols: list[dict]) -> int:
        """유니버스 종목 upsert. 반환: 건수."""
        with self.get_conn() as conn:
            for s in symbols:
                conn.execute("""
                    INSERT INTO swing_universe
                        (symbol, company_name, sector, market_cap, index_member, is_active, updated_at)
                    VALUES (%s, %s, %s, %s, %s, true, now())
                    ON CONFLICT (symbol) DO UPDATE SET
                        company_name = EXCLUDED.company_name,
                        sector = EXCLUDED.sector,
                        market_cap = EXCLUDED.market_cap,
                        index_member = EXCLUDED.index_member,
                        is_active = true,
                        updated_at = now()
                """, (s["symbol"], s.get("company_name", ""),
                      s.get("sector", ""), s.get("market_cap", 0),
                      s.get("index_member", "")))
            conn.commit()
        return len(symbols)

    def deactivate_missing(self, active_symbols: list[str]) -> int:
        """유니버스에서 빠진 종목 비활성화."""
        if not active_symbols:
            return 0
        with self.get_conn() as conn:
            cur = conn.execute("""
                UPDATE swing_universe SET is_active = false, updated_at = now()
                WHERE is_active = true AND symbol != ALL(%s)
            """, (active_symbols,))
            conn.commit()
            return cur.rowcount

    def get_universe(self) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT symbol, company_name, sector, market_cap, index_member
                FROM swing_universe WHERE is_active = true
                ORDER BY market_cap DESC
            """).fetchall()
        return [dict(r) for r in rows]

    # ─── Daily Prices (기존 테이블 재사용) ────────────────

    def upsert_daily_prices(self, rows: list[dict]) -> int:
        """daily_prices에 OHLCV 데이터 upsert."""
        with self.get_conn() as conn:
            for r in rows:
                conn.execute("""
                    INSERT INTO daily_prices (time, symbol, open, high, low, close, volume)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (time, symbol) DO UPDATE SET
                        open = EXCLUDED.open, high = EXCLUDED.high,
                        low = EXCLUDED.low, close = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """, (r["time"], r["symbol"], r["open"], r["high"],
                      r["low"], r["close"], r["volume"]))
            conn.commit()
        return len(rows)

    def get_daily_prices(self, symbol: str, days: int = 250) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT time, symbol, open, high, low, close, volume
                FROM daily_prices
                WHERE symbol = %s AND time >= now() - make_interval(days => %s)
                ORDER BY time
            """, (symbol, days)).fetchall()
        return [dict(r) for r in rows]

    def get_all_daily_prices(self, symbols: list[str], days: int = 250) -> list[dict]:
        """여러 종목 일봉 한번에 조회."""
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT time, symbol, open, high, low, close, volume
                FROM daily_prices
                WHERE symbol = ANY(%s) AND time >= now() - make_interval(days => %s)
                ORDER BY symbol, time
            """, (symbols, days)).fetchall()
        return [dict(r) for r in rows]

    # ─── Indicators ───────────────────────────────────────

    def upsert_indicators(self, rows: list[dict]) -> int:
        """swing_indicators upsert."""
        with self.get_conn() as conn:
            for r in rows:
                conn.execute("""
                    INSERT INTO swing_indicators
                        (time, symbol, close, sma_50, sma_200, return_20d,
                         return_20d_rank, high_5d, volume, volume_avg_20d,
                         volume_ratio, trend_aligned, breakout_5d, volume_surge)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (time, symbol) DO UPDATE SET
                        close = EXCLUDED.close,
                        sma_50 = EXCLUDED.sma_50,
                        sma_200 = EXCLUDED.sma_200,
                        return_20d = EXCLUDED.return_20d,
                        return_20d_rank = EXCLUDED.return_20d_rank,
                        high_5d = EXCLUDED.high_5d,
                        volume = EXCLUDED.volume,
                        volume_avg_20d = EXCLUDED.volume_avg_20d,
                        volume_ratio = EXCLUDED.volume_ratio,
                        trend_aligned = EXCLUDED.trend_aligned,
                        breakout_5d = EXCLUDED.breakout_5d,
                        volume_surge = EXCLUDED.volume_surge
                """, (r["time"], r["symbol"], r["close"], r["sma_50"],
                      r["sma_200"], r["return_20d"], r["return_20d_rank"],
                      r["high_5d"], r["volume"], r["volume_avg_20d"],
                      r["volume_ratio"], r["trend_aligned"],
                      r["breakout_5d"], r["volume_surge"]))
            conn.commit()
        return len(rows)

    def get_latest_indicators(self) -> list[dict]:
        """최신 날짜 기준 전체 indicators."""
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM swing_indicators
                WHERE time = (SELECT MAX(time) FROM swing_indicators)
                ORDER BY return_20d_rank DESC NULLS LAST
            """).fetchall()
        return [dict(r) for r in rows]

    def get_indicator_history(self, symbol: str, days: int = 60) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM swing_indicators
                WHERE symbol = %s AND time >= now() - make_interval(days => %s)
                ORDER BY time
            """, (symbol, days)).fetchall()
        return [dict(r) for r in rows]

    # ─── Signals ──────────────────────────────────────────

    def insert_signal(self, sig: dict) -> int:
        """시그널 삽입, signal_id 반환."""
        with self.get_conn() as conn:
            row = conn.execute("""
                INSERT INTO swing_signals
                    (symbol, signal_type, entry_price, stop_loss, take_profit,
                     return_20d_rank, trend_aligned, breakout_5d, volume_surge,
                     exit_reason, position_id, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING signal_id
            """, (sig["symbol"], sig["signal_type"], sig.get("entry_price"),
                  sig.get("stop_loss"), sig.get("take_profit"),
                  sig.get("return_20d_rank"), sig.get("trend_aligned"),
                  sig.get("breakout_5d"), sig.get("volume_surge"),
                  sig.get("exit_reason"), sig.get("position_id"),
                  sig.get("status", "pending"))).fetchone()
            conn.commit()
        return row["signal_id"]

    def get_signals(self, status: str | None = None, limit: int = 50) -> list[dict]:
        with self.get_conn() as conn:
            if status:
                rows = conn.execute("""
                    SELECT * FROM swing_signals
                    WHERE status = %s ORDER BY time DESC LIMIT %s
                """, (status, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM swing_signals
                    ORDER BY time DESC LIMIT %s
                """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_signal(self, signal_id: int) -> dict | None:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT * FROM swing_signals
                WHERE signal_id = %s ORDER BY time DESC LIMIT 1
            """, (signal_id,)).fetchone()
        return dict(row) if row else None

    def approve_signal(self, signal_id: int) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute("""
                UPDATE swing_signals
                SET status = 'approved', approved_at = now()
                WHERE signal_id = %s AND status = 'pending'
            """, (signal_id,))
            conn.commit()
            return cur.rowcount > 0

    def reject_signal(self, signal_id: int) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute("""
                UPDATE swing_signals SET status = 'rejected'
                WHERE signal_id = %s AND status IN ('pending', 'approved')
            """, (signal_id,))
            conn.commit()
            return cur.rowcount > 0

    def mark_signal_executed(self, signal_id: int, position_id: int = None) -> bool:
        with self.get_conn() as conn:
            if position_id is not None:
                cur = conn.execute("""
                    UPDATE swing_signals
                    SET status = 'executed', executed_at = now(), position_id = %s
                    WHERE signal_id = %s AND status = 'approved'
                """, (position_id, signal_id))
            else:
                cur = conn.execute("""
                    UPDATE swing_signals
                    SET status = 'executed', executed_at = now()
                    WHERE signal_id = %s AND status = 'approved'
                """, (signal_id,))
            conn.commit()
            return cur.rowcount > 0

    def expire_old_signals(self, hours: int = 24) -> int:
        with self.get_conn() as conn:
            cur = conn.execute("""
                UPDATE swing_signals SET status = 'expired'
                WHERE status = 'pending'
                  AND time < now() - make_interval(hours => %s)
            """, (hours,))
            conn.commit()
            return cur.rowcount

    def get_today_entry_count(self) -> int:
        """오늘 체결된 ENTRY 시그널 수 (executed만 카운트, approved는 일시 상태이므로 제외)."""
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT count(*) as cnt FROM swing_signals
                WHERE signal_type = 'ENTRY'
                  AND status = 'executed'
                  AND time::date = CURRENT_DATE
            """).fetchone()
        return row["cnt"]

    # ─── Positions ────────────────────────────────────────

    def open_position(self, pos: dict) -> int:
        """포지션 오픈, position_id 반환."""
        with self.get_conn() as conn:
            row = conn.execute("""
                INSERT INTO swing_positions
                    (symbol, side, qty, entry_price, stop_loss, take_profit,
                     status, signal_id, is_paper)
                VALUES (%s,%s,%s,%s,%s,%s,'open',%s,%s)
                RETURNING position_id
            """, (pos["symbol"], pos.get("side", "BUY"), pos["qty"],
                  pos["entry_price"], pos["stop_loss"], pos["take_profit"],
                  pos.get("signal_id"), pos.get("is_paper", True))).fetchone()
            conn.commit()
        return row["position_id"]

    def close_position(self, position_id: int, exit_price: float,
                       exit_reason: str) -> bool:
        with self.get_conn() as conn:
            # 먼저 포지션 정보 조회
            pos = conn.execute("""
                SELECT entry_price, qty FROM swing_positions
                WHERE position_id = %s AND status = 'open'
            """, (position_id,)).fetchone()
            if not pos:
                return False
            entry = float(pos["entry_price"])
            qty = float(pos["qty"])
            realized_pnl = (exit_price - entry) * qty
            realized_pct = (exit_price - entry) / entry
            hold_days_q = conn.execute("""
                SELECT EXTRACT(DAY FROM now() - entry_time)::int as d
                FROM swing_positions WHERE position_id = %s
            """, (position_id,)).fetchone()
            hold_days = hold_days_q["d"] if hold_days_q else 0

            conn.execute("""
                UPDATE swing_positions SET
                    status = 'closed', exit_price = %s, exit_time = now(),
                    exit_reason = %s, realized_pnl = %s, realized_pct = %s,
                    hold_days = %s
                WHERE position_id = %s
            """, (exit_price, exit_reason, realized_pnl, realized_pct,
                  hold_days, position_id))
            conn.commit()
            return True

    def get_open_positions(self) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM swing_positions
                WHERE status = 'open' ORDER BY entry_time DESC
            """).fetchall()
        return [dict(r) for r in rows]

    def get_closed_positions(self, limit: int = 50) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM swing_positions
                WHERE status = 'closed' ORDER BY exit_time DESC LIMIT %s
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def update_position_price(self, position_id: int, current_price: float) -> None:
        with self.get_conn() as conn:
            conn.execute("""
                UPDATE swing_positions SET
                    current_price = %s,
                    unrealized_pnl = (%s - entry_price) * qty,
                    unrealized_pct = (%s - entry_price) / entry_price
                WHERE position_id = %s AND status = 'open'
            """, (current_price, current_price, current_price, position_id))
            conn.commit()

    def update_position_stop_loss(self, position_id: int, new_sl: float) -> None:
        """포지션 stop_loss 업데이트 (trailing stop용)."""
        with self.get_conn() as conn:
            conn.execute("""
                UPDATE swing_positions SET stop_loss = %s
                WHERE position_id = %s AND status = 'open'
            """, (new_sl, position_id))
            conn.commit()

    def update_high_water_mark(self, position_id: int, hwm: float) -> None:
        """포지션 high water mark 업데이트."""
        with self.get_conn() as conn:
            conn.execute("""
                UPDATE swing_positions SET high_water_mark = %s
                WHERE position_id = %s AND status = 'open'
            """, (hwm, position_id))
            conn.commit()

    def activate_trailing_stop(self, position_id: int) -> None:
        """Trailing stop 활성화 플래그 설정."""
        with self.get_conn() as conn:
            conn.execute("""
                UPDATE swing_positions SET trailing_stop_active = true
                WHERE position_id = %s AND status = 'open'
            """, (position_id,))
            conn.commit()

    def partial_close_position(self, position_id: int, exit_qty: float,
                               exit_price: float) -> bool:
        """분할 청산: qty 감소 + partial_exited=true + 실현손익 기록.

        실현손익 계산: (exit_price - entry_price) * exit_qty
        남은 수량: original_qty - exit_qty
        """
        with self.get_conn() as conn:
            pos = conn.execute("""
                SELECT entry_price, qty FROM swing_positions
                WHERE position_id = %s AND status = 'open'
            """, (position_id,)).fetchone()
            if not pos:
                return False

            entry = float(pos["entry_price"])
            partial_pnl = (exit_price - entry) * exit_qty
            new_qty = float(pos["qty"]) - exit_qty

            conn.execute("""
                UPDATE swing_positions SET
                    qty = %s,
                    partial_exited = true,
                    realized_pnl = COALESCE(realized_pnl, 0) + %s
                WHERE position_id = %s AND status = 'open'
            """, (max(new_qty, 0), partial_pnl, position_id))
            conn.commit()
            return True

    def get_open_position_count(self) -> int:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT count(*) as cnt FROM swing_positions WHERE status = 'open'
            """).fetchone()
        return row["cnt"]

    def has_open_position(self, symbol: str) -> bool:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT count(*) as cnt FROM swing_positions
                WHERE symbol = %s AND status = 'open'
            """, (symbol,)).fetchone()
        return row["cnt"] > 0

    # ─── Trades ───────────────────────────────────────────

    def insert_trade(self, trade: dict) -> int:
        total_amount = trade.get("total_amount", trade["qty"] * trade["price"])
        # 수수료 자동 계산 (commission_rate config, 기본 0.25%)
        if trade.get("commission") is not None and trade["commission"] > 0:
            commission = trade["commission"]
        else:
            rate = float(self.get_config_value("commission_rate", "0.0025"))
            commission = round(total_amount * rate, 4)
        with self.get_conn() as conn:
            row = conn.execute("""
                INSERT INTO swing_trades
                    (position_id, signal_id, symbol, side, qty, price,
                     total_amount, order_id, commission, is_paper)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING trade_id
            """, (trade.get("position_id"), trade.get("signal_id"),
                  trade["symbol"], trade["side"], trade["qty"],
                  trade["price"], total_amount,
                  trade.get("order_id"), commission,
                  trade.get("is_paper", True))).fetchone()
            conn.commit()
        return row["trade_id"]

    def get_total_commissions(self) -> dict:
        """전체 수수료 합계 조회."""
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT coalesce(sum(commission), 0) as total_commission,
                       coalesce(sum(case when side='BUY' then commission else 0 end), 0) as buy_commission,
                       coalesce(sum(case when side='SELL' then commission else 0 end), 0) as sell_commission,
                       coalesce(sum(total_amount), 0) as total_volume,
                       count(*) as trade_count
                FROM swing_trades
            """).fetchone()
        return dict(row)

    def get_trades(self, limit: int = 50) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM swing_trades ORDER BY executed_at DESC LIMIT %s
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ─── Snapshots ────────────────────────────────────────

    def insert_snapshot(self, snap: dict) -> None:
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO swing_snapshots
                    (total_value_usd, total_value_krw, cash_usd, invested_usd,
                     daily_pnl_usd, daily_return, cumulative_return,
                     max_drawdown, open_positions, exchange_rate, trading_pnl)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (snap["total_value_usd"], snap.get("total_value_krw"),
                  snap["cash_usd"], snap["invested_usd"],
                  snap.get("daily_pnl_usd"), snap.get("daily_return"),
                  snap.get("cumulative_return"), snap.get("max_drawdown"),
                  snap.get("open_positions", 0), snap.get("exchange_rate"),
                  snap.get("trading_pnl", 0)))
            conn.commit()

    def get_snapshots(self, days: int = 30) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT * FROM swing_snapshots
                WHERE time >= now() - make_interval(days => %s)
                ORDER BY time
            """, (days,)).fetchall()
        return [dict(r) for r in rows]

    def get_latest_snapshot(self) -> dict | None:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT * FROM swing_snapshots ORDER BY time DESC LIMIT 1
            """).fetchone()
        return dict(row) if row else None

    # ─── Config ───────────────────────────────────────────

    def get_config(self, key: str | None = None) -> dict | list[dict]:
        with self.get_conn() as conn:
            if key:
                row = conn.execute("""
                    SELECT * FROM swing_config WHERE key = %s
                """, (key,)).fetchone()
                return dict(row) if row else {}
            rows = conn.execute("""
                SELECT * FROM swing_config ORDER BY category, key
            """).fetchall()
        return [dict(r) for r in rows]

    def update_config(self, key: str, value: str) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute("""
                UPDATE swing_config SET value = %s, updated_at = now()
                WHERE key = %s
            """, (value, key))
            conn.commit()
            return cur.rowcount > 0

    def get_config_value(self, key: str, default: str = "") -> str:
        cfg = self.get_config(key)
        return cfg.get("value", default) if cfg else default

    # ─── Pipeline Log ─────────────────────────────────────

    def insert_pipeline_log(self, step: str, status: str,
                            elapsed: float = 0, details: dict | None = None,
                            error_msg: str | None = None) -> None:
        with self.get_conn() as conn:
            conn.execute("""
                INSERT INTO swing_pipeline_log
                    (step_name, status, elapsed_sec, details, error_msg)
                VALUES (%s, %s, %s, %s, %s)
            """, (step, status, elapsed,
                  json.dumps(details) if details else "{}",
                  error_msg))
            conn.commit()

    # ─── Backtest ─────────────────────────────────────────

    def insert_backtest_run(self, run: dict) -> int:
        with self.get_conn() as conn:
            row = conn.execute("""
                INSERT INTO swing_backtest_runs
                    (start_date, end_date, initial_capital, final_value,
                     total_return, cagr, max_drawdown, sharpe_ratio,
                     win_rate, total_trades, profit_factor, avg_hold_days,
                     params, equity_curve, trades_log)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING run_id
            """, (run["start_date"], run["end_date"], run["initial_capital"],
                  run["final_value"], run["total_return"], run["cagr"],
                  run["max_drawdown"], run["sharpe_ratio"], run["win_rate"],
                  run["total_trades"], run["profit_factor"],
                  run.get("avg_hold_days"),
                  json.dumps(run.get("params", {})),
                  json.dumps(run.get("equity_curve", [])),
                  json.dumps(run.get("trades_log", [])))).fetchone()
            conn.commit()
        return row["run_id"]

    def get_backtest_runs(self, limit: int = 20) -> list[dict]:
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT run_id, start_date, end_date, initial_capital,
                       final_value, total_return, cagr, max_drawdown,
                       sharpe_ratio, win_rate, total_trades, profit_factor,
                       avg_hold_days, created_at
                FROM swing_backtest_runs ORDER BY created_at DESC LIMIT %s
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_backtest_run(self, run_id: int) -> dict | None:
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT * FROM swing_backtest_runs WHERE run_id = %s
            """, (run_id,)).fetchone()
        return dict(row) if row else None

    # ─── Capital Events ────────────────────────────────────

    def insert_capital_event(self, event_type: str, amount: float, note: str = "") -> int:
        """자금 이벤트 기록 (deposit/withdraw)."""
        with self.get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO swing_capital_events (event_type, amount, note)
                VALUES (%s, %s, %s) RETURNING event_id
            """, (event_type, amount, note))
            conn.commit()
            row = cur.fetchone()
            return row["event_id"]

    def get_capital_events(self) -> list[dict]:
        """전체 자금 이벤트 조회."""
        with self.get_conn() as conn:
            rows = conn.execute("""
                SELECT event_id, event_type, amount, note, created_at
                FROM swing_capital_events ORDER BY created_at
            """).fetchall()
        return [dict(r) for r in rows]

    def get_total_capital_adjustments(self) -> float:
        """총 자금 투입/출금 합계 (deposits - withdrawals)."""
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT COALESCE(
                    SUM(CASE WHEN event_type = 'deposit' THEN amount
                             WHEN event_type = 'withdraw' THEN -amount
                             ELSE 0 END), 0) as net
                FROM swing_capital_events
            """).fetchone()
        return float(row["net"])

    # ─── Watchlist ─────────────────────────────────────────

    def upsert_watchlist(self, symbol: str, company_name: str = "",
                         avg_cost: float = 0, qty: float = 0, notes: str = "") -> int:
        with self.get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO swing_watchlist (symbol, company_name, avg_cost, qty, notes)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol) DO UPDATE SET
                    company_name = EXCLUDED.company_name,
                    avg_cost = EXCLUDED.avg_cost,
                    qty = EXCLUDED.qty,
                    notes = EXCLUDED.notes,
                    is_active = true,
                    updated_at = now()
                RETURNING watchlist_id
            """, (symbol.upper(), company_name, avg_cost, qty, notes))
            conn.commit()
            return cur.fetchone()["watchlist_id"]

    def get_watchlist(self, active_only: bool = True) -> list[dict]:
        with self.get_conn() as conn:
            sql = """SELECT watchlist_id, symbol, company_name, avg_cost, qty,
                            notes, is_active, added_at, updated_at
                     FROM swing_watchlist"""
            if active_only:
                sql += " WHERE is_active = true"
            sql += " ORDER BY symbol"
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def delete_watchlist(self, symbol: str) -> bool:
        with self.get_conn() as conn:
            cur = conn.execute("""
                UPDATE swing_watchlist SET is_active = false, updated_at = now()
                WHERE symbol = %s AND is_active = true
            """, (symbol.upper(),))
            conn.commit()
            return cur.rowcount > 0

    def insert_watchlist_alert(self, alert: dict) -> int:
        with self.get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO swing_watchlist_alerts
                    (symbol, alert_type, direction, confidence, reason,
                     current_price, target_price, stop_price, strategy, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING alert_id
            """, (alert["symbol"], alert["alert_type"], alert["direction"],
                  alert.get("confidence"), alert.get("reason"),
                  alert.get("current_price"), alert.get("target_price"),
                  alert.get("stop_price"), alert.get("strategy"),
                  json.dumps(alert.get("detail", {}))))
            conn.commit()
            return cur.fetchone()["alert_id"]

    def get_watchlist_alerts(self, symbol: str = None, limit: int = 50) -> list[dict]:
        with self.get_conn() as conn:
            sql = """SELECT alert_id, symbol, alert_type, direction, confidence,
                            reason, current_price, target_price, stop_price,
                            strategy, detail, notified, created_at
                     FROM swing_watchlist_alerts"""
            params = []
            if symbol:
                sql += " WHERE symbol = %s"
                params.append(symbol.upper())
            sql += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ─── Watchlist Signal Log ─────────────────────────────

    def upsert_watchlist_signal_log(self, log: dict) -> int:
        """Insert or update daily signal log entry (UPSERT on symbol+date)."""
        with self.get_conn() as conn:
            cur = conn.execute("""
                INSERT INTO swing_watchlist_signal_log
                    (symbol, signal_date, direction, weighted_score, confidence,
                     current_price, regime, category_scores, category_weights,
                     vol_ratio, vol_factor, target_price, stop_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb,
                        %s, %s, %s, %s)
                ON CONFLICT (symbol, signal_date) DO UPDATE SET
                    direction = EXCLUDED.direction,
                    weighted_score = EXCLUDED.weighted_score,
                    confidence = EXCLUDED.confidence,
                    current_price = EXCLUDED.current_price,
                    regime = EXCLUDED.regime,
                    category_scores = EXCLUDED.category_scores,
                    category_weights = EXCLUDED.category_weights,
                    vol_ratio = EXCLUDED.vol_ratio,
                    vol_factor = EXCLUDED.vol_factor,
                    target_price = EXCLUDED.target_price,
                    stop_price = EXCLUDED.stop_price,
                    created_at = now()
                RETURNING log_id
            """, (log["symbol"], log["signal_date"], log["direction"],
                  log["weighted_score"], log["confidence"], log["current_price"],
                  log.get("regime"), json.dumps(log.get("category_scores", {})),
                  json.dumps(log.get("category_weights", {})),
                  log.get("vol_ratio"), log.get("vol_factor"),
                  log.get("target_price"), log.get("stop_price")))
            conn.commit()
            return cur.fetchone()["log_id"]

    def get_watchlist_signal_logs(self, symbol: str = None,
                                  start_date=None, end_date=None,
                                  limit: int = 500) -> list[dict]:
        """Retrieve signal logs for replay backtest."""
        with self.get_conn() as conn:
            conditions = []
            params = []
            if symbol:
                conditions.append("symbol = %s")
                params.append(symbol.upper())
            if start_date:
                conditions.append("signal_date >= %s")
                params.append(start_date)
            if end_date:
                conditions.append("signal_date <= %s")
                params.append(end_date)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = f"""SELECT log_id, symbol, signal_date, direction, weighted_score,
                             confidence, current_price, regime, vol_ratio, vol_factor,
                             target_price, stop_price, created_at
                      FROM swing_watchlist_signal_log {where}
                      ORDER BY signal_date, symbol LIMIT %s"""
            params.append(limit)
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_watchlist_signal_log_stats(self) -> dict:
        """Signal log summary stats."""
        with self.get_conn() as conn:
            row = conn.execute("""
                SELECT count(*) as total,
                       count(DISTINCT symbol) as symbols,
                       count(DISTINCT signal_date) as days,
                       min(signal_date) as first_date,
                       max(signal_date) as last_date,
                       count(*) FILTER (WHERE direction IN ('STRONG_BUY','BUY')) as buy_count,
                       count(*) FILTER (WHERE direction = 'NEUTRAL') as neutral_count,
                       count(*) FILTER (WHERE direction IN ('STRONG_SELL','SELL')) as sell_count
                FROM swing_watchlist_signal_log
            """).fetchone()
            return dict(row) if row else {}

    # ─── Utility ──────────────────────────────────────────

    def health_check(self) -> bool:
        try:
            with self.get_conn() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
# RedisCache
# ═══════════════════════════════════════════════════════════

class RedisCache:
    """Redis 캐시 — 유니버스/indicators/스냅샷 캐싱."""

    def __init__(self, url: str = "redis://localhost:6379"):
        self.client = redis.from_url(url, decode_responses=True)
        self._prefix = "swing:"

    def _key(self, name: str) -> str:
        return f"{self._prefix}{name}"

    # ── Universe cache ──
    def set_universe(self, symbols: list[dict], ttl: int = 86400) -> None:
        self.client.setex(self._key("universe"), ttl, json.dumps(symbols))

    def get_universe(self) -> list[dict] | None:
        raw = self.client.get(self._key("universe"))
        return json.loads(raw) if raw else None

    # ── Latest indicators cache ──
    def set_indicators(self, data: list[dict], ttl: int = 3600) -> None:
        serializable = []
        for row in data:
            r = {}
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
                elif hasattr(v, "item"):
                    r[k] = v.item()
                else:
                    r[k] = v
            serializable.append(r)
        self.client.setex(self._key("indicators"), ttl, json.dumps(serializable))

    def get_indicators(self) -> list[dict] | None:
        raw = self.client.get(self._key("indicators"))
        return json.loads(raw) if raw else None

    # ── Snapshot cache ──
    def set_snapshot(self, data: dict, ttl: int = 3600) -> None:
        serializable = {}
        for k, v in data.items():
            if hasattr(v, "isoformat"):
                serializable[k] = v.isoformat()
            elif hasattr(v, "item"):
                serializable[k] = v.item()
            else:
                serializable[k] = v
        self.client.setex(self._key("snapshot"), ttl, json.dumps(serializable))

    def get_snapshot(self) -> dict | None:
        raw = self.client.get(self._key("snapshot"))
        return json.loads(raw) if raw else None

    # ── Generic ──
    def set_json(self, key: str, data: Any, ttl: int = 3600) -> None:
        self.client.setex(self._key(key), ttl, json.dumps(data, default=str))

    def get_json(self, key: str) -> Any | None:
        raw = self.client.get(self._key(key))
        return json.loads(raw) if raw else None

    def ping(self) -> bool:
        try:
            return self.client.ping()
        except Exception:
            return False
