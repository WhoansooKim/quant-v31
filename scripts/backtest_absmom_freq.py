"""③번 6개월 절대모멘텀 — 진입 빈도 확인 (C기준 vs E2).

진입(BUY) 건수 + 연도별 분포 비교. 필터가 진입 기회를 얼마나 줄이는지 정량화.
"""
import sys
from collections import Counter
sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore
from engine_v4.backtest.runner import BacktestRunner, BacktestParams
from datetime import date

pg = PostgresStore(get_config().pg_dsn)
uni = [u["symbol"] for u in pg.get_universe()]
print(f"universe={len(uni)} symbols\n")

COMMON = dict(
    start_date=date(2022, 1, 1), end_date=date(2025, 12, 31),
    initial_capital=1000.0, position_pct=0.20, max_positions=5,
    max_daily_entries=2, price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, volume_ratio_min=1.2, stop_loss_pct=-0.05,
    use_atr_trailing=True, atr_trailing_mult=2.5, atr_activation_r=1.0,
    partial_exit_r=2.0, partial_exit_pct=0.5,
)
SCENARIOS = {
    "C 기준 (필터無)": dict(use_abs_momentum=False),
    "E2 절대모멘텀 6M>0": dict(use_abs_momentum=True, abs_mom_period=126, abs_mom_min=0.0),
}

runner = BacktestRunner(pg)
res = {}
for name, over in SCENARIOS.items():
    r = runner.run(BacktestParams(**{**COMMON, **over}), universe_symbols=uni)
    buys = [t for t in r.trades_log if t["side"] == "BUY"]
    by_year = Counter(t["date"][:4] for t in buys)
    res[name] = (r, buys, by_year)
    print(f"=== {name} ===")
    print(f"  총 진입(BUY) {len(buys)}건 | 총수익 {r.total_return*100:+.1f}% | Sharpe {r.sharpe_ratio:.2f}")
    print(f"  연도별 진입: " + ", ".join(f"{y}:{by_year[y]}" for y in sorted(by_year)))
    # 4년 기간 → 월평균 진입
    print(f"  월평균 진입: {len(buys)/48:.1f}건\n")

# 비교 요약
c_buys = len(res["C 기준 (필터無)"][1])
e_buys = len(res["E2 절대모멘텀 6M>0"][1])
print("================ 진입 빈도 비교 ================")
print(f"  C 기준     : {c_buys}건 (월 {c_buys/48:.1f})")
print(f"  E2 6M필터  : {e_buys}건 (월 {e_buys/48:.1f})")
diff = e_buys - c_buys
print(f"  차이       : {diff:+d}건 ({diff/c_buys*100:+.1f}%) — 필터로 걸러진 진입")
print("\n연도별 진입 수 (C → E2):")
years = sorted(set(res["C 기준 (필터無)"][2]) | set(res["E2 절대모멘텀 6M>0"][2]))
for y in years:
    c = res["C 기준 (필터無)"][2][y]
    e = res["E2 절대모멘텀 6M>0"][2][y]
    print(f"  {y}: {c:>3} → {e:>3}  ({e-c:+d})")
