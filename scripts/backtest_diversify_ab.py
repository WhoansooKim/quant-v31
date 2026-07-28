"""포지션 정책(집중 vs 분산) A/B 백테스트 — 20개·5% 검증.

현재 라이브 전체 설정(①C안+③E2+거래량 vol≥1.0+브레이크아웃 margin 0.03)에
max_positions × position_pct 만 바꿔 비교. 자본 $2,000(입금 후).
분산(20개·5%)이 집중(5개·20%) 대비 성과 어떻게 변하는지 확인.
"""
import sys
sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore
from engine_v4.backtest.runner import BacktestRunner, BacktestParams
from datetime import date

pg = PostgresStore(get_config().pg_dsn)
uni = [u["symbol"] for u in pg.get_universe()]
print(f"universe={len(uni)} symbols\n")

# 현재 라이브 전체 개선 반영 (포지션 정책 제외)
COMMON = dict(
    start_date=date(2022, 1, 1), end_date=date(2025, 12, 31),
    initial_capital=2000.0, max_daily_entries=2,
    price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, volume_ratio_min=1.0, stop_loss_pct=-0.05,
    use_atr_trailing=True, atr_trailing_mult=2.5, atr_activation_r=1.0,
    partial_exit_r=2.0, partial_exit_pct=0.5,
    use_abs_momentum=True, abs_mom_period=126, abs_mom_min=0.0,
    breakout_margin=0.03,
)
SCENARIOS = {
    "집중 5개×20% (백테기준)": dict(max_positions=5, position_pct=0.20),
    "중간 7개×14% (이전)": dict(max_positions=7, position_pct=0.14),
    "분산 10개×10%": dict(max_positions=10, position_pct=0.10),
    "분산 20개×5% (신규라이브)": dict(max_positions=20, position_pct=0.05),
}

runner = BacktestRunner(pg)
rows = []
for name, over in SCENARIOS.items():
    r = runner.run(BacktestParams(**{**COMMON, **over}), universe_symbols=uni)
    buys = len([t for t in r.trades_log if t["side"] == "BUY"])
    rows.append((name, r, buys))
    print(f"=== {name} ===")
    print(f"  진입 {buys} | 총수익 {r.total_return*100:+.1f}% | CAGR {r.cagr*100:+.1f}% | "
          f"MDD {r.max_drawdown*100:.1f}% | Sharpe {r.sharpe_ratio:.2f}")
    print(f"  승률 {r.win_rate*100:.0f}% | 손익비 {r.payoff_ratio:.2f} | PF {r.profit_factor:.2f} | "
          f"최종 ${r.final_value:.0f}\n")

print("================ 요약 표 ================")
print(f"{'시나리오':<24} {'진입':>5} {'총수익':>8} {'CAGR':>7} {'Sharpe':>7} {'손익비':>6} {'승률':>5} {'MDD':>7}")
for name, r, nb in rows:
    print(f"{name:<24} {nb:>5} {r.total_return*100:>+7.1f}% {r.cagr*100:>+6.1f}% {r.sharpe_ratio:>7.2f} "
          f"{r.payoff_ratio:>6.2f} {r.win_rate*100:>4.0f}% {r.max_drawdown*100:>6.1f}%")
