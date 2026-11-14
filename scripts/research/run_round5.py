#!/usr/bin/env python
"""§22.AO-70 5라운드 — (1) 추세 버퍼 앙상블(파라미터 선택 제거) (2) 하락국면 단기 스윙(trend+bear-swing) 정밀 검증.
SPY OHLC 1994~, t 종가 판정 → t+1 시가 체결, 0.30%/편, 합성 3배(실제 UPRO 보정).
"""
import numpy as np, pandas as pd
import lev_lab as LL
from lev_lab import load, calibrate, Market, lev_to_w, run, cagr, mdd, report

pd.set_option("display.width", 250)
O, C, H, L, rf = load()
cal = calibrate(O, C, rf)
mkt = Market(O, C, H, L, rf, {2: cal[2]["extra_drag"], 3: cal[3]["extra_drag"]})
idx = mkt.idx
spy = C["SPY"]; px = spy.to_numpy(); hi = H["SPY"].to_numpy()
sma200 = spy.rolling(200).mean().to_numpy(); sma5 = spy.rolling(5).mean().to_numpy()
d = spy.diff(); up = d.clip(lower=0).ewm(alpha=1 / 2).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 2).mean()
rsi2 = (100 - 100 / (1 + up / dn)).to_numpy()
ibs = ((spy - L["SPY"]) / (H["SPY"] - L["SPY"])).to_numpy()


def trend_states(bufs):
    st = {b: True for b in bufs}
    def step(i):
        for b in bufs:
            if st[b] and px[i] < sma200[i] * (1 - b):
                st[b] = False
            elif not st[b] and px[i] > sma200[i] * (1 + b):
                st[b] = True
        return sum(st.values()) / len(bufs)
    return step


def ens(bufs, lev=3.0, bear=None, bear_lev=3.0):
    """버퍼 앙상블: on 비율 × lev. bear=(kind, th, max) 면 '전부 off' 구간에서 단기 반등 스윙."""
    step = trend_states(bufs)
    sw = {"on": False, "days": 0}
    log = []
    def f(i):
        if not np.isfinite(sma200[i]):
            return None
        frac = step(i)
        # 스윙 상태 갱신(하락국면 전용)
        if bear is not None:
            kind, th, mx = bear
            if not sw["on"]:
                ent = (rsi2[i] < th) if kind == "rsi2" else (ibs[i] < th)
                if ent and frac == 0:
                    sw["on"], sw["days"], sw["entry"] = True, 0, i
            else:
                sw["days"] += 1
                ex = (px[i] > sma5[i]) if kind == "rsi2" else (ibs[i] > 0.8 or px[i] > hi[i - 1])
                if ex or sw["days"] >= mx or frac > 0:
                    sw["on"] = False
                    log.append((sw["entry"], i))
        lev_t = frac * lev
        if bear is not None and sw["on"]:
            lev_t = max(lev_t, bear_lev)
        return lev_to_w(lev_t)
    f.log = log
    return f


rows = []
start_i = idx.searchsorted(pd.Timestamp("1994-01-03")) - 1
rows.append(report("INCUMBENT 1.5x (11/7)", *run(mkt, lambda i: lev_to_w(1.5) if i == start_i or idx[i].year != idx[min(i + 1, len(idx) - 1)].year else None)))
for b in (0.0, 0.01, 0.02, 0.03):
    rows.append(report(f"trend3 buf{int(b*100)} (단일)", *run(mkt, ens([b]))))
rows.append(report("trend3 ENSEMBLE buf0~3", *run(mkt, ens([0, .01, .02, .03]))))
rows.append(report("trend3 ENSEMBLE buf0~5", *run(mkt, ens([0, .01, .02, .03, .04, .05]))))

# 하락국면 스윙: 파라미터 격자 전체를 본다(최적값 1개가 아니라 분포)
grid = [("rsi2", t, m) for t in (5, 10, 15, 25) for m in (3, 5, 10)] + [("ibs", t, m) for t in (0.1, 0.2, 0.3) for m in (3, 5)]
g_rows = []
for bl in (3.0, 2.0, 1.5):
    for g in grid:
        f = ens([0, .01, .02, .03], bear=g, bear_lev=bl)
        s, t, n = run(mkt, f)
        g_rows.append({"bear_lev": bl, "rule": f"{g[0]} th{g[1]} max{g[2]}", "CAGR": cagr(s), "MDD": mdd(s),
                       "94-09": cagr(s[:"2009"]), "10-26": cagr(s["2010":]), "trades/yr": n,
                       "swings": len(f.log)})
G = pd.DataFrame(g_rows)
base = run(mkt, ens([0, .01, .02, .03]))[0]
b94, b10 = cagr(base[:"2009"]), cagr(base["2010":])
print("=== 추세 버퍼 단일 vs 앙상블 (1994~2026) ===")
df = pd.DataFrame(rows).set_index("name")
show = df.copy()
for c in ["CAGR", "MDD", "94-11", "12-26", "12-19", "19-26", "MDD12-26", "worstY"]:
    show[c] = df[c].map("{:.1%}".format)
show["turn/yr"] = df["turn/yr"].map("{:.1f}".format); show["trades/yr"] = df["trades/yr"].map("{:.1f}".format)
print(show.to_string())
print(f"\n=== 하락국면 스윙 격자 (기준: 앙상블 94-09 {b94:.1%}, 10-26 {b10:.1%}, CAGR {cagr(base):.1%}, MDD {mdd(base):.1%}) ===")
for bl in (3.0, 2.0, 1.5):
    sub = G[G.bear_lev == bl]
    print(f"스윙 레버리지 {bl}x: 격자 {len(sub)}개 중 두 구간 모두 기준 초과 {((sub['94-09'] > b94) & (sub['10-26'] > b10)).mean():.0%}, "
          f"CAGR 중앙값 {sub.CAGR.median():.1%}, MDD 중앙값 {sub.MDD.median():.1%}, 스윙 연 {sub.swings.median()/32.8:.1f}회")
show = G.copy()
for c in ("CAGR", "MDD", "94-09", "10-26"):
    show[c] = G[c].map("{:.1%}".format)
show["trades/yr"] = G["trades/yr"].map("{:.1f}".format)
print(show[G.bear_lev == 3.0].to_string(index=False))
G.to_csv("/home/quant/quant-v31/scripts/research/round5_bear.csv", index=False)
df.to_csv("/home/quant/quant-v31/scripts/research/round5_ens.csv")

# 대표 규칙 1개의 거래 단위 통계 (rsi2 th10 max5, 3x)
f = ens([0, .01, .02, .03], bear=("rsi2", 10, 5), bear_lev=3.0)
run(mkt, f)
spy_o = O["SPY"].to_numpy()
tr = [(idx[a].date(), idx[b].date(), spy_o[b + 1] / spy_o[a + 1] - 1) for a, b in f.log if b + 1 < len(idx)]
r = np.array([x[2] for x in tr])
print(f"\n대표 rsi2<10 max5: 스윙 {len(r)}건, SPY 기준 거래당 중앙 {np.median(r):+.2%}, 평균 {r.mean():+.2%}, 승률 {(r > 0).mean():.0%}, "
      f"3배 환산 최악 {3 * r.min():+.1%}")
yr = pd.Series([x[2] for x in tr], index=pd.to_datetime([x[0] for x in tr])).groupby(lambda t: t.year).agg(["count", "mean"])
print("연도별 스윙 (건수, SPY 평균수익):", {y: (int(c), f"{m:+.1%}") for y, (c, m) in yr.iterrows()})
