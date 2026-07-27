"""③번 절대 모멘텀 필터 A/B 백테스트 — ①번(C안) 위에 TSMOM 필터를 얹어 검증.

Time Series Momentum (Moskowitz-Ooi-Pedersen 2012): 과거 12개월 수익>0 종목만 롱.
하락추세 종목의 브레이크아웃 함정을 걸러 진입 품질↑ 기대. 기준 = C안(①번 적용).
"""
import sys
sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore
from engine_v4.backtest.runner import BacktestRunner, BacktestParams
from datetime import date

pg = PostgresStore(get_config().pg_dsn)
uni = [u["symbol"] for u in pg.get_universe()]
print(f"universe={len(uni)} symbols")

COMMON = dict(
    start_date=date(2022, 1, 1), end_date=date(2025, 12, 31),
    initial_capital=1000.0, position_pct=0.20, max_positions=5,
    max_daily_entries=2, price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, volume_ratio_min=1.2, stop_loss_pct=-0.05,
    use_atr_trailing=True, atr_trailing_mult=2.5, atr_activation_r=1.0,
    partial_exit_r=2.0, partial_exit_pct=0.5,
)

SCENARIOS = {
    "C 기준 (①번, 필터無)": dict(use_abs_momentum=False),
    "E absmom 12M>0": dict(use_abs_momentum=True, abs_mom_period=252, abs_mom_min=0.0),
    "E2 absmom 6M>0": dict(use_abs_momentum=True, abs_mom_period=126, abs_mom_min=0.0),
    "E3 absmom 12M>+10%": dict(use_abs_momentum=True, abs_mom_period=252, abs_mom_min=0.10),
}

runner = BacktestRunner(pg)
rows = []
for name, over in SCENARIOS.items():
    p = BacktestParams(**{**COMMON, **over})
    r = runner.run(p, universe_symbols=uni)
    rows.append((name, r))
    print(f"\n=== {name} ===")
    print(f"  총수익 {r.total_return*100:+.1f}% | CAGR {r.cagr*100:+.1f}% | "
          f"MDD {r.max_drawdown*100:.1f}% | Sharpe {r.sharpe_ratio:.2f}")
    print(f"  거래 {r.total_trades} | 승률 {r.win_rate*100:.0f}% | "
          f"손익비 {r.payoff_ratio:.2f} | PF {r.profit_factor:.2f}")

print("\n\n================ 요약 표 ================")
print(f"{'시나리오':<26} {'총수익':>8} {'Sharpe':>7} {'손익비':>7} {'승률':>5} {'거래':>5} {'MDD':>7}")
for name, r in rows:
    print(f"{name:<26} {r.total_return*100:>+7.1f}% {r.sharpe_ratio:>7.2f} "
          f"{r.payoff_ratio:>7.2f} {r.win_rate*100:>4.0f}% {r.total_trades:>5} {r.max_drawdown*100:>6.1f}%")
