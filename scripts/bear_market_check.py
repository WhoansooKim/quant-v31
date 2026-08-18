"""통과 변이의 하락장 성적 검증 (§22.AO-7).

365d 상승 구간에서 통과한 변이가 하락장에서도 유효한지 확인한다.
Sharpe 는 낙폭을 보지 않으므로 MDD 를 함께 본다.
"""
import json
import logging
import sys
from datetime import date

logging.basicConfig(level=logging.ERROR, format="%(message)s")
sys.path.insert(0, "/home/quant/quant-v31")

from engine_v4.backtest.runner import BacktestRunner
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore
from engine_v4.harness.auto_backtest import _baseline_config, _live_capital, _make_params

PERIODS = [
    ("2022 약세장", date(2022, 1, 1), date(2022, 12, 31)),
    ("2022H1 급락", date(2022, 1, 1), date(2022, 6, 30)),
    ("2020 코로나", date(2020, 1, 1), date(2020, 6, 30)),
]

pg = PostgresStore(get_config().pg_dsn)
base = _baseline_config(pg)
cap = _live_capital(pg)
runner = BacktestRunner(pg)

with pg.get_conn() as conn:
    rows = conn.execute(
        "SELECT variant_id, name, config_diff FROM swing_strategy_variants "
        "WHERE status = 'validated' ORDER BY variant_id"
    ).fetchall()

targets = [("baseline", {})] + [
    (f"v{r['variant_id']} {r['name']}",
     r["config_diff"] if isinstance(r["config_diff"], dict) else json.loads(r["config_diff"]))
    for r in rows
]

print(f"자본 ${cap:,.0f} | 대상 {len(targets)}개 (baseline + validated {len(rows)}건)\n")

for label, start, end in PERIODS:
    print(f"=== {label} ({start} ~ {end}) ===")
    print(f"{'대상':28s} {'수익률':>9s} {'Sharpe':>8s} {'MDD':>9s} {'거래':>6s} {'승률':>7s}")
    for name, diff in targets:
        try:
            p = _make_params(base, diff, start, end, cap)
            r = runner.run(p)
            print(f"{name:28s} {r.total_return:+8.2%} {r.sharpe_ratio:+8.2f} "
                  f"{r.max_drawdown:+8.2%} {r.total_trades:6d} {r.win_rate:6.1%}")
        except Exception as e:
            print(f"{name:28s}  실패: {e}")
    print()
