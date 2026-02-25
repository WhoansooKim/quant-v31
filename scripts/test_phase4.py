#!/usr/bin/env python3
"""
V3.1 Phase 4 — Backtest Verification Test
모든 Phase 4 모듈 + API + Dashboard 검증
"""
import sys
import json
import subprocess
import importlib
import traceback

PASS = 0
FAIL = 0
RESULTS = []


def test(name: str, fn):
    global PASS, FAIL
    try:
        ok, msg = fn()
        status = "PASS" if ok else "FAIL"
        if ok:
            PASS += 1
        else:
            FAIL += 1
        RESULTS.append((status, name, msg))
        print(f"  {'[PASS]' if ok else '[FAIL]'} {name}: {msg}")
    except Exception as e:
        FAIL += 1
        RESULTS.append(("FAIL", name, str(e)))
        print(f"  [FAIL] {name}: {e}")


# ═══════════════════════════════════════
# 1. Module Imports
# ═══════════════════════════════════════
print("\n=== 1. Module Imports ===")


def test_engine_import():
    from engine.backtest.engine import BacktestEngine, BacktestStore, compute_metrics, BacktestMetrics, BacktestResult
    return True, "All engine classes imported"

def test_walk_forward_import():
    from engine.backtest.walk_forward import WalkForwardValidator, WalkForwardFold
    return True, "WalkForwardValidator imported"

def test_dsr_import():
    from engine.backtest.dsr import DeflatedSharpeRatio, DSRResult
    return True, "DeflatedSharpeRatio imported"

def test_monte_carlo_import():
    from engine.backtest.monte_carlo import MonteCarloSimulator, MonteCarloResult
    return True, "MonteCarloSimulator imported"

def test_regime_stress_import():
    from engine.backtest.regime_stress import RegimeStressTester, StressTestResult, STRESS_SCENARIOS
    ok = len(STRESS_SCENARIOS) == 4
    return ok, f"{len(STRESS_SCENARIOS)} scenarios defined"

def test_granger_import():
    from engine.backtest.granger_test import GrangerCausalityTester, GrangerResult
    return True, "GrangerCausalityTester imported"


test("BacktestEngine import", test_engine_import)
test("WalkForward import", test_walk_forward_import)
test("DSR import", test_dsr_import)
test("MonteCarlo import", test_monte_carlo_import)
test("RegimeStress import", test_regime_stress_import)
test("Granger import", test_granger_import)


# ═══════════════════════════════════════
# 2. compute_metrics Unit Test
# ═══════════════════════════════════════
print("\n=== 2. compute_metrics Unit Test ===")

def test_compute_metrics():
    import numpy as np
    from engine.backtest.engine import compute_metrics
    # Synthetic daily returns: slight positive drift
    np.random.seed(42)
    rets = np.random.normal(0.0004, 0.01, 252)
    m = compute_metrics(rets)
    checks = [
        m.n_days == 252,
        m.sharpe != 0,
        m.cagr != 0,
        m.max_drawdown < 0,
        m.volatility > 0,
        0 < m.win_rate < 1,
    ]
    return all(checks), (
        f"Sharpe={m.sharpe:.2f} CAGR={m.cagr:.1%} "
        f"MDD={m.max_drawdown:.1%} Vol={m.volatility:.1%}"
    )

test("compute_metrics", test_compute_metrics)


# ═══════════════════════════════════════
# 3. DSR Unit Test
# ═══════════════════════════════════════
print("\n=== 3. DSR Unit Test ===")

def test_dsr_compute():
    import numpy as np
    from engine.backtest.dsr import DeflatedSharpeRatio
    np.random.seed(42)
    rets = np.random.normal(0.0005, 0.01, 252 * 3)
    dsr = DeflatedSharpeRatio.__new__(DeflatedSharpeRatio)
    dsr.threshold = 0.95
    result = dsr.compute(rets, n_trials=1)
    checks = [
        result.raw_sharpe != 0,
        0 <= result.dsr_score <= 1,
        result.dsr_pvalue >= 0,
        result.n_trials == 1,
    ]
    return all(checks), (
        f"raw_sharpe={result.raw_sharpe:.3f} "
        f"dsr={result.dsr_score:.3f} p={result.dsr_pvalue:.4f}"
    )

def test_dsr_multi_trial():
    import numpy as np
    from engine.backtest.dsr import DeflatedSharpeRatio
    np.random.seed(42)
    rets = np.random.normal(0.0005, 0.01, 252 * 3)
    dsr = DeflatedSharpeRatio.__new__(DeflatedSharpeRatio)
    dsr.threshold = 0.95
    r1 = dsr.compute(rets, n_trials=1)
    r10 = dsr.compute(rets, n_trials=10)
    # More trials → lower DSR (more penalized)
    return r10.dsr_score <= r1.dsr_score, (
        f"1-trial DSR={r1.dsr_score:.3f}, 10-trial DSR={r10.dsr_score:.3f}"
    )

test("DSR compute", test_dsr_compute)
test("DSR multi-trial penalty", test_dsr_multi_trial)


# ═══════════════════════════════════════
# 4. Monte Carlo Unit Test
# ═══════════════════════════════════════
print("\n=== 4. Monte Carlo Unit Test ===")

def test_monte_carlo_run():
    import numpy as np
    from engine.backtest.monte_carlo import MonteCarloSimulator
    np.random.seed(42)
    rets = np.random.normal(0.0004, 0.01, 252)
    mc = MonteCarloSimulator.__new__(MonteCarloSimulator)
    result = mc.run(rets, n_sims=100, n_days=126, block_size=21)
    checks = [
        result.n_simulations == 100,
        result.p5_cagr < result.median_cagr < result.p95_cagr,
        result.p5_sharpe < result.p95_sharpe,
        0 <= result.prob_negative <= 1,
        0 <= result.prob_mdd_over_20 <= 1,
    ]
    return all(checks), (
        f"CAGR: {result.p5_cagr:.1%}/{result.median_cagr:.1%}/{result.p95_cagr:.1%} "
        f"P(loss)={result.prob_negative:.0%}"
    )

test("Monte Carlo run", test_monte_carlo_run)


# ═══════════════════════════════════════
# 5. Stress Scenarios
# ═══════════════════════════════════════
print("\n=== 5. Stress Scenarios ===")

def test_stress_scenarios():
    from engine.backtest.regime_stress import STRESS_SCENARIOS
    required = {"covid_crash", "rate_hike", "recovery", "vix_spike"}
    keys = set(STRESS_SCENARIOS.keys())
    ok = required == keys
    return ok, f"Scenarios: {sorted(keys)}"

def test_stress_dates():
    from engine.backtest.regime_stress import STRESS_SCENARIOS
    from datetime import date
    for key, s in STRESS_SCENARIOS.items():
        assert isinstance(s["start"], date), f"{key} start not date"
        assert isinstance(s["end"], date), f"{key} end not date"
        assert s["start"] < s["end"], f"{key} start >= end"
    return True, "All scenario dates valid"

test("Stress scenario keys", test_stress_scenarios)
test("Stress scenario dates", test_stress_dates)


# ═══════════════════════════════════════
# 6. DB Tables
# ═══════════════════════════════════════
print("\n=== 6. DB Tables ===")

def test_db_tables():
    import psycopg
    conn = psycopg.connect(
        "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb",
        row_factory=psycopg.rows.dict_row,
    )
    tables = conn.execute("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
    """).fetchall()
    table_names = {t["tablename"] for t in tables}

    required = {
        "backtest_runs", "walk_forward_results", "monte_carlo_results",
        "regime_stress_results", "dsr_results", "granger_results",
        "go_stop_log",
    }
    missing = required - table_names
    conn.close()
    if missing:
        return False, f"Missing: {missing}"
    return True, f"All 7 Phase 4 tables exist"

def test_db_hypertables():
    import psycopg
    conn = psycopg.connect(
        "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb",
        row_factory=psycopg.rows.dict_row,
    )
    hypers = conn.execute("""
        SELECT hypertable_name FROM timescaledb_information.hypertables
        WHERE hypertable_schema = 'public'
    """).fetchall()
    ht_names = {h["hypertable_name"] for h in hypers}

    phase4_ht = {
        "walk_forward_results", "monte_carlo_results",
        "regime_stress_results", "dsr_results", "granger_results",
    }
    found = phase4_ht & ht_names
    conn.close()
    return len(found) == len(phase4_ht), f"Hypertables: {len(found)}/{len(phase4_ht)}"

test("Phase 4 DB tables", test_db_tables)
test("Phase 4 hypertables", test_db_hypertables)


# ═══════════════════════════════════════
# 7. Settings Fields
# ═══════════════════════════════════════
print("\n=== 7. Settings Fields ===")

def test_settings_phase4():
    from engine.config.settings import Settings
    s = Settings()
    fields = [
        ("backtest_years", s.backtest_years),
        ("walk_forward_train", s.walk_forward_train),
        ("walk_forward_test", s.walk_forward_test),
        ("slippage_bps", s.slippage_bps),
        ("monte_carlo_sims", s.monte_carlo_sims),
        ("dsr_threshold", s.dsr_threshold),
        ("go_sharpe_min", s.go_sharpe_min),
        ("go_mdd_max", s.go_mdd_max),
        ("go_paper_months", s.go_paper_months),
    ]
    for name, val in fields:
        if val is None:
            return False, f"{name} is None"
    return True, f"All 9 backtest settings present"

test("Phase 4 settings", test_settings_phase4)


# ═══════════════════════════════════════
# 8. BacktestStore DB Operations
# ═══════════════════════════════════════
print("\n=== 8. BacktestStore DB Operations ===")

def test_backtest_store():
    from engine.config.settings import Settings
    from engine.data.storage import PostgresStore
    from engine.backtest.engine import BacktestStore

    pg = PostgresStore(Settings().pg_dsn)
    store = BacktestStore(pg)

    # Create
    run_id = store.create_run("test_run", "unit_test", {"test": True})
    assert run_id > 0, f"Invalid run_id: {run_id}"

    # Complete
    store.complete_run(run_id, {"passed": True})

    # Verify
    with pg.get_conn() as conn:
        row = conn.execute(
            "SELECT status, summary FROM backtest_runs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    assert row["status"] == "completed"

    # Cleanup
    with pg.get_conn() as conn:
        conn.execute("DELETE FROM backtest_runs WHERE run_id = %s", (run_id,))
        conn.commit()

    return True, f"create→complete→verify (run_id={run_id})"

test("BacktestStore CRUD", test_backtest_store)


# ═══════════════════════════════════════
# 9. API Routes (import check)
# ═══════════════════════════════════════
print("\n=== 9. API Routes ===")

def test_api_backtest_routes():
    """Check that main.py has the backtest routes defined"""
    with open("/home/quant/quant-v31/engine/api/main.py") as f:
        content = f.read()

    routes = [
        "/backtest/runs",
        "/backtest/walk-forward",
        "/backtest/monte-carlo",
        "/backtest/stress-test",
        "/backtest/dsr",
        "/backtest/granger",
        "/backtest/go-stop",
    ]
    found = [r for r in routes if r in content]
    return len(found) == len(routes), f"{len(found)}/{len(routes)} routes defined"

def test_api_result_routes():
    """Check result query routes"""
    with open("/home/quant/quant-v31/engine/api/main.py") as f:
        content = f.read()

    routes = [
        "/backtest/walk-forward/results",
        "/backtest/monte-carlo/results",
        "/backtest/stress-test/results",
        "/backtest/dsr/results",
        "/backtest/granger/results",
    ]
    found = [r for r in routes if r in content]
    return len(found) == len(routes), f"{len(found)}/{len(routes)} result routes"

test("Backtest trigger routes", test_api_backtest_routes)
test("Backtest result routes", test_api_result_routes)


# ═══════════════════════════════════════
# 10. Dashboard Page
# ═══════════════════════════════════════
print("\n=== 10. Dashboard ===")

def test_backtest_page_exists():
    import os
    path = "/home/quant/quant-v31/dashboard/QuantDashboard/Components/Pages/Backtest.razor"
    ok = os.path.exists(path)
    if ok:
        with open(path) as f:
            content = f.read()
        has_sections = all(s in content for s in [
            "Walk-Forward", "Monte Carlo", "DSR",
            "Stress Test", "GO/STOP",
        ])
        return has_sections, "Backtest.razor has all 5 sections"
    return False, "Backtest.razor not found"

def test_nav_menu_backtest():
    with open("/home/quant/quant-v31/dashboard/QuantDashboard/Components/Layout/NavMenu.razor") as f:
        content = f.read()
    ok = 'href="backtest"' in content
    return ok, "NavMenu has Backtest link"

def test_dashboard_build():
    result = subprocess.run(
        ["dotnet", "build", "--no-restore"],
        cwd="/home/quant/quant-v31/dashboard/QuantDashboard",
        capture_output=True, text=True, timeout=60,
    )
    ok = result.returncode == 0
    return ok, "Build succeeded" if ok else f"Build failed: {result.stderr[-200:]}"

test("Backtest.razor page", test_backtest_page_exists)
test("NavMenu backtest link", test_nav_menu_backtest)
test("Dashboard build", test_dashboard_build)


# ═══════════════════════════════════════
# 11. Granger (statsmodels check)
# ═══════════════════════════════════════
print("\n=== 11. Granger Dependency ===")

def test_granger_available():
    from engine.backtest.granger_test import GRANGER_AVAILABLE
    return GRANGER_AVAILABLE, f"statsmodels available={GRANGER_AVAILABLE}"

test("Granger statsmodels", test_granger_available)


# ═══════════════════════════════════════
# 12. Block Bootstrap Sanity
# ═══════════════════════════════════════
print("\n=== 12. Block Bootstrap ===")

def test_block_bootstrap():
    import numpy as np
    from engine.backtest.monte_carlo import MonteCarloSimulator
    mc = MonteCarloSimulator.__new__(MonteCarloSimulator)
    rng = np.random.default_rng(42)
    rets = np.random.normal(0, 0.01, 252)
    bootstrapped = mc._block_bootstrap(rets, n_days=126, block_size=21, rng=rng)
    checks = [
        len(bootstrapped) == 126,
        not np.any(np.isnan(bootstrapped)),
        np.std(bootstrapped) > 0,
    ]
    return all(checks), f"126 days bootstrapped, std={np.std(bootstrapped):.4f}"

test("Block bootstrap", test_block_bootstrap)


# ═══════════════════════════════════════
# Summary
# ═══════════════════════════════════════
total = PASS + FAIL
print(f"\n{'='*60}")
print(f"Phase 4 Verification: {PASS}/{total} passed, {FAIL} failed")
print(f"{'='*60}")

if FAIL > 0:
    print("\nFailed tests:")
    for status, name, msg in RESULTS:
        if status == "FAIL":
            print(f"  - {name}: {msg}")

sys.exit(0 if FAIL == 0 else 1)
