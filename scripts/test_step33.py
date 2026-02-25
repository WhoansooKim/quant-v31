"""
V3.1 Step 3.3 Integration Test
gRPC + APScheduler + SHAP + Blazor gRPC Client 검증
"""
import sys
import os
import time

# 프로젝트 루트를 path에 추가
sys.path.insert(0, "/home/quant/quant-v31")
os.chdir("/home/quant/quant-v31")

from dotenv import load_dotenv
load_dotenv("/home/quant/quant-v31/.env")


def test_settings():
    """1. Settings에 gRPC/Scheduler 필드 존재 확인"""
    print("\n[1] Settings gRPC/Scheduler 필드...")
    from engine.config.settings import Settings
    cfg = Settings()
    assert cfg.grpc_port == 50051, f"grpc_port={cfg.grpc_port}"
    assert cfg.grpc_max_workers == 10
    assert cfg.scheduler_enabled is True
    assert cfg.scheduler_timezone == "US/Eastern"
    assert cfg.pipeline_hour == 15
    assert cfg.pipeline_minute == 30
    print(f"  ✅ grpc_port={cfg.grpc_port}, scheduler_enabled={cfg.scheduler_enabled}")


def test_proto_imports():
    """2. Proto 생성 파일 import 확인"""
    print("\n[2] Proto pb2 imports...")
    from engine.api import regime_pb2, regime_pb2_grpc
    from engine.api import portfolio_pb2, portfolio_pb2_grpc
    from engine.api import signals_pb2, signals_pb2_grpc

    # 메시지 생성 테스트
    r = regime_pb2.RegimeResponse(
        current="bull", bull_prob=0.7, sideways_prob=0.2,
        bear_prob=0.1, confidence=0.7, detected_at="2025-02-25",
    )
    assert r.current == "bull"
    assert r.bull_prob == 0.7

    s = portfolio_pb2.SnapshotResponse(
        total_value=100000, regime="bull", kill_level="NORMAL",
    )
    assert s.total_value == 100000

    sig = signals_pb2.Signal(
        symbol="AAPL", direction="long", strength=0.85, strategy="lowvol_quality",
    )
    assert sig.symbol == "AAPL"
    print("  ✅ All proto messages created OK")


def test_grpc_server_creation():
    """3. gRPC 서버 생성 + 포트 바인딩"""
    print("\n[3] gRPC server creation...")
    from engine.config.settings import Settings
    from engine.data.storage import PostgresStore, RedisCache
    from engine.api.grpc_server import create_grpc_server

    cfg = Settings()
    pg = PostgresStore(cfg.pg_dsn)
    cache = RedisCache(cfg.redis_url)

    server = create_grpc_server(pg, cache, port=50052)
    server.start()
    print(f"  gRPC server started on port 50052")
    time.sleep(1)
    server.stop(grace=1).wait()
    print("  ✅ gRPC server start/stop OK")


def test_grpc_client_call():
    """4. gRPC 클라이언트 → 서버 호출"""
    print("\n[4] gRPC client call...")
    import grpc
    from engine.config.settings import Settings
    from engine.data.storage import PostgresStore, RedisCache
    from engine.api.grpc_server import start_grpc_server
    from engine.api import regime_pb2, regime_pb2_grpc
    from engine.api import portfolio_pb2, portfolio_pb2_grpc
    from engine.api import signals_pb2, signals_pb2_grpc

    cfg = Settings()
    pg = PostgresStore(cfg.pg_dsn)
    cache = RedisCache(cfg.redis_url)

    # 서버 시작
    server = start_grpc_server(pg, cache, port=50053)
    time.sleep(1)

    try:
        # 클라이언트 접속
        channel = grpc.insecure_channel("localhost:50053")
        regime_stub = regime_pb2_grpc.RegimeServiceStub(channel)
        portfolio_stub = portfolio_pb2_grpc.PortfolioServiceStub(channel)
        signal_stub = signals_pb2_grpc.SignalServiceStub(channel)

        # GetCurrentRegime
        regime = regime_stub.GetCurrentRegime(regime_pb2.Empty())
        print(f"  Regime: {regime.current} "
              f"(bull={regime.bull_prob:.2f}, "
              f"sideways={regime.sideways_prob:.2f}, "
              f"bear={regime.bear_prob:.2f})")

        # GetSnapshot
        snap = portfolio_stub.GetSnapshot(regime_pb2.Empty())
        print(f"  Snapshot: ${snap.total_value:,.0f} "
              f"regime={snap.regime} kill={snap.kill_level}")

        # GetLatestSignals
        signals = signal_stub.GetLatestSignals(
            signals_pb2.SignalRequest(limit=5))
        print(f"  Signals: {len(signals.signals)} returned")

        channel.close()
        print("  ✅ All gRPC calls OK")
    finally:
        server.stop(grace=1).wait()


def test_scheduler_setup():
    """5. APScheduler 설정 검증"""
    print("\n[5] APScheduler setup...")
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz

    # 스케줄러 직접 생성 (orchestrator 없이 구조만 검증)
    et = pytz.timezone("US/Eastern")
    scheduler = AsyncIOScheduler(timezone=et)

    async def dummy(): pass

    scheduler.add_job(
        dummy,
        CronTrigger(hour=15, minute=30, day_of_week="mon-fri", timezone=et),
        id="daily_pipeline", name="daily pipeline",
        misfire_grace_time=300,
    )
    scheduler.add_job(
        dummy,
        CronTrigger(day_of_week="sat", day="1-7", hour=4, timezone=et),
        id="hmm_retrain", name="hmm retrain",
    )
    scheduler.add_job(
        dummy,
        CronTrigger(hour=17, minute=0, day_of_week="mon-fri", timezone=et),
        id="data_collection", name="data collection",
    )
    scheduler.add_job(
        dummy,
        CronTrigger(hour="9-16", minute=0, day_of_week="mon-fri", timezone=et),
        id="sentiment_scan", name="sentiment scan",
    )
    scheduler.add_job(
        dummy,
        CronTrigger(day_of_week="sun", hour=2, timezone=et),
        id="mv_refresh", name="mv refresh",
    )

    jobs = scheduler.get_jobs()
    assert len(jobs) == 5, f"Expected 5 jobs, got {len(jobs)}"

    for job in jobs:
        nrt = getattr(job, "next_run_time", None)
        print(f"  Job: {job.id:20s} name={job.name}")

    print(f"  ✅ {len(jobs)} scheduler jobs configured")


def test_shap_module():
    """6. SHAP Explainer 모듈 검증"""
    print("\n[6] SHAP Feature Explainer...")
    from engine.config.settings import Settings
    from engine.data.storage import PostgresStore
    from engine.explain.feature_importance import FeatureExplainer

    cfg = Settings()
    pg = PostgresStore(cfg.pg_dsn)
    explainer = FeatureExplainer(pg)

    # regime_feature_importance (DB 쿼리)
    result = explainer.regime_feature_importance()
    if "error" in result:
        print(f"  regime_feature_importance: {result.get('error', 'no data')}")
    else:
        regimes = result.get("regimes", [])
        print(f"  regime_feature_importance: {len(regimes)} regimes")
        for r in regimes:
            print(f"    {r['regime']}: vol={r['avg_volatility']:.4f} "
                  f"mom={r['avg_momentum']:.4f}")

    # strategy_feature_summary
    summary = explainer.strategy_feature_summary("lowvol_quality")
    s_list = summary.get("summary", [])
    print(f"  strategy_feature_summary(lowvol_quality): {len(s_list)} groups")

    # SHAP 라이브러리 확인
    try:
        import shap
        print(f"  ✅ SHAP v{shap.__version__} available")
    except ImportError:
        print("  ⚠️  SHAP not installed (explain_signal limited)")


def test_telegram_alerts():
    """7. Telegram Alert 모듈 존재 확인"""
    print("\n[7] Telegram Alerts...")
    from engine.config.settings import Settings
    from engine.execution.alerts import TelegramAlert

    cfg = Settings()
    telegram = TelegramAlert(cfg)
    has_token = bool(cfg.telegram_bot_token)
    print(f"  Token configured: {has_token}")
    print(f"  Chat ID configured: {bool(cfg.telegram_chat_id)}")
    print(f"  ✅ TelegramAlert module OK")


def test_fastapi_new_routes():
    """8. FastAPI 새 라우트 존재 확인"""
    print("\n[8] FastAPI new routes...")
    from engine.api.main import app

    routes = [r.path for r in app.routes if hasattr(r, "path")]
    expected = ["/health", "/run", "/regime", "/kill-switch",
                "/portfolio", "/account", "/scheduler",
                "/explain/regime", "/explain/strategy/{strategy}",
                "/signals"]

    for ep in expected:
        found = ep in routes
        status = "✅" if found else "❌"
        print(f"  {status} {ep}")

    missing = [ep for ep in expected if ep not in routes]
    assert not missing, f"Missing routes: {missing}"
    print(f"  ✅ All {len(expected)} routes registered")


# ═══════════════════════════════════════
# Run all tests
# ═══════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print(" Quant V3.1 — Step 3.3 Integration Test")
    print("=" * 60)

    tests = [
        test_settings,
        test_proto_imports,
        test_grpc_server_creation,
        test_grpc_client_call,
        test_scheduler_setup,
        test_shap_module,
        test_telegram_alerts,
        test_fastapi_new_routes,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  ❌ FAILED: {e}")

    print("\n" + "=" * 60)
    print(f" Results: {passed}/{passed + failed} passed")
    if failed:
        print(f" ⚠️  {failed} test(s) failed")
    else:
        print(" 🎉 All tests passed!")
    print("=" * 60)
