#!/usr/bin/env python
"""§22.AO-69 1라운드 — 문헌 후보 vs 현행 코어(1.5배), 1994~2026 합성 포함."""
import sys
import numpy as np, pandas as pd
from lev_lab import load, calibrate, Market, lev_to_w, run, report

O, C, H, L, rf = load()
cal = calibrate(O, C, rf)
mkt = Market(O, C, H, L, rf, {2: cal[2]["extra_drag"], 3: cal[3]["extra_drag"]})
idx = mkt.idx
spy = C["SPY"]
ret = spy.pct_change()
sma200 = spy.rolling(200).mean().to_numpy()
sma5 = spy.rolling(5).mean().to_numpy()
vol20 = (ret.rolling(20).std() * np.sqrt(252)).to_numpy()
ewv = (np.sqrt(ret.pow(2).ewm(halflife=10).mean() * 252)).to_numpy()
px = spy.to_numpy()
# RSI(2)
d = spy.diff(); up = d.clip(lower=0).ewm(alpha=1 / 2).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 2).mean()
rsi2 = (100 - 100 / (1 + up / dn)).to_numpy()
ibs = ((C["SPY"] - L["SPY"]) / (H["SPY"] - L["SPY"])).to_numpy()
years = idx.year.to_numpy()
month = idx.month.to_numpy()
# 월말 기준 거래일 순번 (TOM: 월 마지막 거래일 ~ 다음달 3번째 거래일)
dom_from_end = pd.Series(1, index=idx).groupby([idx.year, idx.month]).cumcount(ascending=False).to_numpy()
dom = pd.Series(1, index=idx).groupby([idx.year, idx.month]).cumcount().to_numpy()

rows = []


def const(lev, rebal="annual"):
    w = lev_to_w(lev)
    def f(i):
        if rebal == "annual":
            return w if (i + 1 < len(idx) and years[i + 1] != years[i]) or i == START_I else None
        return w
    return f


START_I = idx.searchsorted(pd.Timestamp("1994-01-03")) - 1


def add(name, f, band=0.0):
    s, turn, ntr = run(mkt, f, band=band)
    rows.append(report(name, s, turn, ntr))
    return s


# ── 기준 ──
add("SPY 1x (B&H)", const(1.0))
add("INCUMBENT 1.5x annual", const(1.5))
add("const 2.0x annual", const(2.0))
add("const 1.5x daily-band5%", lambda i: lev_to_w(1.5), band=0.05)


# ── A. 변동성 타깃 (Moreira-Muir 2017) ──
def voltgt(T, cap=3.0, est=vol20, trend=False, floor_lev=0.0):
    def f(i):
        v = est[i]
        if not np.isfinite(v) or v <= 0:
            return None
        lev = min(cap, T / v)
        if trend and np.isfinite(sma200[i]) and px[i] < sma200[i]:
            lev = min(lev, floor_lev)
        return lev_to_w(lev)
    return f


for T in (0.15, 0.20, 0.25):
    for band in (0.10, 0.20):
        add(f"voltgt T{int(T*100)} cap3 band{int(band*100)}", voltgt(T), band=band)
add("voltgt T20 EWMA cap3 band20", voltgt(0.20, est=ewv), band=0.20)
add("voltgt T20 cap2 band10", voltgt(0.20, cap=2.0), band=0.10)


# ── B. 추세 + 레버리지 (Gayed-Bilello 2016) ──
def trend_lev(lev, buf=0.0, off=0.0):
    state = {"on": True}
    def f(i):
        if not np.isfinite(sma200[i]):
            return None
        if state["on"] and px[i] < sma200[i] * (1 - buf):
            state["on"] = False
        elif not state["on"] and px[i] > sma200[i] * (1 + buf):
            state["on"] = True
        return lev_to_w(lev if state["on"] else off)
    return f


for lev in (1.5, 2.0, 3.0):
    add(f"trend SMA200 {lev}x/cash buf2%", trend_lev(lev, 0.02), band=0.02)

# ── C. 추세 + 변동성 결합 ──
for T in (0.20, 0.25):
    add(f"voltgt T{int(T*100)} + trend(off→0.5x) band15", voltgt(T, trend=True, floor_lev=0.5), band=0.15)


# ── D. 단기 평균회귀 오버레이 (Connors RSI2 / IBS) — 기본 1.5x, 과매도 시 3x ──
def mr_overlay(base, boost, sig="rsi2", th=10):
    state = {"on": False}
    def f(i):
        if not np.isfinite(sma200[i]):
            return None
        if not state["on"]:
            cond = (rsi2[i] < th) if sig == "rsi2" else (ibs[i] < th / 100)
            if cond and px[i] > sma200[i]:
                state["on"] = True
        else:
            if px[i] > sma5[i]:
                state["on"] = False
        return lev_to_w(boost if state["on"] else base)
    return f


add("MR RSI2<10 base1.5→3x", mr_overlay(1.5, 3.0, "rsi2", 10), band=0.05)
add("MR IBS<0.2 base1.5→3x", mr_overlay(1.5, 3.0, "ibs", 20), band=0.05)


# ── E. 월말효과 오버레이 (McConnell-Xu 2008) ──
def tom(base, boost):
    def f(i):
        if i + 1 >= len(idx):
            return None
        # 다음 거래일(체결일)이 TOM 창(월 마지막 거래일 ~ 다음달 3번째 거래일)이면 boost
        j = i + 1
        in_tom = dom_from_end[j] == 0 or dom[j] <= 2
        return lev_to_w(boost if in_tom else base)
    return f


add("TOM base1.5→3x", tom(1.5, 3.0), band=0.05)

pd.set_option("display.width", 250)
df = pd.DataFrame(rows).set_index("name")
fmt = {c: "{:.1%}" for c in df.columns if c not in ("yrs>=18%", "turn/yr", "trades/yr")}
out = df.copy()
for c_, f_ in fmt.items():
    out[c_] = df[c_].map(f_.format)
out["turn/yr"] = df["turn/yr"].map("{:.1f}x".format); out["trades/yr"] = df["trades/yr"].map("{:.0f}".format)
print(out.to_string())
df.to_csv("/home/quant/quant-v31/scripts/research/round1.csv")
