"""
V3.1 Phase 3.3 — APScheduler 자동 실행
미국 동부시간(ET) 기준 5개 스케줄:
  1. 일일 8단계 파이프라인 (15:30 ET, 월~금)
  2. HMM 월간 재학습 (매월 첫 토요일)
  3. 데이터 수집 (17:00 ET, 월~금)
  4. FinBERT 센티먼트 스캔 (장중 매시간)
  5. 물리뷰 갱신 (일요일 02:00 ET)
"""
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

if TYPE_CHECKING:
    from engine.api.main import PortfolioOrchestrator

logger = logging.getLogger(__name__)

# 미국 동부시간
ET = pytz.timezone("US/Eastern")


def setup_scheduler(orchestrator: "PortfolioOrchestrator") -> AsyncIOScheduler:
    """전체 스케줄 설정 (미국 동부시간 기준)"""
    scheduler = AsyncIOScheduler(timezone=ET)

    # ─── 1. 메인 파이프라인: 장 마감 30분 전 (15:30 ET) ───
    scheduler.add_job(
        orchestrator.execute_daily,
        CronTrigger(hour=15, minute=30, day_of_week="mon-fri", timezone=ET),
        id="daily_pipeline",
        name="일일 8단계 파이프라인",
        misfire_grace_time=300,
        max_instances=1,
    )
    logger.info("Scheduled: daily_pipeline @ 15:30 ET (Mon-Fri)")

    # ─── 2. HMM 월간 재학습: 매월 첫 토요일 04:00 ET ───
    scheduler.add_job(
        _retrain_hmm,
        CronTrigger(day_of_week="sat", day="1-7", hour=4, timezone=ET),
        id="hmm_retrain",
        name="HMM 월간 재학습",
        misfire_grace_time=3600,
        max_instances=1,
        args=[orchestrator],
    )
    logger.info("Scheduled: hmm_retrain @ 1st Saturday 04:00 ET")

    # ─── 3. 데이터 수집: 장 마감 후 (17:00 ET) ───
    scheduler.add_job(
        _collect_data,
        CronTrigger(hour=17, minute=0, day_of_week="mon-fri", timezone=ET),
        id="data_collection",
        name="일봉 데이터 수집",
        misfire_grace_time=300,
        max_instances=1,
        args=[orchestrator],
    )
    logger.info("Scheduled: data_collection @ 17:00 ET (Mon-Fri)")

    # ─── 4. 센티먼트 스캔: 장중 매시간 (09~16 ET) ───
    scheduler.add_job(
        _sentiment_scan,
        CronTrigger(
            hour="9-16", minute=0, day_of_week="mon-fri", timezone=ET
        ),
        id="sentiment_scan",
        name="FinBERT 센티먼트 스캔",
        misfire_grace_time=600,
        max_instances=1,
        args=[orchestrator],
    )
    logger.info("Scheduled: sentiment_scan @ hourly 09-16 ET (Mon-Fri)")

    # ─── 5. 물리뷰 갱신: 주 1회 (일요일 02:00 ET) ───
    scheduler.add_job(
        _refresh_views,
        CronTrigger(day_of_week="sun", hour=2, timezone=ET),
        id="mv_refresh",
        name="물리뷰 갱신",
        misfire_grace_time=3600,
        max_instances=1,
        args=[orchestrator],
    )
    logger.info("Scheduled: mv_refresh @ Sunday 02:00 ET")

    scheduler.start()
    logger.info("APScheduler started with 5 jobs")
    return scheduler


# ═══════════════════════════════════════
#  Job Wrappers (에러 격리)
# ═══════════════════════════════════════

async def _retrain_hmm(orchestrator: "PortfolioOrchestrator"):
    """HMM 모델 재학습"""
    logger.info("[scheduler] HMM retrain started")
    try:
        detector = orchestrator.regime_detector
        detector.fit()
        logger.info("[scheduler] HMM retrain completed")
        if orchestrator.telegram:
            await orchestrator.telegram.send(
                "🔄 <b>HMM 재학습 완료</b>\n월간 모델 업데이트 성공"
            )
    except Exception as e:
        logger.error(f"[scheduler] HMM retrain failed: {e}")
        if orchestrator.telegram:
            await orchestrator.telegram.send_error("HMM retrain", str(e))


async def _collect_data(orchestrator: "PortfolioOrchestrator"):
    """일봉 데이터 수집 (yfinance)"""
    logger.info("[scheduler] Data collection started")
    try:
        await orchestrator.collect_daily_data()
        logger.info("[scheduler] Data collection completed")
    except Exception as e:
        logger.error(f"[scheduler] Data collection failed: {e}")
        if orchestrator.telegram:
            await orchestrator.telegram.send_error("Data collection", str(e))


async def _sentiment_scan(orchestrator: "PortfolioOrchestrator"):
    """FinBERT 센티먼트 스캔"""
    logger.info("[scheduler] Sentiment scan started")
    try:
        if hasattr(orchestrator, "sentiment") and orchestrator.sentiment:
            await orchestrator.scan_sentiment()
            logger.info("[scheduler] Sentiment scan completed")
        else:
            logger.debug("[scheduler] Sentiment module not configured, skip")
    except Exception as e:
        logger.error(f"[scheduler] Sentiment scan failed: {e}")


async def _refresh_views(orchestrator: "PortfolioOrchestrator"):
    """물리뷰(Materialized View) 갱신"""
    logger.info("[scheduler] Materialized view refresh started")
    try:
        await orchestrator.refresh_materialized_views()
        logger.info("[scheduler] Materialized view refresh completed")
    except Exception as e:
        logger.error(f"[scheduler] MV refresh failed: {e}")
        if orchestrator.telegram:
            await orchestrator.telegram.send_error("MV refresh", str(e))
