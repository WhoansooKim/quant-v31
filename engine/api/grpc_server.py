"""
V3.1 Phase 3.3 — gRPC Server
Python 엔진 ↔ Blazor 대시보드 양방향 통신
Services: RegimeService, PortfolioService, SignalService
"""
import time
import logging
from concurrent import futures
from datetime import datetime

import grpc

from engine.api import regime_pb2, regime_pb2_grpc
from engine.api import portfolio_pb2, portfolio_pb2_grpc
from engine.api import signals_pb2, signals_pb2_grpc
from engine.data.storage import PostgresStore, RedisCache

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════
#  Regime Service
# ═══════════════════════════════════════

class RegimeServicer(regime_pb2_grpc.RegimeServiceServicer):
    """레짐 상태 조회 + 실시간 스트리밍"""

    def __init__(self, pg: PostgresStore, cache: RedisCache):
        self.pg = pg
        self.cache = cache

    def _build_response(self, regime: dict) -> regime_pb2.RegimeResponse:
        return regime_pb2.RegimeResponse(
            current=regime.get("current", regime.get("regime", "unknown")),
            bull_prob=float(regime.get("bull_prob", regime.get("bull", 0))),
            sideways_prob=float(regime.get("sideways_prob", regime.get("sideways", 0))),
            bear_prob=float(regime.get("bear_prob", regime.get("bear", 0))),
            confidence=float(regime.get("confidence", 0)),
            detected_at=str(regime.get("detected_at", "")),
        )

    def GetCurrentRegime(self, request, context):
        """현재 레짐 상태 (Redis 캐시 → PG fallback)"""
        try:
            regime = self.cache.get_regime()
            if not regime:
                regime = self.pg.get_latest_regime()
            if not regime:
                return regime_pb2.RegimeResponse(current="unknown")
            return self._build_response(regime)
        except Exception as e:
            logger.error(f"gRPC GetCurrentRegime error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return regime_pb2.RegimeResponse(current="error")

    def StreamRegime(self, request, context):
        """레짐 변경 시 스트리밍 (5초 간격 폴링)"""
        last_regime = None
        while context.is_active():
            try:
                regime = self.cache.get_regime()
                if not regime:
                    regime = self.pg.get_latest_regime()
                if regime:
                    current = regime.get("current", regime.get("regime"))
                    if current != last_regime:
                        last_regime = current
                        yield self._build_response(regime)
            except Exception as e:
                logger.error(f"gRPC StreamRegime error: {e}")
            time.sleep(5)


# ═══════════════════════════════════════
#  Portfolio Service
# ═══════════════════════════════════════

class PortfolioServicer(portfolio_pb2_grpc.PortfolioServiceServicer):
    """포트폴리오 스냅샷 + 파이프라인 트리거"""

    def __init__(self, pg: PostgresStore, cache: RedisCache,
                 orchestrator=None):
        self.pg = pg
        self.cache = cache
        self.orchestrator = orchestrator

    def GetSnapshot(self, request, context):
        """최신 포트폴리오 스냅샷"""
        try:
            snap = self.pg.get_latest_snapshot()
            if not snap:
                return portfolio_pb2.SnapshotResponse()

            return portfolio_pb2.SnapshotResponse(
                total_value=float(snap.get("total_value", 0)),
                daily_return=float(snap.get("daily_return", 0)),
                sharpe_ratio=float(snap.get("sharpe_ratio", 0)),
                max_drawdown=float(snap.get("max_drawdown", 0)),
                regime=str(snap.get("regime", "unknown")),
                kill_level=str(snap.get("kill_level", "NORMAL")),
            )
        except Exception as e:
            logger.error(f"gRPC GetSnapshot error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return portfolio_pb2.SnapshotResponse()

    def TriggerPipeline(self, request, context):
        """8단계 파이프라인 트리거"""
        if not self.orchestrator:
            return portfolio_pb2.PipelineStatus(
                success=False,
                message="Orchestrator not configured",
            )
        try:
            import asyncio
            t0 = time.time()
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                self.orchestrator.execute_daily()
            )
            loop.close()
            elapsed = time.time() - t0
            return portfolio_pb2.PipelineStatus(
                success=True,
                message=f"Pipeline completed: {result}",
                elapsed_sec=elapsed,
            )
        except Exception as e:
            logger.error(f"gRPC TriggerPipeline error: {e}")
            return portfolio_pb2.PipelineStatus(
                success=False,
                message=str(e),
            )


# ═══════════════════════════════════════
#  Signal Service
# ═══════════════════════════════════════

class SignalServicer(signals_pb2_grpc.SignalServiceServicer):
    """시그널 조회"""

    def __init__(self, pg: PostgresStore):
        self.pg = pg

    def GetLatestSignals(self, request, context):
        """최근 시그널 목록"""
        try:
            strategy_filter = request.strategy or None
            limit = request.limit if request.limit > 0 else 50

            with self.pg.get_conn() as conn:
                if strategy_filter:
                    rows = conn.execute("""
                        SELECT symbol, direction, strength, strategy,
                               regime, time
                        FROM signal_log
                        WHERE strategy = %s
                        ORDER BY time DESC
                        LIMIT %s
                    """, (strategy_filter, limit)).fetchall()
                else:
                    rows = conn.execute("""
                        SELECT symbol, direction, strength, strategy,
                               regime, time
                        FROM signal_log
                        ORDER BY time DESC
                        LIMIT %s
                    """, (limit,)).fetchall()

            signals = []
            for row in rows:
                signals.append(signals_pb2.Signal(
                    symbol=str(row.get("symbol", "")),
                    direction=str(row.get("direction", "")),
                    strength=float(row.get("strength", 0)),
                    strategy=str(row.get("strategy", "")),
                    regime=str(row.get("regime", "")),
                    time=str(row.get("time", "")),
                ))

            return signals_pb2.SignalList(signals=signals)
        except Exception as e:
            logger.error(f"gRPC GetLatestSignals error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return signals_pb2.SignalList()


# ═══════════════════════════════════════
#  Server Lifecycle
# ═══════════════════════════════════════

def create_grpc_server(
    pg: PostgresStore,
    cache: RedisCache,
    orchestrator=None,
    port: int = 50051,
    max_workers: int = 10,
) -> grpc.Server:
    """gRPC 서버 생성 (start는 호출자 책임)"""

    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers)
    )

    # 서비스 등록
    regime_pb2_grpc.add_RegimeServiceServicer_to_server(
        RegimeServicer(pg, cache), server
    )
    portfolio_pb2_grpc.add_PortfolioServiceServicer_to_server(
        PortfolioServicer(pg, cache, orchestrator), server
    )
    signals_pb2_grpc.add_SignalServiceServicer_to_server(
        SignalServicer(pg), server
    )

    server.add_insecure_port(f"[::]:{port}")
    logger.info(f"gRPC server configured on port {port}")
    return server


def start_grpc_server(
    pg: PostgresStore,
    cache: RedisCache,
    orchestrator=None,
    port: int = 50051,
) -> grpc.Server:
    """gRPC 서버 생성 + 시작"""
    server = create_grpc_server(pg, cache, orchestrator, port)
    server.start()
    logger.info(f"gRPC server started on [::]:{port}")
    return server
