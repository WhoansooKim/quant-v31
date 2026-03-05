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
from engine_v4.strategy.swing import SwingStrategy

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
        """오픈 포지션 청산 조건 체크."""
        start = time.time()
        self.pg.insert_pipeline_log("exit_check", "started")

        try:
            # 포지션별 최신 가격 갱신 (yfinance)
            positions = self.pg.get_open_positions()
            if not positions:
                self.pg.insert_pipeline_log("exit_check", "completed",
                                            time.time() - start,
                                            {"positions": 0, "exits": 0})
                return

            symbols = list(set(p["symbol"] for p in positions))
            # 가격 업데이트를 위해 짧은 기간 수집
            self.collector.collect_prices(symbols, days=5)
            self.collector.compute_indicators(symbols)

            # 청산 스캔
            exits = self.strategy.scan_exits()

            if exits:
                asyncio.run(self.notifier.notify_signals([], exits))

            elapsed = time.time() - start
            self.pg.insert_pipeline_log("exit_check", "completed", elapsed, {
                "positions": len(positions),
                "exits": len(exits),
            })
            logger.info(f"Exit check: {len(exits)} signals from "
                        f"{len(positions)} positions in {elapsed:.1f}s")

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
