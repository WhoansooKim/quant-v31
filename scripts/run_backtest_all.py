#!/usr/bin/env python3
"""
V3.1 — 전체 백테스트 실행 스크립트
Walk-Forward, Monte Carlo, Stress Test, DSR, Granger 순차 실행

Usage:
    PYTHONPATH=/home/quant/quant-v31 python scripts/run_backtest_all.py
"""
import json
import logging
import sys
import time
from datetime import date, timedelta
from dataclasses import asdict

import numpy as np

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backtest_runner")

from engine.config.settings import Settings
from engine.backtest.engine import BacktestEngine, compute_metrics

config = Settings()

# ══════════════════════════════════════════════════════════
# 0. 기본 백테스트 (15년 전체 기간) — Monte Carlo, DSR 입력용
# ══════════════════════════════════════════════════════════
def run_base_backtest():
    logger.info("=" * 60)
    logger.info("STEP 0: Base Backtest (full period)")
    logger.info("=" * 60)

    engine = BacktestEngine(config)
    start = date(2011, 3, 1)
    end = date(2026, 2, 24)

    t0 = time.time()
    result = engine.run(start, end)
    elapsed = time.time() - t0

    m = result.metrics
    logger.info(f"  Elapsed: {elapsed:.1f}s")
    logger.info(f"  Period: {start} ~ {end} ({m.n_days} days)")
    logger.info(f"  Total Return: {m.total_return:.1%}")
    logger.info(f"  CAGR:         {m.cagr:.1%}")
    logger.info(f"  Sharpe:       {m.sharpe:.3f}")
    logger.info(f"  Sortino:      {m.sortino:.3f}")
    logger.info(f"  MDD:          {m.max_drawdown:.1%}")
    logger.info(f"  Calmar:       {m.calmar:.3f}")
    logger.info(f"  Volatility:   {m.volatility:.1%}")
    logger.info(f"  Win Rate:     {m.win_rate:.1%}")
    logger.info(f"  Kill Events:  {m.kill_events}")
    logger.info(f"  Max Kill:     {m.max_kill_level}")
    logger.info(f"  Bull Ret:     {m.bull_return:.1%}")
    logger.info(f"  Sideways Ret: {m.sideways_return:.1%}")
    logger.info(f"  Bear Ret:     {m.bear_return:.1%}")

    return result


# ══════════════════════════════════════════════════════════
# 1. Walk-Forward Validation
# ══════════════════════════════════════════════════════════
def run_walk_forward():
    logger.info("=" * 60)
    logger.info("STEP 1: Walk-Forward Validation")
    logger.info("=" * 60)

    from engine.backtest.walk_forward import WalkForwardValidator
    validator = WalkForwardValidator(config)

    t0 = time.time()
    result = validator.run(
        start_date=date(2011, 3, 1),
        end_date=date(2026, 2, 24),
    )
    elapsed = time.time() - t0

    logger.info(f"  Elapsed: {elapsed:.1f}s")
    logger.info(f"  Folds: {result.get('n_folds', 0)}")
    logger.info(f"  OOS Sharpe (avg): {result.get('oos_sharpe_avg', 0):.3f}")
    logger.info(f"  OOS Sharpe (std): {result.get('oos_sharpe_std', 0):.3f}")
    logger.info(f"  OOS CAGR (avg):   {result.get('oos_cagr_avg', 0):.1%}")
    logger.info(f"  OOS MDD (avg):    {result.get('oos_mdd_avg', 0):.1%}")
    logger.info(f"  OOS MDD (worst):  {result.get('oos_mdd_worst', 0):.1%}")
    logger.info(f"  Degradation:      {result.get('degradation_ratio', 0):.3f}")
    logger.info(f"  PASSED:           {result.get('passed', False)}")

    # 폴드별 결과
    folds = result.get("folds", [])
    for f in folds:
        logger.info(
            f"    Fold {f['fold_num']}: IS_Sharpe={f['is_sharpe']:.2f} "
            f"OOS_Sharpe={f['oos_sharpe']:.2f} "
            f"OOS_MDD={f['oos_mdd']:.1%} "
            f"Bull={f['regime_bull_pct']:.0%} Side={f['regime_sideways_pct']:.0%} Bear={f['regime_bear_pct']:.0%}"
        )

    return result


# ══════════════════════════════════════════════════════════
# 2. Monte Carlo Simulation
# ══════════════════════════════════════════════════════════
def run_monte_carlo(daily_returns: np.ndarray):
    logger.info("=" * 60)
    logger.info("STEP 2: Monte Carlo Simulation")
    logger.info("=" * 60)

    from engine.backtest.monte_carlo import MonteCarloSimulator
    mc = MonteCarloSimulator(config)

    t0 = time.time()
    # VM에서는 1000 sims으로 먼저 테스트, 결과 확인 후 10000 가능
    result = mc.run_and_save(daily_returns, n_sims=10000, n_days=252)
    elapsed = time.time() - t0

    logger.info(f"  Elapsed: {elapsed:.1f}s")
    logger.info(f"  Simulations: {result.n_simulations}")
    logger.info(f"  CAGR:   p5={result.p5_cagr:.1%} | median={result.median_cagr:.1%} | p95={result.p95_cagr:.1%}")
    logger.info(f"  Sharpe: p5={result.p5_sharpe:.2f} | median={result.median_sharpe:.2f} | p95={result.p95_sharpe:.2f}")
    logger.info(f"  MDD:    p5={result.p5_mdd:.1%} | median={result.median_mdd:.1%} | p95={result.p95_mdd:.1%}")
    logger.info(f"  P(loss):      {result.prob_negative:.1%}")
    logger.info(f"  P(MDD>20%):   {result.prob_mdd_over_20:.1%}")

    return result


# ══════════════════════════════════════════════════════════
# 3. Regime Stress Test
# ══════════════════════════════════════════════════════════
def run_stress_test():
    logger.info("=" * 60)
    logger.info("STEP 3: Regime Stress Test (4 scenarios)")
    logger.info("=" * 60)

    from engine.backtest.regime_stress import RegimeStressTester
    tester = RegimeStressTester(config)

    t0 = time.time()
    result = tester.run_all()
    elapsed = time.time() - t0

    logger.info(f"  Elapsed: {elapsed:.1f}s")
    logger.info(f"  Tested: {result.get('scenarios_tested', 0)}")
    logger.info(f"  Passed: {result.get('scenarios_passed', 0)}")
    logger.info(f"  Avg Accuracy: {result.get('avg_regime_accuracy', 0):.1%}")
    logger.info(f"  Avg FPR:      {result.get('avg_false_positive_rate', 0):.1%}")
    logger.info(f"  FPR < 15%:    {result.get('fpr_below_15pct', False)}")

    for r in result.get("results", []):
        logger.info(
            f"    {r['scenario']:15s}: ret={r['total_return']:+.1%} "
            f"mdd={r['max_drawdown']:.1%} acc={r['regime_accuracy']:.0%} "
            f"fpr={r['false_positive_rate']:.0%} kill={r['kill_level_reached']} "
            f"lag={r['detection_lag_days']}d "
            f"{'PASS' if r['passed'] else 'FAIL'}"
        )

    return result


# ══════════════════════════════════════════════════════════
# 4. Deflated Sharpe Ratio (DSR)
# ══════════════════════════════════════════════════════════
def run_dsr(daily_returns: np.ndarray):
    logger.info("=" * 60)
    logger.info("STEP 4: Deflated Sharpe Ratio")
    logger.info("=" * 60)

    from engine.backtest.dsr import DeflatedSharpeRatio
    dsr = DeflatedSharpeRatio(config)

    t0 = time.time()
    # n_trials=5 (5개 전략 변형 테스트)
    result = dsr.run_and_save(daily_returns, n_trials=5)
    elapsed = time.time() - t0

    logger.info(f"  Elapsed: {elapsed:.1f}s")
    logger.info(f"  Raw Sharpe:   {result.raw_sharpe:.3f}")
    logger.info(f"  DSR Score:    {result.dsr_score:.3f} ({result.dsr_score:.1%})")
    logger.info(f"  DSR p-value:  {result.dsr_pvalue:.4f}")
    logger.info(f"  t-stat:       {result.t_stat:.3f}")
    logger.info(f"  n_trials:     {result.n_trials}")
    logger.info(f"  Skewness:     {result.skewness:.3f}")
    logger.info(f"  Kurtosis:     {result.kurtosis:.3f}")
    logger.info(f"  PASSED:       {result.passed}")

    return result


# ══════════════════════════════════════════════════════════
# 5. Granger Causality Test
# ══════════════════════════════════════════════════════════
def run_granger():
    logger.info("=" * 60)
    logger.info("STEP 5: Granger Causality Test")
    logger.info("=" * 60)

    from engine.backtest.granger_test import GrangerCausalityTester
    tester = GrangerCausalityTester(config)

    t0 = time.time()
    result = tester.run(max_lag=5, lookback_days=365)
    elapsed = time.time() - t0

    if "error" in result:
        logger.warning(f"  Granger SKIPPED: {result['error']}")
        logger.info("  (sentiment_scores 데이터가 없어 Granger 테스트 생략)")
        return result

    logger.info(f"  Elapsed: {elapsed:.1f}s")
    logger.info(f"  Symbols Tested: {result.get('symbols_tested', 0)}")
    logger.info(f"  Significant:    {result.get('significant_count', 0)}")
    logger.info(f"  Significant %:  {result.get('significant_pct', 0):.1%}")
    logger.info(f"  PASSED:         {result.get('passed', False)}")

    return result


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════
def main():
    logger.info("╔═══════════════════════════════════════════════════╗")
    logger.info("║  Quant V3.1 — Full Backtest Verification Suite   ║")
    logger.info("╚═══════════════════════════════════════════════════╝")

    results = {}
    total_start = time.time()

    # 0. Base Backtest
    base = run_base_backtest()
    results["base"] = {
        "sharpe": base.metrics.sharpe,
        "cagr": base.metrics.cagr,
        "mdd": base.metrics.max_drawdown,
        "calmar": base.metrics.calmar,
    }

    # 1. Walk-Forward
    wf = run_walk_forward()
    results["walk_forward"] = {
        "oos_sharpe_avg": wf.get("oos_sharpe_avg", 0),
        "degradation_ratio": wf.get("degradation_ratio", 0),
        "passed": wf.get("passed", False),
    }

    # 2. Monte Carlo
    mc = run_monte_carlo(base.daily_returns)
    results["monte_carlo"] = {
        "median_sharpe": mc.median_sharpe,
        "median_cagr": mc.median_cagr,
        "prob_negative": mc.prob_negative,
        "prob_mdd_over_20": mc.prob_mdd_over_20,
    }

    # 3. Stress Test
    st = run_stress_test()
    results["stress_test"] = {
        "scenarios_passed": st.get("scenarios_passed", 0),
        "avg_fpr": st.get("avg_false_positive_rate", 1),
        "all_passed": st.get("all_passed", False),
        "fpr_below_15pct": st.get("fpr_below_15pct", False),
    }

    # 4. DSR
    dsr = run_dsr(base.daily_returns)
    results["dsr"] = {
        "raw_sharpe": dsr.raw_sharpe,
        "dsr_score": dsr.dsr_score,
        "passed": dsr.passed,
    }

    # 5. Granger
    gr = run_granger()
    results["granger"] = {
        "skipped": "error" in gr,
        "passed": gr.get("passed", False),
    }

    # ═══════ 최종 요약 ═══════
    total_elapsed = time.time() - total_start
    logger.info("")
    logger.info("╔═══════════════════════════════════════════════════╗")
    logger.info("║            BACKTEST RESULTS SUMMARY               ║")
    logger.info("╚═══════════════════════════════════════════════════╝")
    logger.info(f"  Total Time: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")
    logger.info("")
    logger.info("  ── Base Backtest ──")
    logger.info(f"  Sharpe:  {results['base']['sharpe']:.3f}")
    logger.info(f"  CAGR:    {results['base']['cagr']:.1%}")
    logger.info(f"  MDD:     {results['base']['mdd']:.1%}")
    logger.info(f"  Calmar:  {results['base']['calmar']:.3f}")
    logger.info("")
    logger.info("  ── GO/STOP Criteria ──")
    logger.info(f"  Walk-Forward OOS Sharpe: {results['walk_forward']['oos_sharpe_avg']:.3f} "
                f"(need >1.1) → {'GO' if results['walk_forward']['passed'] else 'STOP'}")
    logger.info(f"  DSR Score:               {results['dsr']['dsr_score']:.1%} "
                f"(need >95%) → {'GO' if results['dsr']['passed'] else 'STOP'}")
    logger.info(f"  Stress FPR:              {results['stress_test']['avg_fpr']:.1%} "
                f"(need <15%) → {'GO' if results['stress_test']['fpr_below_15pct'] else 'STOP'}")
    logger.info(f"  Base MDD:                {results['base']['mdd']:.1%} "
                f"(need >-18%) → {'GO' if results['base']['mdd'] > -0.18 else 'STOP'}")
    logger.info(f"  MC P(loss):              {results['monte_carlo']['prob_negative']:.1%}")
    logger.info(f"  MC P(MDD>20%):           {results['monte_carlo']['prob_mdd_over_20']:.1%}")
    logger.info(f"  Granger:                 {'SKIPPED (no sentiment data)' if results['granger']['skipped'] else ('PASS' if results['granger']['passed'] else 'FAIL')}")

    # 최종 판정
    all_go = (
        results["walk_forward"]["passed"]
        and results["dsr"]["passed"]
        and results["stress_test"]["fpr_below_15pct"]
        and results["base"]["mdd"] > -0.18
    )
    logger.info("")
    logger.info(f"  ══ OVERALL: {'GO ✓ — Paper Trading 진행 가능' if all_go else 'STOP ✗ — 추가 개선 필요'} ══")

    # JSON 저장
    out_path = "/home/quant/quant-v31/backtest_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
