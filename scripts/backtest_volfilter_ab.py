"""거래량 조건 완화 A/B 백테스트 — 진입 빈도 병목(거래량 급증) 검증.

현재 라이브 상태(①C안 + ③E2 절대모멘텀) 기준. volume_ratio_min 을 낮춰
진입 빈도↑ 하면서 성과(총수익/Sharpe/승률/손익비)가 유지/개선되는지 확인.
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

# 현재 라이브 = ①C안 + ③E2 절대모멘텀
COMMON = dict(
    start_date=date(2022, 1, 1), end_date=date(2025, 12, 31),
    initial_capital=1000.0, position_pct=0.20, max_positions=5,
    max_daily_entries=2, price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, stop_loss_pct=-0.05,
    use_atr_trailing=True, atr_trailing_mult=2.5, atr_activation_r=1.0,
    partial_exit_r=2.0, partial_exit_pct=0.5,
    use_abs_momentum=True, abs_mom_period=126, abs_mom_min=0.0,
)
SCENARIOS = {
    "기준 vol>=1.2 (현재)": dict(volume_ratio_min=1.2),
    "완화 vol>=1.0": dict(volume_ratio_min=1.0),
    "완화 vol>=0.8": dict(volume_ratio_min=0.8),
    "사실상해제 vol>=0.0": dict(volume_ratio_min=0.0),
}

runner = BacktestRunner(pg)
rows = []
for name, over in SCENARIOS.items():
    r = runner.run(BacktestParams(**{**COMMON, **over}), universe_symbols=uni)
    buys = [t for t in r.trades_log if t["side"] == "BUY"]
    rows.append((name, r, len(buys)))
    print(f"=== {name} ===")
    print(f"  진입(BUY) {len(buys)}건 (월 {len(buys)/48:.1f}) | 총수익 {r.total_return*100:+.1f}% | "
          f"CAGR {r.cagr*100:+.1f}% | MDD {r.max_drawdown*100:.1f}% | Sharpe {r.sharpe_ratio:.2f}")
    print(f"  승률 {r.win_rate*100:.0f}% | 손익비 {r.payoff_ratio:.2f} | PF {r.profit_factor:.2f}\n")

print("================ 요약 표 ================")
print(f"{'시나리오':<22} {'진입':>5} {'월':>5} {'총수익':>8} {'Sharpe':>7} {'손익비':>6} {'승률':>5} {'MDD':>7}")
for name, r, nb in rows:
    print(f"{name:<22} {nb:>5} {nb/48:>5.1f} {r.total_return*100:>+7.1f}% {r.sharpe_ratio:>7.2f} "
          f"{r.payoff_ratio:>6.2f} {r.win_rate*100:>4.0f}% {r.max_drawdown*100:>6.1f}%")
