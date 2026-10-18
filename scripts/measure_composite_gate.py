"""composite 게이트가 거른 것이 실제로 나빴나 (§22.AO-56).

§22.AO-50 의 규율을 그대로 쓴다: 중복 ENTRY 제거 · SPY 초과수익 · 날짜별 횡단면 ·
날짜블록 부트스트랩. 게이트 평가는 '통과 vs 기각' 두 군 비교이므로 날짜 내
비교가 되는 날(양쪽이 다 있는 날)만 쓴다.
"""
import sys
sys.path.insert(0,"/home/quant/quant-v31")
import numpy as np, pandas as pd
from engine_v4.data.storage import PostgresStore
from engine_v4.config.settings import get_config

H = (5, 10, 20)
pg = PostgresStore(get_config().pg_dsn)
SQL = """
WITH sig AS (
  SELECT DISTINCT ON (s.symbol, s.time::date)
         s.symbol, s.time::date AS d, s.entry_price::float ep,
         s.composite_score::float comp, s.return_20d_rank::float rank,
         s.technical_score::float tech, s.status
  FROM swing_signals s
  WHERE s.signal_type='ENTRY' AND s.entry_price > 0
  ORDER BY s.symbol, s.time::date, s.time)
SELECT sig.*,
  (SELECT p.close::float FROM daily_prices p WHERE p.symbol=sig.symbol AND p.time::date>sig.d
    ORDER BY p.time LIMIT 1 OFFSET %s) px,
  (SELECT p.close::float FROM daily_prices p WHERE p.symbol='SPY' AND p.time::date<=sig.d
    ORDER BY p.time DESC LIMIT 1) b0,
  (SELECT p.close::float FROM daily_prices p WHERE p.symbol='SPY' AND p.time::date>sig.d
    ORDER BY p.time LIMIT 1 OFFSET %s) b1
FROM sig"""

for h in H:
    with pg.get_conn() as c:
        d = pd.DataFrame(c.execute(SQL, (h-1, h-1)).fetchall())
    d = d.dropna(subset=["px","b0","b1"])
    d["ex"] = (d.px/d.ep - 1) - (d.b1/d.b0 - 1)        # SPY 초과수익
    d["pass_min"] = d.comp >= 61
    sub = d.dropna(subset=["comp"])
    # 날짜 내 양쪽이 다 있는 날만
    ok = sub.groupby("d").pass_min.nunique() == 2
    days = ok[ok].index
    w = sub[sub.d.isin(days)]
    if h == H[0]:
        print(f"표본 {len(d)}건 · composite 있는 것 {len(sub)}건 · "
              f"양쪽 공존 날짜 {len(days)}/{sub.d.nunique()}일 ({len(w)}건)\n")
        print(f"{'h':>3} {'통과n':>6} {'기각n':>6} {'통과중앙':>9} {'기각중앙':>9} "
              f"{'차이':>8} {'날짜내차이중앙':>14} {'95%CI':>20} {'순위상관':>9}")
    p_, f_ = w[w.pass_min], w[~w.pass_min]
    # 날짜별 쌍대 차이 (날짜 고정효과 제거)
    per = w.groupby("d").apply(
        lambda x: x[x.pass_min].ex.median() - x[~x.pass_min].ex.median(), include_groups=False)
    per = per.dropna()
    rng = np.random.default_rng(20261018)
    arr = per.values
    bs = np.median(rng.choice(arr, size=(2000, len(arr)), replace=True), axis=1)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    # composite 자체의 날짜별 횡단면 순위상관
    ics = []
    for dt, g in sub.groupby("d"):
        if g.comp.nunique() > 1 and g.ex.nunique() > 1 and len(g) >= 3:
            ics.append(g.comp.corr(g.ex, method="spearman"))
    print(f"{h:3d} {len(p_):6d} {len(f_):6d} {p_.ex.median()*100:+8.2f}% "
          f"{f_.ex.median()*100:+8.2f}% {(p_.ex.median()-f_.ex.median())*100:+7.2f}%p "
          f"{np.median(arr)*100:+13.2f}%p [{lo*100:+.2f},{hi*100:+.2f}]%p "
          f"{np.median(ics) if ics else float('nan'):+8.3f} (n={len(ics)}일)")
