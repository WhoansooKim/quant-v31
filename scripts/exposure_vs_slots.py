"""v42 검토 — '노출 축소' 효과와 '슬롯 집중' 효과를 분리 (§22.AO-8).

v42(0.04×10=40%)가 baseline(0.05×20=100%) 대비 MDD 가 낮은 것은 당연하다(현금 60%).
같은 40% 노출을 20슬롯으로 나눠도 같은 성적이면 슬롯 수는 무관하고 노출만이 변수다.
"""
import sys
from datetime import date

sys.path.insert(0, "/home/quant/quant-v31")
import logging
logging.basicConfig(level=logging.ERROR)

from engine_v4.backtest.runner import BacktestRunner
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore
from engine_v4.harness.auto_backtest import _baseline_config, _live_capital, _make_params

pg = PostgresStore(get_config().pg_dsn)
base = _baseline_config(pg)
cap = _live_capital(pg)
runner = BacktestRunner(pg)

CONFIGS = [
    ("A baseline   0.05x20 =100%", {}),
    ("B v42        0.04x10 = 40%", {"position_pct": 0.04, "max_positions": 10, "stop_loss_pct": -0.06}),
    ("C 동일노출   0.02x20 = 40%", {"position_pct": 0.02, "max_positions": 20}),
    ("D 동일노출   0.10x04 = 40%", {"position_pct": 0.10, "max_positions": 4}),
    ("E 중간       0.04x20 = 80%", {"position_pct": 0.04, "max_positions": 20}),
]
PERIODS = [
    ("365d 상승장", date(2025, 8, 18), date(2026, 8, 18)),
    ("2022 약세장", date(2022, 1, 1), date(2022, 12, 31)),
]

print(f"자본 ${cap:,.0f}\n")
for plabel, start, end in PERIODS:
    print(f"=== {plabel} ===")
    print(f"{'구성':30s} {'수익률':>9s} {'Sharpe':>8s} {'MDD':>8s} {'거래':>6s} {'승률':>7s}")
    for label, diff in CONFIGS:
        try:
            r = runner.run(_make_params(base, diff, start, end, cap))
            print(f"{label:30s} {r.total_return:+8.2%} {r.sharpe_ratio:+8.2f} "
                  f"{r.max_drawdown:+7.2%} {r.total_trades:6d} {r.win_rate:6.1%}")
        except Exception as e:
            print(f"{label:30s}  실패: {e}")
    print()
