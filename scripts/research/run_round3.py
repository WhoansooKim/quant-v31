#!/usr/bin/env python
"""§22.AO-69 3라운드 — 추세×레버리지의 (1) 워크포워드 (2) 급락 가드.
 - ^GSPC 1962~2026, t 종가 판정 → t+1 종가 체결, 0.30%/편.
 - 파라미터는 1962~1993 에서만 고르고 1994~2026 에서 평가(사후 선택 편향 제거).
 - 급락 가드: 20일 실현변동성이 임계 초과면 레버리지 상한을 낮춘다(1987 형 단일일 급락 대비).
"""
import itertools
import numpy as np, pandas as pd
import run_round2 as R2   # 데이터·long_run 재사용 (모듈 로드 시 2라운드 표도 출력됨)
from lev_lab import cagr, mdd

px, r1, long_run = R2.px, R2.r1, R2.long_run
rv20 = (r1.rolling(20).std() * np.sqrt(252)).to_numpy()


def strat(n, buf, lev, vg=None, vlev=1.0):
    sma = px.rolling(n).mean().to_numpy(); p = px.to_numpy()
    on = True; out = []
    for i in range(len(p)):
        if np.isfinite(sma[i]):
            if on and p[i] < sma[i] * (1 - buf):
                on = False
            elif not on and p[i] > sma[i] * (1 + buf):
                on = True
        l = lev if on else 0.0
        if vg is not None and np.isfinite(rv20[i]) and rv20[i] > vg:
            l = min(l, vlev)
        out.append(l)
    return pd.Series(out, index=px.index)


rows = []
for n, buf, lev, vg in itertools.product((150, 200, 250), (0.0, 0.01, 0.02, 0.03), (2.0, 2.5, 3.0), (None, 0.25, 0.35)):
    eq, turn = long_run(strat(n, buf, lev, vg, 1.0))
    a, b = eq["1962":"1993"], eq["1994":]
    rows.append({"n": n, "buf": buf, "lev": lev, "vg": vg or 0, "IS62-93": cagr(a), "OOS94-26": cagr(b),
                 "MDD_IS": mdd(a), "MDD_OOS": mdd(b), "1987": float(eq[:"1987-10-31"].iloc[-1] / eq[:"1987-09-30"].iloc[-1] - 1),
                 "turn": turn})
df = pd.DataFrame(rows)
inc_eq, _ = long_run(pd.Series(1.5, index=px.index))
inc = {"IS": cagr(inc_eq["1962":"1993"]), "OOS": cagr(inc_eq["1994":]), "MDD_OOS": mdd(inc_eq["1994":])}
pd.set_option("display.width", 220)
print("\n=== 3라운드: 108 조합 ===")
print(f"INCUMBENT 1.5x  IS {inc['IS']:.1%}  OOS {inc['OOS']:.1%}  MDD_OOS {inc['MDD_OOS']:.1%}")
for vg in (0, 0.25, 0.35):
    sub = df[df.vg == vg]
    print(f"vol guard {vg or 'none'}: OOS 중앙값 {sub['OOS94-26'].median():.1%}, OOS>INC {(sub['OOS94-26'] > inc['OOS']).mean():.0%}, "
          f"OOS>=18% {(sub['OOS94-26'] >= 0.18).mean():.0%}, 1987 중앙값 {sub['1987'].median():.1%}, MDD_OOS 중앙값 {sub['MDD_OOS'].median():.1%}")
for lev in (2.0, 2.5, 3.0):
    sub = df[df.lev == lev]
    print(f"lev {lev}: OOS 중앙값 {sub['OOS94-26'].median():.1%}  MDD_OOS 중앙값 {sub['MDD_OOS'].median():.1%}")
# 워크포워드: IS 상위 5개 → OOS
top = df.sort_values("IS62-93", ascending=False).head(5)
print("\nIS(1962~93) 상위 5 → OOS(1994~2026):")
print(top.assign(**{c: top[c].map("{:.1%}".format) for c in ["IS62-93", "OOS94-26", "MDD_IS", "MDD_OOS", "1987"]}).to_string(index=False))
# IS 에서 MDD 제약(-60% 이상) 하 CAGR 최대
cons = df[df.MDD_IS > -0.60].sort_values("IS62-93", ascending=False).head(5)
print("\nIS MDD>-60% 제약 하 상위 5 → OOS:")
print(cons.assign(**{c: cons[c].map("{:.1%}".format) for c in ["IS62-93", "OOS94-26", "MDD_IS", "MDD_OOS", "1987"]}).to_string(index=False))
df.to_csv("/home/quant/quant-v31/scripts/research/round3.csv", index=False)
