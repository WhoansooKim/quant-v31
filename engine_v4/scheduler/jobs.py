"""APScheduler 잡 — KST 기준 스케줄링.

스케줄:
  월~토 07:00 KST  → 데이터 수집 + 시그널 스캔 + 알림
  월~금 22:00 KST  → 프리마켓 갭 체크 (08:00 ET)
  월~금 23:30 KST  → 장중 청산 체크 (09:30 ET)
  화~토 01:00 KST  → 장중 청산 체크 (11:00 ET)
  화~토 03:00 KST  → 장중 청산 체크 (13:00 ET)
  화~토 07:00 KST  → 애프터마켓 체크 (17:00 ET)
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
from engine_v4.data.extended_hours import fetch_extended_hours
from engine_v4.data.storage import PostgresStore, RedisCache
from engine_v4.notify.telegram import TelegramNotifier
from engine_v4.risk.exit_manager import ExitManager, ExitAction
from engine_v4.strategy.swing import SwingStrategy

DEFAULT_INITIAL_CAPITAL = 2200.0

# 벤치마크 — 유니버스 밖이지만 검증/리포트용으로 일일 가격 수집
BENCHMARK_SYMBOLS = ["SPY", "QQQ"]

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
            name="Daily Pipeline (07:00 KST · post-US-close)",
            replace_existing=True,
        )

        # 1b) 월~금 21:30 KST — 프리오픈 파이프라인 (US 장 시작 1시간 전, 22:00 auto_approve 직전)
        self.scheduler.add_job(
            self._job_daily_pipeline,
            CronTrigger(day_of_week="mon-fri", hour=21, minute=30, timezone=KST),
            id="daily_pipeline_preopen",
            name="Daily Pipeline (21:30 KST · pre-US-open)",
            replace_existing=True,
        )

        # 1c) 화~토 02:00 KST — 미드세션 파이프라인 (US 12:00 ET, 장중 신규 시그널 캐치)
        self.scheduler.add_job(
            self._job_daily_pipeline,
            CronTrigger(day_of_week="tue-sat", hour=2, minute=0, timezone=KST),
            id="daily_pipeline_midsession",
            name="Daily Pipeline (02:00 KST · US mid-session)",
            replace_existing=True,
        )

        # 1d) 매월 1·16일 09:00 KST — 검증 재평가 (수정본 기준 ~15일 주기)
        self.scheduler.add_job(
            self._job_validation_recheck,
            CronTrigger(day="1,16", hour=9, minute=0, timezone=KST),
            id="validation_recheck",
            name="Validation Recheck (1·16일 09:00 KST · ~15일 주기)",
            replace_existing=True,
        )

        # 2a) 프리마켓 갭 체크 — 월~금 22:00 KST (08:00 ET)
        self.scheduler.add_job(
            self._job_premarket_check,
            CronTrigger(day_of_week="mon-fri", hour=22, minute=0, timezone=KST),
            id="premarket_check",
            name="Pre-Market Gap Check (08:00 ET)",
            replace_existing=True,
        )

        # 2b) 장중 청산 체크 — 월~금 23:30 KST (09:30 ET)
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

        # 4b) 장 마감 후 청산 체크 — 화~토 05:30 KST (16:30 ET, 장 마감 직후 종가 반영)
        self.scheduler.add_job(
            self._job_exit_check,
            CronTrigger(day_of_week="tue-sat", hour=5, minute=30, timezone=KST),
            id="exit_check_close",
            name="Exit Check (16:30 ET close)",
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

        # 6) 애프터마켓 체크 — 화~토 07:00 KST (17:00 ET)
        self.scheduler.add_job(
            self._job_afterhours_check,
            CronTrigger(day_of_week="tue-sat", hour=7, minute=30, timezone=KST),
            id="afterhours_check",
            name="After-Hours Alert (17:30 ET)",
            replace_existing=True,
        )

        # 7) 매일 06:00 KST — 만료 시그널 정리
        self.scheduler.add_job(
            self._job_expire_signals,
            CronTrigger(hour=6, minute=0, timezone=KST),
            id="expire_signals",
            name="Expire Old Signals",
            replace_existing=True,
        )

        # 8) 매일 07:40 KST — 워치리스트 자동 분석 + 시그널 로그
        self.scheduler.add_job(
            self._job_watchlist_analysis,
            CronTrigger(day_of_week="mon-sat", hour=7, minute=40, timezone=KST),
            id="watchlist_analysis",
            name="Daily Watchlist Analysis + Signal Log",
            replace_existing=True,
        )

        # 9) 매일 06:45 KST — 매크로 데이터 수집 (파이프라인 전)
        self.scheduler.add_job(
            self._job_macro_collect,
            CronTrigger(day_of_week="mon-sat", hour=6, minute=45, timezone=KST),
            id="macro_collect",
            name="Daily Macro Data Collection",
            replace_existing=True,
        )

        # 10) 매일 06:50 KST — 소셜 감성 수집 (파이프라인 전)
        self.scheduler.add_job(
            self._job_social_collect,
            CronTrigger(day_of_week="mon-sat", hour=6, minute=50, timezone=KST),
            id="social_collect",
            name="Daily Social Sentiment Collection",
            replace_existing=True,
        )

        # 11) 토 09:00 KST — LSTM 주간 재학습
        self.scheduler.add_job(
            self._job_lstm_retrain,
            CronTrigger(day_of_week="sat", hour=9, minute=0, timezone=KST),
            id="lstm_retrain",
            name="Weekly LSTM Retrain",
            replace_existing=True,
        )

        # 12) 매일 06:05 KST — 일일 사후분석 (MFE/MAE + EventStudy + News + Brinson + Telegram)
        self.scheduler.add_job(
            self._job_post_market_analysis,
            CronTrigger(day_of_week="tue-sat", hour=6, minute=5, timezone=KST),
            id="post_market_analysis",
            name="Daily Post-Market Analysis + Telegram Digest",
            replace_existing=True,
        )

        # 13) 월~금 22:00 KST — Strategy A 자동 승인 (US 장 시작 30분 전 summer DST)
        self.scheduler.add_job(
            lambda: self._job_auto_approve("pre_open"),
            CronTrigger(day_of_week="mon-fri", hour=22, minute=0, timezone=KST),
            id="auto_approve",
            name="Strategy A/B — Auto-Approve Pending (pre-US-open)",
            replace_existing=True,
        )

        # 14) 화~토 01:30 KST — Strategy B mid-session 재평가
        self.scheduler.add_job(
            lambda: self._job_auto_approve("mid_session"),
            CronTrigger(day_of_week="tue-sat", hour=1, minute=30, timezone=KST),
            id="auto_approve_mid",
            name="Strategy B — Mid-Session Re-evaluation",
            replace_existing=True,
        )

        # 15) 화~토 04:30 KST — Strategy B pre-close 최종 픽업
        self.scheduler.add_job(
            lambda: self._job_auto_approve("pre_close"),
            CronTrigger(day_of_week="tue-sat", hour=4, minute=30, timezone=KST),
            id="auto_approve_close",
            name="Strategy B — Pre-Close Final Pickup",
            replace_existing=True,
        )

        # 16) 일 10:00 KST — Phase 3B 주간 자율 리서치 (arxiv/SSRN/Reddit/Quantocracy)
        self.scheduler.add_job(
            self._job_weekly_research,
            CronTrigger(day_of_week="sun", hour=10, minute=0, timezone=KST),
            id="weekly_research",
            name="Phase 3B — Weekly Autonomous Research",
            replace_existing=True,
        )

        # 17) 매시 정각 — Phase 3F 매크로 적응 체크 (저비용, 변화 시에만 동작)
        self.scheduler.add_job(
            self._job_regime_switch,
            CronTrigger(minute=0, timezone=KST),
            id="regime_switch_check",
            name="Phase 3F — Hourly Macro Regime Switch Check",
            replace_existing=True,
        )

        # 18) 매월 1일 11:00 KST — Phase 3C/3D 변이 생성 + 자동 백테스트 검증
        self.scheduler.add_job(
            self._job_monthly_variant_gen,
            CronTrigger(day=1, hour=11, minute=0, timezone=KST),
            id="monthly_variant_gen",
            name="Phase 3C/3D — Monthly Variant Generate + Auto-Backtest",
            replace_existing=True,
        )

        # 19) 매시 정각 15분 — Phase 3E 변이 롤백 조건 체크 (저비용)
        self.scheduler.add_job(
            self._job_rollback_check,
            CronTrigger(minute=15, timezone=KST),
            id="rollback_check",
            name="Phase 3E — Hourly Rollback Condition Check",
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

            # 벤치마크(SPY/QQQ)도 함께 수집 — 유니버스엔 없지만 검증 stop 조건(SPY 대비) +
            # daily_report.spy_return 산출에 필요. 가격만 수집(스캔/지표 대상 아님).
            price_count = self.collector.collect_prices(symbols + BENCHMARK_SYMBOLS, days=30)
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

            # Step 5: Telegram 요약 보고 (시그널 0 일 때도 발송 — 사용자 확인용)
            self._send_pipeline_summary(elapsed, len(symbols),
                                        len(entries), len(exits))

        except Exception as e:
            elapsed = time.time() - start
            self.pg.insert_pipeline_log("scheduled_pipeline", "failed",
                                        elapsed, error_msg=str(e))
            logger.error(f"Daily pipeline failed: {e}", exc_info=True)
            asyncio.run(self.notifier.notify_error("daily_pipeline", str(e)))

    def _job_validation_recheck(self):
        """검증 재평가 (15일 단위) — 수정본 기준 거래 누적 성과 + stop 조건 판정 → Telegram.

        수정본(집중캡/RSI2/스냅샷, 2026-06-24~) 적용 후 청산거래만 집계.
        stop 조건: 30거래 후 (a) 전략수익 ≥ SPY+3%p 또는 (b) SQN ≥ 1.6 — 둘 다 미달 시 폐기 신호.
        """
        import math as _math
        try:
            base = self.pg.get_config_value("validation_postfix_start", "2026-06-24")
            sqn_target = float(self.pg.get_config_value("validation_sqn_target", "1.6"))
            spy_pp = float(self.pg.get_config_value("validation_spy_outperform_pp", "3.0"))

            with self.pg.get_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT realized_pct, realized_pnl
                    FROM swing_positions
                    WHERE status='closed' AND exit_time >= %s AND realized_pct IS NOT NULL
                    """, (base,)).fetchall()
            rs = [float(r["realized_pct"]) for r in rows]
            n = len(rs)
            wins = sum(1 for r in rs if r > 0)
            total_pnl = sum(float(r["realized_pnl"] or 0) for r in rows)
            win_rate = (wins / n * 100) if n else 0.0
            avg_pct = (sum(rs) / n * 100) if n else 0.0

            # SQN = sqrt(N) * mean(R) / std(R)
            sqn = None
            if n >= 2:
                mean_r = sum(rs) / n
                var = sum((x - mean_r) ** 2 for x in rs) / (n - 1)
                std_r = _math.sqrt(var)
                if std_r > 1e-9:
                    sqn = _math.sqrt(n) * mean_r / std_r

            # 전략 수익(기준일 이후) vs SPY
            def _ret(symbol):
                with self.pg.get_conn() as conn:
                    r = conn.execute(
                        """
                        SELECT (SELECT close FROM daily_prices WHERE symbol=%s AND time::date <= %s ORDER BY time DESC LIMIT 1) last_c,
                               (SELECT close FROM daily_prices WHERE symbol=%s AND time::date >= %s ORDER BY time ASC LIMIT 1) first_c
                        """, (symbol, datetime.now(KST).date(), symbol, base)).fetchone()
                if r and r["first_c"] and r["last_c"]:
                    return (float(r["last_c"]) / float(r["first_c"]) - 1) * 100
                return None
            spy_ret = _ret("SPY")

            base_snap = None
            with self.pg.get_conn() as conn:
                bs = conn.execute(
                    "SELECT total_value_usd FROM swing_snapshots WHERE time::date >= %s ORDER BY time ASC LIMIT 1",
                    (base,)).fetchone()
                if bs and bs["total_value_usd"]:
                    base_snap = float(bs["total_value_usd"])
            latest = self.pg.get_latest_snapshot()
            strat_ret = None
            if base_snap and latest and latest.get("total_value_usd"):
                strat_ret = (float(latest["total_value_usd"]) / base_snap - 1) * 100

            # 판정
            cond_b = (sqn is not None and sqn >= sqn_target)
            cond_a = (strat_ret is not None and spy_ret is not None and strat_ret >= spy_ret + spy_pp)
            evaluable = n >= 30
            if not evaluable:
                verdict = f"📊 누적 중 ({n}/30거래) — 30거래 도달 시 공식 판정"
            elif cond_a or cond_b:
                verdict = "✅ 존속 조건 충족 (a 또는 b)"
            else:
                verdict = "🔴 두 조건 모두 미달 — 폐기 신호 (사용자 결정 필요)"

            def _f(v, suf="", nd=2):
                return f"{v:.{nd}f}{suf}" if v is not None else "—"

            msg = (
                f"<b>🔬 검증 재평가</b> (수정본 기준 {base}~, 15일 주기)\n\n"
                f"<b>거래</b>: {n}건 · 승률 {win_rate:.0f}% · 평균 {_f(avg_pct,'%')} · 누적 ${total_pnl:.2f}\n"
                f"<b>SQN</b>: {_f(sqn)} (목표 ≥{sqn_target})\n"
                f"<b>수익</b>: 전략 {_f(strat_ret,'%')} vs SPY {_f(spy_ret,'%')} "
                f"(조건 ≥SPY+{spy_pp:.0f}%p)\n\n"
                f"{verdict}"
            )
            asyncio.run(self.notifier.send(msg))
            logger.info(f"Validation recheck: n={n} sqn={sqn} strat={strat_ret} spy={spy_ret}")
        except Exception as e:
            logger.error(f"Validation recheck failed: {e}", exc_info=True)

    def _send_pipeline_summary(self, elapsed: float, n_symbols: int,
                                n_entries: int, n_exits: int) -> None:
        """파이프라인 직후 Telegram 요약 1줄 발송 (시그널 0 일 때도)."""
        try:
            now_kst = datetime.now(KST)
            hour = now_kst.hour
            if hour == 7:
                window = "07:00 KST · post-US-close"
            elif hour in (21, 22):
                window = "21:30 KST · pre-US-open"
            elif hour in (2, 3):
                window = "02:00 KST · US mid-session"
            else:
                window = f"{now_kst:%H:%M} KST"

            pending = len([s for s in self.pg.get_signals(status="pending", limit=100)
                          if s.get("signal_type") == "ENTRY"])
            open_pos = len(self.pg.get_open_positions())
            regime = self.pg.get_config_value("current_regime", "NEUTRAL")

            lines = [
                f"<b>📡 Pipeline · {window}</b>",
                f"실행: {elapsed:.1f}s · 유니버스 {n_symbols}",
                f"신규 ENTRY {n_entries} · EXIT {n_exits}",
                f"Pending ENTRY {pending} · Open positions {open_pos}",
                f"Regime: {regime}",
            ]
            self.notifier.send_sync("\n".join(lines))
        except Exception as e:
            logger.warning(f"Pipeline summary telegram failed: {e}")

    def _job_exit_check(self):
        """5-Layer Auto-Exit: ATR Trailing + Hard SL + Time Stop + RSI(2) + Regime.

        auto_sell_enabled=true → 매도 시그널 자동 실행 (승인 불필요)
        auto_sell_enabled=false → 기존 방식 (pending → 수동 승인)
        """
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
            auto_sell = self.pg.get_config_value("auto_sell_enabled", "true") == "true"

            # 현재가 조회 (yfinance, period=2d로 장 시작 전/주말에도 이전 종가 확보)
            current_prices: dict[str, float] = {}
            try:
                data = yf.download(symbols, period="2d", progress=False)
                if len(symbols) == 1:
                    current_prices[symbols[0]] = float(data["Close"].dropna().iloc[-1])
                else:
                    for sym in symbols:
                        try:
                            current_prices[sym] = float(
                                data["Close"][sym].dropna().iloc[-1])
                        except (KeyError, IndexError):
                            pass
            except Exception as e:
                logger.warning(f"yfinance fetch for exit check: {e}")

            # 시세 누락 종목 경고
            missing = [s for s in symbols if s not in current_prices]
            if missing:
                logger.warning(f"Exit check: no price data for {missing} — skip exit evaluation")

            # 포지션별 현재가 업데이트
            for p in positions:
                cp = current_prices.get(p["symbol"])
                if cp:
                    self.pg.update_position_price(p["position_id"], cp)

            # Step 1: 5-Layer 복합 청산 체크
            exit_actions = self.exit_mgr.check_exits(positions, current_prices)
            auto_executed = 0

            for action in exit_actions:
                if auto_sell:
                    # === 자동 매도 실행 ===
                    self._auto_execute_exit(action)
                    auto_executed += 1
                else:
                    # 기존 방식: pending 시그널 생성 (수동 승인 대기)
                    sig = {
                        "symbol": action.symbol,
                        "signal_type": "EXIT",
                        "entry_price": action.current_price,
                        "exit_reason": action.exit_reason,
                        "position_id": action.position_id,
                        "status": "pending",
                    }
                    self.pg.insert_signal(sig)

            # Step 2: Partial Exit 체크
            # 이미 exit_actions에서 전량 청산되지 않은 포지션만 대상
            exited_pids = {a.position_id for a in exit_actions}
            remaining_positions = [p for p in positions
                                   if p["position_id"] not in exited_pids]

            partial_actions = self.exit_mgr.check_partial_exits(
                remaining_positions, current_prices)
            for action in partial_actions:
                self.pg.partial_close_position(
                    action.position_id, action.exit_qty, action.current_price)
                self.pg.insert_trade({
                    "position_id": action.position_id,
                    "symbol": action.symbol,
                    "side": "SELL",
                    "qty": action.exit_qty,
                    "price": action.current_price,
                    "is_paper": True,
                })
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

            # Step 3: 가격/지표 업데이트 + 기존 추세 이탈 스캔
            self.collector.collect_prices(symbols, days=5)
            self.collector.compute_indicators(symbols)
            exits = self.strategy.scan_exits()

            # 기존 scan_exits 결과도 auto-sell 적용
            if exits and auto_sell:
                for sig in exits:
                    pid = sig.get("position_id")
                    if pid and pid not in exited_pids:
                        pos = next((p for p in positions
                                    if p["position_id"] == pid), None)
                        if pos:
                            cp = current_prices.get(sig["symbol"])
                            if cp:
                                action = ExitAction(
                                    position_id=pid,
                                    symbol=sig["symbol"],
                                    current_price=cp,
                                    exit_qty=float(pos.get("qty") or 1),
                                    exit_reason=sig.get("exit_reason", "trend_break"),
                                    gain_pct=(cp - float(pos["entry_price"])) / float(pos["entry_price"]),
                                    layer="ScanExit",
                                )
                                self._auto_execute_exit(action)
                                auto_executed += 1
                                exited_pids.add(pid)
            elif exits:
                asyncio.run(self.notifier.notify_signals([], exits))

            # 스냅샷 생성
            self.generate_snapshot()

            elapsed = time.time() - start
            self.pg.insert_pipeline_log("exit_check", "completed", elapsed, {
                "positions": len(positions),
                "auto_executed": auto_executed,
                "partial_exits": len(partial_actions),
                "scan_exits": len(exits),
                "auto_sell_enabled": auto_sell,
            })
            logger.info(f"Exit check: {auto_executed} auto-exits, "
                        f"{len(partial_actions)} partial exits, "
                        f"{len(exits)} scan exits "
                        f"from {len(positions)} positions in {elapsed:.1f}s "
                        f"(auto_sell={'ON' if auto_sell else 'OFF'})")

        except Exception as e:
            self.pg.insert_pipeline_log("exit_check", "failed",
                                        time.time() - start, error_msg=str(e))
            logger.error(f"Exit check failed: {e}", exc_info=True)

    def _auto_execute_exit(self, action: ExitAction):
        """자동 매도 실행 — 포지션 종료 + trade 기록 + 시그널 + KIS 주문 + 텔레그램."""
        try:
            from engine_v4.broker.kis_client import KisClient
            from engine_v4.config.settings import get_config

            pid = action.position_id
            symbol = action.symbol
            price = action.current_price
            qty = int(action.exit_qty) or 1

            # 포지션 종료
            self.pg.close_position(pid, price, action.exit_reason)

            # Trade 기록
            self.pg.insert_trade({
                "position_id": pid,
                "symbol": symbol,
                "side": "SELL",
                "qty": qty,
                "price": price,
                "is_paper": True,
            })

            # 시그널 기록 (auto-executed)
            sig = {
                "symbol": symbol,
                "signal_type": "EXIT",
                "entry_price": price,
                "exit_reason": action.exit_reason,
                "position_id": pid,
                "status": "executed",
            }
            self.pg.insert_signal(sig)

            # Auto-exit 플래그
            with self.pg.get_conn() as conn:
                conn.execute("""
                    UPDATE swing_positions SET auto_exit = true
                    WHERE position_id = %s
                """, (pid,))
                conn.commit()

            # KIS 매도 주문
            try:
                cfg = get_config()
                kis = KisClient(cfg)
                order = kis.sell(symbol=symbol, qty=qty, price=price)
                logger.info(f"KIS SELL order: {symbol} {qty} @ ${price:.2f} → "
                            f"{order.order_id} ({order.message})")
            except Exception as e:
                logger.warning(f"KIS sell order failed for {symbol}: {e}")

            # 텔레그램 알림 (auto-sell 명시)
            pnl_pct = action.gain_pct
            emoji = "\U0001f7e2" if pnl_pct > 0 else "\U0001f534"
            reason_labels = {
                "hard_stop": "Hard Stop (1.5×ATR)",
                "atr_trailing_stop": "ATR Trailing Stop",
                "time_stop": "Time Stop (15d)",
                "rsi2_overbought": "RSI(2) Overbought",
                "stop_loss": "Stop-Loss",
                "take_profit": "Take-Profit",
                "trend_break": "Trend Break",
            }
            reason_label = reason_labels.get(action.exit_reason, action.exit_reason)

            msg = (
                f"{emoji} <b>AUTO-SELL: {symbol}</b>\n"
                f"Layer: <b>{action.layer}</b>\n"
                f"Reason: {reason_label}\n"
                f"Price: ${price:.2f} | P&L: <b>{pnl_pct:+.1%}</b>\n"
                f"Qty: {qty} shares\n"
                f"\U0001f916 <i>Automated exit — no approval needed</i>"
            )
            asyncio.run(self.notifier.send(msg))

            logger.info(f"AUTO-SELL executed: {symbol} #{pid} @ ${price:.2f} "
                        f"reason={action.exit_reason} layer={action.layer} "
                        f"P&L={pnl_pct:+.1%}")

        except Exception as e:
            logger.error(f"Auto-sell failed for {action.symbol}: {e}",
                         exc_info=True)

    def _job_refresh_universe(self):
        """유니버스 주간 갱신 + 팩터 모멘텀 계산."""
        start = time.time()
        self.pg.insert_pipeline_log("refresh_universe", "started")
        try:
            universe = self.universe_mgr.refresh_universe()

            # Factor momentum 계산
            momentum_data = self._calc_factor_momentum()
            if momentum_data:
                self.cache.set_json("factor_momentum", momentum_data, ttl=604800)
                logger.info(f"Factor momentum cached: {momentum_data['ranked']}")

            elapsed = time.time() - start
            self.pg.insert_pipeline_log("refresh_universe", "completed", elapsed, {
                "symbols": len(universe),
                "factor_momentum": momentum_data.get("ranked") if momentum_data else None,
            })
            logger.info(f"Universe refreshed: {len(universe)} symbols in {elapsed:.1f}s")
        except Exception as e:
            self.pg.insert_pipeline_log("refresh_universe", "failed",
                                        time.time() - start, error_msg=str(e))
            logger.error(f"Universe refresh failed: {e}", exc_info=True)

    def _calc_factor_momentum(self) -> dict | None:
        """팩터 모멘텀 계산 — 최근 30일 시그널의 팩터별 승률 상관관계.

        각 팩터(technical, sentiment, flow, quality, value)의
        승리 포지션 평균 점수 vs 패배 포지션 평균 점수 차이로 성과 측정.
        """
        try:
            # 최근 30일 내 청산된 포지션 + 해당 시그널 팩터 점수 조회
            with self.pg.get_conn() as conn:
                rows = conn.execute("""
                    SELECT s.technical_score, s.sentiment_score, s.flow_score,
                           s.quality_score, s.value_score,
                           p.realized_pnl
                    FROM swing_positions p
                    JOIN swing_signals s ON s.position_id = p.position_id
                    WHERE p.status = 'closed'
                      AND p.exit_time >= now() - interval '30 days'
                      AND s.composite_score IS NOT NULL
                """).fetchall()

            if len(rows) < 3:
                logger.info("Factor momentum: insufficient data "
                            f"({len(rows)} closed positions in 30d)")
                return None

            factors = ["technical", "sentiment", "flow", "quality", "value"]
            factor_keys = {
                "technical": "technical_score",
                "sentiment": "sentiment_score",
                "flow": "flow_score",
                "quality": "quality_score",
                "value": "value_score",
            }

            performance = {}
            for factor in factors:
                key = factor_keys[factor]
                win_scores = []
                lose_scores = []
                for r in rows:
                    score = float(r.get(key) or 50)
                    pnl = float(r.get("realized_pnl") or 0)
                    if pnl > 0:
                        win_scores.append(score)
                    else:
                        lose_scores.append(score)

                # Performance = avg win score - avg lose score (higher = better predictor)
                avg_win = sum(win_scores) / len(win_scores) if win_scores else 50
                avg_lose = sum(lose_scores) / len(lose_scores) if lose_scores else 50
                performance[factor] = round(avg_win - avg_lose, 2)

            # Rank by performance (highest difference = best predictor)
            ranked = sorted(performance, key=lambda f: performance[f], reverse=True)

            return {
                "ranked": ranked,
                "performance": performance,
                "positions_analyzed": len(rows),
                "calculated_at": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Factor momentum calculation failed: {e}", exc_info=True)
            return None

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

    def _job_premarket_check(self):
        """A안: 프리마켓 갭 필터 — 보유 종목 + 워치리스트 + pending 시그널."""
        try:
            # Gather all symbols of interest
            positions = self.pg.get_open_positions()
            watchlist = self.pg.get_watchlist()
            pending = self.pg.get_signals(status="pending")

            syms = set()
            for p in positions:
                syms.add(p["symbol"])
            for w in watchlist:
                syms.add(w["symbol"])
            for s in pending:
                syms.add(s["symbol"])

            if not syms:
                logger.info("Pre-market check: no symbols to check")
                return

            data = fetch_extended_hours(list(syms))
            alerts = []

            for d in data:
                sym = d["symbol"]
                gap = d["gap_pct"]
                pre_price = d.get("pre_price")
                if not pre_price:
                    continue

                is_position = any(p["symbol"] == sym for p in positions)
                is_pending = any(s["symbol"] == sym for s in pending)

                # Position holders: alert on significant gaps
                if is_position and abs(gap) >= 2.0:
                    emoji = "\U0001f7e2" if gap > 0 else "\U0001f534"
                    direction = "GAP UP" if gap > 0 else "GAP DOWN"
                    alerts.append(
                        f"{emoji} <b>Pre-Market {direction}: {sym}</b>\n"
                        f"Gap: <b>{gap:+.1f}%</b> | Pre: ${pre_price:.2f}\n"
                        f"Prev Close: ${d['regular_close']:.2f}"
                    )

                # Pending signals: alert on confirming/conflicting gaps
                if is_pending and abs(gap) >= 1.0:
                    sig = next((s for s in pending if s["symbol"] == sym), None)
                    if sig:
                        sig_type = sig.get("signal_type", "")
                        if sig_type == "ENTRY" and gap >= 1.0:
                            alerts.append(
                                f"\u2705 <b>Pre-Market confirms ENTRY: {sym}</b>\n"
                                f"Gap: <b>{gap:+.1f}%</b> | Pre: ${pre_price:.2f}"
                            )
                        elif sig_type == "ENTRY" and gap <= -2.0:
                            alerts.append(
                                f"\u26a0\ufe0f <b>Pre-Market warns against ENTRY: {sym}</b>\n"
                                f"Gap: <b>{gap:+.1f}%</b> — consider delaying"
                            )

            # Cache results for API/dashboard
            self.cache.set_json("extended_hours", {
                "session": "pre",
                "checked_at": datetime.now().isoformat(),
                "data": data,
            }, ttl=7200)

            # Send consolidated Telegram alert
            if alerts:
                header = f"\U0001f4ca <b>Pre-Market Report</b> ({len(data)} symbols)\n\n"
                msg = header + "\n\n".join(alerts[:10])  # Max 10 alerts
                msg += f"\n\n\u23f0 {datetime.now().strftime('%H:%M KST')}"
                asyncio.run(self.notifier.send(msg))

            logger.info(f"Pre-market check done: {len(data)} symbols, {len(alerts)} alerts")

        except Exception as e:
            logger.error(f"Pre-market check failed: {e}", exc_info=True)

    def _job_afterhours_check(self):
        """B안: 애프터마켓 이상 움직임 감지 — 보유 종목 중심."""
        try:
            positions = self.pg.get_open_positions()
            watchlist = self.pg.get_watchlist()

            syms = set()
            for p in positions:
                syms.add(p["symbol"])
            for w in watchlist:
                syms.add(w["symbol"])

            if not syms:
                logger.info("After-hours check: no symbols")
                return

            data = fetch_extended_hours(list(syms))
            alerts = []

            for d in data:
                sym = d["symbol"]
                post_price = d.get("post_price")
                gap = d["gap_pct"]
                if not post_price:
                    continue

                is_position = any(p["symbol"] == sym for p in positions)

                # Position: after-hours drop >= 3% → urgent alert
                if is_position and gap <= -3.0:
                    alerts.append(
                        f"\U0001f6a8 <b>After-Hours DROP: {sym}</b>\n"
                        f"Change: <b>{gap:+.1f}%</b> | AH: ${post_price:.2f}\n"
                        f"Close: ${d['regular_price']:.2f}\n"
                        f"<i>Consider early exit at next open</i>"
                    )
                # Position: after-hours surge >= 5% → consider partial exit
                elif is_position and gap >= 5.0:
                    alerts.append(
                        f"\U0001f680 <b>After-Hours SURGE: {sym}</b>\n"
                        f"Change: <b>{gap:+.1f}%</b> | AH: ${post_price:.2f}\n"
                        f"Close: ${d['regular_price']:.2f}\n"
                        f"<i>Consider partial profit-taking</i>"
                    )
                # Watchlist: big moves (either direction)
                elif not is_position and abs(gap) >= 4.0:
                    emoji = "\U0001f7e2" if gap > 0 else "\U0001f534"
                    alerts.append(
                        f"{emoji} <b>After-Hours Move: {sym}</b>\n"
                        f"Change: <b>{gap:+.1f}%</b> | AH: ${post_price:.2f}"
                    )

            # Cache results
            self.cache.set_json("extended_hours", {
                "session": "post",
                "checked_at": datetime.now().isoformat(),
                "data": data,
            }, ttl=7200)

            # Telegram
            if alerts:
                header = f"\U0001f319 <b>After-Hours Report</b> ({len(data)} symbols)\n\n"
                msg = header + "\n\n".join(alerts[:10])
                msg += f"\n\n\u23f0 {datetime.now().strftime('%H:%M KST')}"
                asyncio.run(self.notifier.send(msg))

            logger.info(f"After-hours check done: {len(data)} symbols, {len(alerts)} alerts")

        except Exception as e:
            logger.error(f"After-hours check failed: {e}", exc_info=True)

    def generate_snapshot(self) -> dict | None:
        """포트폴리오 스냅샷 생성 — 현재가 조회 + DB 저장."""
        import math
        import yfinance as yf

        def _finite_price(v) -> float | None:
            """가격이 유한한 양수일 때만 반환 (NaN/inf/0 이하 → None).
            bool(float('nan'))==True 라서 `if cp:` 만으로는 NaN을 거른다는 보장이 없음."""
            try:
                f = float(v)
            except (TypeError, ValueError):
                return None
            return f if math.isfinite(f) and f > 0 else None

        try:
            INITIAL_CAPITAL = float(
                self.pg.get_config_value("initial_capital",
                                         str(DEFAULT_INITIAL_CAPITAL)))

            # 오픈/청산 경계 레이스 방어 (스냅샷 ~$22 글리치 버그 수정).
            # get_open_positions() 와 get_closed_positions() 를 따로 읽는 사이 포지션이
            # 청산되면, 같은 포지션이 양쪽에 잡혀 손익이 이중 계산됨.
            # → 오픈을 먼저 읽고, 청산을 읽은 뒤, 청산 집합에 있는 id 는 오픈에서 제외.
            #   (오픈-우선 순서 → 경계에서 청산되는 포지션은 항상 '청산'으로 정확히 1회 계산)
            all_open = self.pg.get_open_positions()
            closed = self.pg.get_closed_positions(limit=9999)
            closed_ids = {p["position_id"] for p in closed}
            positions = [p for p in all_open if p["position_id"] not in closed_ids]
            if len(positions) != len(all_open):
                logger.warning(
                    f"Snapshot 레이스 방어: 오픈/청산 동시 출현 "
                    f"{len(all_open) - len(positions)}건 오픈에서 제외(청산으로 계산)")
            open_count = len(positions)

            # 현재가 조회 (period=2d로 장외 시간에도 이전 종가 확보)
            current_prices: dict[str, float] = {}
            if positions:
                symbols = list(set(p["symbol"] for p in positions))
                try:
                    data = yf.download(symbols, period="2d", progress=False)
                    if len(symbols) == 1:
                        px = _finite_price(data["Close"].dropna().iloc[-1])
                        if px is not None:
                            current_prices[symbols[0]] = px
                    else:
                        for sym in symbols:
                            try:
                                px = _finite_price(data["Close"][sym].dropna().iloc[-1])
                                if px is not None:
                                    current_prices[sym] = px
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
                cp = _finite_price(current_prices.get(p["symbol"]))
                if cp is not None:
                    self.pg.update_position_price(p["position_id"], cp)
                    invested_usd += qty * cp
                else:
                    invested_usd += qty * ep

            # 실현손익 (위에서 이미 읽은 closed 재사용 — 오픈/청산 일관성 유지)
            realized_pnl = sum(float(p.get("realized_pnl") or 0) for p in closed)

            # 총 수수료 차감 — api/main.py:_generate_snapshot 와 동일 공식 유지 필수.
            # (두 스냅샷 생성기가 달라 976↔954 진동했던 글리치 수정: 수수료 일관 차감)
            total_commission = float(self.pg.get_total_commissions()["total_commission"])

            # 포트폴리오 계산 (수수료 차감)
            capital_adj = self.pg.get_total_capital_adjustments()
            cash_usd = INITIAL_CAPITAL + capital_adj + realized_pnl - entry_cost - total_commission
            total_value = cash_usd + invested_usd

            # 순수 트레이딩 손익 (입출금 제외, 수수료 차감)
            unrealized_pnl = invested_usd - entry_cost
            trading_pnl = realized_pnl + unrealized_pnl - total_commission

            total_invested = INITIAL_CAPITAL + capital_adj
            cumulative_return = trading_pnl / total_invested if total_invested > 0 else 0

            # Daily P&L: 순수 트레이딩 손익 변동분 (입출금 제외)
            prev = self.pg.get_latest_snapshot()
            if prev and prev.get("trading_pnl") is not None:
                prev_trading_pnl = float(prev["trading_pnl"])
            elif prev and prev.get("total_value_usd") is not None:
                # 이전 스냅샷에 trading_pnl 없으면 추정
                prev_trading_pnl = float(prev["total_value_usd"]) - total_invested
            else:
                prev_trading_pnl = 0
            daily_pnl = trading_pnl - prev_trading_pnl
            daily_return = daily_pnl / total_invested if total_invested > 0 else 0

            # Max drawdown (TWR 기반 — 입출금 무관)
            all_snaps = self.pg.get_snapshots(days=9999)
            peak_return = 0.0
            worst_dd = 0.0
            for s in all_snaps:
                cr = float(s.get("cumulative_return") or 0)
                if cr > peak_return:
                    peak_return = cr
                dd = cr - peak_return  # 수익률 기준 drawdown
                if dd < worst_dd:
                    worst_dd = dd
            # 현재 포함
            if cumulative_return > peak_return:
                peak_return = cumulative_return
            curr_dd = cumulative_return - peak_return
            if curr_dd < worst_dd:
                worst_dd = curr_dd

            # 최종 방어선: 비유한(NaN/inf) 값이 하나라도 있으면 오염 스냅샷 저장 거부
            if not all(math.isfinite(x) for x in
                       (total_value, cash_usd, invested_usd, daily_pnl,
                        daily_return, cumulative_return, worst_dd, trading_pnl)):
                logger.error(
                    "Snapshot 비유한 값 감지 — 저장 건너뜀 "
                    f"(total={total_value}, invested={invested_usd}, trading_pnl={trading_pnl})")
                return None

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
                "trading_pnl": round(trading_pnl, 2),
            }
            self.pg.insert_snapshot(snap)
            self.cache.set_snapshot(snap)
            logger.info(f"Snapshot: total=${total_value:.2f}, "
                        f"positions={open_count}, daily_pnl=${daily_pnl:.2f}")
            return snap

        except Exception as e:
            logger.error(f"Snapshot generation failed: {e}", exc_info=True)
            return None

    def _job_lstm_retrain(self):
        """LSTM 주간 재학습 (토요일)."""
        import requests
        try:
            lstm_enabled = self.pg.get_config_value("lstm_enabled", "true")
            if lstm_enabled != "true":
                logger.info("LSTM retrain skipped: disabled in config")
                return

            resp = requests.post("http://localhost:8001/lstm/train", timeout=10)
            if resp.status_code == 200:
                logger.info("LSTM retrain triggered via API")
            else:
                logger.warning(f"LSTM retrain trigger failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"LSTM retrain job failed: {e}", exc_info=True)

    def _job_macro_collect(self):
        """매크로 지표 수집 + 스코어링 + DB 스냅샷."""
        import requests
        try:
            macro_enabled = self.pg.get_config_value("macro_enabled", "true")
            if macro_enabled != "true":
                logger.info("Macro collect skipped: disabled in config")
                return

            resp = requests.post("http://localhost:8001/macro/collect", timeout=30)
            if resp.status_code == 200:
                logger.info("Macro collect triggered via API")
            else:
                logger.warning(f"Macro collect trigger failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"Macro collect job failed: {e}", exc_info=True)

    def _job_social_collect(self):
        """소셜 감성 수집 (Reddit + StockTwits)."""
        import requests
        try:
            social_enabled = self.pg.get_config_value("social_enabled", "true")
            if social_enabled != "true":
                logger.info("Social collect skipped: disabled in config")
                return

            resp = requests.post("http://localhost:8001/social/collect", timeout=10)
            if resp.status_code == 200:
                logger.info("Social collect triggered via API")
            else:
                logger.warning(f"Social collect trigger failed: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"Social collect job failed: {e}", exc_info=True)

    def _job_auto_approve(self, check_label: str = "scheduled"):
        """Strategy A/B — Auto-approve pending ENTRY signals.

        check_label: 'pre_open' (22:00) | 'mid_session' (01:30) | 'pre_close' (04:30)
        """
        from engine_v4.strategy.auto_approve import run_auto_approve
        try:
            from engine_v4.risk.position_manager import PositionManager
            from engine_v4.broker.kis_client import KisClient
            pos_mgr = PositionManager(self.pg, self.cfg)
            kis = KisClient(self.cfg)
            summary = run_auto_approve(
                self.pg, pos_mgr, self.notifier, kis_client=kis, macro_scorer=None,
                anthropic_key=getattr(self.cfg, "anthropic_key", None),
                cache=self.cache,
                check_label=check_label,
            )
            self.pg.insert_pipeline_log(
                f"auto_approve_{check_label}", "completed", 0,
                {"approved": summary.get("auto_approved"), "executed": summary.get("executed"),
                 "skipped": summary.get("skipped"), "errors": summary.get("errors_count"),
                 "llm_gate": summary.get("llm_gate_enabled")},
            )
            logger.info(f"Auto-approve [{check_label}]: {summary.get('auto_approved')}/"
                        f"{summary.get('evaluated')} approved, {summary.get('executed')} executed, "
                        f"LLM_gate={summary.get('llm_gate_enabled')}")
        except Exception as e:
            logger.exception(f"auto_approve [{check_label}] failed: {e}")
            self.pg.insert_pipeline_log(f"auto_approve_{check_label}", "failed", 0, {"error": str(e)})

    def _job_regime_switch(self):
        """Phase 3F — Hourly regime switch check (low cost)."""
        try:
            from engine_v4.harness.regime_switcher import check_and_switch
            result = check_and_switch(self.pg, self.notifier)
            if result.get("switched"):
                logger.info(f"Regime auto-switch: {result}")
        except Exception as e:
            logger.exception(f"regime_switch_check failed: {e}")

    def _job_rollback_check(self):
        """Phase 3E — Hourly rollback condition check."""
        try:
            from engine_v4.harness.auto_deploy import check_rollback_conditions
            result = check_rollback_conditions(self.pg, self.notifier)
            if result.get("rolled_back"):
                logger.info(f"Auto-rollback fired: {result}")
        except Exception as e:
            logger.exception(f"rollback_check failed: {e}")

    def _job_monthly_variant_gen(self):
        """Phase 3C/3D — Monthly variant generation + auto-backtest."""
        enabled = self.pg.get_config_value("harness_variant_gen_enabled", "false")
        if enabled.lower() not in ("true", "1", "yes"):
            logger.info("harness_variant_gen_enabled=false — skipping monthly_variant_gen")
            return
        try:
            from engine_v4.harness.variant_generator import generate_variants
            from engine_v4.harness.auto_backtest import validate_all_pending
            gen_summary = generate_variants(
                self.pg,
                anthropic_key=getattr(self.cfg, "anthropic_key", None),
                prefer_ollama=True, max_variants=5,
            )
            logger.info(f"Monthly variant gen: {gen_summary}")
            # Validate immediately
            bt_summary = validate_all_pending(self.pg, max_per_run=5)
            logger.info(f"Monthly variant backtest: {bt_summary}")
        except Exception as e:
            logger.exception(f"monthly_variant_gen failed: {e}")

    def _job_weekly_research(self):
        """Phase 3B — Weekly autonomous research agent."""
        enabled = self.pg.get_config_value("harness_research_enabled", "true")
        if enabled.lower() not in ("true", "1", "yes"):
            logger.info("harness_research_enabled=false — skipping weekly_research")
            return
        try:
            from engine_v4.harness.researcher import run_research
            summary = run_research(self.pg, self.notifier)
            logger.info(f"Weekly research done: {summary}")
        except Exception as e:
            logger.exception(f"weekly_research failed: {e}")
            self.pg.insert_pipeline_log("weekly_research", "failed", 0, {"error": str(e)})

    def _job_post_market_analysis(self):
        """일일 사후분석 — MFE/MAE + Event Study + News + Metrics + Telegram."""
        from datetime import date
        from engine_v4.analysis.daily_report import run_and_notify

        try:
            today = date.today()
            rep = run_and_notify(
                self.pg, self.notifier, report_date=today,
                anthropic_key=getattr(self.cfg, "anthropic_key", None),
            )
            self.pg.insert_pipeline_log(
                "post_market_analysis", "completed", 0,
                {"closed": rep.get("closed_count"), "open": rep.get("open_count")},
            )
            logger.info(f"Post-market analysis done: {rep['closed_count']} closed, {rep['open_count']} open")
        except Exception as e:
            logger.exception(f"post_market_analysis failed: {e}")
            self.pg.insert_pipeline_log(
                "post_market_analysis", "failed", 0, {"error": str(e)},
            )

    def _job_watchlist_analysis(self):
        """매일 워치리스트 자동 분석 → 시그널 로그 기록."""
        import requests
        try:
            watchlist = self.pg.get_watchlist()
            if not watchlist:
                logger.info("Watchlist analysis skipped: no symbols")
                return

            logger.info(f"Watchlist analysis starting: {len(watchlist)} symbols")
            resp = requests.post("http://localhost:8001/watchlist/analyze", timeout=300)
            logger.info(f"Watchlist analysis triggered: {resp.status_code}")

            # Poll for completion (max 5 min)
            import time
            for _ in range(100):
                time.sleep(3)
                result = requests.get("http://localhost:8001/watchlist/analysis", timeout=10)
                data = result.json()
                if data.get("status") == "done":
                    count = data.get("count", 0)
                    logger.info(f"Watchlist analysis done: {count} symbols analyzed & logged")
                    self.pg.insert_pipeline_log("watchlist_analysis", "completed", 0, {
                        "symbols_analyzed": count,
                    })
                    return
            logger.warning("Watchlist analysis timed out after 5 min")
        except Exception as e:
            logger.error(f"Watchlist analysis job failed: {e}", exc_info=True)
