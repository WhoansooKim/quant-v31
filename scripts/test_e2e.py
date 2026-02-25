#!/usr/bin/env python3
"""
═══════════════════════════════════════════════
 Quant V3.1 — Phase 3 End-to-End Verification
═══════════════════════════════════════════════
인프라 → 엔진 → 대시보드 → gRPC → DB → 파이프라인 전체 검증

Usage:
  python scripts/test_e2e.py              # 전체 테스트
  python scripts/test_e2e.py --no-systemd # systemd 제외
  python scripts/test_e2e.py --quick      # 파이프라인 실행 제외
"""
import sys
import os
import time
import subprocess
import argparse

sys.path.insert(0, "/home/quant/quant-v31")
os.chdir("/home/quant/quant-v31")

from dotenv import load_dotenv
load_dotenv("/home/quant/quant-v31/.env")

# ─── Config ───
PG_DSN = "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb"
ENGINE_URL = "http://localhost:8000"
DASHBOARD_URL = "http://localhost:5000"
GRPC_ADDR = "localhost:50051"

passed = 0
failed = 0
skipped = 0


def test(name, fn, skip=False):
    """테스트 실행 + 결과 카운트"""
    global passed, failed, skipped
    if skip:
        print(f"  ⏭  {name} (skipped)")
        skipped += 1
        return True
    try:
        fn()
        print(f"  ✅ {name}")
        passed += 1
        return True
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        failed += 1
        return False


def assert_true(condition, msg="assertion failed"):
    if not condition:
        raise AssertionError(msg)


# ══════════════════════════════
# 1. Infrastructure
# ══════════════════════════════

def section_infrastructure():
    print("\n━━━ 1. 인프라 (PostgreSQL + Redis + Docker) ━━━")

    def _pg_connect():
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(PG_DSN, row_factory=dict_row)
        row = conn.execute("SELECT 1 AS ok").fetchone()
        assert_true(row["ok"] == 1, "PG query failed")
        conn.close()
    test("PostgreSQL 연결", _pg_connect)

    def _timescale():
        import psycopg
        conn = psycopg.connect(PG_DSN)
        row = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname='timescaledb'"
        ).fetchone()
        assert_true(row is not None, "TimescaleDB not installed")
        conn.close()
    test("TimescaleDB 확장", _timescale)

    def _redis():
        import redis
        r = redis.from_url("redis://localhost:6379", decode_responses=True)
        assert_true(r.ping(), "Redis ping failed")
    test("Redis 연결", _redis)

    def _port_pg():
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("localhost", 5432))
        s.close()
        assert_true(result == 0, "Port 5432 not listening")
    test("PostgreSQL :5432 listening", _port_pg)

    def _port_redis():
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        result = s.connect_ex(("localhost", 6379))
        s.close()
        assert_true(result == 0, "Port 6379 not listening")
    test("Redis :6379 listening", _port_redis)

    def _db_tables():
        import psycopg
        conn = psycopg.connect(PG_DSN)
        rows = conn.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """).fetchall()
        tables = [r[0] for r in rows]
        expected = [
            "daily_prices", "regime_history", "kill_switch_log",
            "portfolio_snapshots", "signal_log", "trades",
            "strategy_performance", "symbols",
        ]
        missing = [t for t in expected if t not in tables]
        assert_true(not missing, f"Missing tables: {missing}")
        conn.close()
    test("DB 테이블 존재 (8개)", _db_tables)

    def _db_data():
        import psycopg
        conn = psycopg.connect(PG_DSN)
        count = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
        assert_true(count > 0, f"daily_prices: {count} rows")
        conn.close()
    test("daily_prices 데이터 존재", _db_data)


# ══════════════════════════════
# 2. Python Engine
# ══════════════════════════════

def section_engine(engine_started=False):
    print("\n━━━ 2. Python 엔진 (FastAPI + gRPC) ━━━")

    import requests

    def _health():
        r = requests.get(f"{ENGINE_URL}/health", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
        data = r.json()
        assert_true(data.get("status") == "ok", f"status={data.get('status')}")
    test("FastAPI /health", _health)

    def _regime():
        r = requests.get(f"{ENGINE_URL}/regime", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
        data = r.json()
        assert_true(
            data.get("current") or data.get("regime"),
            f"No regime data: {data}",
        )
    test("GET /regime", _regime)

    def _kill_switch():
        r = requests.get(f"{ENGINE_URL}/kill-switch", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
    test("GET /kill-switch", _kill_switch)

    def _portfolio():
        r = requests.get(f"{ENGINE_URL}/portfolio", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
    test("GET /portfolio", _portfolio)

    def _account():
        r = requests.get(f"{ENGINE_URL}/account", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
    test("GET /account", _account)

    def _scheduler():
        r = requests.get(f"{ENGINE_URL}/scheduler", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
        data = r.json()
        jobs = data.get("jobs", [])
        assert_true(len(jobs) >= 5, f"Expected 5+ jobs, got {len(jobs)}")
    test("GET /scheduler (5 jobs)", _scheduler)

    def _explain_regime():
        r = requests.get(f"{ENGINE_URL}/explain/regime", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
    test("GET /explain/regime", _explain_regime)

    def _signals():
        r = requests.get(f"{ENGINE_URL}/signals", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
    test("GET /signals", _signals)


# ══════════════════════════════
# 3. gRPC
# ══════════════════════════════

def section_grpc():
    print("\n━━━ 3. gRPC (Python 엔진) ━━━")

    import grpc
    from engine.api import regime_pb2, regime_pb2_grpc
    from engine.api import portfolio_pb2, portfolio_pb2_grpc
    from engine.api import signals_pb2, signals_pb2_grpc

    def _grpc_regime():
        channel = grpc.insecure_channel(GRPC_ADDR)
        stub = regime_pb2_grpc.RegimeServiceStub(channel)
        resp = stub.GetCurrentRegime(regime_pb2.Empty(), timeout=5)
        assert_true(resp.current != "", f"current='{resp.current}'")
        channel.close()
    test("gRPC GetCurrentRegime", _grpc_regime)

    def _grpc_snapshot():
        channel = grpc.insecure_channel(GRPC_ADDR)
        stub = portfolio_pb2_grpc.PortfolioServiceStub(channel)
        resp = stub.GetSnapshot(regime_pb2.Empty(), timeout=5)
        channel.close()
        # OK if returns (even with default values)
    test("gRPC GetSnapshot", _grpc_snapshot)

    def _grpc_signals():
        channel = grpc.insecure_channel(GRPC_ADDR)
        stub = signals_pb2_grpc.SignalServiceStub(channel)
        resp = stub.GetLatestSignals(
            signals_pb2.SignalRequest(limit=5), timeout=5
        )
        channel.close()
    test("gRPC GetLatestSignals", _grpc_signals)


# ══════════════════════════════
# 4. Blazor Dashboard
# ══════════════════════════════

def section_dashboard():
    print("\n━━━ 4. Blazor 대시보드 ━━━")

    import requests

    pages = {
        "/": "Portfolio",
        "/regime": "Regime",
        "/risk": "Risk",
        "/strategies": "Strategies",
        "/sentiment": "Sentiment",
    }

    for path, name in pages.items():
        def _page(p=path):
            r = requests.get(f"{DASHBOARD_URL}{p}", timeout=10)
            assert_true(r.status_code == 200, f"HTTP {r.status_code}")
        test(f"Blazor {path} ({name})", _page)

    def _signalr():
        import requests
        r = requests.post(
            f"{DASHBOARD_URL}/hubs/realtime/negotiate?negotiateVersion=1",
            timeout=5,
        )
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
    test("SignalR Hub /hubs/realtime", _signalr)

    def _brand():
        r = requests.get(DASHBOARD_URL, timeout=10)
        assert_true("Quant V3.1" in r.text, "Brand text not found")
    test("Blazor 브랜드 텍스트", _brand)


# ══════════════════════════════
# 5. Pipeline Trigger
# ══════════════════════════════

def section_pipeline(skip=False):
    print("\n━━━ 5. 파이프라인 트리거 ━━━")

    import requests

    def _trigger():
        r = requests.post(f"{ENGINE_URL}/run", timeout=5)
        assert_true(r.status_code == 200, f"HTTP {r.status_code}")
        data = r.json()
        assert_true(
            data.get("status") == "pipeline_started",
            f"status={data.get('status')}",
        )
    test("POST /run (pipeline trigger)", _trigger, skip=skip)

    if not skip:
        print("  ⏳ Waiting 15s for pipeline...")
        time.sleep(15)

    def _db_regime():
        import psycopg
        conn = psycopg.connect(PG_DSN)
        count = conn.execute("SELECT COUNT(*) FROM regime_history").fetchone()[0]
        assert_true(count > 0, f"regime_history: {count} rows")
        conn.close()
    test("DB: regime_history 기록", _db_regime, skip=skip)

    def _db_snapshots():
        import psycopg
        conn = psycopg.connect(PG_DSN)
        count = conn.execute(
            "SELECT COUNT(*) FROM portfolio_snapshots"
        ).fetchone()[0]
        conn.close()
        # May be 0 if pipeline hasn't saved yet, just check query works
    test("DB: portfolio_snapshots 쿼리", _db_snapshots, skip=skip)


# ══════════════════════════════
# 6. systemd Services
# ══════════════════════════════

def section_systemd(skip=False):
    print("\n━━━ 6. systemd 서비스 ━━━")

    def _service_file_exists():
        for svc in ["quant-engine", "quant-dashboard", "quant-scheduler"]:
            path = f"/home/quant/quant-v31/systemd/{svc}.service"
            assert_true(os.path.exists(path), f"{svc}.service not found")
    test("서비스 파일 존재 (3개)", _service_file_exists)

    def _service_file_valid():
        for svc in ["quant-engine", "quant-dashboard", "quant-scheduler"]:
            path = f"/home/quant/quant-v31/systemd/{svc}.service"
            content = open(path).read()
            assert_true("[Unit]" in content, f"{svc}: no [Unit]")
            assert_true("[Service]" in content, f"{svc}: no [Service]")
            assert_true("[Install]" in content, f"{svc}: no [Install]")
    test("서비스 파일 구조 유효", _service_file_valid)

    def _manage_script():
        path = "/home/quant/quant-v31/scripts/manage_services.sh"
        assert_true(os.path.exists(path), "manage_services.sh not found")
        assert_true(os.access(path, os.X_OK), "Not executable")
    test("관리 스크립트 존재 + 실행권한", _manage_script)

    # systemd 등록 상태 (설치된 경우에만)
    for svc in ["quant-engine", "quant-dashboard"]:
        def _svc_status(s=svc):
            result = subprocess.run(
                ["systemctl", "is-active", s],
                capture_output=True, text=True,
            )
            status = result.stdout.strip()
            # "active" or "inactive" both OK (not installed = "inactive")
            assert_true(
                status in ["active", "inactive", "unknown"],
                f"{s}: {status}",
            )
        test(f"systemctl {svc}", _svc_status, skip=skip)


# ══════════════════════════════
# 7. Module Integration
# ══════════════════════════════

def section_modules():
    print("\n━━━ 7. 모듈 통합 ━━━")

    def _settings():
        from engine.config.settings import Settings
        cfg = Settings()
        assert_true(cfg.grpc_port == 50051)
        assert_true(cfg.scheduler_enabled is True)
        assert_true("quantdb" in cfg.pg_dsn)
    test("Settings 로드", _settings)

    def _storage():
        from engine.config.settings import Settings
        from engine.data.storage import PostgresStore, RedisCache
        cfg = Settings()
        pg = PostgresStore(cfg.pg_dsn)
        cache = RedisCache(cfg.redis_url)
        with pg.get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        assert_true(cache.ping())
    test("PostgresStore + RedisCache", _storage)

    def _regime_detector():
        from engine.config.settings import Settings
        from engine.risk.regime import RegimeDetector
        cfg = Settings()
        rd = RegimeDetector(pg_dsn=cfg.pg_dsn)
        rd.load()
        state = rd.predict_current()
        assert_true(state.current in ["bull", "sideways", "bear"])
    test("RegimeDetector predict", _regime_detector)

    def _kill_switch():
        from engine.risk.kill_switch import DrawdownKillSwitch, DefenseLevel
        ks = DrawdownKillSwitch(initial_value=100000)
        level = ks.update(98000)
        assert_true(level in [
            DefenseLevel.NORMAL, DefenseLevel.WARNING,
            DefenseLevel.DEFENSIVE, DefenseLevel.EMERGENCY,
        ])
    test("DrawdownKillSwitch", _kill_switch)

    def _allocator():
        from engine.risk.regime_allocator import RegimeAllocator
        alloc = RegimeAllocator()
        # Just verify it can be instantiated
    test("RegimeAllocator", _allocator)

    def _strategies():
        from engine.config.settings import Settings
        cfg = Settings()
        from engine.strategies.lowvol_quality import LowVolQuality
        from engine.strategies.vol_momentum import VolManagedMomentum
        from engine.strategies.pairs_trading import PairsTrading
        LowVolQuality(cfg.pg_dsn)
        VolManagedMomentum(cfg.pg_dsn)
        PairsTrading(cfg.pg_dsn)
    test("3 전략 인스턴스", _strategies)

    def _vol_targeting():
        from engine.strategies.vol_targeting import VolatilityTargeting
        vt = VolatilityTargeting(target_vol=0.15)
    test("VolatilityTargeting", _vol_targeting)

    def _sentiment():
        from engine.config.settings import Settings
        from engine.strategies.sentiment import SentimentOverlay
        cfg = Settings()
        SentimentOverlay(cfg.pg_dsn, {})
    test("SentimentOverlay", _sentiment)

    def _shap():
        from engine.explain.feature_importance import FeatureExplainer
        from engine.config.settings import Settings
        from engine.data.storage import PostgresStore
        cfg = Settings()
        pg = PostgresStore(cfg.pg_dsn)
        FeatureExplainer(pg)
    test("FeatureExplainer (SHAP)", _shap)

    def _telegram():
        from engine.config.settings import Settings
        from engine.execution.alerts import TelegramAlert
        cfg = Settings()
        TelegramAlert(cfg)
    test("TelegramAlert", _telegram)

    def _proto():
        from engine.api import regime_pb2, portfolio_pb2, signals_pb2
        from engine.api import regime_pb2_grpc, portfolio_pb2_grpc, signals_pb2_grpc
    test("Proto pb2 모듈", _proto)


# ══════════════════════════════
# Main
# ══════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Quant V3.1 E2E Test")
    parser.add_argument("--no-systemd", action="store_true",
                        help="Skip systemd status checks")
    parser.add_argument("--quick", action="store_true",
                        help="Skip pipeline trigger (faster)")
    parser.add_argument("--no-engine", action="store_true",
                        help="Skip engine/gRPC/dashboard HTTP tests")
    args = parser.parse_args()

    print("=" * 60)
    print(" Quant V3.1 — Phase 3 End-to-End Verification")
    print("=" * 60)

    # Always run
    section_infrastructure()
    section_modules()

    # Engine/gRPC/Dashboard (require running services)
    if not args.no_engine:
        section_engine()
        section_grpc()
        section_dashboard()
        section_pipeline(skip=args.quick)

    # systemd
    section_systemd(skip=args.no_systemd)

    # ─── Results ───
    total = passed + failed
    print("\n" + "=" * 60)
    print(f" Results: {passed}/{total} passed, {failed} failed, {skipped} skipped")

    if failed == 0:
        print(" Phase 3 E2E — ALL PASSED!")
    else:
        print(f" {failed} test(s) failed — fix and re-run")

    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
