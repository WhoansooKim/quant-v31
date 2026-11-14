#!/usr/bin/env python
"""§22.AO-70 4라운드 — (A) 지수 ETF 단기 스윙 × 수수료 스윕 (B) 추세×3배의 off 자산 (C) 주식·채권 레버리지 혼합.

(A) SPY OHLC(1994~)로 판정, 3배 합성 ETF 로 체결. t 종가 판정 → t+1 시가 체결.
    워크포워드: 규칙별 파라미터를 1994~2009 에서 고르고 2010~2026 에서 평가. 비용 0.30/0.15/0.07/0.03%.
    비교 기준: 추세×3배(현행, SMA200 buf0)와 같은 창·같은 비용.
(B) off(SPY<SMA200) 때 BIL 대신 IEF/TLT/GLD/추세필터 채권. 2003~ (채권 ETF 데이터 시작).
(C) UPRO+TMF(합성 3배 TLT) 55/45 분기 리밸런스, 채권 추세게이트 변형. 2003~.
"""
import itertools
import numpy as np, pandas as pd
import lev_lab as LL
from lev_lab import load, calibrate, Market, lev_to_w, run, cagr, mdd

pd.set_option("display.width", 250)
O, C, H, L, rf = load()
cal = calibrate(O, C, rf)
mkt = Market(O, C, H, L, rf, {2: cal[2]["extra_drag"], 3: cal[3]["extra_drag"]})
idx = mkt.idx
spy = C["SPY"]; px = spy.to_numpy()
hi, lo, op = H["SPY"].to_numpy(), L["SPY"].to_numpy(), O["SPY"].to_numpy()
sma200 = spy.rolling(200).mean().to_numpy()
sma5 = spy.rolling(5).mean().to_numpy()
d = spy.diff(); up = d.clip(lower=0).ewm(alpha=1 / 2).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 2).mean()
rsi2 = (100 - 100 / (1 + up / dn)).to_numpy()
ibs = ((spy - L["SPY"]) / (H["SPY"] - L["SPY"])).to_numpy()
hh = {n: spy.rolling(n).max().to_numpy() for n in (20, 55)}
ll = {n: spy.rolling(n).min().to_numpy() for n in (10, 20)}
IS_END, OOS_START = "2009-12-31", "2010-01-04"


def trend3(i, st={}):
    return lev_to_w(3.0 if px[i] > sma200[i] else 0.0) if np.isfinite(sma200[i]) else None


def swing(kind, p, base_off=0.0, filt=True):
    """단기 스윙: 신호 시 3배, 청산 후 base_off 레버리지(0=현금). filt=True 면 SPY>SMA200 일 때만 진입."""
    st = {"on": False, "days": 0}
    def f(i):
        if not np.isfinite(sma200[i]):
            return None
        ok = (px[i] > sma200[i]) if filt else True
        if not st["on"]:
            if kind == "rsi2":
                ent = rsi2[i] < p["th"]
            elif kind == "ibs":
                ent = ibs[i] < p["th"]
            elif kind == "3low":
                ent = i >= 3 and px[i] < px[i - 1] < px[i - 2] < px[i - 3]
            elif kind == "donch":
                ent = px[i] >= hh[p["n"]][i]
            if ent and ok:
                st["on"], st["days"] = True, 0
        else:
            st["days"] += 1
            if kind in ("rsi2", "3low"):
                ex = px[i] > sma5[i] or st["days"] >= p["max"]
            elif kind == "ibs":
                ex = ibs[i] > 0.8 or (i > 0 and px[i] > hi[i - 1]) or st["days"] >= p["max"]
            elif kind == "donch":
                ex = px[i] <= ll[p["x"]][i]
            if ex:
                st["on"] = False
        return lev_to_w(3.0 if st["on"] else base_off)
    return f


def combo(kind, p):
    """추세×3배 + 하락국면(SPY<SMA200)에서만 단기 스윙 반등 매매 — 현행 코어에 스윙을 더하는 형태."""
    sw = swing(kind, p, 0.0, filt=False)
    def f(i):
        if not np.isfinite(sma200[i]):
            return None
        w = sw(i)                      # 상태는 매일 갱신
        if px[i] > sma200[i]:
            return lev_to_w(3.0)
        return w
    return f


GRID = {
    "rsi2": [{"th": t, "max": m} for t in (5, 10, 15, 25) for m in (5, 10)],
    "ibs": [{"th": t, "max": m} for t in (0.1, 0.2, 0.3) for m in (3, 5)],
    "3low": [{"max": m} for m in (5, 10)],
    "donch": [{"n": n, "x": x} for n in (20, 55) for x in (10, 20)],
}
COSTS = (0.003, 0.0015, 0.0007, 0.0003)

rows = []
for cost in COSTS:
    LL.COST = cost
    base_is, _, _ = run(mkt, trend3, end=IS_END)
    base_oos, bt, bn = run(mkt, trend3, start=OOS_START)
    rows.append({"cost": cost, "rule": "TREND×3 (현행)", "param": "SMA200", "IS": cagr(base_is), "OOS": cagr(base_oos),
                 "MDD_OOS": mdd(base_oos), "trades/yr": bn})
    for fam, mk in (("swing", lambda k, p: swing(k, p)), ("trend+bear-swing", combo)):
        for kind, grid in GRID.items():
            if fam == "trend+bear-swing" and kind == "donch":
                continue
            best = None
            for p in grid:
                s_is, _, _ = run(mkt, mk(kind, p), end=IS_END, band=0.0)
                if best is None or cagr(s_is) > best[0]:
                    best = (cagr(s_is), p)
            s_oos, t, n = run(mkt, mk(kind, best[1]), start=OOS_START)
            rows.append({"cost": cost, "rule": f"{fam}:{kind}", "param": str(best[1]), "IS": best[0], "OOS": cagr(s_oos),
                         "MDD_OOS": mdd(s_oos), "trades/yr": n})
A = pd.DataFrame(rows)
show = A.copy()
for c in ("IS", "OOS", "MDD_OOS"):
    show[c] = A[c].map("{:.1%}".format)
show["trades/yr"] = A["trades/yr"].map("{:.0f}".format)
show["cost"] = A["cost"].map(lambda x: f"{x*100:.2f}%")
print("=== (A) 지수 ETF 단기 스윙 — IS 1994~2009 선택 → OOS 2010~2026 ===")
print(show.to_string(index=False))
A.to_csv("/home/quant/quant-v31/scripts/research/round4a.csv", index=False)

# ───────── (B) off 자산 ─────────
LL.COST = 0.003
# 합성 3배 TLT (TMF 대용: 보수 1.06%, 추가 드래그는 UPRO 보정치 사용)
tlt_c = C["TLT"]; tlt_o = O["TLT"]
r_t = tlt_c.pct_change()
drag = 2 * rf + (0.0106 + cal[3]["extra_drag"]) / 252
tmf_c = (1 + (3 * r_t - drag).fillna(0)).cumprod().where(tlt_c.notna())
tmf_o = tmf_c.shift(1) * (1 + 3 * (tlt_o / tlt_c.shift(1) - 1))
mkt.px_o["TMF"], mkt.px_c["TMF"] = tmf_o, tmf_c
tlt_sma = tlt_c.rolling(200).mean().to_numpy(); tltv = tlt_c.to_numpy()
ief_sma = C["IEF"].rolling(200).mean().to_numpy(); iefv = C["IEF"].to_numpy()


def trend_off(off):
    def f(i):
        if not np.isfinite(sma200[i]):
            return None
        if px[i] > sma200[i]:
            return lev_to_w(3.0)
        if off == "BIL":
            return {"CASH": 1.0}
        if off == "IEF/trend":
            return {"IEF": 1.0} if iefv[i] > ief_sma[i] else {"CASH": 1.0}
        if off == "TLT/trend":
            return {"TLT": 1.0} if tltv[i] > tlt_sma[i] else {"CASH": 1.0}
        return {off: 1.0}
    return f


rows = []
S0 = "2004-12-01"   # GLD 시작 + SMA 워밍업
for off in ("BIL", "IEF", "TLT", "GLD", "IEF/trend", "TLT/trend"):
    s, t, n = run(mkt, trend_off(off), start=S0)
    rows.append({"name": f"TREND×3 off={off}", "CAGR05-26": cagr(s), "MDD": mdd(s), "05-11": cagr(s[:"2011"]),
                 "12-26": cagr(s["2012":]), "2022": float(s["2022-12-30":].iloc[0] / s[:"2021-12-31"].iloc[-1] - 1), "trades/yr": n})


# ───────── (C) 주식·채권 레버리지 혼합 ─────────
def mix(ws, gate_bond=False, gate_eq=False, months=(1, 4, 7, 10)):
    def f(i):
        if i + 1 >= len(idx) or not np.isfinite(sma200[i]):
            return None
        rebal = idx[i + 1].month != idx[i].month and idx[i + 1].month in months
        eq_on = (px[i] > sma200[i]) if gate_eq else True
        bd_on = (tltv[i] > tlt_sma[i]) if gate_bond else True
        key = (eq_on, bd_on)
        if not rebal and f.last == key:
            return None
        f.last = key
        w = {}
        for k, v in ws.items():
            if k in ("L3", "L2", "SPY") and not eq_on:
                w["CASH"] = w.get("CASH", 0) + v
            elif k in ("TMF", "TLT") and not bd_on:
                w["CASH"] = w.get("CASH", 0) + v
            else:
                w[k] = v
        return w
    f.last = None
    return f


for name, ws, gb, ge in [("UPRO55/TMF45 분기", {"L3": .55, "TMF": .45}, False, False),
                         ("UPRO55/TMF45 채권추세게이트", {"L3": .55, "TMF": .45}, True, False),
                         ("UPRO55/TMF45 주식·채권 추세게이트", {"L3": .55, "TMF": .45}, True, True),
                         ("UPRO70/TLT30 주식·채권 추세게이트", {"L3": .70, "TLT": .30}, True, True),
                         ("SSO60/TMF40 분기", {"L2": .60, "TMF": .40}, False, False)]:
    s, t, n = run(mkt, mix(ws, gb, ge), start=S0)
    rows.append({"name": name, "CAGR05-26": cagr(s), "MDD": mdd(s), "05-11": cagr(s[:"2011"]), "12-26": cagr(s["2012":]),
                 "2022": float(s["2022-12-30":].iloc[0] / s[:"2021-12-31"].iloc[-1] - 1), "trades/yr": n})
B = pd.DataFrame(rows)
show = B.copy()
for c in ("CAGR05-26", "MDD", "05-11", "12-26", "2022"):
    show[c] = B[c].map("{:.1%}".format)
show["trades/yr"] = B["trades/yr"].map("{:.1f}".format)
print("\n=== (B)(C) off 자산 · 주식채권 혼합 — 2005-01~2026-11, 0.30%/편 ===")
print(show.to_string(index=False))
B.to_csv("/home/quant/quant-v31/scripts/research/round4bc.csv", index=False)
