#!/usr/bin/env python
"""§22.AO-69 연구 하네스 — 지수 레버리지 전략을 1994~2026 (32년) 동일 조건으로 측정.

왜 새로 만드나: §22.AO-68 측정창(2012~2026)에는 2000~02·2008 같은 장기 약세장이 없다.
1.5배 코어 MDD −47% 도 이 창에서 나온 숫자다. 레버리지는 장기 약세장에서 결정된다.

데이터: SPY(1993~), ^IRX(T-bill), ^VIX. 레버리지 ETF 는 SPY 로 **합성**하고
실제 SSO(2006~)/UPRO(2009~)와 겹치는 구간에서 보정·검증한다 (calibrate()).

체결 모델(모든 전략 공통, §22.AO-65/66 교훈):
  - t 일 종가로 판정 → t+1 일 시가 체결
  - 비용: 거래금액 × 0.30% (KIS 0.25% + 슬리피지 5bp)
  - 현금 = T-bill 수익(^IRX). 거래 비용은 위험자산 매매에만.
"""
from __future__ import annotations
import numpy as np, pandas as pd

LONG = "/home/quant/quant-v31/data/parquet/etf/long_daily.parquet"
COST = 0.0030
EXP = {1: 0.0009, 2: 0.0089, 3: 0.0091}      # 연 보수
EXTRA = {1: 0.0, 2: None, 3: None}           # 스왑 스프레드 등 추가 드래그 — calibrate() 로 채움


def load():
    e = pd.read_parquet(LONG); e["d"] = pd.to_datetime(e.d)
    O = e.pivot(index="d", columns="symbol", values="o")
    C = e.pivot(index="d", columns="symbol", values="c")
    H = e.pivot(index="d", columns="symbol", values="h")
    L = e.pivot(index="d", columns="symbol", values="l")
    idx = C["SPY"].dropna().index
    O, C, H, L = (x.reindex(idx) for x in (O, C, H, L))
    rf = (C["^IRX"].ffill() / 100 / 252).shift(1).fillna(0)       # 전일 고시 금리로 당일 이자
    return O, C, H, L, rf


def synth(O, C, rf, lev, extra):
    """SPY 기반 일간 리셋 L배 ETF (시가·종가). 반환 (open, close) 시계열."""
    cc = C["SPY"].pct_change().fillna(0)
    on = (O["SPY"] / C["SPY"].shift(1) - 1).fillna(0)
    drag = (lev - 1) * rf + (EXP[lev] + extra) / 252
    r = lev * cc - drag
    close = (1 + r).cumprod()
    open_ = close.shift(1).fillna(1) * (1 + lev * on)
    return open_, close


def calibrate(O, C, rf):
    """실제 SSO/UPRO 종가수익과 합성의 연율 차이 → EXTRA. 겹치는 구간 전체."""
    out = {}
    for lev, sym in ((2, "SSO"), (3, "UPRO")):
        real = C[sym].dropna()
        _, syn = synth(O, C, rf, lev, 0.0)
        syn = syn.reindex(real.index)
        yrs = (real.index[-1] - real.index[0]).days / 365.25
        g_real = (real.iloc[-1] / real.iloc[0]) ** (1 / yrs) - 1
        g_syn = (syn.iloc[-1] / syn.iloc[0]) ** (1 / yrs) - 1
        # 연율 차이를 로그 드래그로 환산
        extra = np.log(1 + g_syn) - np.log(1 + g_real)
        dr = real.pct_change().dropna(); ds = syn.pct_change().reindex(dr.index)
        out[lev] = {"sym": sym, "from": str(real.index[0].date()), "cagr_real": g_real, "cagr_syn0": g_syn,
                    "extra_drag": extra, "daily_corr": float(dr.corr(ds)),
                    "te_ann": float((dr - ds).std() * np.sqrt(252))}
    return out


class Market:
    """판정에 쓰는 SPY 지표 + 체결에 쓰는 상품(SPY, L2, L3, 현금) 가격."""

    def __init__(self, O, C, H, L, rf, extra):
        self.O, self.C, self.H, self.L, self.rf = O, C, H, L, rf
        self.idx = C.index
        self.px_o, self.px_c = {}, {}
        self.px_o["SPY"], self.px_c["SPY"] = O["SPY"], C["SPY"]
        for lev, nm in ((2, "L2"), (3, "L3")):
            self.px_o[nm], self.px_c[nm] = synth(O, C, rf, lev, extra[lev])
        cash = (1 + rf).cumprod()
        self.px_o["CASH"] = cash.shift(1).fillna(1)   # 이자는 종가에 붙는다
        self.px_c["CASH"] = cash
        for k in ("TLT", "IEF", "GLD", "EFA", "QQQ"):
            if k in C:
                self.px_o[k], self.px_c[k] = O[k], C[k]


def lev_to_w(lev: float) -> dict:
    """목표 레버리지 → SPY/L2/L3/CASH 비중 (가장 가까운 두 상품으로)."""
    lev = float(np.clip(lev, 0, 3))
    if lev <= 1:
        return {"SPY": lev, "CASH": 1 - lev}
    if lev <= 2:
        return {"SPY": 2 - lev, "L2": lev - 1}
    return {"L2": 3 - lev, "L3": lev - 2}


def run(mkt: Market, decide, start="1994-01-03", end=None, band=0.0):
    """decide(i) -> 목표비중 dict 또는 None(유지). i 는 판정일 인덱스(종가까지 정보 사용).
    band: 목표와 현재 비중 차 합(L1)/2 가 band 미만이면 거래 생략 — 회전율 제어."""
    idx = mkt.idx
    s = idx.searchsorted(pd.Timestamp(start)); e = len(idx) if end is None else idx.searchsorted(pd.Timestamp(end), "right")
    syms = list(mkt.px_c)
    PO = pd.DataFrame(mkt.px_o)[syms].to_numpy(); PC = pd.DataFrame(mkt.px_c)[syms].to_numpy()
    k = {s_: j for j, s_ in enumerate(syms)}
    hold = np.zeros(len(syms)); hold[k["CASH"]] = 1.0 / PC[s - 1, k["CASH"]]   # 단위 수
    eq = np.empty(e - s); traded = 0.0; pending = None; ntr = 0
    for t in range(s, e):
        if pending is not None:
            po = np.nan_to_num(PO[t]); V = float(hold @ po)
            cur = hold * po / V
            tgt = np.zeros(len(syms))
            for s_, w in pending.items():
                tgt[k[s_]] = w
            tgt[k["CASH"]] += max(0.0, 1 - tgt.sum())
            diff = tgt - cur
            risky = np.abs(diff).copy(); risky[k["CASH"]] = 0
            if np.abs(diff).sum() / 2 >= band:
                c = COST * risky.sum() * V
                V -= c; traded += risky.sum() / 2
                if np.abs(diff).sum() / 2 >= 0.05:      # 비중 드리프트 미세조정은 '거래 횟수'에서 제외
                    ntr += 1
                with np.errstate(divide="ignore", invalid="ignore"):
                    hold = np.where(po > 0, tgt * V / po, 0.0)
            pending = None
        eq[t - s] = float(hold @ np.nan_to_num(PC[t]))
        w = decide(t)
        if w is not None:
            pending = w
    ser = pd.Series(eq, index=idx[s:e])
    yrs = (ser.index[-1] - ser.index[0]).days / 365.25
    return ser, traded / yrs, ntr / yrs


def cagr(s):
    y = (s.index[-1] - s.index[0]).days / 365.25
    return (s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1


def mdd(s):
    return float((s / s.cummax() - 1).min())


def report(name, s, turn, ntr):
    yr = s.resample("YE").last(); yr = pd.concat([s.iloc[:1], yr]).pct_change().dropna()
    yr = yr[yr.index.year < 2026]   # 2026 은 부분 연도
    segs = {"94-11": s[:"2011-12-31"], "12-26": s["2012-03-01":], "12-19": s["2012-03-01":"2019-06-30"],
            "19-26": s["2019-07-01":]}
    row = {"name": name, "CAGR": cagr(s), "MDD": mdd(s)}
    for k_, v in segs.items():
        row[k_] = cagr(v)
    row["MDD12-26"] = mdd(s["2012-03-01":])
    row["yrs>=18%"] = f"{(yr >= 0.18).sum()}/{len(yr)}"
    row["worstY"] = float(yr.min())
    row["turn/yr"] = turn
    row["trades/yr"] = ntr
    return row
