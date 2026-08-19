"""breakout 음수 기여 진단 (§22.AO-13).

교집합 연구에서 breakout(5일 고점 돌파 + 거래량 급증)이 −0.88%p 로 유일한 음수 기여.
묶어서 본 값이라 분리하고, 다른 화면과의 조건부로도 확인한다.
"""
import sys
from datetime import date
from statistics import mean

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

pg = PostgresStore(get_config().pg_dsn)

SQL = """
SELECT s.symbol, s.time::date AS d, s.entry_price, s.return_20d_rank,
       s.technical_score, s.breakout_5d, s.volume_surge, s.trend_aligned,
       (SELECT p.close FROM daily_prices p
         WHERE p.symbol = s.symbol AND p.time::date > s.time::date
         ORDER BY p.time LIMIT 1 OFFSET %s) AS px_fwd
FROM swing_signals s
WHERE s.entry_price > 0
"""


def load(h):
    with pg.get_conn() as conn:
        rows = [r for r in conn.execute(SQL, (h - 1,)).fetchall() if r["px_fwd"]]
    return rows


def ret(r):
    return (float(r["px_fwd"]) - float(r["entry_price"])) / float(r["entry_price"])


def show(label, rows, cond):
    yes = [ret(r) for r in rows if cond(r)]
    no = [ret(r) for r in rows if not cond(r)]
    if not yes or not no:
        print(f"  {label:34s} (표본부족 yes={len(yes)} no={len(no)})")
        return
    wy = sum(1 for x in yes if x > 0) / len(yes)
    wn = sum(1 for x in no if x > 0) / len(no)
    print(f"  {label:34s} 충족 n={len(yes):3d} {mean(yes):+7.2%} (승률 {wy:4.0%})  |  "
          f"미충족 n={len(no):3d} {mean(no):+7.2%} (승률 {wn:4.0%})  → {mean(yes)-mean(no):+.2%}p")


for h in (5, 10, 20):
    rows = load(h)
    print(f"\n=== 전방 {h}일 (표본 {len(rows)}건) ===")
    show("breakout_5d 단독", rows, lambda r: bool(r["breakout_5d"]))
    show("volume_surge 단독", rows, lambda r: bool(r["volume_surge"]))
    show("breakout AND volume", rows, lambda r: bool(r["breakout_5d"]) and bool(r["volume_surge"]))
    show("breakout 만 (거래량 없이)", rows, lambda r: bool(r["breakout_5d"]) and not bool(r["volume_surge"]))
    show("volume 만 (돌파 없이)", rows, lambda r: bool(r["volume_surge"]) and not bool(r["breakout_5d"]))

# 고모멘텀 구간에서의 조건부 (교집합 게이트 통과분 안에서)
rows = load(10)
gate = [r for r in rows if r["return_20d_rank"] is not None and float(r["return_20d_rank"]) >= 0.70
        and r["technical_score"] is not None and float(r["technical_score"]) >= 60]
print(f"\n=== 교집합 게이트 통과분 내부 (전방 10일, n={len(gate)}) ===")
show("breakout_5d", gate, lambda r: bool(r["breakout_5d"]))
show("volume_surge", gate, lambda r: bool(r["volume_surge"]))
