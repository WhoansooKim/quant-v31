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
from engine_v4.ai.factor_crowding import FactorCrowdingMonitor
from engine_v4.ai.fundamental import FundamentalAnalyzer
from engine_v4.ai.lstm_predictor import LSTMPredictor
from engine_v4.ai.macro_scorer import MacroScorer
from engine_v4.ai.multi_factor import MultiFactorScorer
from engine_v4.ai.social_sentiment import SocialSentimentCollector
from engine_v4.data.macro_collector import MacroDataCollector
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
from engine_v4.strategy.watchlist_strategy import WatchlistStrategy

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
finnhub_client = FinnhubClient(config.finnhub_api_key)
strategy = SwingStrategy(pg, config, finnhub=finnhub_client)
macro_collector = MacroDataCollector(cache)
macro_scorer_inst = MacroScorer(macro_collector, cache)
pos_mgr = PositionManager(pg, config, macro_scorer=macro_scorer_inst)
exit_mgr = ExitManager(pg, macro_scorer=macro_scorer_inst)
backtester = BacktestRunner(pg)
kis = KisClient(config)
notifier = TelegramNotifier(config)
sentiment = SentimentAnalyzer(pg, config.anthropic_key,
                              ollama_url=config.ollama_url,
                              ollama_model=config.ollama_model)
social_collector = SocialSentimentCollector(
    pg, cache,
    reddit_client_id=config.reddit_client_id,
    reddit_client_secret=config.reddit_client_secret,
    ollama_url=config.ollama_url,
    ollama_model=config.ollama_model,
)
lstm_predictor = LSTMPredictor(pg, cache)
crowding_monitor = FactorCrowdingMonitor(pg, cache)
scorer = MultiFactorScorer(pg, finnhub_client, config.anthropic_key,
                           ollama_url=config.ollama_url,
                           ollama_model=config.ollama_model,
                           cache=cache,
                           social_collector=social_collector,
                           lstm_predictor=lstm_predictor,
                           macro_scorer=macro_scorer_inst,
                           crowding_monitor=crowding_monitor)
optimizer = StrategyOptimizer(pg, backtester, config.anthropic_key)
event_collector = EventCollector(pg, finnhub_client)
event_processor = EventProcessor(pg)
edgar = EdgarRssMonitor()
fundamental_analyzer = FundamentalAnalyzer(
    finnhub_client, edgar, config.anthropic_key,
    ollama_url=config.ollama_url,
    ollama_model=config.ollama_model)
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


class ReplayBacktestRequest(BaseModel):
    initial_capital: float = 1000.0
    position_pct: float = 0.20
    max_positions: int = 3
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
        "ai_mode": sentiment.mode,
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

    # ENTRY 시그널: 승인 전에 validation 먼저 (approve 후 자기 자신이 daily count에 포함되는 버그 방지)
    if sig["signal_type"] == "ENTRY":
        valid, reason = pos_mgr.validate_entry(sig["symbol"], float(sig["entry_price"]))
        if not valid:
            raise HTTPException(400, f"Entry validation failed: {reason}")

    # 승인
    pg.approve_signal(signal_id)

    # 체결
    account_value = _get_account_value()

    if sig["signal_type"] == "ENTRY":
        result = pos_mgr.execute_entry(sig, account_value)
        if not result:
            pg.reject_signal(signal_id)
            raise HTTPException(400, "Entry execution failed (limits or validation)")

        # KIS 주문 (live 모드에서 실패 시 경고만 — DB 포지션은 유지)
        order = kis.buy(
            symbol=sig["symbol"],
            qty=result["qty"],
            price=float(sig["entry_price"]),
        )
        result["order_id"] = order.order_id
        result["kis_message"] = order.message
        if kis.is_connected and not order.success:
            logger.error(f"KIS BUY order failed for {sig['symbol']}: {order.message}")
            result["kis_warning"] = f"KIS order failed: {order.message}. DB position created but broker order may need manual action."

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
        if kis.is_connected and not order.success:
            logger.error(f"KIS SELL order failed for {result['symbol']}: {order.message}")
            result["kis_warning"] = f"KIS order failed: {order.message}. Manual sell may be required."

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
async def analyze_signal(signal_id: int, bg: BackgroundTasks):
    """단일 시그널 AI 분석 (백그라운드)."""
    sig = pg.get_signal(signal_id)
    if not sig:
        raise HTTPException(404, "Signal not found")

    def _run():
        try:
            result = sentiment.analyze_signal(signal_id)
            cache.set_json("ai_analyze_result", {
                "status": "done", "analyzed": 1,
                "mode": sentiment.mode, "results": [result],
            }, ttl=600)
        except Exception as e:
            logger.error(f"AI analysis failed for signal {signal_id}: {e}", exc_info=True)
            cache.set_json("ai_analyze_result", {
                "status": "error", "message": str(e),
            }, ttl=600)

    # 진행 상태 초기화
    cache.set_json("ai_analyze_result", {
        "status": "running", "total": 1, "done": 0, "mode": sentiment.mode,
    }, ttl=600)
    bg.add_task(_run)
    return {"status": "started", "mode": sentiment.mode, "total": 1}


@app.post("/signals/analyze-pending")
async def analyze_pending_signals(bg: BackgroundTasks):
    """모든 pending 시그널 일괄 AI 분석 (백그라운드)."""
    signals = pg.get_signals(status="pending", limit=20)
    todo = [s for s in signals if s.get("llm_score") is None]
    if not todo:
        return {"status": "done", "analyzed": 0, "mode": sentiment.mode, "results": []}

    def _run():
        results = []
        for i, sig in enumerate(todo):
            try:
                cache.set_json("ai_analyze_result", {
                    "status": "running", "total": len(todo),
                    "done": i, "current": sig["symbol"], "mode": sentiment.mode,
                }, ttl=600)
                result = sentiment.analyze_signal(sig["signal_id"])
                results.append(result)
            except Exception as e:
                logger.error(f"AI analysis failed for signal {sig['signal_id']}: {e}")
        cache.set_json("ai_analyze_result", {
            "status": "done", "analyzed": len(results),
            "mode": sentiment.mode, "results": results,
        }, ttl=600)

    cache.set_json("ai_analyze_result", {
        "status": "running", "total": len(todo), "done": 0, "mode": sentiment.mode,
    }, ttl=600)
    bg.add_task(_run)
    return {"status": "started", "mode": sentiment.mode, "total": len(todo)}


@app.get("/ai/analyze-status")
async def analyze_status():
    """AI 분석 진행 상태 폴링."""
    data = cache.get_json("ai_analyze_result")
    if not data:
        return {"status": "idle"}
    return data


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
            "finnhub": finnhub_client.is_available,
            "claude": scorer._claude is not None,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Batch factor scoring failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ═══════════════════════════════════════════════════════════
# Tier 2.1: Fundamental Analysis (SEC 10-Q/10-K + LLM)
# ═══════════════════════════════════════════════════════════

@app.post("/signals/{signal_id}/fundamental")
async def analyze_signal_fundamental(signal_id: int):
    """시그널 펀더멘탈 분석 (SEC 10-Q/10-K + Finnhub → LLM 스코어링).

    Redis 캐시 7일 TTL. 캐시 히트 시 즉시 반환.
    """
    sig = pg.get_signal(signal_id)
    if not sig:
        raise HTTPException(404, "Signal not found")

    symbol = sig["symbol"]
    cache_key = f"fundamental:{symbol}"

    # 캐시 확인
    cached = cache.get_json(cache_key)
    if cached:
        cached["cache_hit"] = True
        cached["signal_id"] = signal_id
        return cached

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, fundamental_analyzer.analyze, symbol)
        result["signal_id"] = signal_id
        result["symbol"] = symbol
        result["cache_hit"] = False

        # Redis 캐시 저장 (7일 TTL)
        cache.set_json(cache_key, result, ttl=7 * 86400)

        return result
    except Exception as e:
        logger.error(f"Fundamental analysis failed for signal {signal_id} ({symbol}): {e}",
                     exc_info=True)
        raise HTTPException(500, str(e))


@app.get("/fundamental/{symbol}")
async def get_fundamental(symbol: str):
    """종목 펀더멘탈 분석 조회 (캐시 or 신규 분석).

    Redis 캐시 7일 TTL. 캐시 없으면 실시간 분석.
    """
    symbol = symbol.upper()
    cache_key = f"fundamental:{symbol}"

    # 캐시 확인
    cached = cache.get_json(cache_key)
    if cached:
        cached["cache_hit"] = True
        return cached

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, fundamental_analyzer.analyze, symbol)
        result["symbol"] = symbol
        result["cache_hit"] = False

        # Redis 캐시 저장 (7일 TTL)
        cache.set_json(cache_key, result, ttl=7 * 86400)

        return result
    except Exception as e:
        logger.error(f"Fundamental analysis failed for {symbol}: {e}", exc_info=True)
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
# Commission (수수료)
# ═══════════════════════════════════════════════════════════

@app.get("/commissions")
async def get_commissions():
    """수수료 현황 조회."""
    data = pg.get_total_commissions()
    rate = float(pg.get_config_value("commission_rate", "0.0025"))
    return {
        "commission_rate": rate,
        "commission_rate_pct": f"{rate * 100:.2f}%",
        "total_commission": round(float(data["total_commission"]), 2),
        "buy_commission": round(float(data["buy_commission"]), 2),
        "sell_commission": round(float(data["sell_commission"]), 2),
        "total_volume": round(float(data["total_volume"]), 2),
        "trade_count": data["trade_count"],
    }


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
        "withdrawable_usd": balance.withdrawable_usd,
        "holdings": balance.holdings,
        "db_positions": pg.get_open_position_count(),
        "max_positions": config.max_positions,
    }


# ═══════════════════════════════════════════════════════════
# KIS Broker API
# ═══════════════════════════════════════════════════════════

@app.get("/broker/status")
async def broker_status():
    """KIS 브로커 연결 상태 + 연결 테스트."""
    return kis.test_connection()


@app.get("/broker/balance")
async def broker_balance():
    """KIS 실제 잔고 조회 (보유종목 포함)."""
    balance = kis.get_balance()
    return {
        "connected": kis.is_connected,
        "total_value_usd": balance.total_value_usd,
        "cash_usd": balance.cash_usd,
        "invested_usd": balance.invested_usd,
        "profit_usd": balance.profit_usd,
        "profit_rate": balance.profit_rate,
        "withdrawable_usd": balance.withdrawable_usd,
        "holdings": balance.holdings,
        "message": balance.message,
    }


@app.get("/broker/quote/{symbol}")
async def broker_quote(symbol: str):
    """KIS 종목 시세 조회."""
    q = kis.get_quote(symbol.upper())
    return {
        "symbol": q.symbol,
        "price": q.price,
        "change": q.change,
        "change_pct": q.change_pct,
        "volume": q.volume,
        "high": q.high,
        "low": q.low,
        "open": q.open,
        "prev_close": q.prev_close,
        "message": q.message,
    }


@app.get("/broker/pending-orders")
async def broker_pending_orders():
    """KIS 미체결 주문 목록."""
    orders = kis.get_pending_orders()
    return {
        "connected": kis.is_connected,
        "orders": [vars(o) for o in orders],
        "count": len(orders),
    }


@app.post("/broker/cancel/{order_id}")
async def broker_cancel_order(order_id: str):
    """KIS 미체결 주문 취소."""
    result = kis.cancel_order(order_id)
    if not result.success:
        raise HTTPException(400, f"Cancel failed: {result.message}")
    return {"status": "cancelled", "order_id": order_id}


@app.get("/broker/orderable/{symbol}")
async def broker_orderable(symbol: str, price: float | None = None):
    """KIS 주문 가능 금액/수량 조회."""
    info = kis.get_orderable_amount(symbol.upper(), price)
    return {
        "symbol": symbol.upper(),
        "orderable_cash": info.orderable_cash,
        "orderable_qty": info.orderable_qty,
        "message": info.message,
    }


@app.get("/broker/orders")
async def broker_daily_orders(start: str | None = None, end: str | None = None):
    """KIS 일별 주문 내역."""
    from datetime import date as date_type
    start_date = date_type.fromisoformat(start) if start else None
    end_date = date_type.fromisoformat(end) if end else None
    orders = kis.get_daily_orders(start_date, end_date)
    return {"orders": orders, "count": len(orders)}


@app.get("/broker/sync")
async def broker_sync_positions():
    """DB 포지션 ↔ KIS 보유종목 동기화 비교."""
    db_positions = pg.get_open_positions()
    result = kis.sync_positions(db_positions)
    return result


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
    # position_pct 안전 검증: 1 초과이면 % 단위로 입력한 것 → 소수로 변환
    value = body.value
    if key == "position_pct":
        try:
            v = float(value)
            if v > 1.0:
                value = str(round(v / 100.0, 4))
                logger.warning(f"position_pct={v} > 1.0 — auto-corrected to {value}")
        except ValueError:
            pass
    ok = pg.update_config(key, value)
    if not ok:
        raise HTTPException(404, f"Config key '{key}' not found")
    return {"status": "updated", "key": key, "value": value}


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

    # 3.5) 총 수수료 차감
    comm_data = pg.get_total_commissions()
    total_commission = float(comm_data["total_commission"])

    # 4) 포트폴리오 계산 (수수료 차감)
    capital_adj = pg.get_total_capital_adjustments()
    cash_usd = INITIAL_CAPITAL + capital_adj + realized_pnl - entry_cost - total_commission
    total_value = cash_usd + invested_usd

    # 5) 순수 트레이딩 손익 (입출금 제외, 수수료 차감)
    unrealized_pnl = invested_usd - entry_cost
    trading_pnl = realized_pnl + unrealized_pnl - total_commission

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
                f"daily_pnl=${daily_pnl:.2f}, commission=${total_commission:.2f}")

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


# ── Watchlist Strategy Instance ──
_watchlist_strategy = WatchlistStrategy(finnhub_client=finnhub_client)


@app.post("/watchlist/analyze")
async def analyze_watchlist(bg: BackgroundTasks):
    """워치리스트 종목 매수/매도 분석 (백그라운드) — 5-Layer Tactical Quality Momentum."""
    bg.add_task(_analyze_watchlist)
    return {"status": "running", "message": "Watchlist analysis started (5-Layer TQM)"}


def _analyze_watchlist():
    """워치리스트 분석 — 5-Layer Tactical Quality Momentum.

    연구 기반 (다층 학술 논문 + 실전 검증):
      Layer 1: 레짐 필터 — Faber 10M SMA (2007), Antonacci Dual Momentum (2014)
      Layer 2: 종목 랭킹 — IBD RS Rating (O'Neil), Weinstein Stage (1988)
      Layer 3: 진입 타이밍 — BB/KC Squeeze (Carter), RSI(2) 변형 (Connors 2008)
      Layer 4: 포지션 사이징 — Quarter-Kelly (Thorp 2006), ATR (Carver 2015)
      Layer 5: 매도 — KAMA (Kaufman 2013), ATR Trailing, Graduated Drawdown (Grossman-Zhou)
      Quality: GP/Assets (Novy-Marx 2013), AQR QMJ (2014)
    """
    import yfinance as yf
    from datetime import date as _date_type

    items = pg.get_watchlist()
    if not items:
        cache.set_json("watchlist_analysis", {"status": "done", "results": []}, ttl=86400)
        return

    symbols = [w["symbol"] for w in items]

    # VIX 포함하여 다운로드 (Layer 1 레짐 필터용)
    download_symbols = list(set(symbols + ["QQQ", "^VIX"]))
    try:
        data = yf.download(download_symbols, period="1y", progress=False)
    except Exception as e:
        logger.error(f"Watchlist yfinance failed: {e}")
        cache.set_json("watchlist_analysis", {"status": "failed", "error": str(e)}, ttl=3600)
        return

    # ── 5-Layer Tactical Quality Momentum 분석 ──
    results = _watchlist_strategy.analyze(items, data)

    # ── 결과 저장 (알림/시그널 로그/Telegram) ──
    for result in results:
        sym = result["symbol"]
        direction = result["direction"]
        confidence = result["confidence"]
        weighted_final = result["weighted_score"]
        regime = result["regime"]
        rsi2_val = result["rsi2"]
        cum_rsi2 = result["cum_rsi2"]
        connors_exit = result["connors_exit"]
        opex_week = result["opex_week"]
        bb_squeeze = result["bb_squeeze"]
        current_price = result["current_price"]
        target_price = result["target_price"]
        stop_price = result["stop_price"]
        rel_str_5d = result["rel_str_5d"]
        rel_str_20d = result["rel_str_20d"]
        composite = result.get("composite_score", 0)

        try:
            # Save alert
            rsi2_score = result["category_scores"]["rsi2_reversion"]
            trend_score = result["category_scores"]["trend"]
            vol_score = result["category_scores"]["volume"]
            rs_score = result["category_scores"]["rel_strength"]
            volatility_score = result["category_scores"]["volatility"]

            alert = {
                "symbol": sym,
                "alert_type": "tqm_5layer",
                "direction": direction,
                "confidence": confidence,
                "reason": (
                    f"{direction} (Score {weighted_final:+.2f}, Composite {composite:.0f}, {regime}): "
                    f"RSI2={rsi2_val:.0f} "
                    f"Stage={result.get('layer2_ranking', {}).get('stage', '?')} "
                    f"Squeeze={'FIRED' if result.get('layer3_entry', {}).get('squeeze_fired') else ('ON' if bb_squeeze else 'OFF')} "
                    f"Quality={result.get('quality', {}).get('score', 0):.0f} "
                    f"{'OPEX' if opex_week else ''}"
                ),
                "current_price": current_price,
                "target_price": target_price,
                "stop_price": stop_price,
                "strategy": "tqm_5layer",
                "detail": {
                    "layer1_regime": result.get("layer1_regime"),
                    "layer2_ranking": result.get("layer2_ranking"),
                    "layer3_entry": result.get("layer3_entry"),
                    "layer4_sizing": result.get("layer4_sizing"),
                    "layer5_exit": result.get("layer5_exit"),
                    "quality": result.get("quality"),
                    "regime": regime,
                    "rsi2": rsi2_val,
                    "cum_rsi2": cum_rsi2,
                    "connors_exit": connors_exit,
                    "opex_week": opex_week,
                    "bb_squeeze": bb_squeeze,
                },
            }
            pg.insert_watchlist_alert(alert)

            # Signal log
            pg.upsert_watchlist_signal_log({
                "symbol": sym,
                "signal_date": _date_type.today(),
                "direction": direction,
                "weighted_score": round(weighted_final, 4),
                "confidence": confidence,
                "current_price": current_price,
                "regime": regime,
                "category_scores": result["category_scores"],
                "category_weights": result["category_weights"],
                "vol_ratio": result["vol_ratio"],
                "vol_factor": result["vol_factor"],
                "target_price": target_price,
                "stop_price": stop_price,
            })

            # Telegram
            if "STRONG" in direction or (direction != "NEUTRAL" and confidence >= 60):
                emoji = "\U0001f7e2" if "BUY" in direction else "\U0001f534"
                label = {"STRONG_BUY": "Strong Buy", "BUY": "Buy",
                         "STRONG_SELL": "Strong Sell", "SELL": "Sell"}.get(direction, direction)
                l1 = result.get("layer1_regime", {})
                l2 = result.get("layer2_ranking", {})
                l3 = result.get("layer3_entry", {})
                qual = result.get("quality", {})
                asyncio.run(notifier.send(
                    f"<b>{emoji} Watchlist: {label} {sym}</b>\n\n"
                    f"Price: <b>${current_price:.2f}</b> | Composite: <b>{composite:.0f}/100</b>\n"
                    f"<b>RSI(2): {rsi2_val:.0f}</b> | Stage: {l2.get('stage', '?')}\n"
                    f"Market: {l1.get('market_trend', '?')} | VIX: {l1.get('vix', 0):.0f}\n"
                    f"RS Rating: {l2.get('rs_rating', 0):.0f} | Quality: {qual.get('score', 0):.0f}\n"
                    f"Squeeze: {'FIRED!' if l3.get('squeeze_fired') else ('ON' if bb_squeeze else 'OFF')}\n"
                    f"vs QQQ: 5d {rel_str_5d:+.1f}% / 20d {rel_str_20d:+.1f}%\n"
                    f"Target: ${target_price:.2f} / Stop: ${stop_price:.2f}\n"
                    f"\u23f0 {datetime.now().strftime('%H:%M KST')}"
                ))

        except Exception as e:
            logger.warning(f"Watchlist post-analysis failed for {sym}: {e}")
            continue

    cache.set_json("watchlist_analysis", {
        "status": "done",
        "analyzed_at": datetime.now().isoformat(),
        "count": len(results),
        "strategy": "tqm_5layer",
        "results": results,
    }, ttl=86400)
    logger.info(f"Watchlist analysis done: {len(results)} symbols (5-Layer TQM strategy)")

    # ── 이전 코드 참조용 (삭제됨) ──
    # 기존 Connors RSI(2) 인라인 분석 코드는 engine_v4/strategy/watchlist_strategy.py 로 이전됨


@app.get("/watchlist/drawdown-defense")
async def get_drawdown_defense():
    """Graduated Drawdown Defense 상태 조회 (Grossman-Zhou 기반 4단계)."""
    snapshots = pg.get_snapshots(days=60)
    if not snapshots:
        return {"tier": 0, "action": "NORMAL", "size_mult": 1.0, "message": "No snapshot data"}
    peak = max(s.get("total_value", 0) for s in snapshots)
    current = snapshots[-1].get("total_value", peak)
    return WatchlistStrategy.check_drawdown_defense(current, peak)


@app.get("/watchlist/analysis")
async def get_watchlist_analysis(refresh_price: bool = False):
    """워치리스트 분석 결과 조회 (캐시). refresh_price=true이면 현재가 실시간 갱신."""
    result = cache.get_json("watchlist_analysis")
    if not result:
        return {"status": "no_results", "message": "Run POST /watchlist/analyze first"}

    # 실시간 가격 갱신 옵션
    if refresh_price and result.get("status") == "done" and result.get("results"):
        import yfinance as yf
        symbols = [r["symbol"] for r in result["results"]]
        try:
            live = yf.download(symbols, period="1d", interval="1m", progress=False)
            if not live.empty:
                for r in result["results"]:
                    sym = r["symbol"]
                    try:
                        col = live["Close"].dropna() if len(symbols) == 1 else live["Close"][sym].dropna()
                        if len(col) > 0:
                            new_price = round(float(col.iloc[-1]), 2)
                            old_price = r.get("current_price", 0)
                            r["current_price"] = new_price
                            # P&L 재계산
                            avg_cost = r.get("avg_cost", 0)
                            if avg_cost and avg_cost > 0:
                                r["pnl_pct"] = round((new_price - avg_cost) / avg_cost * 100, 2)
                    except Exception:
                        pass
        except Exception:
            pass

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


@app.get("/watchlist/chart/{symbol}")
async def get_watchlist_chart(symbol: str, period: str = "1d"):
    """워치리스트 종목 차트 데이터 (1d/5d/1mo/6mo)."""
    import yfinance as yf

    from datetime import datetime as _dt
    import pytz as _pytz

    _PERIOD_MAP = {
        "1d":  None,  # 별도 로직으로 처리
        "5d":  {"period": "5d",  "interval": "30m", "prepost": False},
        "1mo": {"period": "1mo", "interval": "1d",  "prepost": False},
        "6mo": {"period": "6mo", "interval": "1d",  "prepost": False},
        "1y":  {"period": "1y",  "interval": "1d",  "prepost": False},
        "5y":  {"period": "5y",  "interval": "1wk", "prepost": False},
    }

    try:
        tkr = yf.Ticker(symbol)
        et = _pytz.timezone("US/Eastern")
        today_et = _dt.now(et).date()

        if period == "1d":
            # 프리마켓 포함 오늘 데이터 확보: 2d → 5d fallback
            df = tkr.history(period="2d", interval="5m", prepost=True)
            today_df = df[df.index.date == today_et] if not df.empty else df
            if today_df.empty:
                # 2d로도 오늘 데이터가 없으면 5d로 재시도 (휴일 직후 등)
                df = tkr.history(period="5d", interval="5m", prepost=True)
                today_df = df[df.index.date == today_et] if not df.empty else df

            if not today_df.empty:
                df = today_df
                data_date = str(today_et)
            elif not df.empty:
                # 오늘 데이터 없음 (프리마켓 전 or 휴일) → 최신 거래일
                last_date = df.index[-1].date()
                df = df[df.index.date == last_date]
                data_date = str(last_date)
            else:
                return {"symbol": symbol, "period": period, "points": [], "prev_close": None,
                        "data_date": None, "today": str(today_et)}
        else:
            params = _PERIOD_MAP.get(period, {"period": "5d", "interval": "30m", "prepost": False})
            df = tkr.history(**params)
            data_date = None

        if df.empty:
            return {"symbol": symbol, "period": period, "points": [], "prev_close": None}

        prev_close = None
        if period == "1d":
            info = tkr.info
            prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
            if prev_close:
                prev_close = round(float(prev_close), 2)

        points = []
        for idx, row in df.iterrows():
            p = round(float(row["Close"]), 2)
            if period == "1d":
                ts = idx.tz_convert("US/Eastern") if idx.tzinfo else idx
                hour, minute = ts.hour, ts.minute
                t = hour * 60 + minute
                session = "pre" if t < 570 else ("regular" if t < 960 else "post")
                points.append({"time": ts.strftime("%H:%M"), "price": p, "session": session})
            elif period == "5d":
                ts = idx.tz_convert("US/Eastern") if idx.tzinfo else idx
                points.append({"time": ts.strftime("%m/%d %H:%M"), "price": p})
            elif period in ("1y", "5y"):
                ts = idx
                fmt = "%Y-%m" if period == "5y" else "%Y-%m-%d"
                points.append({"time": ts.strftime(fmt), "price": p})
            else:
                ts = idx
                points.append({"time": ts.strftime("%m/%d"), "price": p})

        resp = {
            "symbol": symbol,
            "period": period,
            "prev_close": prev_close,
            "points": points,
        }
        if period == "1d":
            resp["data_date"] = data_date
            resp["today_et"] = str(today_et)
        return resp
    except Exception as e:
        logger.error(f"Chart fetch failed for {symbol}/{period}: {e}")
        return {"symbol": symbol, "period": period, "points": [], "prev_close": None, "error": str(e)}


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
# Signal Log & Replay Backtest
# ═══════════════════════════════════════════════════════════

@app.get("/watchlist/signal-log")
async def get_signal_log(symbol: str = None, limit: int = 200):
    """워치리스트 시그널 로그 조회."""
    logs = pg.get_watchlist_signal_logs(symbol=symbol, limit=limit)
    # Convert dates to strings for JSON
    for log in logs:
        for k in ("signal_date", "created_at"):
            if log.get(k):
                log[k] = str(log[k])
    return {"logs": logs, "count": len(logs)}


@app.get("/watchlist/signal-log/stats")
async def get_signal_log_stats():
    """시그널 로그 통계."""
    stats = pg.get_watchlist_signal_log_stats()
    for k in ("first_date", "last_date"):
        if stats.get(k):
            stats[k] = str(stats[k])
    return stats


@app.post("/watchlist/replay-backtest")
async def run_replay_backtest(req: ReplayBacktestRequest, bg: BackgroundTasks):
    """실제 기록된 시그널 로그 기반 리플레이 백테스트."""
    stats = pg.get_watchlist_signal_log_stats()
    days = stats.get("days", 0) or 0
    if days < 2:
        return {"status": "error", "message": f"Signal log has only {days} days. Need at least 2 days of logged signals. Run 'Analyze All' daily to accumulate data."}
    cache.set_json("watchlist_replay_backtest", {"status": "running"}, ttl=600)
    bg.add_task(_run_replay_backtest, req)
    return {"status": "running", "days_logged": days}


def _run_replay_backtest(req: ReplayBacktestRequest):
    """리플레이 백테스트 실행 (background task)."""
    import numpy as np

    logs = pg.get_watchlist_signal_logs(limit=50000)
    if not logs:
        cache.set_json("watchlist_replay_backtest", {"status": "error", "message": "No signal logs"}, ttl=60)
        return

    # Group logs by date
    from collections import defaultdict
    daily_signals = defaultdict(list)
    for log in logs:
        d = str(log["signal_date"])
        daily_signals[d].append(log)

    dates = sorted(daily_signals.keys())
    cash = req.initial_capital
    positions = {}  # symbol -> {entry_price, qty, entry_date, high_water_mark}
    equity_curve = []
    trades_log = []
    slippage = 0.001  # 0.1%

    for day in dates:
        signals = {s["symbol"]: s for s in daily_signals[day]}

        # --- Exit phase ---
        to_close = []
        for sym, pos in list(positions.items()):
            sig = signals.get(sym)
            price = sig["current_price"] if sig else pos["last_price"]
            pos["last_price"] = price

            # Update high water mark
            if price > pos.get("high_water_mark", 0):
                pos["high_water_mark"] = price

            # Check exit conditions
            reason = None
            # 1) Signal says SELL/STRONG_SELL/NEUTRAL
            if sig and sig["direction"] in ("SELL", "STRONG_SELL", "NEUTRAL"):
                reason = f"signal_{sig['direction'].lower()}"
            # 2) Trailing stop
            elif pos["high_water_mark"] > 0:
                drawdown = (pos["high_water_mark"] - price) / pos["high_water_mark"]
                if drawdown >= req.trailing_stop_pct:
                    reason = "trailing_stop"
            # 3) Max hold days
            from datetime import datetime as _dt
            hold_days = (_dt.strptime(day, "%Y-%m-%d") - _dt.strptime(pos["entry_date"], "%Y-%m-%d")).days
            if hold_days >= req.max_hold_days:
                reason = "max_hold_days"

            if reason:
                to_close.append((sym, price, reason))

        for sym, price, reason in to_close:
            pos = positions.pop(sym)
            exit_price = price * (1 - slippage)
            pnl = (exit_price - pos["entry_price"]) * pos["qty"]
            pnl_pct = (exit_price / pos["entry_price"] - 1) if pos["entry_price"] > 0 else 0
            cash += exit_price * pos["qty"]
            hold = 0
            try:
                from datetime import datetime as _dt2
                hold = (_dt2.strptime(day, "%Y-%m-%d") - _dt2.strptime(pos["entry_date"], "%Y-%m-%d")).days
            except:
                pass
            trades_log.append({
                "symbol": sym,
                "side": "SELL",
                "entry_date": pos["entry_date"],
                "exit_date": day,
                "entry_price": round(pos["entry_price"], 2),
                "exit_price": round(exit_price, 2),
                "qty": pos["qty"],
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct * 100, 2),
                "hold_days": hold,
                "reason": reason,
            })

        # --- Entry phase ---
        candidates = []
        for sym, sig in signals.items():
            if sym in positions:
                continue
            if sig["direction"] in ("STRONG_BUY", "BUY"):
                candidates.append(sig)

        # Sort by score descending
        candidates.sort(key=lambda s: s["weighted_score"], reverse=True)

        for sig in candidates:
            if len(positions) >= req.max_positions:
                break
            price = sig["current_price"] * (1 + slippage)
            alloc = cash * req.position_pct
            if alloc < 10 or price <= 0:
                continue
            qty = int(alloc / price)
            if qty < 1:
                continue
            cost = price * qty
            if cost > cash:
                continue
            cash -= cost
            positions[sig["symbol"]] = {
                "entry_price": price,
                "qty": qty,
                "entry_date": day,
                "high_water_mark": price,
                "last_price": sig["current_price"],
            }
            trades_log.append({
                "symbol": sig["symbol"],
                "side": "BUY",
                "entry_date": day,
                "exit_date": None,
                "entry_price": round(price, 2),
                "exit_price": None,
                "qty": qty,
                "pnl": 0,
                "pnl_pct": 0,
                "hold_days": 0,
                "reason": f"signal_{sig['direction'].lower()}",
            })

        # --- Equity snapshot ---
        invested = sum(pos["last_price"] * pos["qty"] for pos in positions.values())
        equity_curve.append({
            "date": day,
            "value": round(cash + invested, 2),
            "cash": round(cash, 2),
            "positions": len(positions),
        })

    # Force-close remaining positions at last known price
    if positions and equity_curve:
        last_day = dates[-1]
        for sym, pos in list(positions.items()):
            exit_price = pos["last_price"] * (1 - slippage)
            pnl = (exit_price - pos["entry_price"]) * pos["qty"]
            pnl_pct = (exit_price / pos["entry_price"] - 1) if pos["entry_price"] > 0 else 0
            cash += exit_price * pos["qty"]
            try:
                from datetime import datetime as _dt3
                hold = (_dt3.strptime(last_day, "%Y-%m-%d") - _dt3.strptime(pos["entry_date"], "%Y-%m-%d")).days
            except:
                hold = 0
            trades_log.append({
                "symbol": sym,
                "side": "SELL",
                "entry_date": pos["entry_date"],
                "exit_date": last_day,
                "entry_price": round(pos["entry_price"], 2),
                "exit_price": round(exit_price, 2),
                "qty": pos["qty"],
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct * 100, 2),
                "hold_days": hold,
                "reason": "period_end",
            })
        positions.clear()

    # --- Compute metrics ---
    sell_trades = [t for t in trades_log if t["side"] == "SELL"]
    wins = [t for t in sell_trades if t["pnl"] > 0]
    losses = [t for t in sell_trades if t["pnl"] <= 0]
    total_trades = len(sell_trades)
    win_rate = (len(wins) / total_trades * 100) if total_trades > 0 else 0
    gross_profit = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses)) or 1
    profit_factor = gross_profit / gross_loss
    avg_hold = (sum(t["hold_days"] for t in sell_trades) / total_trades) if total_trades > 0 else 0

    final_value = equity_curve[-1]["value"] if equity_curve else req.initial_capital
    total_return = ((final_value / req.initial_capital) - 1) * 100

    # Max drawdown
    peak = 0
    max_dd = 0
    for pt in equity_curve:
        if pt["value"] > peak:
            peak = pt["value"]
        dd = (peak - pt["value"]) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Sharpe (daily returns)
    if len(equity_curve) > 1:
        values = [pt["value"] for pt in equity_curve]
        returns = [(values[i] / values[i-1] - 1) for i in range(1, len(values))]
        mean_r = np.mean(returns)
        std_r = np.std(returns) or 1e-10
        sharpe = (mean_r / std_r) * np.sqrt(252)
    else:
        sharpe = 0

    # Monthly returns
    monthly_returns = []
    if equity_curve:
        from itertools import groupby
        for month_key, group in groupby(equity_curve, key=lambda x: x["date"][:7]):
            pts = list(group)
            monthly_returns.append({
                "month": month_key,
                "start_value": pts[0]["value"],
                "end_value": pts[-1]["value"],
                "return_pct": round(((pts[-1]["value"] / pts[0]["value"]) - 1) * 100, 2) if pts[0]["value"] > 0 else 0,
            })

    # Signal accuracy
    signal_accuracy = {}
    buy_trades = [t for t in trades_log if t["side"] == "BUY"]
    sell_closures = {(t["symbol"], t["entry_date"]): t for t in sell_trades}
    for bt in buy_trades:
        key = (bt["symbol"], bt["entry_date"])
        closure = sell_closures.get(key)
        direction = bt["reason"].replace("signal_", "").upper() if bt["reason"] else "BUY"
        if direction not in signal_accuracy:
            signal_accuracy[direction] = {"total": 0, "profitable": 0}
        signal_accuracy[direction]["total"] += 1
        if closure and closure["pnl"] > 0:
            signal_accuracy[direction]["profitable"] += 1
    for k, v in signal_accuracy.items():
        v["accuracy"] = round((v["profitable"] / v["total"]) * 100, 1) if v["total"] > 0 else 0

    stats = pg.get_watchlist_signal_log_stats()

    cache.set_json("watchlist_replay_backtest", {
        "status": "done",
        "days_logged": stats.get("days", 0),
        "first_date": str(stats.get("first_date", "")),
        "last_date": str(stats.get("last_date", "")),
        "params": {
            "initial_capital": req.initial_capital,
            "position_pct": req.position_pct,
            "max_positions": req.max_positions,
            "trailing_stop_pct": req.trailing_stop_pct,
            "max_hold_days": req.max_hold_days,
        },
        "total_return": round(total_return, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "sharpe_ratio": round(float(sharpe), 2),
        "win_rate": round(win_rate, 1),
        "total_trades": total_trades,
        "profit_factor": round(profit_factor, 2),
        "avg_hold_days": round(avg_hold, 1),
        "final_value": round(final_value, 2),
        "equity_curve": equity_curve,
        "trades_log": sell_trades[:200],
        "monthly_returns": monthly_returns,
        "signal_accuracy": signal_accuracy,
    }, ttl=86400)
    logger.info(f"Replay backtest done: {total_trades} trades, {total_return:+.1f}% return")


@app.get("/watchlist/replay-backtest")
async def get_replay_backtest():
    """리플레이 백테스트 결과 조회."""
    result = cache.get_json("watchlist_replay_backtest")
    if not result:
        return {"status": "no_results", "message": "Run POST /watchlist/replay-backtest first"}
    return result


# ═══════════════════════════════════════════════════════════
# Ticker
# ═══════════════════════════════════════════════════════════

@app.get("/ticker")
async def get_ticker_data():
    """티커바 데이터 — 오픈 포지션 심볼 현재가 (Redis 캐시 60초)."""
    cached = cache.get_json("ticker_data")
    if cached:
        return cached

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
    result = {"tickers": tickers}
    cache.set_json("ticker_data", result, ttl=60)
    return result


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
# Short Interest
# ═══════════════════════════════════════════════════════════

@app.get("/short-interest/{symbol}")
async def get_short_interest(symbol: str):
    """공매도 잔고 데이터 조회 (yfinance)."""
    import yfinance as yf

    sym = symbol.upper()
    try:
        info = yf.Ticker(sym).info
        shares_short = info.get("sharesShort", 0) or 0
        short_ratio = info.get("shortRatio", 0) or 0
        short_pct_float = info.get("shortPercentOfFloat", 0) or 0
        shares_prior = info.get("sharesShortPriorMonth", 0) or 0

        change_pct = 0.0
        if shares_prior > 0:
            change_pct = round((shares_short - shares_prior) / shares_prior * 100, 2)

        return {
            "symbol": sym,
            "short_interest": shares_short,
            "short_ratio": round(float(short_ratio), 2),
            "short_pct_float": round(float(short_pct_float) * 100, 2),
            "change_pct": change_pct,
            "shares_prior_month": shares_prior,
            "available": shares_short > 0,
            "source": "yfinance",
            "fetched_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.warning(f"yfinance short interest failed for {sym}: {e}")
        return {
            "symbol": sym,
            "short_interest": 0,
            "short_ratio": 0.0,
            "short_pct_float": 0.0,
            "change_pct": 0.0,
            "available": False,
            "source": "error",
            "fetched_at": datetime.now().isoformat(),
        }


# ═══════════════════════════════════════════════════════════
# Macro Overlay (VIX + HY Spread + Gold/SPY + Yield Curve + Cu/Au + BTC)
# ═══════════════════════════════════════════════════════════


@app.get("/macro")
async def get_macro_score():
    """현재 매크로 오버레이 점수 (캐시 반환)."""
    cached = cache.get_json("macro_score")
    if cached:
        cached["cache_hit"] = True
        return cached
    try:
        result = macro_scorer_inst.calc_macro_score()
        result["cache_hit"] = False
        return result
    except Exception as e:
        raise HTTPException(500, f"Macro score failed: {e}")


@app.post("/macro/collect")
async def collect_macro_data(bg: BackgroundTasks):
    """매크로 데이터 수집 + 스코어링 (수동/스케줄러 트리거)."""
    def _run():
        try:
            data = macro_collector.collect_macro_data(force=True)
            result = macro_scorer_inst.calc_macro_score(force_collect=True)
            # DB 스냅샷 저장
            _save_macro_snapshot(result, data)
            logger.info(f"Macro collect done: score={result['macro_score']:.1f}, "
                        f"regime={result['regime']}")
        except Exception as e:
            logger.error(f"Macro collect failed: {e}", exc_info=True)

    bg.add_task(_run)
    return {"status": "collecting", "message": "Macro data collection started"}


@app.get("/macro/history")
async def get_macro_history(days: int = 30):
    """매크로 스냅샷 이력."""
    with pg.get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM swing_macro_snapshots
            WHERE time >= now() - make_interval(days => %s)
            ORDER BY time DESC
        """, (days,)).fetchall()
    return {"snapshots": [dict(r) for r in rows], "count": len(rows)}


def _save_macro_snapshot(score_result: dict, raw_data: dict):
    """매크로 스냅샷 DB 저장."""
    with pg.get_conn() as conn:
        conn.execute("""
            INSERT INTO swing_macro_snapshots
                (macro_score, risk_off_score, yield_curve_score,
                 copper_gold_score, dollar_trend_score, btc_momentum_score,
                 regime, vix, tnx, dxy, gold_spy_ratio, hy_spread,
                 copper_gold_ratio, btc_momentum_20d, dxy_momentum_20d, detail)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (score_result["macro_score"],
              score_result["risk_off"]["score"],
              score_result["yield_curve"]["score"],
              score_result["copper_gold"]["score"],
              score_result["dollar_trend"]["score"],
              score_result["btc_momentum"]["score"],
              score_result["regime"],
              raw_data.get("vix"), raw_data.get("tnx"), raw_data.get("dxy"),
              raw_data.get("gold_spy_ratio"), raw_data.get("hy_spread"),
              raw_data.get("copper_gold_ratio"), raw_data.get("btc_momentum_20d"),
              raw_data.get("dxy_momentum_20d"),
              json.dumps(score_result, default=str)))
        conn.commit()


@app.get("/macro/risk-adjustment")
async def get_macro_risk_adjustment():
    """현재 매크로 레짐 기반 리스크 조절 상태."""
    position_adj = pos_mgr.get_risk_adjustment()
    trailing_adj = exit_mgr.get_exit_params()
    return {
        "position_sizing": position_adj,
        "exit_strategy": trailing_adj,
    }


@app.get("/exit-strategy")
async def get_exit_strategy():
    """5-Layer Auto-Exit 전략 현재 파라미터."""
    params = exit_mgr.get_exit_params()
    # 각 포지션의 ATR 정보 포함
    positions = pg.get_open_positions()
    pos_info = []
    for p in positions:
        entry_atr = float(p.get("entry_atr") or 0)
        entry_price = float(p["entry_price"])
        r_mult = 0
        if entry_atr > 0 and p.get("current_price"):
            r_mult = (float(p["current_price"]) - entry_price) / entry_atr
        pos_info.append({
            "position_id": p["position_id"],
            "symbol": p["symbol"],
            "entry_price": entry_price,
            "current_price": float(p.get("current_price") or entry_price),
            "entry_atr": entry_atr,
            "hard_stop": float(p.get("hard_stop") or 0),
            "stop_loss": float(p.get("stop_loss") or 0),
            "trailing_active": bool(p.get("trailing_stop_active")),
            "r_multiple": round(r_mult, 2),
            "hold_days": (datetime.now(p["entry_time"].tzinfo) - p["entry_time"]).days
                if p.get("entry_time") else 0,
        })
    return {
        "params": params,
        "positions": pos_info,
    }


# ═══════════════════════════════════════════════════════════
# Social Sentiment (Reddit + StockTwits)
# ═══════════════════════════════════════════════════════════

@app.get("/social/{symbol}")
async def get_social_sentiment(symbol: str):
    """종목별 소셜 감성 데이터 (Reddit + StockTwits)."""
    data = social_collector.get_social_sentiment(symbol.upper())
    return data


@app.post("/social/collect")
async def collect_social_all(bg: BackgroundTasks):
    """유니버스 전체 소셜 감성 수집 (백그라운드)."""
    bg.add_task(_run_social_collect)
    return {"status": "started", "message": "Social sentiment collection started"}


def _run_social_collect():
    try:
        result = social_collector.collect_all()
        logger.info(f"Social collect done: {result}")
    except Exception as e:
        logger.error(f"Social collect failed: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════
# LSTM Momentum Prediction
# ═══════════════════════════════════════════════════════════

@app.get("/lstm/info")
async def lstm_model_info():
    """LSTM 모델 정보 조회."""
    return lstm_predictor.get_model_info()


@app.get("/lstm/predict/{symbol}")
async def lstm_predict(symbol: str):
    """종목별 LSTM 5일 후 상승 확률 예측."""
    result = lstm_predictor.predict(symbol.upper())
    return result


@app.post("/lstm/train")
async def lstm_train(bg: BackgroundTasks):
    """LSTM 모델 학습 시작 (백그라운드)."""
    bg.add_task(_run_lstm_train)
    return {"status": "started", "message": "LSTM training started in background"}


_lstm_train_result = {}


def _run_lstm_train():
    global _lstm_train_result
    _lstm_train_result = {"status": "running"}
    try:
        result = lstm_predictor.train()
        _lstm_train_result = {"status": "done", **result}
        logger.info(f"LSTM training done: {result}")
    except Exception as e:
        _lstm_train_result = {"status": "error", "error": str(e)}
        logger.error(f"LSTM training failed: {e}", exc_info=True)


@app.get("/lstm/train-status")
async def lstm_train_status():
    """LSTM 학습 상태 조회."""
    return _lstm_train_result


@app.post("/lstm/predict-all")
async def lstm_predict_all(bg: BackgroundTasks):
    """유니버스 전체 LSTM 예측 (백그라운드)."""
    bg.add_task(_run_lstm_predict_all)
    return {"status": "started", "message": "LSTM prediction started"}


def _run_lstm_predict_all():
    try:
        results = lstm_predictor.predict_universe()
        logger.info(f"LSTM predict-all done: {len(results)} predictions")
    except Exception as e:
        logger.error(f"LSTM predict-all failed: {e}", exc_info=True)


# ═══════════════════════════════════════════════════════════
# Market Overview (Sector Heatmap)
# ═══════════════════════════════════════════════════════════

_SECTOR_ETFS = {
    "XLK":  {"name": "기술",         "name_en": "Technology",       "weight": 30},
    "XLF":  {"name": "금융",         "name_en": "Financials",       "weight": 13},
    "XLV":  {"name": "헬스케어",     "name_en": "Healthcare",       "weight": 13},
    "XLY":  {"name": "경기소비재",   "name_en": "Consumer Disc.",   "weight": 10},
    "XLC":  {"name": "커뮤니케이션", "name_en": "Communication",    "weight": 9},
    "XLI":  {"name": "산업재",       "name_en": "Industrials",      "weight": 8},
    "XLP":  {"name": "필수소비재",   "name_en": "Consumer Staples", "weight": 7},
    "XLE":  {"name": "에너지",       "name_en": "Energy",           "weight": 4},
    "XLB":  {"name": "소재",         "name_en": "Materials",        "weight": 3},
    "XLRE": {"name": "부동산",       "name_en": "Real Estate",      "weight": 3},
    "XLU":  {"name": "유틸리티",     "name_en": "Utilities",        "weight": 3},
}
_INDICES = {
    "SPY": {"name": "S&P 500"},
    "QQQ": {"name": "NASDAQ 100"},
    "DIA": {"name": "다우존스"},
    "IWM": {"name": "러셀 2000"},
}


@app.get("/market/overview")
async def get_market_overview():
    """섹터 ETF + 주요 지수 일일 변동률."""
    cached = cache.get_json("market_overview")
    if cached:
        return cached

    import yfinance as yf

    all_syms = list(_SECTOR_ETFS.keys()) + list(_INDICES.keys())
    sectors = []
    index_data = []

    try:
        df = yf.download(all_syms, period="2d", progress=False)
        close = df["Close"] if "Close" in df.columns else df.get(("Close",), df)

        for sym, info in _SECTOR_ETFS.items():
            try:
                col = close[sym].dropna()
                if len(col) >= 2:
                    pct = round(((float(col.iloc[-1]) - float(col.iloc[-2])) / float(col.iloc[-2])) * 100, 2)
                else:
                    pct = 0.0
                sectors.append({**info, "symbol": sym, "change_pct": pct})
            except Exception:
                sectors.append({**info, "symbol": sym, "change_pct": 0.0})

        for sym, info in _INDICES.items():
            try:
                col = close[sym].dropna()
                if len(col) >= 2:
                    pct = round(((float(col.iloc[-1]) - float(col.iloc[-2])) / float(col.iloc[-2])) * 100, 2)
                else:
                    pct = 0.0
                index_data.append({**info, "symbol": sym, "change_pct": pct})
            except Exception:
                index_data.append({**info, "symbol": sym, "change_pct": 0.0})
    except Exception as e:
        logger.warning(f"Market overview fetch failed: {e}")

    # 상승/하락 카운트
    up = sum(1 for s in sectors if s["change_pct"] > 0)
    down = sum(1 for s in sectors if s["change_pct"] < 0)

    result = {
        "sectors": sectors, "indices": index_data,
        "advance": up, "decline": down, "unchanged": len(sectors) - up - down,
        "updated_at": datetime.now().isoformat(),
    }
    cache.set_json("market_overview", result, ttl=1800)
    return result


# 섹터 ETF 상위 보유 종목 (근사 비중)
_SECTOR_HOLDINGS = {
    "XLK": [
        ("AAPL", "Apple", 22), ("MSFT", "Microsoft", 20), ("NVDA", "NVIDIA", 18),
        ("AVGO", "Broadcom", 6), ("CRM", "Salesforce", 3), ("ORCL", "Oracle", 3),
        ("ADBE", "Adobe", 3), ("AMD", "AMD", 3), ("CSCO", "Cisco", 2), ("ACN", "Accenture", 2),
        ("INTC", "Intel", 2), ("IBM", "IBM", 2), ("INTU", "Intuit", 2),
        ("NOW", "ServiceNow", 2), ("QCOM", "Qualcomm", 2),
    ],
    "XLF": [
        ("BRK-B", "Berkshire", 14), ("JPM", "JPMorgan", 11), ("V", "Visa", 8),
        ("MA", "Mastercard", 7), ("BAC", "BofA", 5), ("WFC", "Wells Fargo", 4),
        ("GS", "Goldman Sachs", 4), ("MS", "Morgan Stanley", 3), ("SPGI", "S&P Global", 3),
        ("AXP", "Amex", 3), ("BLK", "BlackRock", 3), ("C", "Citigroup", 3),
        ("SCHW", "Schwab", 2), ("PGR", "Progressive", 2), ("CB", "Chubb", 2),
    ],
    "XLV": [
        ("LLY", "Eli Lilly", 13), ("UNH", "UnitedHealth", 10), ("JNJ", "J&J", 7),
        ("ABBV", "AbbVie", 7), ("MRK", "Merck", 5), ("TMO", "Thermo Fisher", 4),
        ("ABT", "Abbott", 4), ("PFE", "Pfizer", 3), ("AMGN", "Amgen", 3),
        ("DHR", "Danaher", 3), ("ISRG", "Intuitive Surg.", 3), ("BMY", "BMS", 3),
        ("SYK", "Stryker", 2), ("GILD", "Gilead", 2), ("VRTX", "Vertex", 2),
    ],
    "XLY": [
        ("AMZN", "Amazon", 23), ("TSLA", "Tesla", 15), ("HD", "Home Depot", 9),
        ("MCD", "McDonald's", 5), ("LOW", "Lowe's", 4), ("NKE", "Nike", 3),
        ("BKNG", "Booking", 4), ("SBUX", "Starbucks", 3), ("TJX", "TJX Cos", 3),
        ("CMG", "Chipotle", 2), ("ORLY", "O'Reilly", 2), ("MAR", "Marriott", 2),
        ("GM", "GM", 2), ("F", "Ford", 1), ("ROST", "Ross Stores", 1),
    ],
    "XLC": [
        ("META", "Meta", 23), ("GOOGL", "Alphabet A", 22), ("GOOG", "Alphabet C", 5),
        ("NFLX", "Netflix", 6), ("T", "AT&T", 5), ("CMCSA", "Comcast", 4),
        ("DIS", "Disney", 4), ("TMUS", "T-Mobile", 4), ("VZ", "Verizon", 3),
        ("CHTR", "Charter", 3), ("EA", "EA", 2), ("WBD", "Warner Bros", 2),
    ],
    "XLI": [
        ("GE", "GE Aerospace", 8), ("CAT", "Caterpillar", 5), ("RTX", "RTX", 5),
        ("UNP", "Union Pacific", 5), ("HON", "Honeywell", 4), ("DE", "Deere", 4),
        ("BA", "Boeing", 4), ("LMT", "Lockheed", 3), ("UPS", "UPS", 3),
        ("ADP", "ADP", 3), ("ETN", "Eaton", 3), ("MMM", "3M", 2),
        ("GD", "General Dynamics", 2), ("WM", "Waste Mgmt", 2), ("FDX", "FedEx", 2),
    ],
    "XLP": [
        ("PG", "Procter&Gamble", 15), ("COST", "Costco", 13), ("WMT", "Walmart", 10),
        ("KO", "Coca-Cola", 9), ("PEP", "PepsiCo", 8), ("PM", "Philip Morris", 5),
        ("MDLZ", "Mondelez", 4), ("MO", "Altria", 3), ("CL", "Colgate", 3),
        ("TGT", "Target", 3), ("KR", "Kroger", 2), ("STZ", "Constellation", 2),
    ],
    "XLE": [
        ("XOM", "Exxon", 23), ("CVX", "Chevron", 16), ("COP", "ConocoPhillips", 8),
        ("EOG", "EOG Resources", 5), ("SLB", "Schlumberger", 5), ("MPC", "Marathon Petro", 4),
        ("PSX", "Phillips 66", 4), ("WMB", "Williams", 4), ("VLO", "Valero", 3),
        ("OKE", "ONEOK", 3), ("PXD", "Pioneer", 3), ("HES", "Hess", 3),
    ],
    "XLB": [
        ("LIN", "Linde", 18), ("SHW", "Sherwin-Williams", 10), ("FCX", "Freeport", 7),
        ("APD", "Air Products", 6), ("ECL", "Ecolab", 5), ("NEM", "Newmont", 5),
        ("DOW", "Dow Inc", 5), ("NUE", "Nucor", 4), ("DD", "DuPont", 4),
        ("VMC", "Vulcan", 3), ("MLM", "Martin Mar.", 3), ("PPG", "PPG", 3),
    ],
    "XLRE": [
        ("PLD", "Prologis", 14), ("AMT", "Amer Tower", 10), ("EQIX", "Equinix", 9),
        ("WELL", "Welltower", 6), ("SPG", "Simon Prop", 5), ("DLR", "Digital Realty", 5),
        ("O", "Realty Income", 5), ("PSA", "Public Storage", 4), ("CCI", "Crown Castle", 4),
        ("VICI", "VICI Prop", 3), ("CBRE", "CBRE", 3), ("AVB", "AvalonBay", 2),
    ],
    "XLU": [
        ("NEE", "NextEra", 15), ("SO", "Southern Co", 9), ("DUK", "Duke Energy", 8),
        ("CEG", "Constellation E", 7), ("SRE", "Sempra", 5), ("AEP", "AEP", 5),
        ("D", "Dominion", 4), ("PCG", "PG&E", 4), ("XEL", "Xcel", 3),
        ("EXC", "Exelon", 3), ("ED", "Con Edison", 3), ("WEC", "WEC Energy", 2),
    ],
}


@app.get("/market/sector/{etf_symbol}")
async def get_sector_detail(etf_symbol: str):
    """섹터 ETF 상위 종목 일일 변동률."""
    etf = etf_symbol.upper()
    if etf not in _SECTOR_HOLDINGS:
        raise HTTPException(404, f"Unknown sector ETF: {etf}")

    cache_key = f"sector_detail_{etf}"
    cached = cache.get_json(cache_key)
    if cached:
        return cached

    import yfinance as yf

    holdings = _SECTOR_HOLDINGS[etf]
    symbols = [h[0] for h in holdings]
    name_map = {h[0]: h[1] for h in holdings}
    weight_map = {h[0]: h[2] for h in holdings}

    stocks = []
    try:
        df = yf.download(symbols, period="2d", progress=False)
        close = df["Close"] if "Close" in df.columns else df

        for sym in symbols:
            try:
                col = close[sym].dropna()
                if len(col) >= 2:
                    pct = round(((float(col.iloc[-1]) - float(col.iloc[-2])) / float(col.iloc[-2])) * 100, 2)
                    price = round(float(col.iloc[-1]), 2)
                else:
                    pct, price = 0.0, 0.0
                stocks.append({
                    "symbol": sym, "name": name_map[sym],
                    "weight": weight_map[sym], "change_pct": pct, "price": price,
                })
            except Exception:
                stocks.append({
                    "symbol": sym, "name": name_map[sym],
                    "weight": weight_map[sym], "change_pct": 0.0, "price": 0.0,
                })
    except Exception as e:
        logger.warning(f"Sector detail fetch failed for {etf}: {e}")

    up = sum(1 for s in stocks if s["change_pct"] > 0)
    down = sum(1 for s in stocks if s["change_pct"] < 0)

    result = {
        "etf": etf, "sector": _SECTOR_ETFS[etf]["name"],
        "sector_en": _SECTOR_ETFS[etf]["name_en"],
        "stocks": stocks, "advance": up, "decline": down,
        "unchanged": len(stocks) - up - down,
        "updated_at": datetime.now().isoformat(),
    }
    cache.set_json(cache_key, result, ttl=600)
    return result


# ═══════════════════════════════════════════════════════════
# Factor Crowding — 팩터 크라우딩 모니터
# ═══════════════════════════════════════════════════════════

@app.get("/factor-crowding")
def get_factor_crowding():
    """현재 오픈 포지션 + pending 시그널의 팩터 크라우딩 분석."""
    try:
        result = crowding_monitor.get_portfolio_crowding()
        return result
    except Exception as e:
        logger.error(f"팩터 크라우딩 분석 실패: {e}")
        raise HTTPException(500, f"Factor crowding analysis failed: {e}")


@app.post("/factor-crowding/refresh")
def refresh_factor_crowding():
    """ETF 보유 종목 데이터 갱신 (yfinance + 시드 폴백)."""
    try:
        result = crowding_monitor.refresh_etf_holdings()
        return {"status": "ok", "refreshed": result}
    except Exception as e:
        logger.error(f"ETF 보유 종목 갱신 실패: {e}")
        raise HTTPException(500, f"ETF holdings refresh failed: {e}")


@app.get("/factor-crowding/{symbol}")
def get_symbol_crowding(symbol: str):
    """단일 종목의 팩터 크라우딩 점수 조회."""
    try:
        result = crowding_monitor.get_crowding_score(symbol)
        return result
    except Exception as e:
        logger.error(f"종목 크라우딩 조회 실패: {symbol} — {e}")
        raise HTTPException(500, f"Symbol crowding check failed: {e}")


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
