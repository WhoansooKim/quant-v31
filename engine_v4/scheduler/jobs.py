"""APScheduler 잡 — KST 기준 스케줄링.

스케줄:
  월~토 07:00 KST  → 데이터 수집 + 시그널 스캔 + 알림
  월~금 23:30 KST  → 장중 청산 체크 (09:30 ET)
  화~토 01:00 KST  → 장중 청산 체크 (11:00 ET)
  화~토 03:00 KST  → 장중 청산 체크 (13:00 ET)
  토    10:00 KST  → 유니버스 주간 갱신
  매일  06:00 KST  → 만료 시그널 정리
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from engine_v4.config.settings import SwingSettings
from engine_v4.data.collector import DataCollector, UniverseManager
from engine_v4.data.storage import PostgresStore, RedisCache
from engine_v4.notify.telegram import TelegramNotifier
from engine_v4.risk.exit_manager import ExitManager
from engine_v4.strategy.swing import SwingStrategy

DEFAULT_INITIAL_CAPITAL = 2200.0

logger = logging.getLogger(__name__)

KST = pytz.timezone("Asia/Seoul")


class SwingScheduler:
    """APScheduler 기반 스케줄러."""

    def __init__(
        self,
        pg: PostgresStore,
        cache: RedisCache,
        settings: SwingSettings,
        universe_mgr: UniverseManager,
        collector: DataCollector,
        strategy: SwingStrategy,
        notifier: TelegramNotifier,
    ):
        self.pg = pg
        self.cache = cache
        self.cfg = settings
        self.universe_mgr = universe_mgr
        self.collector = collector
        self.strategy = strategy
        self.notifier = notifier
        self.exit_mgr = ExitManager(pg)
        self.scheduler = BackgroundScheduler(timezone=KST)
        self._setup_jobs()

    def _setup_jobs(self):
        """스케줄 잡 등록."""
        # 1) 매일 07:00 KST — 데이터 수집 + 시그널 스캔
        self.scheduler.add_job(
            self._job_daily_pipeline,
            CronTrigger(day_of_week="mon-sat", hour=7, minute=0, timezone=KST),
            id="daily_pipeline",
            name="Daily Pipeline (Collect + Scan + Notify)",
            replace_existing=True,
        )

        # 2) 장중 청산 체크 — 월~금 23:30 KST (09:30 ET)
        self.scheduler.add_job(
            self._job_exit_check,
            CronTrigger(day_of_week="mon-fri", hour=23, minute=30, timezone=KST),
            id="exit_check_1",
            name="Exit Check (09:30 ET)",
            replace_existing=True,
        )

        # 3) 장중 청산 체크 — 화~토 01:00 KST (11:00 ET)
        self.scheduler.add_job(
            self._job_exit_check,
            CronTrigger(day_of_week="tue-sat", hour=1, minute=0, timezone=KST),
            id="exit_check_2",
            name="Exit Check (11:00 ET)",
            replace_existing=True,
        )

        # 4) 장중 청산 체크 — 화~토 03:00 KST (13:00 ET)
        self.scheduler.add_job(
            self._job_exit_check,
            CronTrigger(day_of_week="tue-sat", hour=3, minute=0, timezone=KST),
            id="exit_check_3",
            name="Exit Check (13:00 ET)",
            replace_existing=True,
        )

        # 5) 토 10:00 KST — 유니버스 주간 갱신
        self.scheduler.add_job(
            self._job_refresh_universe,
            CronTrigger(day_of_week="sat", hour=10, minute=0, timezone=KST),
            id="refresh_universe",
            name="Weekly Universe Refresh",
            replace_existing=True,
        )

        # 6) 매일 06:00 KST — 만료 시그널 정리
        self.scheduler.add_job(
            self._job_expire_signals,
            CronTrigger(hour=6, minute=0, timezone=KST),
            id="expire_signals",
            name="Expire Old Signals",
            replace_existing=True,
        )

    def start(self):
        """스케줄러 시작."""
        self.scheduler.start()
        logger.info("Scheduler started with %d jobs", len(self.scheduler.get_jobs()))
        for job in self.scheduler.get_jobs():
            try:
                nrt = job.next_run_time
            except AttributeError:
                nrt = "N/A"
            logger.info(f"  Job: {job.id} → next run: {nrt}")

    def stop(self):
        """스케줄러 정지."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def get_jobs(self) -> list[dict]:
        """잡 목록 반환."""
        jobs = []
        for job in self.scheduler.get_jobs():
            try:
                next_run = str(job.next_run_time) if job.next_run_time else None
            except AttributeError:
                next_run = None
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": next_run,
            })
        return jobs

    # ─── Job Implementations ─────────────────────────

    def _job_daily_pipeline(self):
        """Step1 Collect → Step2 Scan → Step3 Notify."""
        start = time.time()
        self.pg.insert_pipeline_log("scheduled_pipeline", "started")

        try:
            # Step 1: 유니버스 확인 + 데이터 수집
            universe = self.universe_mgr.get_universe()
            if not universe:
                universe = self.universe_mgr.refresh_universe()
            symbols = [u["symbol"] for u in universe]

            price_count = self.collector.collect_prices(symbols, days=30)
            ind_count = self.collector.compute_indicators(symbols)

            # Step 2: 시그널 스캔
            entries = self.strategy.scan_entries()
            exits = self.strategy.scan_exits()

            # Step 3: 텔레그램 알림
            if entries or exits:
                asyncio.run(self.notifier.notify_signals(entries, exits))

            # Step 4: 스냅샷 생성
            self.generate_snapshot()

            elapsed = time.time() - start
            self.pg.insert_pipeline_log("scheduled_pipeline", "completed", elapsed, {
                "symbols": len(symbols),
                "prices": price_count,
                "indicators": ind_count,
                "entries": len(entries),
                "exits": len(exits),
            })
            logger.info(f"Daily pipeline done: {len(entries)} entries, "
                        f"{len(exits)} exits in {elapsed:.1f}s")

        except Exception as e:
            elapsed = time.time() - start
            self.pg.insert_pipeline_log("scheduled_pipeline", "failed",
                                        elapsed, error_msg=str(e))
            logger.error(f"Daily pipeline failed: {e}", exc_info=True)
            asyncio.run(self.notifier.notify_error("daily_pipeline", str(e)))

    def _job_exit_check(self):
        """오픈 포지션 청산 조건 체크 (Trailing Stop + Partial Exit + 기존 Exit)."""
        import yfinance as yf

        start = time.time()
        self.pg.insert_pipeline_log("exit_check", "started")

        try:
            positions = self.pg.get_open_positions()
            if not positions:
                self.pg.insert_pipeline_log("exit_check", "completed",
                                            time.time() - start,
                                            {"positions": 0, "exits": 0})
                return

            symbols = list(set(p["symbol"] for p in positions))

            # 현재가 조회 (yfinance)
            current_prices: dict[str, float] = {}
            try:
                data = yf.download(symbols, period="1d", progress=False)
                if len(symbols) == 1:
                    current_prices[symbols[0]] = float(data["Close"].iloc[-1])
                else:
                    for sym in symbols:
                        try:
                            current_prices[sym] = float(
                                data["Close"][sym].dropna().iloc[-1])
                        except (KeyError, IndexError):
                            pass
            except Exception as e:
                logger.warning(f"yfinance fetch for exit check: {e}")

            # 포지션별 현재가 업데이트
            for p in positions:
                cp = current_prices.get(p["symbol"])
                if cp:
                    self.pg.update_position_price(p["position_id"], cp)

            # Step 1: Trailing Stop 업데이트
            trailing_updated = self.exit_mgr.update_trailing_stops(
                positions, current_prices)

            # Step 2: Partial Exit 체크
            partial_actions = self.exit_mgr.check_partial_exits(
                positions, current_prices)
            for action in partial_actions:
                self.pg.partial_close_position(
                    action.position_id, action.exit_qty, action.current_price)
                # 분할 청산 trade 기록
                self.pg.insert_trade({
                    "position_id": action.position_id,
                    "symbol": action.symbol,
                    "side": "SELL",
                    "qty": action.exit_qty,
                    "price": action.current_price,
                    "is_paper": True,
                })
                # 시그널 생성
                sig = {
                    "symbol": action.symbol,
                    "signal_type": "EXIT",
                    "entry_price": action.current_price,
                    "exit_reason": "partial_exit",
                    "position_id": action.position_id,
                    "status": "executed",
                }
                self.pg.insert_signal(sig)
                logger.info(f"PARTIAL EXIT executed: {action.symbol} "
                            f"sold {action.exit_qty} @ ${action.current_price:.2f} "
                            f"(gain={action.gain_pct:+.1%})")

            # Step 3: 가격/지표 업데이트 + 기존 청산 스캔
            self.collector.collect_prices(symbols, days=5)
            self.collector.compute_indicators(symbols)
            exits = self.strategy.scan_exits()

            if exits:
                asyncio.run(self.notifier.notify_signals([], exits))

            # 스냅샷 생성
            self.generate_snapshot()

            elapsed = time.time() - start
            self.pg.insert_pipeline_log("exit_check", "completed", elapsed, {
                "positions": len(positions),
                "exits": len(exits),
                "trailing_updated": trailing_updated,
                "partial_exits": len(partial_actions),
            })
            logger.info(f"Exit check: {len(exits)} exit signals, "
                        f"{trailing_updated} trailing updates, "
                        f"{len(partial_actions)} partial exits "
                        f"from {len(positions)} positions in {elapsed:.1f}s")

        except Exception as e:
            self.pg.insert_pipeline_log("exit_check", "failed",
                                        time.time() - start, error_msg=str(e))
            logger.error(f"Exit check failed: {e}", exc_info=True)

    def _job_refresh_universe(self):
        """유니버스 주간 갱신."""
        start = time.time()
        self.pg.insert_pipeline_log("refresh_universe", "started")
        try:
            universe = self.universe_mgr.refresh_universe()
            elapsed = time.time() - start
            self.pg.insert_pipeline_log("refresh_universe", "completed", elapsed, {
                "symbols": len(universe),
            })
            logger.info(f"Universe refreshed: {len(universe)} symbols in {elapsed:.1f}s")
        except Exception as e:
            self.pg.insert_pipeline_log("refresh_universe", "failed",
                                        time.time() - start, error_msg=str(e))
            logger.error(f"Universe refresh failed: {e}", exc_info=True)

    def _job_expire_signals(self):
        """만료 시그널 정리."""
        try:
            hours = int(self.pg.get_config_value("signal_expiry_hours", "24"))
            expired = self.pg.expire_old_signals(hours)
            if expired:
                logger.info(f"Expired {expired} old signals (>{hours}h)")
                self.pg.insert_pipeline_log("expire_signals", "completed", 0, {
                    "expired": expired,
                })
        except Exception as e:
            logger.error(f"Expire signals failed: {e}")

    def generate_snapshot(self) -> dict | None:
        """포트폴리오 스냅샷 생성 — 현재가 조회 + DB 저장."""
        import yfinance as yf

        try:
            INITIAL_CAPITAL = float(
                self.pg.get_config_value("initial_capital",
                                         str(DEFAULT_INITIAL_CAPITAL)))

            positions = self.pg.get_open_positions()
            open_count = len(positions)

            # 현재가 조회
            current_prices: dict[str, float] = {}
            if positions:
                symbols = list(set(p["symbol"] for p in positions))
                try:
                    data = yf.download(symbols, period="1d", progress=False)
                    if len(symbols) == 1:
                        current_prices[symbols[0]] = float(data["Close"].iloc[-1])
                    else:
                        for sym in symbols:
                            try:
                                current_prices[sym] = float(
                                    data["Close"][sym].dropna().iloc[-1])
                            except (KeyError, IndexError):
                                pass
                except Exception as e:
                    logger.warning(f"yfinance fetch for snapshot: {e}")

            # 포지션 현재가 업데이트 + 투자액/원가 계산
            invested_usd = 0.0
            entry_cost = 0.0
            for p in positions:
                qty = float(p.get("qty") or 1)
                ep = float(p["entry_price"])
                entry_cost += qty * ep
                cp = current_prices.get(p["symbol"])
                if cp:
                    self.pg.update_position_price(p["position_id"], cp)
                    invested_usd += qty * cp
                else:
                    invested_usd += qty * ep

            # 실현손익
            closed = self.pg.get_closed_positions(limit=9999)
            realized_pnl = sum(float(p.get("realized_pnl") or 0) for p in closed)

            # 포트폴리오 계산
            cash_usd = INITIAL_CAPITAL + realized_pnl - entry_cost
            total_value = cash_usd + invested_usd

            prev = self.pg.get_latest_snapshot()
            prev_total = (float(prev["total_value_usd"])
                          if prev and prev.get("total_value_usd")
                          else INITIAL_CAPITAL)
            daily_pnl = total_value - prev_total
            daily_return = daily_pnl / prev_total if prev_total > 0 else 0
            cumulative_return = (total_value / INITIAL_CAPITAL) - 1

            # Max drawdown
            all_snaps = self.pg.get_snapshots(days=9999)
            peak = INITIAL_CAPITAL
            worst_dd = 0.0
            for s in all_snaps:
                val = float(s.get("total_value_usd") or 0)
                if val > peak:
                    peak = val
                dd = (val - peak) / peak if peak > 0 else 0
                if dd < worst_dd:
                    worst_dd = dd
            if total_value > peak:
                peak = total_value
            curr_dd = (total_value - peak) / peak if peak > 0 else 0
            if curr_dd < worst_dd:
                worst_dd = curr_dd

            snap = {
                "total_value_usd": round(total_value, 2),
                "total_value_krw": None,
                "cash_usd": round(cash_usd, 2),
                "invested_usd": round(invested_usd, 2),
                "daily_pnl_usd": round(daily_pnl, 2),
                "daily_return": round(daily_return, 6),
                "cumulative_return": round(cumulative_return, 6),
                "max_drawdown": round(worst_dd, 6),
                "open_positions": open_count,
                "exchange_rate": None,
            }
            self.pg.insert_snapshot(snap)
            self.cache.set_snapshot(snap)
            logger.info(f"Snapshot: total=${total_value:.2f}, "
                        f"positions={open_count}, daily_pnl=${daily_pnl:.2f}")
            return snap

        except Exception as e:
            logger.error(f"Snapshot generation failed: {e}", exc_info=True)
            return None
