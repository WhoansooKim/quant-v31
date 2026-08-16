"""Tier 1 시장 트렌드 필터 백테스트 — SPY 200일 SMA 진입 게이트.

가설(GEM/Faber): SPY<SMA200 시 진입 중단 → 하락장 손실 회피 → MDD↓, 위험조정↑.
전체기간(2022-2025) + 약세장(2022) 집중 비교. 현재 라이브 전체 설정 기준.
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

BASE = dict(
    initial_capital=2000.0, position_pct=0.05, max_positions=20,
    max_daily_entries=2, price_range_min=10.0, price_range_max=250.0,
    return_rank_min=0.6, volume_ratio_min=1.0, stop_loss_pct=-0.05,
    use_atr_trailing=True, atr_trailing_mult=2.5, atr_activation_r=1.0,
    partial_exit_r=2.0, partial_exit_pct=0.5,
    use_abs_momentum=True, abs_mom_period=126, abs_mom_min=0.0,
    breakout_margin=0.0,
)
runner = BacktestRunner(pg)

def run(label, start, end, mkt):
    p = BacktestParams(**{**BASE, "start_date": start, "end_date": end, "use_market_filter": mkt})
    r = runner.run(p, universe_symbols=list(uni))
    buys = len([t for t in r.trades_log if t["side"] == "BUY"])
    print(f"  [{label}] 진입 {buys} | 총수익 {r.total_return*100:+.1f}% | Sharpe {r.sharpe_ratio:.2f} | "
          f"MDD {r.max_drawdown*100:.1f}% | 승률 {r.win_rate*100:.0f}%")
    return r

print("=== 전체 기간 2022-2025 ===")
run("필터 OFF", date(2022,1,1), date(2025,12,31), False)
run("필터 ON ", date(2022,1,1), date(2025,12,31), True)

print("\n=== 약세장 집중 2022 (하락장 방어 검증) ===")
run("필터 OFF", date(2022,1,1), date(2022,12,31), False)
run("필터 ON ", date(2022,1,1), date(2022,12,31), True)

print("\n=== 강세장 2023-2024 (기회비용 검증) ===")
run("필터 OFF", date(2023,1,1), date(2024,12,31), False)
run("필터 ON ", date(2023,1,1), date(2024,12,31), True)
