"""①번 손익비 개선 A/B 백테스트 — 고정 TP vs ATR 트레일링(+부분익절).

동일 유니버스/기간/진입조건에서 청산 정책만 바꿔 손익비(payoff_ratio)·총수익·샤프·MDD 비교.
현재 라이브 파라미터에 맞춤: stop -5%, ATR trail 2.5×, activation 1R, 부분익절 0.5.
"""
import sys, json
sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore
from engine_v4.backtest.runner import BacktestRunner, BacktestParams
from datetime import date

pg = PostgresStore(get_config().pg_dsn)
uni = [u["symbol"] for u in pg.get_universe()]
print(f"universe={len(uni)} symbols")

# 라이브와 동일한 유니버스/기간/진입조건 (청산만 변경)
COMMON = dict(
    start_date=date(2022, 1, 1), end_date=date(2025, 12, 31),
    initial_capital=1000.0, position_pct=0.20, max_positions=5,
    max_daily_entries=2, price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, volume_ratio_min=1.2, stop_loss_pct=-0.05,
)

SCENARIOS = {
    "A_fixed_TP10 (baseline)": dict(take_profit_pct=0.10, use_atr_trailing=False),
    "A2_fixed_TP20 (현재라이브)": dict(take_profit_pct=0.20, use_atr_trailing=False),
    "B_ATRtrail (부분익절無)": dict(use_atr_trailing=True, atr_trailing_mult=2.5,
                                    atr_activation_r=1.0, partial_exit_r=0.0),
    "C_ATRtrail+부분익절0.5@2R": dict(use_atr_trailing=True, atr_trailing_mult=2.5,
                                      atr_activation_r=1.0, partial_exit_r=2.0,
                                      partial_exit_pct=0.5),
}

runner = BacktestRunner(pg)
# 데이터는 시나리오마다 재다운로드되므로, 첫 실행에서 캐시 없음 — 순차 실행
rows = []
for name, over in SCENARIOS.items():
    p = BacktestParams(**{**COMMON, **over})
    r = runner.run(p, universe_symbols=uni)
    rows.append((name, r))
    print(f"\n=== {name} ===")
    print(f"  총수익 {r.total_return*100:+.1f}% | CAGR {r.cagr*100:+.1f}% | "
          f"MDD {r.max_drawdown*100:.1f}% | Sharpe {r.sharpe_ratio:.2f}")
    print(f"  거래 {r.total_trades} | 승률 {r.win_rate*100:.0f}% | "
          f"손익비 {r.payoff_ratio:.2f} (승 {r.avg_win_pct*100:+.1f}% / 패 {r.avg_loss_pct*100:+.1f}%) | "
          f"PF {r.profit_factor:.2f} | 보유 {r.avg_hold_days:.1f}일")

print("\n\n================ 요약 표 ================")
print(f"{'시나리오':<28} {'총수익':>8} {'Sharpe':>7} {'손익비':>7} {'승률':>5} {'거래':>5} {'MDD':>7}")
for name, r in rows:
    print(f"{name:<28} {r.total_return*100:>+7.1f}% {r.sharpe_ratio:>7.2f} "
          f"{r.payoff_ratio:>7.2f} {r.win_rate*100:>4.0f}% {r.total_trades:>5} {r.max_drawdown*100:>6.1f}%")
