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
            capital_adj = self.pg.get_total_capital_adjustments()
            cash_usd = INITIAL_CAPITAL + capital_adj + realized_pnl - entry_cost
            total_value = cash_usd + invested_usd

            # 순수 트레이딩 손익 (입출금 제외)
            unrealized_pnl = invested_usd - entry_cost
            trading_pnl = realized_pnl + unrealized_pnl

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
