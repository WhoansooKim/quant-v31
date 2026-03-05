"""Swing Trading Engine — FastAPI 4단계 파이프라인."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import date

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from engine_v4.backtest.runner import BacktestParams, BacktestRunner
from engine_v4.broker.kis_client import KisClient
from engine_v4.config.settings import get_config
from engine_v4.data.collector import DataCollector, UniverseManager
from engine_v4.data.storage import PostgresStore, RedisCache
from engine_v4.notify.telegram import TelegramNotifier
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
backtester = BacktestRunner(pg)
kis = KisClient(config)
notifier = TelegramNotifier(config)
swing_scheduler = SwingScheduler(
    pg, cache, config, universe_mgr, collector, strategy, notifier)


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

    return {"status": "executed", "result": result}


@app.post("/signals/{signal_id}/reject")
async def reject_signal(signal_id: int):
    ok = pg.reject_signal(signal_id)
    if not ok:
        raise HTTPException(400, "Cannot reject (not pending)")
    return {"status": "rejected", "signal_id": signal_id}


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
