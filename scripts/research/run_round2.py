#!/usr/bin/env python
"""§22.AO-69 2라운드 — 추세×레버리지 강건성.
 (a) 파라미터 민감도: SMA 길이 × 버퍼 × 레버리지 × off 자산 (SPY 1994~2026, 시가 체결)
 (b) 장기 스트레스: ^GSPC 1962~2026 (1973-74·1987·2000-02·2008 포함), 판정 t 종가 → 체결 t+1 종가.
     ^GSPC 는 가격지수 → 배당을 시기별 근사(아래 DIV)로 더한다. 절대수준이 아니라 **전략 간 비교**용.
"""
import numpy as np, pandas as pd
from lev_lab import load, calibrate, Market, lev_to_w, run, report, cagr, mdd

pd.set_option("display.width", 250)

# ───────── (a) 민감도 ─────────
O, C, H, L, rf = load()
cal = calibrate(O, C, rf)
mkt = Market(O, C, H, L, rf, {2: cal[2]["extra_drag"], 3: cal[3]["extra_drag"]})
idx = mkt.idx
spy = C["SPY"].to_numpy()


def trend(lev, n=200, buf=0.02, off="CASH", off_lev=0.0):
    sma = pd.Series(spy).rolling(n).mean().to_numpy()
    st = {"on": True}
    def f(i):
        if not np.isfinite(sma[i]):
            return None
        if st["on"] and spy[i] < sma[i] * (1 - buf):
            st["on"] = False
        elif not st["on"] and spy[i] > sma[i] * (1 + buf):
            st["on"] = True
        if st["on"]:
            return lev_to_w(lev)
        if off == "CASH":
            return lev_to_w(off_lev)
        w = lev_to_w(off_lev); w = {k: v for k, v in w.items() if k != "CASH"}
        w[off] = 1 - sum(w.values())
        return w
    return f


rows = []
start_i = idx.searchsorted(pd.Timestamp("1994-01-03")) - 1
inc = run(mkt, lambda i: lev_to_w(1.5) if i == start_i or idx[i].year != idx[min(i + 1, len(idx) - 1)].year else None, band=0)
rows.append(report("INCUMBENT 1.5x", *inc))
for lev in (2.0, 2.5, 3.0):
    for n in (150, 200, 250):
        for buf in (0.0, 0.01, 0.02, 0.03):
            rows.append(report(f"trend {lev}x SMA{n} buf{int(buf*100)}", *run(mkt, trend(lev, n, buf), band=0.02)))
# off 자산 변형 (2002~ 데이터 → 1994~2002 는 CASH 와 같음: TLT/IEF NaN 이면 0 처리 위험 → 2003 시작으로 별도)
for off in ("IEF", "TLT"):
    rows.append(report(f"trend 3.0x SMA200 buf2 off={off} [2003~]", *run(mkt, trend(3.0, 200, 0.02, off), start="2003-01-02", band=0.02)))
rows.append(report("trend 3.0x SMA200 buf2 off=CASH [2003~]", *run(mkt, trend(3.0, 200, 0.02), start="2003-01-02", band=0.02)))
rows.append(report("INCUMBENT 1.5x [2003~]", *run(mkt, lambda i: lev_to_w(1.5) if idx[i].year != idx[min(i + 1, len(idx) - 1)].year or idx[i] == idx[idx.searchsorted(pd.Timestamp('2003-01-02')) - 1] else None, start="2003-01-02")))
# 오프 시 1x 유지(완전 현금 대신)
rows.append(report("trend 3.0x SMA200 buf2 off=1.0x", *run(mkt, trend(3.0, 200, 0.02, "CASH", 1.0), band=0.02)))
rows.append(report("trend 2.0x SMA200 buf2 off=1.0x", *run(mkt, trend(2.0, 200, 0.02, "CASH", 1.0), band=0.02)))

df = pd.DataFrame(rows).set_index("name")
show = df.copy()
for c in ["CAGR", "MDD", "94-11", "12-26", "12-19", "19-26", "MDD12-26", "worstY"]:
    show[c] = df[c].map("{:.1%}".format)
show["turn/yr"] = df["turn/yr"].map("{:.1f}".format); show["trades/yr"] = df["trades/yr"].map("{:.1f}".format)
print(show.to_string())
df.to_csv("/home/quant/quant-v31/scripts/research/round2a.csv")

# ───────── (b) 장기 스트레스 1962~2026 ─────────
g = pd.read_parquet("/home/quant/quant-v31/data/parquet/etf/gspc_long.parquet"); g["d"] = pd.to_datetime(g.d)
G = g.pivot(index="d", columns="symbol", values="c")
px = G["^GSPC"].dropna(); px = px[px.index >= "1960-01-01"]
irx = G["^IRX"].reindex(px.index).ffill()
rfd = (irx / 100 / 252).shift(1).fillna(0)
DIV = pd.Series(np.select([px.index.year < 1980, px.index.year < 1995, px.index.year < 2009],
                          [0.035, 0.035, 0.017], 0.019), index=px.index) / 252
r1 = (px.pct_change().fillna(0) + DIV)
EXT = {1: 0.0009, 2: 0.0089 + cal[2]["extra_drag"], 3: 0.0091 + cal[3]["extra_drag"]}


def lev_ret(lev):
    return lev * r1 - (lev - 1) * rfd - EXT[int(lev)] / 252


R = {1: r1 - EXT[1] / 252, 2: lev_ret(2), 3: lev_ret(3), 0: rfd}
COST = 0.003


def long_run(target_lev):
    """target_lev: 일자별 목표 레버리지(판정일 기준). 체결은 다음 거래일 종가 → 수익은 그 다음날부터."""
    tl = target_lev.shift(1)          # t 판정 → t+1 종가 체결
    w = {k: pd.Series(0.0, index=px.index) for k in (0, 1, 2, 3)}
    for i_, l in enumerate(tl.to_numpy()):
        pass
    l = tl.fillna(0).clip(0, 3).to_numpy()
    wd = {0: np.where(l <= 1, 1 - l, 0), 1: np.where(l <= 1, l, np.where(l <= 2, 2 - l, 0)),
          2: np.where((l > 1) & (l <= 2), l - 1, np.where(l > 2, 3 - l, 0)), 3: np.where(l > 2, l - 2, 0)}
    W = pd.DataFrame(wd, index=px.index)
    rr = pd.DataFrame({k: R[k] for k in (0, 1, 2, 3)})
    port = (W.shift(1).fillna(0) * rr).sum(axis=1)              # 체결 다음날부터 보유 수익
    turn = W.diff().abs().drop(columns=[0]).sum(axis=1).fillna(0)
    port = port - COST * turn.shift(1).fillna(0)
    eq = (1 + port).cumprod()
    return eq, float(turn.sum() / 2 / ((px.index[-1] - px.index[0]).days / 365.25))


sma = px.rolling(200).mean()


def trend_series(lev, buf=0.02, off=0.0):
    on = True; out = []
    for p, s in zip(px.to_numpy(), sma.to_numpy()):
        if np.isfinite(s):
            if on and p < s * (1 - buf):
                on = False
            elif not on and p > s * (1 + buf):
                on = True
        out.append(lev if on else off)
    return pd.Series(out, index=px.index)


rv = r1.rolling(20).std() * np.sqrt(252); rv60 = r1.rolling(60).std() * np.sqrt(252)


def voltgt_series(T, lo=0.5, hi=3.0, band=0.3):
    est = np.maximum(rv.to_numpy(), rv60.to_numpy()); cur = 1.5; out = []
    for v in est:
        if np.isfinite(v) and v > 0:
            tgt = float(np.clip(T / v, lo, hi))
            if abs(tgt - cur) > band:
                cur = tgt
        out.append(cur)
    return pd.Series(out, index=px.index)


def condvol_series():
    q20 = rv.rolling(2520, min_periods=1260).quantile(0.2); q80 = rv.rolling(2520, min_periods=1260).quantile(0.8)
    me = pd.Series(px.index.month, index=px.index); is_me = me != me.shift(-1)
    cur = 1.5; out = []
    for d, v, a, b, m in zip(px.index, rv.to_numpy(), q20.to_numpy(), q80.to_numpy(), is_me.to_numpy()):
        if m and np.isfinite(a):
            cur = 0.75 if v > b else (2.0 if v < a else 1.5)
        out.append(cur)
    return pd.Series(out, index=px.index)


def fastslow_series(full):
    tr = (1 + r1).cumprod(); cash = (1 + rfd).cumprod()
    ex12 = tr / tr.shift(252) - cash / cash.shift(252); ex1 = tr / tr.shift(21) - cash / cash.shift(21)
    me = pd.Series(px.index.month, index=px.index); is_me = me != me.shift(-1)
    cur = full; out = []
    for a, b, m in zip(ex12.to_numpy(), ex1.to_numpy(), is_me.to_numpy()):
        if m and np.isfinite(a) and np.isfinite(b):
            cur = full if (a > 0 and b > 0) else (0.0 if (a < 0 and b < 0) else full / 2)
        out.append(cur)
    return pd.Series(out, index=px.index)


rows = []
yrs = px.index.year
for name, tl in [("1x B&H", pd.Series(1.0, index=px.index)), ("INCUMBENT 1.5x (daily)", pd.Series(1.5, index=px.index)),
                 ("const 2x", pd.Series(2.0, index=px.index)),
                 ("trend 1.5x", trend_series(1.5)), ("trend 2x", trend_series(2.0)), ("trend 2.5x", trend_series(2.5)),
                 ("trend 3x", trend_series(3.0)), ("trend 3x off1x", trend_series(3.0, off=1.0)),
                 ("trend 3x buf0", trend_series(3.0, buf=0.0)), ("trend 3x buf3", trend_series(3.0, buf=0.03)),
                 ("trend 2.5x buf2", trend_series(2.5)),
                 ("voltgt T24 max(20,60) [0.5,3] band.3", voltgt_series(0.24)),
                 ("condvol 1.5x (0.75/2.0 by 10y quintile)", condvol_series()),
                 ("fast/slow 12m&1m 3x/1.5x/0", fastslow_series(3.0)),
                 ("fast/slow 12m&1m 2x/1x/0", fastslow_series(2.0))]:
    eq, turn = long_run(tl)
    eq = eq[eq.index >= "1962-01-01"]
    yr = eq.resample("YE").last().pct_change().dropna(); yr = yr[yr.index.year < 2026]
    seg = lambda a, b: cagr(eq[a:b])
    rows.append({"name": name, "CAGR62-26": cagr(eq), "MDD": mdd(eq), "62-79": seg("1962", "1979"), "80-99": seg("1980", "1999"),
                 "00-11": seg("2000", "2011"), "12-26": seg("2012", "2026"), "MDD73-74": mdd(eq["1972-12":"1975-06"]),
                 "1987(Oct)": float(eq[:"1987-10-31"].iloc[-1] / eq[:"1987-09-30"].iloc[-1] - 1),
                 "MDD00-02": mdd(eq["2000":"2003-06"]), "MDD08-09": mdd(eq["2007-10":"2009-12"]),
                 "yrs>=18%": f"{(yr >= 0.18).sum()}/{len(yr)}", "worstY": float(yr.min()), "turn/yr": turn})
df = pd.DataFrame(rows).set_index("name")
show = df.copy()
for c in df.columns:
    if c not in ("yrs>=18%", "turn/yr"):
        show[c] = df[c].map(lambda x: "n/a" if pd.isna(x) else f"{x:.1%}")
show["turn/yr"] = df["turn/yr"].map("{:.1f}".format)
print("\n=== 장기 스트레스 ^GSPC 1962~2026 (배당 근사, t+1 종가 체결) ===")
print(show.to_string())
df.to_csv("/home/quant/quant-v31/scripts/research/round2b.csv")
