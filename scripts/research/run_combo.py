#!/usr/bin/env python
"""§22.AO-70 결합 측정 — 추세×3배 코어(버퍼 앙상블 0~5%, UPRO 비율 + 현금) × J(MA21/MA200 상위10, 월간).
창: 2012-03 ~ 패널 끝 (J 데이터 한계). 2026 제외 구간(2012-03~2025-12)을 함께 본다.
(a) 고정 혼합 w_core/w_J, 월말 종가 슬리브 리밸런스(이동분 × cost)
(b) 코어 off 비율을 BIL 대신 J 로 — 판정 t 종가, 전환 t+1 종가(양쪽 같은 지연, 코어 단독도 같은 규약으로 재계산)
(c) J 슬리브는 코어 on 일 때만(=SPY 추세 필터) — 참고
"""
import numpy as np, pandas as pd
import lev_lab as LL
from lev_lab import load, calibrate, Market, run
from stock_lab import Panel, simulate

pd.set_option("display.width", 250)
O, C, H, L, rf = load()
cal = calibrate(O, C, rf)
mkt = Market(O, C, H, L, rf, {2: cal[2]["extra_drag"], 3: cal[3]["extra_drag"]})
spy = C["SPY"]; px = spy.to_numpy(); sma = spy.rolling(200).mean().to_numpy()
BUFS = [0, .01, .02, .03, .04, .05]


def frac_series():
    st = {b: True for b in BUFS}; out = np.full(len(px), np.nan)
    for i in range(len(px)):
        if not np.isfinite(sma[i]):
            continue
        for b in BUFS:
            if st[b] and px[i] < sma[i] * (1 - b): st[b] = False
            elif not st[b] and px[i] > sma[i] * (1 + b): st[b] = True
        out[i] = sum(st.values()) / len(BUFS)
    return pd.Series(out, index=mkt.idx)


FR = frac_series()
fr_np = FR.to_numpy()
core_eq, _, _ = run(mkt, lambda i: None if not np.isfinite(fr_np[i]) else {"L3": fr_np[i], "CASH": 1 - fr_np[i]}, start="1994-01-03")

P = Panel(); D = P.df
Cp, Vp = D(P.C), D(P.V)
liq = ((Cp * Vp).rolling(50).mean() >= 20e6) & (Cp >= 10)
me = pd.Series(P.dates.month, index=P.dates); me = (me != me.shift(-1)).to_numpy()
sJ = (Cp.rolling(21).mean() / Cp.rolling(200).mean()).where(liq).to_numpy(dtype=float)

L3c = mkt.px_c["L3"]; cashc = mkt.px_c["CASH"]


def stats(name, eq):
    eq = eq / eq.iloc[0]
    def cg(s):
        y = (s.index[-1] - s.index[0]).days / 365.25; return (s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1
    ex = eq[:"2025-12-31"]
    yr = pd.concat([eq.iloc[:1], eq.resample("YE").last()]).pct_change().dropna()
    yr = yr[yr.index.year < 2026]
    r6 = eq.pct_change(126).dropna(); r6x = ex.pct_change(126).dropna()
    return {"name": name, "CAGR": cg(eq), "CAGR~2025": cg(ex), "MDD": float((eq / eq.cummax() - 1).min()),
            "6m>=9%": float((r6 >= .09).mean()), "6m>=9%~25": float((r6x >= .09).mean()), "6m_p10": float(r6.quantile(.1)),
            "worstY": float(yr.min()), "yrs>=18.8%": f"{(yr >= .188).sum()}/{len(yr)}", "eq": eq}


rows = []
for cost in (0.003, 0.0012):
    LL.COST = cost
    core_eq, _, _ = run(mkt, lambda i: None if not np.isfinite(fr_np[i]) else {"L3": fr_np[i], "CASH": 1 - fr_np[i]}, start="1994-01-03")
    J_eq, _ = simulate(P, sJ, K=10, cost=cost, mode="rebal", rebal_days=me, hold_rank=30)
    ix = J_eq.index.intersection(core_eq.index); ix = ix[ix >= "2012-03-01"]
    ce, je = core_eq.reindex(ix), J_eq.reindex(ix)
    rc, rj = ce.pct_change().fillna(0).to_numpy(), je.pct_change().fillna(0).to_numpy()
    mend = pd.Series(ix.month, index=ix); mend = (mend != mend.shift(-1)).to_numpy()
    tag = f"{cost*100:.2f}%"
    rows.append(stats(f"[{tag}] 코어 단독", ce)); rows.append(stats(f"[{tag}] J 단독", je))
    corr = float(pd.Series(rc).corr(pd.Series(rj)))
    # (a) 고정 혼합
    for wc in (0.8, 0.7, 0.6, 0.5):
        a, b = wc, 1 - wc; eq = np.empty(len(ix)); V = 1.0
        for t in range(len(ix)):
            a *= 1 + rc[t]; b *= 1 + rj[t]; V = a + b
            if mend[t]:
                mv = abs(a - wc * V); V -= 2 * cost * mv; a, b = wc * V, (1 - wc) * V
            eq[t] = V
        rows.append(stats(f"[{tag}] (a) 코어{int(wc*100)}+J{int((1-wc)*100)} 월간", pd.Series(eq, ix)))
    # (b)/(c): 지연 규약 — t 판정 비중을 t+2 수익부터(=t+1 종가 전환)
    f = FR.reindex(ix).to_numpy()
    rL3 = L3c.reindex(ix).pct_change().fillna(0).to_numpy(); rcash = cashc.reindex(ix).pct_change().fillna(0).to_numpy()
    def mix(wfun):
        V = 1.0; eq = np.empty(len(ix)); prev = None
        for t in range(len(ix)):
            if t >= 2:
                w = wfun(f[t - 2]); V *= 1 + sum(w[k] * r for k, r in (("L3", rL3[t]), ("J", rj[t]), ("CASH", rcash[t])))
                if prev is not None:
                    V -= cost * V * sum(abs(w[k] - prev[k]) for k in w)   # 슬리브 간 이동분 (양 다리)
                prev = w
            eq[t] = V
        return pd.Series(eq, ix)
    rows.append(stats(f"[{tag}] 코어 단독(지연 규약)", mix(lambda x: {"L3": x, "J": 0.0, "CASH": 1 - x})))
    rows.append(stats(f"[{tag}] (b) 코어 off분 → J", mix(lambda x: {"L3": x, "J": 1 - x, "CASH": 0.0})))
    rows.append(stats(f"[{tag}] (c) 70/30, J 는 코어 on 비율만큼", mix(lambda x: {"L3": 0.7 * x, "J": 0.3 * x, "CASH": 1 - x})))
    print(tag, "일간 수익 상관(코어,J) =", round(corr, 3), "| 창", ix[0].date(), "~", ix[-1].date())
    # 연도별
    yr = pd.DataFrame({k: pd.concat([s.iloc[:1], s.resample("YE").last()]).pct_change().dropna()
                       for k, s in (("코어", ce), ("J", je), ("70/30", rows[3]["eq"] if cost == 0.003 else rows[-8]["eq"]))})
    if cost == 0.003:
        print((yr * 100).round(1).to_string())

df = pd.DataFrame([{k: v for k, v in r.items() if k != "eq"} for r in rows])
show = df.copy()
for c in ("CAGR", "CAGR~2025", "MDD", "6m>=9%", "6m>=9%~25", "6m_p10", "worstY"):
    show[c] = df[c].map(lambda v: f"{v:.1%}")
print(show.to_string(index=False))
df.to_csv("/home/quant/quant-v31/scripts/research/combo.csv", index=False)
