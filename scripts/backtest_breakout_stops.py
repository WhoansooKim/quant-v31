"""브레이크아웃 근접 margin의 손절 영향 재검증 — 갭 리스크 확인.

앞 백테스트(총수익만)에서 놓친 손절 빈도/조기손절을 margin별 비교.
가설: 근접(-3%)이 '이미 오른 종목 늦게 잡아 되돌림' → stop_loss/조기손절 증가?
현재 라이브 전체 설정 기준.
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
    initial_capital=2000.0, position_pct=0.05, max_positions=20,
    max_daily_entries=2, price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, volume_ratio_min=1.0, stop_loss_pct=-0.05,
    use_atr_trailing=True, atr_trailing_mult=2.5, atr_activation_r=1.0,
    partial_exit_r=2.0, partial_exit_pct=0.5,
    use_abs_momentum=True, abs_mom_period=126, abs_mom_min=0.0,
)
SCENARIOS = {
    "margin 0% (엄격돌파)": dict(breakout_margin=0.0),
    "margin 1% 근접": dict(breakout_margin=0.01),
    "margin 2% 근접": dict(breakout_margin=0.02),
    "margin 3% 근접 (현재)": dict(breakout_margin=0.03),
}

runner = BacktestRunner(pg)
rows = []
for name, over in SCENARIOS.items():
    r = runner.run(BacktestParams(**{**COMMON, **over}), universe_symbols=uni)
    sells = [t for t in r.trades_log if t["side"] == "SELL"]
    reasons = Counter(t["reason"] for t in sells)
    n_sell = len(sells)
    n_sl = reasons.get("stop_loss", 0)
    # 조기 손절: stop_loss 중 hold_days<=2 (진입 직후 되돌림 근사)
    early_sl = sum(1 for t in sells if t["reason"] == "stop_loss" and t["hold_days"] <= 2)
    sl_pct = n_sl / n_sell * 100 if n_sell else 0
    rows.append((name, r, n_sell, n_sl, sl_pct, early_sl))
    print(f"=== {name} ===")
    print(f"  총청산 {n_sell} | stop_loss {n_sl}건({sl_pct:.0f}%) | 조기손절(≤2일) {early_sl}건 | "
          f"총수익 {r.total_return*100:+.1f}% | Sharpe {r.sharpe_ratio:.2f}")
    print(f"  청산사유: {dict(reasons)}\n")

print("================ 손절 영향 요약 ================")
print(f"{'시나리오':<22} {'총청산':>6} {'손절수':>6} {'손절%':>6} {'조기손절':>7} {'총수익':>8} {'Sharpe':>7}")
for name, r, ns, nsl, slp, esl in rows:
    print(f"{name:<22} {ns:>6} {nsl:>6} {slp:>5.0f}% {esl:>7} {r.total_return*100:>+7.1f}% {r.sharpe_ratio:>7.2f}")
