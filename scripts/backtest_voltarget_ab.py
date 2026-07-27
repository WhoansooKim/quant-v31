"""②번 변동성 타깃팅 A/B 백테스트 — ①번(C안) 위에 inverse-vol 사이징을 얹어 검증.

기준 = C안(ATR 트레일링 + 부분익절, ①번 적용 상태). 여기에 변동성 타깃팅 on/off 비교.
목표: 변동성 낮은 종목↑/높은 종목↓ 배분 → 위험조정 수익(Sharpe)·MDD 개선 여부 확인.
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

# ①번 C안 = 공통 기준 (트레일링+부분익절)
COMMON = dict(
    start_date=date(2022, 1, 1), end_date=date(2025, 12, 31),
    initial_capital=1000.0, position_pct=0.20, max_positions=5,
    max_daily_entries=2, price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, volume_ratio_min=1.2, stop_loss_pct=-0.05,
    use_atr_trailing=True, atr_trailing_mult=2.5, atr_activation_r=1.0,
    partial_exit_r=2.0, partial_exit_pct=0.5,
)

SCENARIOS = {
    "C 기준 (①번, 고정사이징)": dict(use_vol_targeting=False),
    "D voltgt 3% (mult 0.5~1.25)": dict(use_vol_targeting=True, target_atr_pct=0.03,
                                        vol_mult_min=0.5, vol_mult_max=1.25),
    "D2 voltgt 2.5% (더 공격적)": dict(use_vol_targeting=True, target_atr_pct=0.025,
                                      vol_mult_min=0.5, vol_mult_max=1.25),
    "D3 voltgt 3% (넓은 0.4~1.25)": dict(use_vol_targeting=True, target_atr_pct=0.03,
                                        vol_mult_min=0.4, vol_mult_max=1.25),
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
print(f"{'시나리오':<30} {'총수익':>8} {'Sharpe':>7} {'손익비':>7} {'승률':>5} {'거래':>5} {'MDD':>7}")
for name, r in rows:
    print(f"{name:<30} {r.total_return*100:>+7.1f}% {r.sharpe_ratio:>7.2f} "
          f"{r.payoff_ratio:>7.2f} {r.win_rate*100:>4.0f}% {r.total_trades:>5} {r.max_drawdown*100:>6.1f}%")
