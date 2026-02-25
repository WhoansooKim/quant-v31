"""
V3.1 Phase 3 — 8단계 일일 파이프라인 오케스트레이터 + FastAPI

① 레짐 감지 → ② Kill Switch → ③ 레짐별 배분 → ④ 전략 시그널
→ ⑤ 센티먼트 오버레이 → ⑥ Vol-Targeting → ⑦ ATR 사이징 → ⑧ VWAP 실행
"""

from fastapi import FastAPI, BackgroundTasks
from contextlib import asynccontextmanager
import logging
import numpy as np
from datetime import datetime

from engine.config.settings import Settings
from engine.data.storage import PostgresStore, RedisCache
from engine.risk.regime import RegimeDetector
from engine.risk.regime_allocator import RegimeAllocator
from engine.risk.kill_switch import DrawdownKillSwitch, DefenseLevel
from engine.risk.position_sizer import DynamicPositionSizer
from engine.strategies.lowvol_quality import LowVolQuality
from engine.strategies.vol_momentum import VolManagedMomentum
from engine.strategies.pairs_trading import PairsTrading
from engine.strategies.vol_targeting import VolatilityTargeting
from engine.strategies.sentiment import SentimentOverlay
from engine.execution.alpaca_client import AlpacaExecutor
from engine.execution.vwap import VWAPExecutor
from engine.execution.alerts import TelegramAlert
from engine.execution.scheduler import setup_scheduler
from engine.api.grpc_server import start_grpc_server
from engine.explain.feature_importance import FeatureExplainer
from engine.backtest.engine import BacktestEngine, BacktestStore, compute_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("orchestrator")

# ─── 전역 설정 ───
config = Settings()
pg = PostgresStore(config.pg_dsn)
cache = RedisCache(config.redis_url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작 시 오케스트레이터 + gRPC + 스케줄러 초기화"""
    logger.info("Quant V3.1 Engine starting...")
    orch = PortfolioOrchestrator()
    app.state.orchestrator = orch

    # gRPC 서버 시작
    grpc_server = start_grpc_server(
        pg, cache, orch, port=config.grpc_port,
    )
    app.state.grpc_server = grpc_server
    logger.info(f"gRPC server started on port {config.grpc_port}")

    # APScheduler 시작
    scheduler = None
    if config.scheduler_enabled:
        scheduler = setup_scheduler(orch)
        app.state.scheduler = scheduler
        logger.info("APScheduler started")

    # SHAP Explainer
    app.state.explainer = FeatureExplainer(pg)

    logger.info("Quant V3.1 Engine ready")
    yield

    # 정리
    logger.info("Quant V3.1 Engine shutting down...")
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
    grpc_server.stop(grace=5)
    logger.info("gRPC server stopped")


app = FastAPI(
    title="Quant V3.1 Engine",
    version="3.1.0-ubuntu",
    lifespan=lifespan,
)


class PortfolioOrchestrator:
    """일일 8단계 파이프라인 — PostgreSQL 연동"""

    def __init__(self):
        # ─── 레짐 엔진 ───
        self.regime_detector = RegimeDetector(
            pg_dsn=config.pg_dsn,
            n_states=config.hmm_n_states,
            lookback=config.hmm_lookback_days,
        )
        # 모델 로드 (재학습 필요 시 자동 학습)
        if self.regime_detector.should_retrain(config.hmm_retrain_interval):
            logger.info("HMM 재학습 실행 (월간)")
            self.regime_detector.fit()
        else:
            self.regime_detector.load()
        logger.info("HMM 레짐 모델 로드 완료")

        # ─── 배분 + 방어 + 사이징 ───
        self.allocator = RegimeAllocator()
        self.kill_switch = DrawdownKillSwitch()
        self.sizer = DynamicPositionSizer(
            risk_per_trade=config.risk_per_trade,
            kelly_fraction=config.kelly_fraction,
            max_position_pct=config.max_position_pct,
            max_sector_pct=config.max_sector_pct,
        )

        # ─── 5대 전략 (pg_dsn 전달) ───
        self.strategies = {
            "lowvol_quality": LowVolQuality(config.pg_dsn),
            "vol_momentum": VolManagedMomentum(config.pg_dsn),
            "pairs_trading": PairsTrading(config.pg_dsn),
        }
        self.vol_targeting = VolatilityTargeting(
            target_vol=0.15, max_leverage=1.3,
            min_exposure=0.3, lookback=21,
        )
        self.sentiment = SentimentOverlay(config.pg_dsn, {
            "finbert_threshold": config.finbert_threshold,
            "claude_enabled": config.claude_enabled,
        })

        # ─── 실행 ───
        self.executor = AlpacaExecutor(config)
        self.vwap = VWAPExecutor(
            self.executor, slices=config.vwap_slices,
            interval_sec=config.vwap_interval_sec,
        )
        self.telegram = TelegramAlert(config)

        # ─── 상태 ───
        self.last_regime = None

        # ─── 초기 PV로 peak 설정 ───
        pv = self.executor.get_portfolio_value()
        self.kill_switch = DrawdownKillSwitch(initial_value=pv)
        logger.info(f"초기 포트폴리오: ${pv:,.2f}")

    async def execute_daily(self) -> dict:
        """=== 일일 8단계 파이프라인 ==="""
        start = datetime.now()
        logger.info(f"{'='*60}")
        logger.info(f"일일 파이프라인 시작: {start.isoformat()}")

        result = {"status": "ok", "steps": {}}

        try:
            # ══════════════════════════════
            # STEP 1: 레짐 감지
            # ══════════════════════════════
            regime = self.regime_detector.predict_current()

            # DB + Cache 기록
            pg.insert_regime(regime)
            cache.set_regime(regime)

            if regime.is_transition:
                await self.telegram.send_regime_change(
                    regime.previous or "unknown",
                    regime.current,
                    regime.bull_prob,
                    regime.sideways_prob,
                    regime.bear_prob,
                )
            self.last_regime = regime.current
            logger.info(f"  ① 레짐: {regime.current} "
                       f"(conf={regime.confidence:.1%})")
            result["steps"]["regime"] = regime.current

            # ══════════════════════════════
            # STEP 2: Kill Switch
            # ══════════════════════════════
            pv = self.executor.get_portfolio_value()
            prev_level = self.kill_switch.level
            kill_level = self.kill_switch.update(pv)
            mdd = self.kill_switch.current_mdd

            if kill_level != prev_level:
                pg.insert_kill_switch_event(
                    prev_level.value, kill_level.value,
                    mdd, pv,
                    self.kill_switch.get_exposure_limit(),
                    self.kill_switch.cooldown_until,
                )
                await self.telegram.send_kill_switch(
                    prev_level.value, kill_level.value, mdd, pv,
                )

            cache.set_kill_switch(
                kill_level.value, mdd,
                self.kill_switch.get_exposure_limit(),
            )

            # EMERGENCY → 즉시 청산 후 종료
            if kill_level == DefenseLevel.EMERGENCY:
                logger.warning("EMERGENCY: 전량 청산 실행")
                await self._emergency_liquidate(pv, regime, kill_level)
                result["steps"]["kill_switch"] = "EMERGENCY"
                result["status"] = "emergency_liquidated"
                return result

            logger.info(f"  ② Kill Switch: {kill_level.value} "
                       f"(MDD={mdd:.2%}, exp={self.kill_switch.get_exposure_limit():.0%})")
            result["steps"]["kill_switch"] = kill_level.value

            # ══════════════════════════════
            # STEP 3: 레짐별 배분
            # ══════════════════════════════
            exposure_limit = self.kill_switch.get_exposure_limit()
            alloc = self.allocator.get_allocation(regime, exposure_limit)

            logger.info(f"  ③ 배분: LV={alloc.lowvol_quality:.1%} "
                       f"Mom={alloc.vol_momentum:.1%} "
                       f"Pairs={alloc.pairs_trading:.1%} "
                       f"Cash={alloc.cash:.1%}")
            result["steps"]["allocation"] = {
                "lowvol_quality": alloc.lowvol_quality,
                "vol_momentum": alloc.vol_momentum,
                "pairs_trading": alloc.pairs_trading,
                "cash": alloc.cash,
            }

            # ══════════════════════════════
            # STEP 4: 전략 시그널 생성
            # ══════════════════════════════
            all_signals = {}
            allowed = self.kill_switch.get_allowed_strategies()

            strategy_alloc_map = {
                "lowvol_quality": alloc.lowvol_quality,
                "vol_momentum": alloc.vol_momentum,
                "pairs_trading": alloc.pairs_trading,
            }

            for name, strat in self.strategies.items():
                if "all" not in allowed and name not in allowed:
                    logger.info(f"  ④ {name}: BLOCKED by Kill Switch")
                    continue

                try:
                    sigs = strat.generate_signals(
                        regime.current, regime.confidence)
                    all_signals[name] = sigs

                    # 시그널 DB 기록
                    for sig in sigs:
                        pg.insert_signal(
                            sig.symbol, sig.direction,
                            sig.strength, name, regime.current,
                        )
                    logger.info(f"  ④ {name}: {len(sigs)} 시그널")
                except Exception as e:
                    logger.error(f"  ④ {name} ERROR: {e}")

            total_signals = sum(len(s) for s in all_signals.values())
            result["steps"]["signals"] = total_signals

            if not all_signals:
                logger.info("  → 시그널 없음, 스냅샷만 기록")
                self._record_snapshot(pv, regime, kill_level)
                result["status"] = "no_signals"
                return result

            # ══════════════════════════════
            # STEP 5: 센티먼트 오버레이
            # ══════════════════════════════
            symbols_in_signals = set()
            for sigs in all_signals.values():
                for sig in sigs:
                    symbols_in_signals.add(sig.symbol)

            sentiment_scores = {}
            if symbols_in_signals:
                sentiment_scores = self.sentiment.get_sentiment_scores(
                    list(symbols_in_signals))

            # 센티먼트 조정 적용
            sentiment_range = alloc.sentiment  # 센티먼트 배분 비중
            for name, sigs in all_signals.items():
                if sentiment_scores:
                    all_signals[name] = self.sentiment.apply_overlay(
                        sigs, sentiment_scores, weight=sentiment_range)

            logger.info(f"  ⑤ 센티먼트: {len(sentiment_scores)} 종목 조정")
            result["steps"]["sentiment"] = len(sentiment_scores)

            # ══════════════════════════════
            # STEP 6: Vol-Targeting
            # ══════════════════════════════
            # SPY 수익률로 포트폴리오 변동성 추정
            spy_data = pg.get_ohlcv("SPY", days=30)
            if spy_data and len(spy_data) > 2:
                spy_closes = np.array([float(d["close"]) for d in spy_data])
                spy_returns = np.diff(spy_closes) / spy_closes[:-1]
            else:
                spy_returns = np.zeros(21)

            vol_scale = self.vol_targeting.calculate_scale(
                spy_returns, regime.current)

            logger.info(f"  ⑥ Vol-Targeting: scale={vol_scale:.2f}x")
            result["steps"]["vol_scale"] = vol_scale

            # ══════════════════════════════
            # STEP 7: ATR 포지션 사이징
            # ══════════════════════════════
            orders = []
            for name, sigs in all_signals.items():
                strategy_weight = strategy_alloc_map.get(name, 0)
                for sig in sigs:
                    if abs(sig.strength) < 0.1:
                        continue

                    atr_14 = pg.get_atr(sig.symbol, period=14)
                    price = pg.get_latest_price(sig.symbol)

                    if price <= 0 or atr_14 <= 0:
                        continue

                    pos_size = self.sizer.calculate(
                        symbol=sig.symbol,
                        portfolio_value=pv,
                        current_price=price,
                        atr=atr_14,
                    )

                    # 전략 배분 + Vol Scale + 시그널 강도 적용
                    adj_qty = int(
                        pos_size.shares
                        * strategy_weight
                        * vol_scale
                        * abs(sig.strength)
                    )

                    if adj_qty > 0:
                        side = "buy" if sig.direction == "long" else "sell"
                        orders.append({
                            "symbol": sig.symbol,
                            "side": side,
                            "qty": adj_qty,
                            "strategy": name,
                            "strength": sig.strength,
                            "price": price,
                        })

            logger.info(f"  ⑦ 사이징: {len(orders)} 주문 준비")
            result["steps"]["orders_prepared"] = len(orders)

            # ══════════════════════════════
            # STEP 8: VWAP 분할 실행
            # ══════════════════════════════
            trade_results = []
            for order in orders:
                trade = await self.vwap.execute(
                    order["symbol"], order["side"],
                    order["qty"], slices=config.vwap_slices,
                )

                if trade:
                    # 거래 기록 → PG
                    pg.insert_trade({
                        "order_id": trade["order_id"],
                        "symbol": order["symbol"],
                        "strategy": order["strategy"],
                        "side": order["side"],
                        "qty": trade["filled_qty"],
                        "price": trade["avg_price"],
                        "regime": regime.current,
                        "kill_level": kill_level.value,
                        "is_paper": config.alpaca_paper,
                    })
                    trade_results.append(trade)

            logger.info(f"  ⑧ VWAP 실행: "
                       f"{len(trade_results)}/{len(orders)} 체결")
            result["steps"]["trades_executed"] = len(trade_results)

            # ─── 스냅샷 기록 ───
            pv_after = self.executor.get_portfolio_value()
            self._record_snapshot(pv_after, regime, kill_level, vol_scale)

            # ─── 전략별 성과 기록 ───
            for name in self.strategies:
                sig_count = len(all_signals.get(name, []))
                pg.insert_strategy_perf(
                    strategy=name,
                    daily_return=0.0,  # TODO: 실제 수익률 계산
                    allocation=strategy_alloc_map.get(name, 0),
                    regime=regime.current,
                    signal_count=sig_count,
                )

            # ─── 결과 알림 ───
            elapsed = (datetime.now() - start).total_seconds()
            await self.telegram.send_pipeline_complete(
                regime=regime.current,
                kill_level=kill_level.value,
                signal_count=total_signals,
                trade_count=len(trade_results),
                pv=pv_after,
                mdd=mdd,
                elapsed=elapsed,
            )

            result["elapsed"] = elapsed
            result["pv"] = pv_after
            logger.info(f"파이프라인 완료 ({elapsed:.1f}s)")

        except Exception as e:
            logger.error(f"파이프라인 오류: {e}", exc_info=True)
            await self.telegram.send_error(str(e))
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _record_snapshot(self, value: float, regime, kill_level,
                         vol_scale: float = 1.0):
        """포트폴리오 스냅샷 → PostgreSQL"""
        mdd = self.kill_switch.current_mdd
        pg.insert_snapshot(
            value=value,
            regime=regime.current,
            regime_confidence=regime.confidence,
            kill_level=kill_level.value,
            exposure_limit=self.kill_switch.get_exposure_limit(),
            vol_scale=vol_scale,
            mdd=mdd,
        )

    async def _emergency_liquidate(self, pv: float, regime, kill_level):
        """EMERGENCY: 전량 청산"""
        positions = self.executor.get_positions()
        for pos in positions:
            await self.executor.close_position(pos.symbol)

        self._record_snapshot(pv, regime, kill_level)
        await self.telegram.send_emergency(
            len(positions), self.kill_switch.cooldown_days)

    async def collect_daily_data(self):
        """일봉 데이터 수집 (yfinance → PostgreSQL)"""
        logger.info("데이터 수집 시작...")
        try:
            import yfinance as yf
            with pg.get_conn() as conn:
                symbols = conn.execute(
                    "SELECT symbol FROM symbols WHERE is_active = true"
                ).fetchall()

            count = 0
            for row in symbols:
                sym = row["symbol"]
                try:
                    df = yf.download(sym, period="5d", progress=False)
                    if df.empty:
                        continue
                    with pg.get_conn() as conn:
                        for idx, r in df.iterrows():
                            conn.execute("""
                                INSERT INTO daily_prices
                                    (time, symbol, open, high, low, close, volume)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (time, symbol) DO NOTHING
                            """, (idx, sym,
                                  float(r["Open"]), float(r["High"]),
                                  float(r["Low"]), float(r["Close"]),
                                  int(r["Volume"])))
                        conn.commit()
                    count += 1
                except Exception as e:
                    logger.warning(f"  {sym} 수집 실패: {e}")
            logger.info(f"데이터 수집 완료: {count}/{len(symbols)} 종목")
        except Exception as e:
            logger.error(f"데이터 수집 오류: {e}")
            raise

    async def scan_sentiment(self):
        """FinBERT 센티먼트 스캔 (장중 매시간)"""
        logger.info("센티먼트 스캔 시작...")
        try:
            with pg.get_conn() as conn:
                symbols = conn.execute(
                    "SELECT symbol FROM symbols WHERE is_active = true"
                ).fetchall()
            sym_list = [r["symbol"] for r in symbols[:20]]
            scores = self.sentiment.get_sentiment_scores(sym_list)
            logger.info(f"센티먼트 스캔 완료: {len(scores)} 종목")
        except Exception as e:
            logger.error(f"센티먼트 스캔 오류: {e}")

    async def refresh_materialized_views(self):
        """물리뷰 갱신"""
        logger.info("물리뷰 갱신 시작...")
        try:
            with pg.get_conn() as conn:
                # TimescaleDB 연속집계 갱신
                conn.execute(
                    "CALL refresh_continuous_aggregate("
                    "'portfolio_daily', NULL, NULL)"
                )
                conn.commit()
            logger.info("물리뷰 갱신 완료")
        except Exception as e:
            logger.warning(f"물리뷰 갱신 참고: {e}")


# ══════════════════════════════
# FastAPI Routes
# ══════════════════════════════

@app.get("/health")
async def health():
    """헬스체크"""
    return {
        "status": "ok",
        "version": "3.1-ubuntu",
        "time": datetime.now().isoformat(),
        "redis": cache.ping(),
    }


@app.post("/run")
async def run_pipeline(bg: BackgroundTasks):
    """파이프라인 수동 실행 (비동기 백그라운드)"""
    bg.add_task(app.state.orchestrator.execute_daily)
    return {"status": "pipeline_started", "time": datetime.now().isoformat()}


@app.get("/regime")
async def get_regime():
    """현재 레짐 상태"""
    cached = cache.get_regime()
    if cached:
        return cached
    db_regime = pg.get_latest_regime()
    return db_regime or {"regime": "unknown"}


@app.get("/kill-switch")
async def get_kill_switch():
    """Kill Switch 상태"""
    cached = cache.get_kill_switch()
    if cached:
        return cached
    orch = app.state.orchestrator
    state = orch.kill_switch.get_state()
    return {
        "level": state.level.value,
        "mdd": state.current_mdd,
        "exposure_limit": state.exposure_limit,
        "peak_value": state.peak_value,
    }


@app.get("/portfolio")
async def get_portfolio():
    """최신 포트폴리오 스냅샷"""
    snapshot = pg.get_latest_snapshot()
    if snapshot:
        return dict(snapshot)
    return {"total_value": 0, "regime": "unknown"}


@app.get("/account")
async def get_account():
    """Alpaca 계좌 정보"""
    orch = app.state.orchestrator
    return orch.executor.get_account()


@app.get("/scheduler")
async def get_scheduler_status():
    """스케줄러 상태 조회"""
    scheduler = getattr(app.state, "scheduler", None)
    if not scheduler:
        return {"status": "disabled"}

    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None,
        })
    return {"status": "running", "jobs": jobs}


@app.get("/explain/regime")
async def explain_regime():
    """레짐 피처 중요도"""
    explainer = getattr(app.state, "explainer", None)
    if not explainer:
        return {"error": "explainer not configured"}
    return explainer.regime_feature_importance()


@app.get("/explain/strategy/{strategy}")
async def explain_strategy(strategy: str):
    """전략별 시그널 통계"""
    explainer = getattr(app.state, "explainer", None)
    if not explainer:
        return {"error": "explainer not configured"}
    return explainer.strategy_feature_summary(strategy)


@app.get("/signals")
async def get_signals(strategy: str = "", limit: int = 50):
    """최근 시그널 목록"""
    with pg.get_conn() as conn:
        if strategy:
            rows = conn.execute("""
                SELECT symbol, direction, strength, strategy,
                       regime, time
                FROM signal_log
                WHERE strategy = %s
                ORDER BY time DESC LIMIT %s
            """, (strategy, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT symbol, direction, strength, strategy,
                       regime, time
                FROM signal_log
                ORDER BY time DESC LIMIT %s
            """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════
# Phase 4 — Backtest API Routes
# ══════════════════════════════

@app.get("/backtest/runs")
async def get_backtest_runs(limit: int = 20):
    """백테스트 실행 이력"""
    with pg.get_conn() as conn:
        rows = conn.execute("""
            SELECT run_id, name, run_type, status,
                   started_at, finished_at, summary
            FROM backtest_runs
            ORDER BY started_at DESC
            LIMIT %s
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.get("/backtest/runs/{run_id}")
async def get_backtest_run(run_id: int):
    """백테스트 단일 실행 상세"""
    with pg.get_conn() as conn:
        row = conn.execute("""
            SELECT run_id, name, run_type, status, config,
                   started_at, finished_at, summary
            FROM backtest_runs WHERE run_id = %s
        """, (run_id,)).fetchone()
    if not row:
        return {"error": "run not found"}
    return dict(row)


@app.post("/backtest/walk-forward")
async def run_walk_forward(bg: BackgroundTasks):
    """Walk-Forward 검증 실행 (백그라운드)"""
    from engine.backtest.walk_forward import WalkForwardValidator
    validator = WalkForwardValidator(config)

    async def _run():
        try:
            validator.run()
        except Exception as e:
            logger.error(f"Walk-Forward failed: {e}")

    bg.add_task(_run)
    return {"status": "walk_forward_started"}


@app.post("/backtest/monte-carlo")
async def run_monte_carlo(bg: BackgroundTasks, n_sims: int = 10000):
    """Monte Carlo 시뮬레이션 (백그라운드)"""
    from engine.backtest.monte_carlo import MonteCarloSimulator
    from datetime import date, timedelta

    async def _run():
        try:
            engine = BacktestEngine(config)
            start = date.today() - timedelta(days=config.backtest_years * 365)
            result = engine.run(start, date.today())
            mc = MonteCarloSimulator(config)
            mc.run_and_save(result.daily_returns, n_sims=n_sims)
        except Exception as e:
            logger.error(f"Monte Carlo failed: {e}")

    bg.add_task(_run)
    return {"status": "monte_carlo_started", "n_sims": n_sims}


@app.post("/backtest/stress-test")
async def run_stress_test(bg: BackgroundTasks):
    """Regime Stress Test (백그라운드)"""
    from engine.backtest.regime_stress import RegimeStressTester

    async def _run():
        try:
            tester = RegimeStressTester(config)
            tester.run_all()
        except Exception as e:
            logger.error(f"Stress Test failed: {e}")

    bg.add_task(_run)
    return {"status": "stress_test_started"}


@app.post("/backtest/dsr")
async def run_dsr(bg: BackgroundTasks, n_trials: int = 1):
    """DSR 계산 (백그라운드)"""
    from engine.backtest.dsr import DeflatedSharpeRatio
    from datetime import date, timedelta

    async def _run():
        try:
            engine = BacktestEngine(config)
            start = date.today() - timedelta(days=config.backtest_years * 365)
            result = engine.run(start, date.today())
            dsr = DeflatedSharpeRatio(config)
            dsr.run_and_save(result.daily_returns, n_trials=n_trials)
        except Exception as e:
            logger.error(f"DSR failed: {e}")

    bg.add_task(_run)
    return {"status": "dsr_started", "n_trials": n_trials}


@app.post("/backtest/granger")
async def run_granger(bg: BackgroundTasks, max_lag: int = 5):
    """Granger Causality Test (백그라운드)"""
    from engine.backtest.granger_test import GrangerCausalityTester

    async def _run():
        try:
            tester = GrangerCausalityTester(config)
            tester.run(max_lag=max_lag)
        except Exception as e:
            logger.error(f"Granger failed: {e}")

    bg.add_task(_run)
    return {"status": "granger_started", "max_lag": max_lag}


@app.get("/backtest/walk-forward/results")
async def get_walk_forward_results(run_id: int = 0):
    """Walk-Forward 결과 조회"""
    with pg.get_conn() as conn:
        if run_id > 0:
            rows = conn.execute("""
                SELECT * FROM walk_forward_results
                WHERE run_id = %s ORDER BY fold_num
            """, (run_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT wf.* FROM walk_forward_results wf
                JOIN (SELECT run_id FROM backtest_runs
                      WHERE run_type = 'walk_forward' AND status = 'completed'
                      ORDER BY finished_at DESC LIMIT 1) latest
                ON wf.run_id = latest.run_id
                ORDER BY wf.fold_num
            """).fetchall()
    return [dict(r) for r in rows]


@app.get("/backtest/monte-carlo/results")
async def get_monte_carlo_results(run_id: int = 0):
    """Monte Carlo 결과 조회"""
    with pg.get_conn() as conn:
        if run_id > 0:
            row = conn.execute("""
                SELECT * FROM monte_carlo_results WHERE run_id = %s
            """, (run_id,)).fetchone()
        else:
            row = conn.execute("""
                SELECT mc.* FROM monte_carlo_results mc
                JOIN (SELECT run_id FROM backtest_runs
                      WHERE run_type = 'monte_carlo' AND status = 'completed'
                      ORDER BY finished_at DESC LIMIT 1) latest
                ON mc.run_id = latest.run_id
            """).fetchone()
    return dict(row) if row else {"error": "no results"}


@app.get("/backtest/stress-test/results")
async def get_stress_results(run_id: int = 0):
    """Regime Stress Test 결과 조회"""
    with pg.get_conn() as conn:
        if run_id > 0:
            rows = conn.execute("""
                SELECT * FROM regime_stress_results WHERE run_id = %s
            """, (run_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT rs.* FROM regime_stress_results rs
                JOIN (SELECT run_id FROM backtest_runs
                      WHERE run_type = 'regime_stress' AND status = 'completed'
                      ORDER BY finished_at DESC LIMIT 1) latest
                ON rs.run_id = latest.run_id
            """).fetchall()
    return [dict(r) for r in rows]


@app.get("/backtest/dsr/results")
async def get_dsr_results(run_id: int = 0):
    """DSR 결과 조회"""
    with pg.get_conn() as conn:
        if run_id > 0:
            row = conn.execute("""
                SELECT * FROM dsr_results WHERE run_id = %s
            """, (run_id,)).fetchone()
        else:
            row = conn.execute("""
                SELECT d.* FROM dsr_results d
                JOIN (SELECT run_id FROM backtest_runs
                      WHERE run_type = 'dsr' AND status = 'completed'
                      ORDER BY finished_at DESC LIMIT 1) latest
                ON d.run_id = latest.run_id
            """).fetchone()
    return dict(row) if row else {"error": "no results"}


@app.get("/backtest/granger/results")
async def get_granger_results(run_id: int = 0):
    """Granger 결과 조회"""
    with pg.get_conn() as conn:
        if run_id > 0:
            rows = conn.execute("""
                SELECT * FROM granger_results WHERE run_id = %s
            """, (run_id,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT g.* FROM granger_results g
                JOIN (SELECT run_id FROM backtest_runs
                      WHERE run_type = 'granger' AND status = 'completed'
                      ORDER BY finished_at DESC LIMIT 1) latest
                ON g.run_id = latest.run_id
            """).fetchall()
    return [dict(r) for r in rows]


@app.get("/backtest/go-stop")
async def get_go_stop_status():
    """GO/STOP 최종 판정 조회"""
    with pg.get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM go_stop_log
            ORDER BY decided_at DESC LIMIT 1
        """).fetchone()
    if not row:
        return {"decision": "NOT_YET", "message": "No GO/STOP decision yet"}
    return dict(row)
