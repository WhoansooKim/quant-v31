"""Swing Trading Engine — FastAPI 4단계 파이프라인."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from engine_v4.ai.data_feeds import FinnhubClient
from engine_v4.ai.multi_factor import MultiFactorScorer
from engine_v4.ai.optimizer import StrategyOptimizer
from engine_v4.ai.sentiment import SentimentAnalyzer
from engine_v4.backtest.runner import BacktestParams, BacktestRunner
from engine_v4.broker.kis_client import KisClient
from engine_v4.config.settings import get_config
from engine_v4.data.collector import DataCollector, UniverseManager
from engine_v4.data.storage import PostgresStore, RedisCache
from engine_v4.notify.telegram import TelegramNotifier
from engine_v4.events.collector import EventCollector
from engine_v4.events.edgar import EdgarRssMonitor
from engine_v4.events.processor import EventProcessor
from engine_v4.risk.exit_manager import ExitManager
from engine_v4.risk.position_manager import PositionManager
from engine_v4.scheduler.jobs import SwingScheduler
from engine_v4.strategy.swing import SwingStrategy

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Global instances ──
config = get_config()
pg = PostgresStore(config.pg_dsn)
cache = RedisCache(config.redis_url)
universe_mgr = UniverseManager(pg, cache)
collector = DataCollector(pg, cache, config)
strategy = SwingStrategy(pg, config)
pos_mgr = PositionManager(pg, config)
exit_mgr = ExitManager(pg)
backtester = BacktestRunner(pg)
kis = KisClient(config)
notifier = TelegramNotifier(config)
sentiment = SentimentAnalyzer(pg, config.anthropic_key)
finnhub = FinnhubClient(config.finnhub_api_key)
scorer = MultiFactorScorer(pg, finnhub, config.anthropic_key)
optimizer = StrategyOptimizer(pg, backtester, config.anthropic_key)
event_collector = EventCollector(pg, finnhub)
event_processor = EventProcessor(pg)
edgar = EdgarRssMonitor()
swing_scheduler = SwingScheduler(
    pg, cache, config, universe_mgr, collector, strategy, notifier)

# ── SSE (Server-Sent Events) ──
_sse_subscribers: list[asyncio.Queue] = []


def _sse_broadcast(data: dict):
    """SSE 구독자 전체에게 이벤트 브로드캐스트."""
    msg = json.dumps(data, default=str)
    dead = []
    for q in _sse_subscribers:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _sse_subscribers.remove(q)


# ── Lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Swing Engine V4 starting...")
    logger.info(f"  DB: {config.pg_dsn[:40]}...")
    logger.info(f"  Redis: {config.redis_url}")
    logger.info(f"  Mode: {config.trading_mode}")
    logger.info(f"  KIS: {'connected' if kis.is_connected else 'simulation'}")
    logger.info(f"  Telegram: {'enabled' if notifier.is_enabled else 'disabled'}")
    swing_scheduler.start()
    yield
    swing_scheduler.stop()
    logger.info("Swing Engine V4 stopped")


app = FastAPI(
    title="Swing Trading Engine V4",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════
# Request / Response Models
# ═══════════════════════════════════════════════════════════

class BacktestRequest(BaseModel):
    start_date: date = date(2020, 1, 1)
    end_date: date = date(2025, 12, 31)
    initial_capital: float = 2200.0
    stop_loss_pct: float = -0.05
    take_profit_pct: float = 0.10
    max_positions: int = 4
    position_pct: float = 0.05


class OptimizeRequest(BaseModel):
    start_date: date = date(2022, 1, 1)
    end_date: date = date(2025, 12, 31)
    initial_capital: float = 10000.0
    rounds: int = 1


class ConfigUpdate(BaseModel):
    value: str


# ═══════════════════════════════════════════════════════════
# Health
# ═══════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "engine": "swing_v4",
        "mode": config.trading_mode,
        "db": pg.health_check(),
        "redis": cache.ping(),
        "kis": kis.is_connected,
        "telegram": notifier.is_enabled,
        "scheduler_jobs": len(swing_scheduler.get_jobs()),
    }


# ═══════════════════════════════════════════════════════════
# Step 1: COLLECT
# ═══════════════════════════════════════════════════════════

@app.post("/collect")
async def collect_data(bg: BackgroundTasks):
    """데이터 수집 (백그라운드)."""
    bg.add_task(_run_collect)
    return {"status": "collecting", "message": "Data collection started in background"}


def _run_collect():
    start = time.time()
    pg.insert_pipeline_log("collect", "started")
    try:
        universe = universe_mgr.get_universe()
        if not universe:
            universe = universe_mgr.refresh_universe()
        symbols = [u["symbol"] for u in universe]

        count = collector.collect_prices(symbols, days=300)
        ind_count = collector.compute_indicators(symbols)

        elapsed = time.time() - start
        pg.insert_pipeline_log("collect", "completed", elapsed, {
            "symbols": len(symbols), "prices": count, "indicators": ind_count,
        })
        logger.info(f"Collect done: {count} prices, {ind_count} indicators in {elapsed:.1f}s")
    except Exception as e:
        pg.insert_pipeline_log("collect", "failed", time.time() - start, error_msg=str(e))
        logger.error(f"Collect failed: {e}")


# ═══════════════════════════════════════════════════════════
# Step 2: SCAN
# ═══════════════════════════════════════════════════════════

@app.post("/scan")
async def scan_signals():
    """시그널 스캔 (진입 + 청산)."""
    start = time.time()
    pg.insert_pipeline_log("scan", "started")
    try:
        entries = strategy.scan_entries()
        exits = strategy.scan_exits()
        elapsed = time.time() - start
        pg.insert_pipeline_log("scan", "completed", elapsed, {
            "entries": len(entries), "exits": len(exits),
        })
        return {
            "status": "ok",
            "entries": len(entries),
            "exits": len(exits),
            "signals": entries + exits,
            "elapsed_sec": round(elapsed, 2),
        }
    except Exception as e:
        pg.insert_pipeline_log("scan", "failed", time.time() - start, error_msg=str(e))
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════
# Step 3: Signals CRUD
# ═══════════════════════════════════════════════════════════

@app.get("/signals")
async def list_signals(status: str | None = None, limit: int = 50):
    signals = pg.get_signals(status=status, limit=limit)
    return {"signals": signals, "count": len(signals)}


@app.get("/signals/{signal_id}")
async def get_signal(signal_id: int):
    sig = pg.get_signal(signal_id)
    if not sig:
        raise HTTPException(404, "Signal not found")
    return sig


@app.post("/signals/{signal_id}/approve")
async def approve_signal(signal_id: int):
    """시그널 승인 → 자동 체결."""
    sig = pg.get_signal(signal_id)
    if not sig:
        raise HTTPException(404, "Signal not found")
    if sig["status"] != "pending":
        raise HTTPException(400, f"Signal status is '{sig['status']}', not 'pending'")

    # 승인
    pg.approve_signal(signal_id)

    # 체결
    account_value = _get_account_value()

    if sig["signal_type"] == "ENTRY":
        result = pos_mgr.execute_entry(sig, account_value)
        if not result:
            pg.reject_signal(signal_id)
            raise HTTPException(400, "Entry execution failed (limits or validation)")

        # KIS 주문
        order = kis.buy(
            symbol=sig["symbol"],
            qty=result["qty"],
            price=float(sig["entry_price"]),
        )
        result["order_id"] = order.order_id
        result["kis_message"] = order.message

        # 텔레그램 알림
        await notifier.notify_trade({
            "side": "BUY", "symbol": sig["symbol"],
            "qty": result["qty"], "entry_price": sig["entry_price"],
            "amount": result["amount"], "order_id": order.order_id,
        })

    elif sig["signal_type"] == "EXIT":
        result = pos_mgr.execute_exit(sig)
        if not result:
            raise HTTPException(400, "Exit execution failed")

        # KIS 주문
        order = kis.sell(
            symbol=result["symbol"],
            qty=int(result.get("qty", 0) or 0) or 1,
            price=result["exit_price"],
        )
        result["order_id"] = order.order_id
        result["kis_message"] = order.message

        # 텔레그램 알림
        await notifier.notify_trade({
            "side": "SELL", "symbol": result["symbol"],
            "qty": result.get("qty"), "exit_price": result["exit_price"],
            "pnl": result.get("pnl"), "order_id": order.order_id,
        })
    else:
        raise HTTPException(400, f"Unknown signal type: {sig['signal_type']}")

    # SSE broadcast
    _sse_broadcast({
        "type": "trade_executed",
        "symbol": sig["symbol"],
        "side": sig["signal_type"],
        "signal_id": signal_id,
    })

    return {"status": "executed", "result": result}


@app.post("/signals/{signal_id}/reject")
async def reject_signal(signal_id: int):
    ok = pg.reject_signal(signal_id)
    if not ok:
        raise HTTPException(400, "Cannot reject (not pending)")
    return {"status": "rejected", "signal_id": signal_id}


@app.post("/signals/{signal_id}/analyze")
async def analyze_signal(signal_id: int):
    """단일 시그널 AI 분석."""
    sig = pg.get_signal(signal_id)
    if not sig:
        raise HTTPException(404, "Signal not found")
    try:
        result = sentiment.analyze_signal(signal_id)
        return result
    except Exception as e:
        logger.error(f"AI analysis failed for signal {signal_id}: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/signals/analyze-pending")
async def analyze_pending_signals():
    """모든 pending 시그널 일괄 AI 분석."""
    try:
        results = sentiment.analyze_pending()
        return {
            "status": "ok",
            "analyzed": len(results),
            "mode": "live" if sentiment.is_live else "mock",
            "results": results,
        }
    except Exception as e:
        logger.error(f"Batch AI analysis failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════
# Multi-Factor Scoring
# ═══════════════════════════════════════════════════════════

@app.post("/signals/{signal_id}/score")
async def score_signal(signal_id: int):
    """단일 시그널 멀티팩터 스코어링."""
    sig = pg.get_signal(signal_id)
    if not sig:
        raise HTTPException(404, "Signal not found")
    try:
        result = scorer.score_signal(signal_id)
        return result
    except Exception as e:
        logger.error(f"Factor scoring failed for signal {signal_id}: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@app.post("/signals/score-pending")
async def score_pending_signals():
    """모든 pending 시그널 멀티팩터 스코어링."""
    try:
        results = scorer.score_pending_signals()
        return {
            "status": "ok",
            "scored": len(results),
            "finnhub": finnhub.is_available,
            "claude": scorer._claude is not None,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Batch factor scoring failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════
# Step 4: Positions
# ═══════════════════════════════════════════════════════════

@app.get("/positions")
async def list_positions():
    positions = pg.get_open_positions()
    return {"positions": positions, "count": len(positions)}


@app.get("/positions/closed")
async def closed_positions(limit: int = 50):
    positions = pg.get_closed_positions(limit=limit)
    return {"positions": positions, "count": len(positions)}


# ═══════════════════════════════════════════════════════════
# Portfolio
# ═══════════════════════════════════════════════════════════

@app.get("/portfolio")
async def portfolio_snapshot():
    """현재 포트폴리오 상태."""
    snap = cache.get_snapshot()
    if not snap:
        snap = pg.get_latest_snapshot()
    positions = pg.get_open_positions()
    return {
        "snapshot": snap,
        "open_positions": len(positions),
        "positions": positions,
    }


@app.get("/portfolio/history")
async def portfolio_history(days: int = 30):
    snapshots = pg.get_snapshots(days=days)
    return {"snapshots": snapshots, "count": len(snapshots)}


# ═══════════════════════════════════════════════════════════
# Account
# ═══════════════════════════════════════════════════════════

@app.get("/account")
async def account_info():
    """계좌 잔고 (KIS API 연동)."""
    balance = kis.get_balance()
    return {
        "mode": config.trading_mode,
        "kis_connected": kis.is_connected,
        "total_value_usd": balance.total_value_usd,
        "cash_usd": balance.cash_usd,
        "invested_usd": balance.invested_usd,
        "profit_usd": balance.profit_usd,
        "profit_rate": balance.profit_rate,
        "holdings": balance.holdings,
        "db_positions": pg.get_open_position_count(),
        "max_positions": config.max_positions,
    }


@app.get("/scheduler")
async def scheduler_status():
    """스케줄러 상태."""
    return {
        "jobs": swing_scheduler.get_jobs(),
        "count": len(swing_scheduler.get_jobs()),
    }


# ═══════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════

@app.get("/config")
async def get_all_config():
    configs = pg.get_config()
    return {"configs": configs}


@app.put("/config/{key}")
async def update_config(key: str, body: ConfigUpdate):
    ok = pg.update_config(key, body.value)
    if not ok:
        raise HTTPException(404, f"Config key '{key}' not found")
    return {"status": "updated", "key": key, "value": body.value}


# ═══════════════════════════════════════════════════════════
# Backtest
# ═══════════════════════════════════════════════════════════

@app.post("/backtest/run")
async def run_backtest(req: BacktestRequest, bg: BackgroundTasks):
    """백테스트 실행 (백그라운드)."""
    bg.add_task(_run_backtest, req)
    return {"status": "running", "message": "Backtest started in background"}


def _run_backtest(req: BacktestRequest):
    params = BacktestParams(
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        stop_loss_pct=req.stop_loss_pct,
        take_profit_pct=req.take_profit_pct,
        max_positions=req.max_positions,
        position_pct=req.position_pct,
    )
    result = backtester.run(params)
    cache.set_json("backtest_latest", {
        "total_return": result.total_return,
        "cagr": result.cagr,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "win_rate": result.win_rate,
        "total_trades": result.total_trades,
    }, ttl=86400)


@app.get("/backtest/results")
async def backtest_results(limit: int = 20):
    runs = pg.get_backtest_runs(limit=limit)
    return {"runs": runs, "count": len(runs)}


@app.get("/backtest/results/{run_id}")
async def backtest_detail(run_id: int):
    run = pg.get_backtest_run(run_id)
    if not run:
        raise HTTPException(404, "Backtest run not found")
    return run


# ═══════════════════════════════════════════════════════════
# Strategy Optimization (Phase D)
# ═══════════════════════════════════════════════════════════

@app.post("/optimize/run")
async def run_optimization(req: OptimizeRequest, bg: BackgroundTasks):
    """LLM 기반 전략 최적화 (백그라운드)."""
    bg.add_task(_run_optimization, req)
    return {"status": "running",
            "message": f"Optimization started: {req.start_date}~{req.end_date}, "
                       f"${req.initial_capital:,.0f}, {req.rounds} round(s)"}


def _run_optimization(req: OptimizeRequest):
    try:
        result = optimizer.optimize(
            rounds=req.rounds,
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
        )
        cache.set_json("optimize_latest", result, ttl=86400)
        logger.info(f"Optimization completed: {result.get('total_variations')} variants")
    except Exception as e:
        logger.error(f"Optimization failed: {e}", exc_info=True)
        cache.set_json("optimize_latest", {"status": "failed", "error": str(e)}, ttl=3600)


@app.get("/optimize/results")
async def get_optimization_results():
    """최적화 결과 조회 (캐시)."""
    result = cache.get_json("optimize_latest")
    if not result:
        return {"status": "no_results", "message": "Run POST /optimize/run first"}
    return result


# ═══════════════════════════════════════════════════════════
# Events (Phase E)
# ═══════════════════════════════════════════════════════════

@app.post("/events/scan")
async def scan_events():
    """보유 종목 이벤트 스캔 (Finnhub + yfinance)."""
    try:
        events = event_collector.scan_events()
        results = event_processor.process_batch(events)

        # Telegram: critical/warning 이벤트 알림
        if notifier.is_enabled:
            sent = await notifier.notify_events_batch(results)
            if sent:
                logger.info(f"Telegram: {sent} event alerts sent")

        # SSE broadcast
        _sse_broadcast({
            "type": "events_scanned",
            "count": len(results),
            "critical": sum(1 for r in results if r.get("severity") == "critical"),
            "warning": sum(1 for r in results if r.get("severity") == "warning"),
        })

        return {
            "status": "ok",
            "events_found": len(events),
            "processed": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error(f"Event scan failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@app.get("/events")
async def list_events(limit: int = 50,
                      event_type: str | None = None,
                      symbol: str | None = None,
                      severity: str | None = None):
    """이벤트 목록 조회."""
    events = event_processor.get_events(
        limit=limit, event_type=event_type,
        symbol=symbol, severity=severity)
    return {"events": events, "count": len(events)}


@app.post("/webhook/tradingview")
async def tradingview_webhook(payload: dict):
    """TradingView 웹훅 수신."""
    from engine_v4.events.models import Event
    event = Event(
        event_type="tradingview_alert",
        symbol=payload.get("symbol"),
        severity=payload.get("severity", "info"),
        title=payload.get("title", "TradingView Alert"),
        detail=payload,
    )
    result = event_processor.process(event)
    return {"status": "received", **result}


# ═══════════════════════════════════════════════════════════
# SSE (Server-Sent Events)
# ═══════════════════════════════════════════════════════════

@app.get("/events/stream")
async def event_stream(request: Request):
    """SSE 스트림 — 대시보드 실시간 알림."""
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_subscribers.append(q)

    async def generate():
        try:
            # 연결 확인 heartbeat
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            if q in _sse_subscribers:
                _sse_subscribers.remove(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════
# Trading Mode (Paper/Live Toggle)
# ═══════════════════════════════════════════════════════════

class TradingModeRequest(BaseModel):
    mode: str  # "paper" or "live"
    confirm: bool = False


@app.post("/config/trading-mode")
async def change_trading_mode(req: TradingModeRequest):
    """트레이딩 모드 변경 (paper ↔ live)."""
    if req.mode not in ("paper", "live"):
        raise HTTPException(400, "Mode must be 'paper' or 'live'")

    old_mode = pg.get_config_value("trading_mode", "paper")
    if old_mode == req.mode:
        return {"status": "unchanged", "mode": req.mode}

    # Live 모드 전환 시 확인 필요
    if req.mode == "live" and not req.confirm:
        raise HTTPException(400,
            "Live trading requires confirmation. "
            "Set confirm=true to proceed. "
            "WARNING: Real money will be used for trades!")

    # Live 전환 시 KIS 키 확인
    if req.mode == "live":
        if not config.kis_app_key or config.kis_app_key == "":
            raise HTTPException(400, "KIS API keys not configured. Set KIS_APP_KEY in .env")

    # DB 업데이트
    pg.update_config("trading_mode", req.mode)

    # KIS 클라이언트 재초기화
    kis._initialized = False
    if req.mode == "live":
        config.kis_is_paper = False
    else:
        config.kis_is_paper = True
    kis.settings = config
    kis._init_client()

    # Telegram 알림
    if notifier.is_enabled:
        await notifier.notify_mode_change(old_mode, req.mode)

    # SSE broadcast
    _sse_broadcast({
        "type": "mode_changed",
        "old_mode": old_mode,
        "new_mode": req.mode,
    })

    logger.warning(f"Trading mode changed: {old_mode} → {req.mode}")
    return {
        "status": "changed",
        "old_mode": old_mode,
        "new_mode": req.mode,
        "kis_connected": kis.is_connected,
    }


# ═══════════════════════════════════════════════════════════
# SEC EDGAR RSS
# ═══════════════════════════════════════════════════════════

@app.post("/events/edgar-scan")
async def scan_edgar():
    """SEC EDGAR RSS 스캔 — 보유 종목 공시 확인."""
    try:
        positions = pg.get_open_positions()
        if not positions:
            return {"status": "ok", "events_found": 0, "message": "No open positions"}

        symbols = list(set(p["symbol"] for p in positions))
        events = edgar.scan_filings(symbols)
        results = event_processor.process_batch(events)

        # Telegram: critical/warning 알림
        if notifier.is_enabled:
            await notifier.notify_events_batch(results)

        # SSE broadcast
        if results:
            _sse_broadcast({
                "type": "edgar_scanned",
                "count": len(results),
            })

        return {
            "status": "ok",
            "events_found": len(events),
            "processed": len(results),
            "results": results,
        }
    except Exception as e:
        logger.error(f"EDGAR scan failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════
# Trades
# ═══════════════════════════════════════════════════════════

@app.get("/trades")
async def list_trades(limit: int = 50):
    trades = pg.get_trades(limit=limit)
    return {"trades": trades, "count": len(trades)}


# ═══════════════════════════════════════════════════════════
# Universe
# ═══════════════════════════════════════════════════════════

@app.get("/universe")
async def get_universe():
    uni = universe_mgr.get_universe()
    return {"symbols": uni, "count": len(uni)}


@app.post("/universe/refresh")
async def refresh_universe(bg: BackgroundTasks):
    bg.add_task(universe_mgr.refresh_universe)
    return {"status": "refreshing", "message": "Universe refresh started"}


# ═══════════════════════════════════════════════════════════
# Pipeline (full cycle)
# ═══════════════════════════════════════════════════════════

@app.post("/pipeline/run")
async def run_full_pipeline(bg: BackgroundTasks):
    """4단계 전체 파이프라인 실행."""
    bg.add_task(_run_pipeline)
    return {"status": "running", "message": "Full pipeline started"}


def _run_pipeline():
    """Step1 Collect → Step2 Scan → Step3 Notify."""
    import asyncio
    start = time.time()
    pg.insert_pipeline_log("full_pipeline", "started")
    try:
        # Step 1: Collect
        universe = universe_mgr.get_universe()
        if not universe:
            universe = universe_mgr.refresh_universe()
        symbols = [u["symbol"] for u in universe]

        collector.collect_prices(symbols, days=300)
        collector.compute_indicators(symbols)

        # Step 2: Scan
        entries = strategy.scan_entries()
        exits = strategy.scan_exits()

        # Step 2.5: Multi-Factor Scoring (entries only)
        if entries and config.factor_scoring_enabled:
            try:
                scored = scorer.score_pending_signals()
                logger.info(f"Factor scoring: {len(scored)} signals scored")
            except Exception as e:
                logger.warning(f"Factor scoring failed (non-fatal): {e}")

        # Step 3: Notify
        if entries or exits:
            asyncio.run(notifier.notify_signals(entries, exits))
        logger.info(f"Pipeline signals: {len(entries)} entries, {len(exits)} exits")

        # Expire old signals
        expired = pg.expire_old_signals(
            int(pg.get_config_value("signal_expiry_hours", "24")))
        if expired:
            logger.info(f"Expired {expired} old signals")

        elapsed = time.time() - start
        pg.insert_pipeline_log("full_pipeline", "completed", elapsed, {
            "entries": len(entries), "exits": len(exits), "expired": expired,
        })
    except Exception as e:
        pg.insert_pipeline_log("full_pipeline", "failed", time.time() - start,
                               error_msg=str(e))
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        asyncio.run(notifier.notify_error("full_pipeline", str(e)))


# ═══════════════════════════════════════════════════════════
# Snapshot Generation
# ═══════════════════════════════════════════════════════════

@app.post("/snapshot/generate")
async def generate_snapshot():
    """포트폴리오 스냅샷 수동 생성."""
    try:
        result = _generate_snapshot()
        return {"status": "ok", **result}
    except Exception as e:
        logger.error(f"Snapshot generation failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


def _generate_snapshot() -> dict:
    """현재 포트폴리오 상태로 스냅샷 생성.

    계산:
      cash = initial_capital + sum(realized_pnl) - sum(qty * entry_price)
      invested = sum(qty * current_price)
      total = cash + invested
    """
    import yfinance as yf

    INITIAL_CAPITAL = float(pg.get_config_value("initial_capital", "2200"))

    # 1) 오픈 포지션 + 현재가 조회
    positions = pg.get_open_positions()
    open_count = len(positions)

    current_prices = {}
    if positions:
        symbols = list(set(p["symbol"] for p in positions))
        try:
            data = yf.download(symbols, period="1d", progress=False)
            if len(symbols) == 1:
                price = float(data["Close"].iloc[-1])
                current_prices[symbols[0]] = price
            else:
                for sym in symbols:
                    try:
                        price = float(data["Close"][sym].dropna().iloc[-1])
                        current_prices[sym] = price
                    except (KeyError, IndexError):
                        pass
        except Exception as e:
            logger.warning(f"yfinance fetch failed: {e}")

    # 2) 포지션별 현재가 업데이트
    invested_usd = 0.0
    entry_cost = 0.0
    for p in positions:
        sym = p["symbol"]
        qty = float(p.get("qty") or 1)
        ep = float(p["entry_price"])
        entry_cost += qty * ep

        cp = current_prices.get(sym)
        if cp:
            pg.update_position_price(p["position_id"], cp)
            invested_usd += qty * cp
        else:
            invested_usd += qty * ep  # fallback to entry price

    # 3) 실현손익 합산 (closed positions)
    closed = pg.get_closed_positions(limit=9999)
    realized_pnl = sum(float(p.get("realized_pnl") or 0) for p in closed)

    # 4) 포트폴리오 계산
    cash_usd = INITIAL_CAPITAL + realized_pnl - entry_cost
    total_value = cash_usd + invested_usd

    # 5) 일간/누적 수익률, 최대 낙폭
    prev = pg.get_latest_snapshot()
    prev_total = float(prev["total_value_usd"]) if prev and prev.get("total_value_usd") else INITIAL_CAPITAL
    daily_pnl = total_value - prev_total
    daily_return = daily_pnl / prev_total if prev_total > 0 else 0
    cumulative_return = (total_value / INITIAL_CAPITAL) - 1

    # Max drawdown: worst from all snapshots + current
    all_snaps = pg.get_snapshots(days=9999)
    peak = INITIAL_CAPITAL
    worst_dd = 0.0
    for s in all_snaps:
        val = float(s.get("total_value_usd") or 0)
        if val > peak:
            peak = val
        dd = (val - peak) / peak if peak > 0 else 0
        if dd < worst_dd:
            worst_dd = dd
    # Include current
    if total_value > peak:
        peak = total_value
    curr_dd = (total_value - peak) / peak if peak > 0 else 0
    if curr_dd < worst_dd:
        worst_dd = curr_dd

    # 6) 스냅샷 저장
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
    pg.insert_snapshot(snap)
    cache.set_snapshot(snap)

    logger.info(f"Snapshot: total=${total_value:.2f}, cash=${cash_usd:.2f}, "
                f"invested=${invested_usd:.2f}, positions={open_count}, "
                f"daily_pnl=${daily_pnl:.2f}")

    return snap


# ═══════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════

def _get_account_value() -> float:
    """계좌 총 가치. KIS > 스냅샷 > 기본값 순서."""
    # 1) KIS 잔고
    if kis.is_connected:
        bal = kis.get_balance()
        if bal.total_value_usd > 0:
            return bal.total_value_usd
    # 2) DB 스냅샷
    snap = pg.get_latest_snapshot()
    if snap and snap.get("total_value_usd"):
        return float(snap["total_value_usd"])
    # 3) 기본값
    return 2200.0


# ═══════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "engine_v4.api.main:app",
        host=config.api_host,
        port=config.api_port,
        reload=True,
    )
