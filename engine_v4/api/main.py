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


class WatchlistBacktestRequest(BaseModel):
    start_date: date = date(2025, 1, 1)
    end_date: date = date(2025, 12, 31)
    initial_capital: float = 1000.0
    position_pct: float = 0.20
    max_positions: int = 3
    buy_threshold: float = 0.12
    sell_threshold: float = -0.12
    trailing_stop_pct: float = 0.05
    max_hold_days: int = 30


class OptimizeRequest(BaseModel):
    start_date: date = date(2022, 1, 1)
    end_date: date = date(2025, 12, 31)
    initial_capital: float = 10000.0
    rounds: int = 1


class ConfigUpdate(BaseModel):
    value: str


class CapitalEventRequest(BaseModel):
    event_type: str  # "deposit" or "withdraw"
    amount: float
    note: str = ""


class WatchlistAddRequest(BaseModel):
    symbol: str
    company_name: str = ""
    avg_cost: float = 0
    qty: float = 0
    notes: str = ""


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
    capital_adj = pg.get_total_capital_adjustments()
    cash_usd = INITIAL_CAPITAL + capital_adj + realized_pnl - entry_cost
    total_value = cash_usd + invested_usd

    # 5) 순수 트레이딩 손익 (입출금 제외)
    unrealized_pnl = invested_usd - entry_cost
    trading_pnl = realized_pnl + unrealized_pnl

    total_invested = INITIAL_CAPITAL + capital_adj
    cumulative_return = trading_pnl / total_invested if total_invested > 0 else 0

    # Daily P&L: 순수 트레이딩 손익 변동분 (입출금 제외)
    prev = pg.get_latest_snapshot()
    if prev and prev.get("trading_pnl") is not None:
        prev_trading_pnl = float(prev["trading_pnl"])
    elif prev and prev.get("total_value_usd") is not None:
        prev_trading_pnl = float(prev["total_value_usd"]) - total_invested
    else:
        prev_trading_pnl = 0
    daily_pnl = trading_pnl - prev_trading_pnl
    daily_return = daily_pnl / total_invested if total_invested > 0 else 0

    # Max drawdown (TWR 기반 — 입출금 무관)
    all_snaps = pg.get_snapshots(days=9999)
    peak_return = 0.0
    worst_dd = 0.0
    for s in all_snaps:
        cr = float(s.get("cumulative_return") or 0)
        if cr > peak_return:
            peak_return = cr
        dd = cr - peak_return
        if dd < worst_dd:
            worst_dd = dd
    if cumulative_return > peak_return:
        peak_return = cumulative_return
    curr_dd = cumulative_return - peak_return
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
        "trading_pnl": round(trading_pnl, 2),
    }
    pg.insert_snapshot(snap)
    cache.set_snapshot(snap)

    logger.info(f"Snapshot: total=${total_value:.2f}, cash=${cash_usd:.2f}, "
                f"invested=${invested_usd:.2f}, positions={open_count}, "
                f"daily_pnl=${daily_pnl:.2f}")

    return snap


# ═══════════════════════════════════════════════════════════
# Capital Events
# ═══════════════════════════════════════════════════════════

@app.post("/capital/event")
async def add_capital_event(req: CapitalEventRequest):
    """자금 투입/출금 기록."""
    if req.event_type not in ("deposit", "withdraw"):
        raise HTTPException(400, "event_type must be 'deposit' or 'withdraw'")
    if req.amount <= 0:
        raise HTTPException(400, "amount must be positive")

    event_id = pg.insert_capital_event(req.event_type, req.amount, req.note)

    # Telegram 알림
    emoji = "\U0001f4b0" if req.event_type == "deposit" else "\U0001f4b8"
    await notifier.send(
        f"<b>{emoji} Capital {req.event_type.title()}</b>\n\n"
        f"Amount: <b>${req.amount:,.2f}</b>\n"
        f"Note: {req.note or 'N/A'}\n"
        f"\u23f0 {datetime.now().strftime('%H:%M KST')}"
    )

    # SSE broadcast
    _sse_broadcast({
        "type": "capital_event",
        "event_type": req.event_type,
        "amount": req.amount,
    })

    return {"status": "ok", "event_id": event_id, "event_type": req.event_type, "amount": req.amount}


@app.get("/capital/events")
async def list_capital_events():
    events = pg.get_capital_events()
    total = pg.get_total_capital_adjustments()
    return {"events": events, "count": len(events), "net_adjustment": total}


# ═══════════════════════════════════════════════════════════
# Watchlist
# ═══════════════════════════════════════════════════════════

@app.post("/watchlist")
async def add_watchlist(req: WatchlistAddRequest):
    wid = pg.upsert_watchlist(req.symbol, req.company_name, req.avg_cost, req.qty, req.notes)
    return {"status": "ok", "watchlist_id": wid, "symbol": req.symbol.upper()}


@app.get("/watchlist")
async def get_watchlist():
    items = pg.get_watchlist()
    return {"watchlist": items, "count": len(items)}


@app.delete("/watchlist/{symbol}")
async def remove_watchlist(symbol: str):
    ok = pg.delete_watchlist(symbol)
    if not ok:
        raise HTTPException(404, f"{symbol} not in watchlist")
    return {"status": "removed", "symbol": symbol.upper()}


@app.get("/watchlist/alerts")
async def get_watchlist_alerts(symbol: str = None, limit: int = 50):
    alerts = pg.get_watchlist_alerts(symbol=symbol, limit=limit)
    return {"alerts": alerts, "count": len(alerts)}


def _ema(data, period):
    """Calculate EMA of last value."""
    import numpy as np
    if len(data) < period:
        return float(np.mean(data))
    multiplier = 2 / (period + 1)
    ema = float(data[0])
    for price in data[1:]:
        ema = (float(price) - ema) * multiplier + ema
    return ema


def _ema_from_arr(arr, period):
    """EMA of array, return last value."""
    import numpy as np
    if len(arr) < period:
        return float(np.mean(arr))
    multiplier = 2 / (period + 1)
    ema = float(arr[0])
    for v in arr[1:]:
        ema = (float(v) - ema) * multiplier + ema
    return ema


@app.post("/watchlist/analyze")
async def analyze_watchlist(bg: BackgroundTasks):
    """워치리스트 종목 매수/매도 분석 (백그라운드)."""
    bg.add_task(_analyze_watchlist)
    return {"status": "running", "message": "Watchlist analysis started"}


def _analyze_watchlist():
    """워치리스트 전체 분석 — Investing.com 스타일 12개 기술지표 기반 매수/매도 추천."""
    import yfinance as yf
    import numpy as np

    items = pg.get_watchlist()
    if not items:
        cache.set_json("watchlist_analysis", {"status": "done", "results": []}, ttl=86400)
        return

    results = []
    symbols = [w["symbol"] for w in items]

    try:
        data = yf.download(symbols, period="1y", progress=False)
    except Exception as e:
        logger.error(f"Watchlist yfinance failed: {e}")
        cache.set_json("watchlist_analysis", {"status": "failed", "error": str(e)}, ttl=3600)
        return

    def _get_col(col, sym):
        if len(symbols) == 1:
            return data[col].dropna().values
        return data[col][sym].dropna().values

    def _ema_arr(arr, period):
        """Return full EMA array."""
        out = np.empty_like(arr, dtype=float)
        out[0] = float(arr[0])
        m = 2.0 / (period + 1)
        for i in range(1, len(arr)):
            out[i] = (float(arr[i]) - out[i - 1]) * m + out[i - 1]
        return out

    def _sma_arr(arr, period):
        """Return rolling SMA array (NaN-padded)."""
        out = np.full(len(arr), np.nan)
        for i in range(period - 1, len(arr)):
            out[i] = np.mean(arr[i - period + 1:i + 1])
        return out

    def _rsi_series(arr, period=14):
        """Return RSI array."""
        d = np.diff(arr)
        g = np.where(d > 0, d, 0.0)
        l = np.where(d < 0, -d, 0.0)
        avg_g = np.empty(len(d))
        avg_l = np.empty(len(d))
        avg_g[0] = g[0]
        avg_l[0] = max(l[0], 1e-10)
        for i in range(1, len(d)):
            avg_g[i] = (avg_g[i - 1] * (period - 1) + g[i]) / period
            avg_l[i] = (avg_l[i - 1] * (period - 1) + l[i]) / period
        rs = avg_g / np.maximum(avg_l, 1e-10)
        return 100.0 - 100.0 / (1.0 + rs)

    def _stoch(high, low, close, k_period=14, d_period=3):
        """Stochastic %K, %D."""
        k_arr = np.full(len(close), np.nan)
        for i in range(k_period - 1, len(close)):
            hh = np.max(high[i - k_period + 1:i + 1])
            ll = np.min(low[i - k_period + 1:i + 1])
            k_arr[i] = ((close[i] - ll) / max(hh - ll, 1e-10)) * 100
        d_arr = _sma_arr(k_arr, d_period)
        return k_arr, d_arr

    def _williams_r(high, low, close, period=14):
        """Williams %R."""
        out = np.full(len(close), np.nan)
        for i in range(period - 1, len(close)):
            hh = np.max(high[i - period + 1:i + 1])
            ll = np.min(low[i - period + 1:i + 1])
            out[i] = ((hh - close[i]) / max(hh - ll, 1e-10)) * -100
        return out

    def _cci(high, low, close, period=20):
        """CCI."""
        tp = (high + low + close) / 3.0
        out = np.full(len(close), np.nan)
        for i in range(period - 1, len(close)):
            window = tp[i - period + 1:i + 1]
            sma = np.mean(window)
            md = np.mean(np.abs(window - sma))
            out[i] = (tp[i] - sma) / max(md * 0.015, 1e-10)
        return out

    def _adx(high, low, close, period=14):
        """ADX."""
        n = len(close)
        if n < period * 2:
            return np.full(n, np.nan)
        tr = np.maximum(high[1:] - low[1:],
                        np.maximum(np.abs(high[1:] - close[:-1]),
                                   np.abs(low[1:] - close[:-1])))
        up = high[1:] - high[:-1]
        dn = low[:-1] - low[1:]
        pdm = np.where((up > dn) & (up > 0), up, 0.0)
        ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
        atr_s = _ema_arr(tr, period)
        pdm_s = _ema_arr(pdm, period)
        ndm_s = _ema_arr(ndm, period)
        pdi = 100 * pdm_s / np.maximum(atr_s, 1e-10)
        ndi = 100 * ndm_s / np.maximum(atr_s, 1e-10)
        dx = 100 * np.abs(pdi - ndi) / np.maximum(pdi + ndi, 1e-10)
        adx_arr = _ema_arr(dx, period)
        out = np.full(n, np.nan)
        out[1:] = adx_arr
        return out

    def _ultimate_osc(high, low, close, p1=7, p2=14, p3=28):
        """Ultimate Oscillator."""
        bp = close[1:] - np.minimum(low[1:], close[:-1])
        tr = np.maximum(high[1:] - low[1:],
                        np.maximum(np.abs(high[1:] - close[:-1]),
                                   np.abs(low[1:] - close[:-1])))
        n = len(bp)
        out = np.full(len(close), np.nan)
        for i in range(max(p1, p2, p3) - 1, n):
            a1 = np.sum(bp[i - p1 + 1:i + 1]) / max(np.sum(tr[i - p1 + 1:i + 1]), 1e-10)
            a2 = np.sum(bp[i - p2 + 1:i + 1]) / max(np.sum(tr[i - p2 + 1:i + 1]), 1e-10)
            a3 = np.sum(bp[i - p3 + 1:i + 1]) / max(np.sum(tr[i - p3 + 1:i + 1]), 1e-10)
            out[i + 1] = 100 * (4 * a1 + 2 * a2 + a3) / 7.0
        return out

    def _roc(close, period=12):
        """Rate of Change."""
        out = np.full(len(close), np.nan)
        for i in range(period, len(close)):
            out[i] = ((close[i] - close[i - period]) / max(abs(close[i - period]), 1e-10)) * 100
        return out

    def _bull_bear_power(high, low, close, period=13):
        """Bull/Bear Power (Elder)."""
        ema_s = _ema_arr(close, period)
        bull = high - ema_s
        bear = low - ema_s
        return bull, bear

    for item in items:
        sym = item["symbol"]
        try:
            close_arr = _get_col("Close", sym)
            high_arr = _get_col("High", sym)
            low_arr = _get_col("Low", sym)
            vol_arr = _get_col("Volume", sym)

            n = len(close_arr)
            if n < 50:
                continue

            current_price = float(close_arr[-1])

            # ── Calculate all 12 indicators ──
            # 1) RSI(14)
            rsi_arr = _rsi_series(close_arr, 14)
            rsi_val = float(rsi_arr[-1])

            # 2) Stochastic(14,3,3)
            stoch_k, stoch_d = _stoch(high_arr, low_arr, close_arr, 14, 3)
            stoch_k_val = float(stoch_k[-1]) if not np.isnan(stoch_k[-1]) else 50
            stoch_d_val = float(stoch_d[-1]) if not np.isnan(stoch_d[-1]) else 50

            # 3) StochRSI(14)
            rsi_for_stoch = rsi_arr[-14:] if len(rsi_arr) >= 14 else rsi_arr
            rsi_high = np.max(rsi_for_stoch)
            rsi_low = np.min(rsi_for_stoch)
            stoch_rsi = ((rsi_val - rsi_low) / max(rsi_high - rsi_low, 1e-10)) * 100

            # 4) MACD(12,26,9)
            ema12 = _ema_arr(close_arr, 12)
            ema26 = _ema_arr(close_arr, 26)
            macd_line_arr = ema12 - ema26
            signal_arr = _ema_arr(macd_line_arr, 9)
            macd_val = float(macd_line_arr[-1])
            macd_signal = float(signal_arr[-1])
            macd_hist = macd_val - macd_signal

            # 5) ADX(14)
            adx_arr = _adx(high_arr, low_arr, close_arr, 14)
            adx_val = float(adx_arr[-1]) if not np.isnan(adx_arr[-1]) else 25

            # 6) Williams %R(14)
            wr_arr = _williams_r(high_arr, low_arr, close_arr, 14)
            wr_val = float(wr_arr[-1]) if not np.isnan(wr_arr[-1]) else -50

            # 7) CCI(20)
            cci_arr = _cci(high_arr, low_arr, close_arr, 20)
            cci_val = float(cci_arr[-1]) if not np.isnan(cci_arr[-1]) else 0

            # 8) ATR(14)
            tr_arr = np.maximum(high_arr[1:] - low_arr[1:],
                                np.maximum(np.abs(high_arr[1:] - close_arr[:-1]),
                                           np.abs(low_arr[1:] - close_arr[:-1])))
            atr_val = float(np.mean(tr_arr[-14:])) if len(tr_arr) >= 14 else float(np.mean(tr_arr))

            # 9) Highs/Lows (14-day)
            high_14 = float(np.max(high_arr[-14:]))
            low_14 = float(np.min(low_arr[-14:]))
            hl_mid = (high_14 + low_14) / 2

            # 10) Ultimate Oscillator(7,14,28)
            uo_arr = _ultimate_osc(high_arr, low_arr, close_arr)
            uo_val = float(uo_arr[-1]) if not np.isnan(uo_arr[-1]) else 50

            # 11) ROC(12)
            roc_arr = _roc(close_arr, 12)
            roc_val = float(roc_arr[-1]) if not np.isnan(roc_arr[-1]) else 0

            # 12) Bull/Bear Power(13)
            bull_arr, bear_arr = _bull_bear_power(high_arr, low_arr, close_arr, 13)
            bull_val = float(bull_arr[-1])
            bear_val = float(bear_arr[-1])
            bp_val = bull_val + bear_val

            # ── Per-indicator signal judgment ──
            ind_list = []

            # 1) RSI
            if rsi_val < 30:
                ind_list.append({"name": "RSI(14)", "value": round(rsi_val, 1), "signal": "BUY"})
            elif rsi_val > 70:
                ind_list.append({"name": "RSI(14)", "value": round(rsi_val, 1), "signal": "SELL"})
            else:
                ind_list.append({"name": "RSI(14)", "value": round(rsi_val, 1), "signal": "NEUTRAL"})

            # 2) Stochastic
            if stoch_k_val < 20:
                ind_list.append({"name": "STOCH(14,3)", "value": round(stoch_k_val, 1), "signal": "BUY"})
            elif stoch_k_val > 80:
                ind_list.append({"name": "STOCH(14,3)", "value": round(stoch_k_val, 1), "signal": "SELL"})
            else:
                ind_list.append({"name": "STOCH(14,3)", "value": round(stoch_k_val, 1), "signal": "NEUTRAL"})

            # 3) StochRSI
            if stoch_rsi < 20:
                ind_list.append({"name": "StochRSI", "value": round(stoch_rsi, 1), "signal": "BUY"})
            elif stoch_rsi > 80:
                ind_list.append({"name": "StochRSI", "value": round(stoch_rsi, 1), "signal": "SELL"})
            else:
                ind_list.append({"name": "StochRSI", "value": round(stoch_rsi, 1), "signal": "NEUTRAL"})

            # 4) MACD
            if macd_hist > 0:
                ind_list.append({"name": "MACD(12,26)", "value": round(macd_hist, 3), "signal": "BUY"})
            elif macd_hist < 0:
                ind_list.append({"name": "MACD(12,26)", "value": round(macd_hist, 3), "signal": "SELL"})
            else:
                ind_list.append({"name": "MACD(12,26)", "value": round(macd_hist, 3), "signal": "NEUTRAL"})

            # 5) ADX — trend strength; direction from +DI/-DI proxy
            if adx_val > 25:
                # Strong trend — use price vs SMA as proxy for direction
                sma_20 = float(np.mean(close_arr[-20:]))
                if current_price > sma_20:
                    ind_list.append({"name": "ADX(14)", "value": round(adx_val, 1), "signal": "BUY"})
                else:
                    ind_list.append({"name": "ADX(14)", "value": round(adx_val, 1), "signal": "SELL"})
            else:
                ind_list.append({"name": "ADX(14)", "value": round(adx_val, 1), "signal": "NEUTRAL"})

            # 6) Williams %R
            if wr_val < -80:
                ind_list.append({"name": "W%R(14)", "value": round(wr_val, 1), "signal": "BUY"})
            elif wr_val > -20:
                ind_list.append({"name": "W%R(14)", "value": round(wr_val, 1), "signal": "SELL"})
            else:
                ind_list.append({"name": "W%R(14)", "value": round(wr_val, 1), "signal": "NEUTRAL"})

            # 7) CCI
            if cci_val < -100:
                ind_list.append({"name": "CCI(20)", "value": round(cci_val, 1), "signal": "BUY"})
            elif cci_val > 100:
                ind_list.append({"name": "CCI(20)", "value": round(cci_val, 1), "signal": "SELL"})
            else:
                ind_list.append({"name": "CCI(20)", "value": round(cci_val, 1), "signal": "NEUTRAL"})

            # 8) ATR — volatility, neutral by nature; high vol = caution
            atr_pct = (atr_val / current_price) * 100
            ind_list.append({"name": "ATR(14)", "value": round(atr_val, 2), "signal": "NEUTRAL"})

            # 9) Highs/Lows
            if current_price > hl_mid:
                ind_list.append({"name": "Highs/Lows", "value": round(current_price - hl_mid, 2), "signal": "BUY"})
            elif current_price < hl_mid:
                ind_list.append({"name": "Highs/Lows", "value": round(current_price - hl_mid, 2), "signal": "SELL"})
            else:
                ind_list.append({"name": "Highs/Lows", "value": 0, "signal": "NEUTRAL"})

            # 10) Ultimate Oscillator
            if uo_val < 30:
                ind_list.append({"name": "UO(7,14,28)", "value": round(uo_val, 1), "signal": "BUY"})
            elif uo_val > 70:
                ind_list.append({"name": "UO(7,14,28)", "value": round(uo_val, 1), "signal": "SELL"})
            else:
                ind_list.append({"name": "UO(7,14,28)", "value": round(uo_val, 1), "signal": "NEUTRAL"})

            # 11) ROC
            if roc_val > 0:
                ind_list.append({"name": "ROC(12)", "value": round(roc_val, 2), "signal": "BUY"})
            elif roc_val < 0:
                ind_list.append({"name": "ROC(12)", "value": round(roc_val, 2), "signal": "SELL"})
            else:
                ind_list.append({"name": "ROC(12)", "value": round(roc_val, 2), "signal": "NEUTRAL"})

            # 12) Bull/Bear Power
            if bp_val > 0:
                ind_list.append({"name": "Bull/Bear", "value": round(bp_val, 2), "signal": "BUY"})
            elif bp_val < 0:
                ind_list.append({"name": "Bull/Bear", "value": round(bp_val, 2), "signal": "SELL"})
            else:
                ind_list.append({"name": "Bull/Bear", "value": round(bp_val, 2), "signal": "NEUTRAL"})

            # ── Oscillator aggregate (12 indicators) ──
            osc_buy = sum(1 for x in ind_list if x["signal"] == "BUY")
            osc_sell = sum(1 for x in ind_list if x["signal"] == "SELL")
            osc_neutral = sum(1 for x in ind_list if x["signal"] == "NEUTRAL")

            # ── Moving Averages (SMA & EMA × 6 periods = 12 signals) ──
            ma_list = []
            ma_periods = [5, 10, 20, 50, 100, 200]
            for p in ma_periods:
                if len(close_arr) >= p:
                    sma_v = float(np.mean(close_arr[-p:]))
                    ema_v = float(_ema_arr(close_arr, p)[-1])
                    sma_sig = "BUY" if current_price > sma_v else "SELL"
                    ema_sig = "BUY" if current_price > ema_v else "SELL"
                    ma_list.append({"name": f"SMA({p})", "value": round(sma_v, 2), "signal": sma_sig})
                    ma_list.append({"name": f"EMA({p})", "value": round(ema_v, 2), "signal": ema_sig})

            ma_buy = sum(1 for x in ma_list if x["signal"] == "BUY")
            ma_sell = sum(1 for x in ma_list if x["signal"] == "SELL")
            ma_neutral = 0  # MA is always buy or sell

            # ── Grand Total (oscillators + moving averages) — for display ──
            total_buy = osc_buy + ma_buy
            total_sell = osc_sell + ma_sell
            total_neutral = osc_neutral + ma_neutral
            total_all = total_buy + total_sell + total_neutral

            # ── Weighted Category Scoring (research-backed) ──
            # Helper: convert signal list to score [-1, +1]
            def _sig_score(signals):
                if not signals:
                    return 0.0
                total = sum(1 if s == "BUY" else -1 if s == "SELL" else 0 for s in signals)
                return total / len(signals)

            # Map indicators to categories by name
            ind_by_name = {i["name"]: i["signal"] for i in ind_list}

            # Category 1: Trend (MAs + ADX + Highs/Lows)
            ma_score = (ma_buy - ma_sell) / max(ma_buy + ma_sell, 1)
            trend_osc = [ind_by_name.get("ADX(14)", "NEUTRAL"), ind_by_name.get("Highs/Lows", "NEUTRAL")]
            trend_score = 0.6 * ma_score + 0.4 * _sig_score(trend_osc)

            # Category 2: Momentum (RSI, ROC, UO, Bull/Bear)
            mom_sigs = [ind_by_name.get(n, "NEUTRAL") for n in ["RSI(14)", "ROC(12)", "UO(7,14,28)", "Bull/Bear"]]
            momentum_score = _sig_score(mom_sigs)

            # Category 3: MACD
            macd_score = _sig_score([ind_by_name.get("MACD(12,26)", "NEUTRAL")])

            # Category 4: Mean-Reversion (Stoch, StochRSI, W%R, CCI)
            mr_sigs = [ind_by_name.get(n, "NEUTRAL") for n in ["STOCH(14,3)", "StochRSI", "W%R(14)", "CCI(20)"]]
            meanrev_score = _sig_score(mr_sigs)

            # Category 5: Volume (regular + pre-market boost)
            vol_ratio = float(np.mean(vol_arr[-5:])) / max(float(np.mean(vol_arr[-20:])), 1) if len(vol_arr) >= 20 else 1.0
            vol_score = 1.0 if vol_ratio >= 2.0 else (0.5 if vol_ratio >= 1.5 else (0.0 if vol_ratio >= 1.0 else -0.5))

            # C안: Pre-market volume confirmation boost
            pre_vol_boost = 0
            try:
                import yfinance as yf
                tkr = yf.Ticker(sym)
                info = tkr.info
                pre_price = info.get("preMarketPrice")
                mkt_state = info.get("marketState", "")
                if pre_price and mkt_state in ("PRE", "PREPRE"):
                    # Pre-market gap provides additional signal
                    prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose") or current_price
                    pre_gap = ((pre_price - prev_close) / prev_close) if prev_close else 0
                    if abs(pre_gap) >= 0.01:  # 1%+ gap
                        pre_vol_boost = 0.3 if pre_gap > 0 else -0.3
                        vol_score = min(1.0, max(-1.0, vol_score + pre_vol_boost))
            except Exception:
                pass  # Pre-market data not available, use regular vol_score

            # ── Regime Detection via ADX ──
            if adx_val > 25:
                regime = "TRENDING"
                w_trend, w_mom, w_macd, w_mr, w_vol = 0.40, 0.25, 0.15, 0.10, 0.10
            elif adx_val < 20:
                regime = "SIDEWAYS"
                w_trend, w_mom, w_macd, w_mr, w_vol = 0.15, 0.20, 0.20, 0.30, 0.15
            else:
                regime = "MIXED"
                w_trend, w_mom, w_macd, w_mr, w_vol = 0.30, 0.25, 0.20, 0.15, 0.10

            # Weighted composite score [-1, +1]
            weighted_raw = (
                w_trend * trend_score +
                w_mom * momentum_score +
                w_macd * macd_score +
                w_mr * meanrev_score +
                w_vol * vol_score
            )

            # Volume confirmation: dampen signal if volume is low
            vol_factor = 1.0 if vol_ratio >= 1.5 else 0.5
            weighted_final = weighted_raw * vol_factor

            # Direction from weighted score
            if weighted_final >= 0.35:
                direction = "STRONG_BUY"
            elif weighted_final >= 0.12:
                direction = "BUY"
            elif weighted_final <= -0.35:
                direction = "STRONG_SELL"
            elif weighted_final <= -0.12:
                direction = "SELL"
            else:
                direction = "NEUTRAL"

            # Confidence: scale weighted_final to 0-100
            confidence = min(99, max(1, int(abs(weighted_final) * 100 + 50)))

            # P&L vs avg cost
            avg_cost = float(item.get("avg_cost") or 0)
            pnl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else None

            # Target/Stop (ATR-based)
            if "BUY" in direction:
                target_price = round(current_price + 2 * atr_val, 2)
                stop_price = round(current_price - 1.5 * atr_val, 2)
            elif "SELL" in direction:
                target_price = round(current_price - 2 * atr_val, 2)
                stop_price = round(current_price + 1.5 * atr_val, 2)
            else:
                target_price = round(float(np.max(close_arr[-20:])), 2)
                stop_price = round(float(np.min(close_arr[-20:])), 2)

            result = {
                "symbol": sym,
                "company_name": item.get("company_name", ""),
                "current_price": round(current_price, 2),
                "avg_cost": avg_cost,
                "qty": float(item.get("qty") or 0),
                "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
                "direction": direction,
                "confidence": confidence,
                # Oscillators (12)
                "osc_buy": osc_buy,
                "osc_sell": osc_sell,
                "osc_neutral": osc_neutral,
                "indicators": ind_list,
                # Moving Averages (up to 12)
                "ma_buy": ma_buy,
                "ma_sell": ma_sell,
                "ma_neutral": ma_neutral,
                "moving_averages": ma_list,
                # Grand total (for display)
                "total_buy": total_buy,
                "total_sell": total_sell,
                "total_neutral": total_neutral,
                # Weighted scoring (research-backed)
                "regime": regime,
                "vol_factor": vol_factor,
                "weighted_score": round(weighted_final, 3),
                "category_scores": {
                    "trend": round(trend_score, 3),
                    "momentum": round(momentum_score, 3),
                    "macd": round(macd_score, 3),
                    "mean_reversion": round(meanrev_score, 3),
                    "volume": round(vol_score, 3),
                },
                "category_weights": {
                    "trend": w_trend, "momentum": w_mom,
                    "macd": w_macd, "mean_reversion": w_mr, "volume": w_vol,
                },
                "target_price": target_price,
                "stop_price": stop_price,
                "atr": round(atr_val, 2),
                "vol_ratio": round(vol_ratio, 2),
                "pre_vol_boost": pre_vol_boost,
            }
            results.append(result)

            # Save alert to DB
            alert = {
                "symbol": sym,
                "alert_type": "technical_full",
                "direction": direction,
                "confidence": confidence,
                "reason": f"{direction} (Score {weighted_final:+.2f}, {regime}, Vol×{vol_factor}): T{trend_score:+.2f} M{momentum_score:+.2f} MACD{macd_score:+.1f} MR{meanrev_score:+.2f} V{vol_score:+.1f}",
                "current_price": current_price,
                "target_price": target_price,
                "stop_price": stop_price,
                "strategy": "weighted_category",
                "detail": {
                    "oscillators": {i["name"]: {"value": i["value"], "signal": i["signal"]} for i in ind_list},
                    "moving_averages": {i["name"]: {"value": i["value"], "signal": i["signal"]} for i in ma_list},
                    "regime": regime,
                    "weighted_score": round(weighted_final, 3),
                    "vol_factor": vol_factor,
                },
            }
            pg.insert_watchlist_alert(alert)

            # Telegram for STRONG signals or high-confidence directional
            if "STRONG" in direction or (direction != "NEUTRAL" and confidence >= 65):
                emoji = "\U0001f7e2" if "BUY" in direction else "\U0001f534"
                label = {"STRONG_BUY": "Strong Buy", "BUY": "Buy", "STRONG_SELL": "Strong Sell", "SELL": "Sell"}.get(direction, direction)
                vol_lbl = "High" if vol_ratio >= 1.5 else "Low"
                asyncio.run(notifier.send(
                    f"<b>{emoji} Watchlist: {label} {sym}</b>\n\n"
                    f"Price: <b>${current_price:.2f}</b>\n"
                    f"Score: <b>{weighted_final:+.3f}</b> | Regime: {regime}\n"
                    f"Volume: ×{vol_ratio:.1f} ({vol_lbl})\n"
                    f"Trend {trend_score:+.2f} · Mom {momentum_score:+.2f} · MACD {macd_score:+.1f}\n"
                    f"MeanRev {meanrev_score:+.2f} · Vol {vol_score:+.1f}\n"
                    f"Target: ${target_price:.2f} / Stop: ${stop_price:.2f}\n"
                    f"\u23f0 {datetime.now().strftime('%H:%M KST')}"
                ))

        except Exception as e:
            logger.warning(f"Watchlist analysis failed for {sym}: {e}")
            continue

    cache.set_json("watchlist_analysis", {
        "status": "done",
        "analyzed_at": datetime.now().isoformat(),
        "count": len(results),
        "results": results,
    }, ttl=86400)
    logger.info(f"Watchlist analysis done: {len(results)} symbols")


@app.get("/watchlist/analysis")
async def get_watchlist_analysis():
    """워치리스트 분석 결과 조회 (캐시)."""
    result = cache.get_json("watchlist_analysis")
    if not result:
        return {"status": "no_results", "message": "Run POST /watchlist/analyze first"}
    return result


@app.get("/watchlist/intraday/{symbol}")
async def get_watchlist_intraday(symbol: str):
    """워치리스트 종목 인트라데이 차트 데이터 (프리마켓+장중+애프터)."""
    import yfinance as yf
    try:
        tkr = yf.Ticker(symbol)
        # 1d 5분봉 — 프리마켓/애프터마켓 포함
        df = tkr.history(period="1d", interval="5m", prepost=True)
        if df.empty:
            # 장 마감 상태이면 2일치 시도
            df = tkr.history(period="2d", interval="5m", prepost=True)
        if df.empty:
            return {"symbol": symbol, "points": [], "prev_close": None}

        # 전일 종가 (기준선)
        info = tkr.info
        prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")

        # 오늘 날짜의 데이터만
        if len(df) > 0:
            last_date = df.index[-1].date()
            df_today = df[df.index.date == last_date]
            if df_today.empty:
                df_today = df

        points = []
        for idx, row in df_today.iterrows():
            ts = idx.tz_convert("US/Eastern") if idx.tzinfo else idx
            hour = ts.hour
            minute = ts.minute
            t = hour * 60 + minute  # minutes from midnight

            # Session: pre(4:00-9:29), regular(9:30-15:59), post(16:00-20:00)
            if t < 570:        # before 9:30
                session = "pre"
            elif t < 960:      # 9:30 - 15:59
                session = "regular"
            else:
                session = "post"

            points.append({
                "time": ts.strftime("%H:%M"),
                "price": round(float(row["Close"]), 2),
                "session": session,
            })

        return {
            "symbol": symbol,
            "prev_close": round(float(prev_close), 2) if prev_close else None,
            "points": points,
        }
    except Exception as e:
        logger.error(f"Intraday fetch failed for {symbol}: {e}")
        return {"symbol": symbol, "points": [], "prev_close": None, "error": str(e)}


@app.post("/watchlist/backtest")
async def run_watchlist_backtest(req: WatchlistBacktestRequest, bg: BackgroundTasks):
    """워치리스트 종목 가중 스코어링 백테스트."""
    items = pg.get_watchlist()
    if not items:
        return {"status": "error", "message": "No watchlist symbols"}
    symbols = [w["symbol"] for w in items]
    cache.set_json("watchlist_backtest", {"status": "running", "symbols": symbols}, ttl=600)
    bg.add_task(_run_watchlist_backtest, req, symbols)
    return {"status": "running", "symbols": symbols}


def _run_watchlist_backtest(req: WatchlistBacktestRequest, symbols: list[str]):
    from engine_v4.backtest.watchlist_backtest import WatchlistBacktester, WatchlistBacktestParams
    bt = WatchlistBacktester()
    params = WatchlistBacktestParams(
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        position_pct=req.position_pct,
        max_positions=req.max_positions,
        buy_threshold=req.buy_threshold,
        sell_threshold=req.sell_threshold,
        trailing_stop_pct=req.trailing_stop_pct,
        max_hold_days=req.max_hold_days,
    )
    result = bt.run(symbols, params)
    cache.set_json("watchlist_backtest", {
        "status": "done",
        "symbols": symbols,
        "params": {
            "start_date": str(req.start_date),
            "end_date": str(req.end_date),
            "initial_capital": req.initial_capital,
            "position_pct": req.position_pct,
            "max_positions": req.max_positions,
            "buy_threshold": req.buy_threshold,
            "sell_threshold": req.sell_threshold,
            "trailing_stop_pct": req.trailing_stop_pct,
            "max_hold_days": req.max_hold_days,
        },
        "total_return": result.total_return,
        "cagr": result.cagr,
        "max_drawdown": result.max_drawdown,
        "sharpe_ratio": result.sharpe_ratio,
        "win_rate": result.win_rate,
        "total_trades": result.total_trades,
        "profit_factor": result.profit_factor,
        "avg_hold_days": result.avg_hold_days,
        "final_value": result.final_value,
        "equity_curve": result.equity_curve,
        "trades_log": result.trades_log,
        "score_series": result.score_series,
    }, ttl=86400)


@app.get("/watchlist/backtest")
async def get_watchlist_backtest():
    """워치리스트 백테스트 결과 조회."""
    result = cache.get_json("watchlist_backtest")
    if not result:
        return {"status": "no_results", "message": "Run POST /watchlist/backtest first"}
    return result


# ═══════════════════════════════════════════════════════════
# Ticker
# ═══════════════════════════════════════════════════════════

@app.get("/ticker")
async def get_ticker_data():
    """티커바 데이터 — 오픈 포지션 심볼 현재가."""
    positions = pg.get_open_positions()
    if not positions:
        return {"tickers": []}

    symbols = list(set(p["symbol"] for p in positions))
    tickers = []

    try:
        import yfinance as yf
        data = yf.download(symbols, period="2d", progress=False)
        for sym in symbols:
            try:
                if len(symbols) == 1:
                    closes = data["Close"].dropna()
                else:
                    closes = data["Close"][sym].dropna()
                if len(closes) >= 2:
                    current = float(closes.iloc[-1])
                    prev = float(closes.iloc[-2])
                    change = ((current - prev) / prev) * 100
                elif len(closes) == 1:
                    current = float(closes.iloc[-1])
                    change = 0
                else:
                    continue
                tickers.append({"symbol": sym, "price": round(current, 2), "change_pct": round(change, 2)})
            except (KeyError, IndexError):
                pass
    except Exception as e:
        logger.warning(f"Ticker data fetch failed: {e}")

    tickers.sort(key=lambda t: t["symbol"])
    return {"tickers": tickers}


# ═══════════════════════════════════════════════════════════
# Extended Hours (Pre-market / After-hours)
# ═══════════════════════════════════════════════════════════

@app.get("/extended-hours")
async def get_extended_hours():
    """최근 프리마켓/애프터마켓 데이터 조회 (캐시)."""
    result = cache.get_json("extended_hours")
    if not result:
        return {"status": "no_data", "message": "No extended hours data cached yet"}
    return result


@app.post("/extended-hours/check")
async def check_extended_hours_now():
    """수동 프리마켓/애프터마켓 체크."""
    from engine_v4.data.extended_hours import fetch_extended_hours

    positions = pg.get_open_positions()
    watchlist_items = pg.get_watchlist()
    pending = pg.get_signals(status="pending")

    syms = set()
    for p in positions:
        syms.add(p["symbol"])
    for w in watchlist_items:
        syms.add(w["symbol"])
    for s in pending:
        syms.add(s["symbol"])

    if not syms:
        return {"status": "no_symbols", "data": []}

    data = fetch_extended_hours(list(syms))

    # Annotate each symbol with context
    pos_syms = {p["symbol"] for p in positions}
    wl_syms = {w["symbol"] for w in watchlist_items}
    pend_syms = {s["symbol"] for s in pending}
    for d in data:
        s = d["symbol"]
        d["is_position"] = s in pos_syms
        d["is_watchlist"] = s in wl_syms
        d["is_pending"] = s in pend_syms

    result = {
        "session": data[0]["session"] if data else "unknown",
        "checked_at": datetime.now().isoformat(),
        "count": len(data),
        "data": data,
    }
    cache.set_json("extended_hours", result, ttl=7200)
    return result


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
