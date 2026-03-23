"""백테스트 비교: 현재 설정 vs 변경 설정 (2년 단위, 1990~현재)."""

import sys
sys.path.insert(0, "/home/quant/quant-v31")

from datetime import date
from engine_v4.backtest.runner import BacktestParams, BacktestRunner

runner = BacktestRunner()

# 2년 단위 구간
periods = []
for y in range(1990, 2026, 2):
    start = date(y, 1, 1)
    end = date(min(y + 2, 2026), 3, 23)  # 마지막 구간은 오늘까지
    if y + 2 <= 2026:
        end = date(y + 2, 1, 1)
    periods.append((start, end))

# 두 가지 파라미터 세트
configs = {
    "CURRENT": {
        "take_profit_pct": 0.10,
        "max_positions": 7,
        "position_pct": 0.20,
    },
    "NEW (TP20/MP10)": {
        "take_profit_pct": 0.20,
        "max_positions": 10,
        "position_pct": 0.10,
    },
}

print(f"{'Period':<16} | {'Config':<16} | {'Return':>8} | {'CAGR':>7} | {'MDD':>7} | {'Sharpe':>7} | {'WinRate':>7} | {'Trades':>6} | {'AvgHold':>7} | {'PF':>6}")
print("-" * 120)

for start, end in periods:
    label = f"{start.year}-{end.year}"
    for cfg_name, cfg in configs.items():
        params = BacktestParams(
            start_date=start,
            end_date=end,
            initial_capital=10000.0,
            stop_loss_pct=-0.05,
            take_profit_pct=cfg["take_profit_pct"],
            max_positions=cfg["max_positions"],
            position_pct=cfg["position_pct"],
            max_daily_entries=2,
            price_range_min=10.0,
            price_range_max=80.0,
        )
        try:
            result = runner.run(params)
            print(
                f"{label:<16} | {cfg_name:<16} | "
                f"{result.total_return:>7.1f}% | "
                f"{result.cagr:>6.1f}% | "
                f"{result.max_drawdown:>6.1f}% | "
                f"{result.sharpe_ratio:>7.2f} | "
                f"{result.win_rate:>6.1f}% | "
                f"{result.total_trades:>6} | "
                f"{result.avg_hold_days:>6.1f}d | "
                f"{result.profit_factor:>5.2f}"
            )
        except Exception as e:
            print(f"{label:<16} | {cfg_name:<16} | ERROR: {e}")

    print("-" * 120)
