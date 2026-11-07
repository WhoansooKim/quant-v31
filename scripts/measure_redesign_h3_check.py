#!/usr/bin/env python
"""§22.AO-68 H3 건전성 — 대형주 모멘텀 30%(무필터)는 생존편향/데이터 결함인가.
  1) SPMO·MTUM(실물 모멘텀 ETF, 생존편향 없음)과 같은 창(2015-10-12~) 비교
  2) 기여 상위 종목 · 연도 — 소수 종목·분할 오류가 만든 수치인지
  3) 변형: 룩백 6-1 · 상위10/20 · 유동성 상위 200/500
"""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, "/home/quant/quant-v31/scripts"); sys.path.insert(0, "/home/quant/quant-v31")
from measure_redesign_h1_h5 import *

Oe, Ce = load_etf(); pg = PostgresStore(get_config().pg_dsn)
Os, Cs, Vs = load_stocks(pg)
O = Oe.join(Os, how="outer"); C = Ce.join(Cs, how="outer")
dates = Ce.index[(Ce.index >= START) & (Ce.index <= END) & Ce["SPY"].notna()]
mid = dates[len(dates) // 2]
w2 = dates[dates >= pd.Timestamp("2015-10-13")]
V = {
    "상위10 12-1 유동500 무필터": dict(n=10, filt=False),
    "상위10 12-1 유동500 +필터": dict(n=10),
    "상위20 12-1 유동500 무필터": dict(n=20, hold_rank=50, filt=False),
    "상위10 6-1 유동500 무필터": dict(n=10, look=126, filt=False),
    "상위10 12-1 유동200 무필터": dict(n=10, top_liq=200, filt=False),
}
rows, curves, tgs = [], {}, {}
for k, kw in V.items():
    tg = momentum_targets(Os, Cs, Vs, Ce, dates, **kw); tgs[k] = tg
    eq, turn, e = simulate(O, C, tg, dates); curves[k] = eq
    rows.append({"변형": k, "전체": cagr(eq), "전반": cagr(eq[:mid]), "후반": cagr(eq[mid:]),
                 "2015-10~": cagr(eq[w2]), "왕복/년": turn / 2, "MDD": mdd(eq)})
    print("  done", k, flush=True)
for b in ("SPY", "QQQ", "SPMO", "MTUM"):
    s = Ce[b].reindex(w2)
    rows.append({"변형": f"[실물] {b} 보유", "2015-10~": cagr(s / s.iloc[0])})
print(pd.DataFrame(rows).round(2).to_string(index=False))

# 기여: 무필터 상위10 — 월별 보유의 다음 달 수익 근사(종가 기준)로 종목별 기여 합
k = "상위10 12-1 유동500 무필터"; tg = tgs[k]
ds = sorted(tg); contrib = {}
for a, b in zip(ds, ds[1:] + [dates[-1]]):
    for s, w in tg[a].items():
        r = Cs[s].get(b, np.nan) / Cs[s].get(a, np.nan) - 1
        if np.isfinite(r): contrib[s] = contrib.get(s, 0) + w * np.log1p(r) if r > -1 else contrib.get(s, 0)
cs = pd.Series(contrib).sort_values()
tot = cs.sum()
print(f"\n로그수익 기여 합 {tot:.2f} · 상위10 종목 합 {cs.tail(10).sum():.2f} ({cs.tail(10).sum()/tot:.0%})")
print("상위:", ", ".join(f"{s} {v:+.2f}" for s, v in cs.tail(12)[::-1].items()))
print("하위:", ", ".join(f"{s} {v:+.2f}" for s, v in cs.head(8).items()))
# 월간 수익 극단치(분할 오류 의심): 한 달 +150% 이상 보유 사례
ext = []
for a, b in zip(ds, ds[1:] + [dates[-1]]):
    for s in tg[a]:
        r = Cs[s].get(b, np.nan) / Cs[s].get(a, np.nan) - 1
        if np.isfinite(r) and (r > 1.5 or r < -0.6): ext.append((a.date(), s, round(r * 100)))
print("한 달 +150%↑/−60%↓ 보유:", ext[:20], f"(총 {len(ext)})")
