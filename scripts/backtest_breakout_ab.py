"""브레이크아웃 조건 완화 A/B 백테스트 — 진입 빈도 진짜 병목 검증.

현재 라이브(①C안 + ③E2 + 거래량 vol≥1.0) 기준. 브레이크아웃 완화(근접마진/기간/제거)로
진입 빈도↑ 하면서 성과 유지/개선되는지 확인.
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

# 현재 라이브 = ①C안 + ③E2 + 거래량 vol≥1.0
COMMON = dict(
    start_date=date(2022, 1, 1), end_date=date(2025, 12, 31),
    initial_capital=1000.0, position_pct=0.20, max_positions=5,
    max_daily_entries=2, price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, volume_ratio_min=1.0, stop_loss_pct=-0.05,
    use_atr_trailing=True, atr_trailing_mult=2.5, atr_activation_r=1.0,
    partial_exit_r=2.0, partial_exit_pct=0.5,
    use_abs_momentum=True, abs_mom_period=126, abs_mom_min=0.0,
)
SCENARIOS = {
    "기준 5일돌파 엄격": dict(breakout_days=5, breakout_margin=0.0),
    "근접 5일 -1%": dict(breakout_days=5, breakout_margin=0.01),
    "근접 5일 -3%": dict(breakout_days=5, breakout_margin=0.03),
    "3일돌파 엄격": dict(breakout_days=3, breakout_margin=0.0),
    "브레이크아웃 제거": dict(require_breakout=False),
}

runner = BacktestRunner(pg)
rows = []
for name, over in SCENARIOS.items():
    r = runner.run(BacktestParams(**{**COMMON, **over}), universe_symbols=uni)
    buys = len([t for t in r.trades_log if t["side"] == "BUY"])
    rows.append((name, r, buys))
    print(f"=== {name} ===")
    print(f"  진입(BUY) {buys}건 (월 {buys/48:.1f}) | 총수익 {r.total_return*100:+.1f}% | "
          f"CAGR {r.cagr*100:+.1f}% | MDD {r.max_drawdown*100:.1f}% | Sharpe {r.sharpe_ratio:.2f}")
    print(f"  승률 {r.win_rate*100:.0f}% | 손익비 {r.payoff_ratio:.2f} | PF {r.profit_factor:.2f}\n")

print("================ 요약 표 ================")
print(f"{'시나리오':<20} {'진입':>5} {'월':>5} {'총수익':>8} {'Sharpe':>7} {'손익비':>6} {'승률':>5} {'MDD':>7}")
for name, r, nb in rows:
    print(f"{name:<20} {nb:>5} {nb/48:>5.1f} {r.total_return*100:>+7.1f}% {r.sharpe_ratio:>7.2f} "
          f"{r.payoff_ratio:>6.2f} {r.win_rate*100:>4.0f}% {r.max_drawdown*100:>6.1f}%")
