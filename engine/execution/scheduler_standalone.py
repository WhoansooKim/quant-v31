"""
V3.1 Phase 3.4 — Standalone Scheduler Entry Point
quant-scheduler.service 에서 사용
NOTE: 기본적으로 스케줄러는 engine(main.py)에 내장.
      이 모듈은 독립 실행이 필요할 때만 사용.
"""
import asyncio
import logging
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("scheduler_standalone")


def main():
    from engine.config.settings import Settings
    from engine.data.storage import PostgresStore, RedisCache
    from engine.risk.regime import RegimeDetector
    from engine.risk.regime_allocator import RegimeAllocator
    from engine.risk.kill_switch import DrawdownKillSwitch
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

    logger.info("Standalone scheduler starting...")
    config = Settings()

    # Minimal orchestrator (same as main.py but lightweight)
    from engine.api.main import PortfolioOrchestrator
    orch = PortfolioOrchestrator()

    scheduler = setup_scheduler(orch)
    logger.info("Standalone scheduler running. Press Ctrl+C to stop.")

    # Graceful shutdown
    loop = asyncio.new_event_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(stop_event.wait())
    finally:
        scheduler.shutdown(wait=False)
        loop.close()
        logger.info("Standalone scheduler stopped.")


if __name__ == "__main__":
    main()
