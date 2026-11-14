#!/usr/bin/env python
"""§22.AO-70 종목 스윙 연구 엔진 — 시점(PIT) S&P500 유니버스, 다음날 시가 체결, 갭 스톱 시가 체결.

과거 실패(§22.AO-65/66/68)에서 배운 것을 엔진 수준에서 강제한다:
  - 유니버스: 판정일 t 에 S&P500 구성종목이었던 종목만 (fja05680/sp500 이력). 현재 구성종목 룩어헤드 제거.
    가격이 없는 과거 구성종목(주로 상장폐지, 약 23%)은 거래 불가로 남는다 → 결과와 함께 편향 표기.
  - 체결: t 종가 판정 → t+1 시가. 스톱은 장중 저가가 스톱 이하면 min(시가, 스톱)에 체결(갭다운은 시가).
  - 비용: 편도 cost (수수료+슬리피지)를 매수·매도 금액에 부과.
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd

PANEL = "/home/quant/quant-v31/data/pit/panel.npz"
sys.path.insert(0, "/home/quant/quant-v31")


def build_panel():
    from engine_v4.config.settings import get_config
    from engine_v4.data.storage import PostgresStore
    pg = PostgresStore(get_config().pg_dsn)
    with pg.get_conn() as c:
        df = pd.DataFrame(c.execute("""SELECT time::date d, symbol, open::float o, high::float h, low::float l,
                                       close::float c, volume v FROM hist_prices_adj""").fetchall())
        sec = {r["symbol"]: r["sector"] for r in c.execute("select ticker as symbol, sector from symbols").fetchall()}
    df["d"] = pd.to_datetime(df.d)
    piv = {k: df.pivot(index="d", columns="symbol", values=k) for k in ("o", "h", "l", "c", "v")}
    dates, syms = piv["c"].index, piv["c"].columns
    comp = pd.read_csv("/home/quant/quant-v31/data/pit/sp500_components.csv", parse_dates=["date"])
    comp = comp.set_index("date").tickers.str.split(",")
    mem = np.zeros((len(dates), len(syms)), bool)
    col = {s: j for j, s in enumerate(syms)}
    ci = comp.index.searchsorted(dates, side="right") - 1
    for i, k in enumerate(ci):
        if k >= 0:
            for s in comp.iloc[k]:
                j = col.get(s) or col.get(s.replace(".", "-"))
                if j is not None:
                    mem[i, j] = True
    np.savez_compressed(PANEL, dates=dates.values.astype("datetime64[D]"), syms=np.array(syms),
                        sector=np.array([sec.get(s, "?") for s in syms]), mem=mem,
                        **{k: piv[k].to_numpy() for k in piv})
    print("panel", len(dates), "days x", len(syms), "syms; avg members/day", mem.sum(1).mean().round(1))


class Panel:
    def __init__(self):
        z = np.load(PANEL, allow_pickle=True)
        self.dates = pd.DatetimeIndex(z["dates"]); self.syms = z["syms"]; self.sector = z["sector"]
        self.mem = z["mem"]
        self.O, self.H, self.L, self.C, self.V = (z[k] for k in ("o", "h", "l", "c", "v"))
        self.df = lambda a: pd.DataFrame(a, index=self.dates, columns=self.syms)


def simulate(P: Panel, score, K=10, cost=0.003, mode="swing", start="2012-03-01", end=None,
             stop=None, trail=None, max_hold=None, exit_sig=None, market_ok=None, rebal_days=None,
             hold_rank=None, min_px=5.0):
    """score: (T×N) 판정일 점수(클수록 우선), NaN=부적격.
    mode='swing'  : 빈 슬롯마다 상위 점수 신규 진입. 청산=stop/trail/max_hold/exit_sig.
    mode='rebal'  : rebal_days(판정일 bool) 마다 상위 K 목표, 보유 종목은 순위 hold_rank 안이면 유지(밴드).
    market_ok: (T,) bool — False 면 신규 진입 금지(기존 보유는 규칙대로).
    반환: equity(Series), trades(DataFrame)
    """
    T, N = P.C.shape
    s0 = P.dates.searchsorted(pd.Timestamp(start)); e0 = T if end is None else P.dates.searchsorted(pd.Timestamp(end), "right")
    O, H, L, C = P.O, P.H, P.L, P.C
    elig = P.mem & np.isfinite(score) & (C > min_px)
    cash = 1.0; pos = {}  # j -> dict(qty, entry_px, entry_i, peak, stop_px)
    eq = np.empty(e0 - s0); trades = []
    pend_buy, pend_sell = [], set()
    for t in range(s0, e0):
        # 1) 시가 체결 (전일 판정)
        for j in list(pend_sell):
            if j in pos and np.isfinite(O[t, j]):
                p = pos.pop(j); px = O[t, j]
                cash += p["qty"] * px * (1 - cost)
                trades.append((p["entry_i"], t, P.syms[j], p["entry_px"], px, "signal"))
        pend_sell = set()
        if pend_buy:
            V = cash + sum(p["qty"] * (O[t, j] if np.isfinite(O[t, j]) else p.get("last", p["entry_px"])) for j, p in pos.items())
            for j in pend_buy:
                if len(pos) >= K or j in pos or not np.isfinite(O[t, j]) or O[t, j] <= 0:
                    continue
                alloc = min(V / K, cash)
                if alloc <= V * 0.02:
                    continue
                qty = alloc / (O[t, j] * (1 + cost)); cash -= alloc
                sj = (stop[t - 1, j] if isinstance(stop, np.ndarray) else stop) if stop is not None else None
                tj = (trail[t - 1, j] if isinstance(trail, np.ndarray) else trail) if trail is not None else None
                sj = sj if (sj is not None and np.isfinite(sj) and sj > 0) else None
                tj = tj if (tj is not None and np.isfinite(tj) and tj > 0) else None
                pos[j] = {"qty": qty, "entry_px": O[t, j], "entry_i": t, "peak": O[t, j], "trail": tj,
                          "stop_px": O[t, j] * (1 - sj) if sj else None}
            pend_buy = []
        # 2) 장중 스톱/트레일 — 트레일 기준 고점은 **전일까지**(당일 고저 순서 미상 → 낙관 편향 제거)
        for j in list(pos):
            p = pos[j]
            sp = p["stop_px"]
            if p["trail"] and t > p["entry_i"]:
                sp = max(sp or 0, p["peak"] * (1 - p["trail"]))
            if sp and np.isfinite(L[t, j]) and L[t, j] <= sp:
                px = min(O[t, j], sp) if np.isfinite(O[t, j]) else sp
                pos.pop(j); cash += p["qty"] * px * (1 - cost)
                trades.append((p["entry_i"], t, P.syms[j], p["entry_px"], px, "stop"))
                continue
            if np.isfinite(H[t, j]):
                p["peak"] = max(p["peak"], H[t, j])
        # 3) 종가 평가
        val = cash
        for j, p in pos.items():
            c = C[t, j] if np.isfinite(C[t, j]) else p.get("last", p["entry_px"])
            p["last"] = c; val += p["qty"] * c
        eq[t - s0] = val
        # 4) 판정 (t 종가 정보) → t+1 시가 주문
        if t + 1 >= e0:
            break
        for j, p in pos.items():
            held = t - p["entry_i"]
            if max_hold and held >= max_hold:
                pend_sell.add(j)
            elif exit_sig is not None and exit_sig[t, j]:
                pend_sell.add(j)
            elif not P.mem[t, j] and mode == "rebal":
                pend_sell.add(j)
        mk = True if market_ok is None else bool(market_ok[t])
        if mode == "rebal":
            if rebal_days is not None and rebal_days[t]:
                sc = np.where(elig[t], score[t], -np.inf)
                order = np.argsort(-sc)
                rank = np.empty(N, int); rank[order] = np.arange(N)
                hr = hold_rank or K
                for j in pos:
                    if not np.isfinite(sc[j]) or rank[j] >= hr:
                        pend_sell.add(j)
                if mk:
                    keep = len(pos) - len(pend_sell)
                    pend_buy = [j for j in order[: K * 3] if np.isfinite(sc[j]) and j not in pos][: max(0, K - keep)]
                elif market_ok is not None:
                    pend_sell |= set(pos)
        else:
            free = K - (len(pos) - len(pend_sell))
            if free > 0 and mk:
                sc = np.where(elig[t], score[t], -np.inf)
                cand = [j for j in np.argsort(-sc)[: free * 3 + len(pos)] if np.isfinite(sc[j]) and j not in pos]
                pend_buy = cand[:free]
    eq = pd.Series(eq[: t - s0 + 1], index=P.dates[s0: t + 1])
    tr = pd.DataFrame(trades, columns=["ei", "xi", "sym", "entry", "exit", "why"])
    if len(tr):
        tr["ret"] = tr.exit / tr.entry * (1 - cost) / (1 + cost) - 1
        tr["days"] = tr.xi - tr.ei
    return eq, tr


def stats(name, eq, tr, spy=None):
    y = (eq.index[-1] - eq.index[0]).days / 365.25
    cg = (eq.iloc[-1] / eq.iloc[0]) ** (1 / y) - 1
    dd = float((eq / eq.cummax() - 1).min())
    half = eq.index[len(eq) // 2]
    h1 = eq[:half]; h2 = eq[half:]
    c1 = (h1.iloc[-1] / h1.iloc[0]) ** (365.25 / (h1.index[-1] - h1.index[0]).days) - 1
    c2 = (h2.iloc[-1] / h2.iloc[0]) ** (365.25 / (h2.index[-1] - h2.index[0]).days) - 1
    # 6개월 롤링 수익 ≥ 9% 비율 (사용자 목표: 6개월 9%)
    r6 = eq.pct_change(126).dropna()
    row = {"name": name, "CAGR": cg, "H1": c1, "H2": c2, "MDD": dd, "6m>=9%": float((r6 >= 0.09).mean()),
           "6m_med": float(r6.median()), "trades/yr": len(tr) / y if len(tr) else 0,
           "med_trade": float(tr.ret.median()) if len(tr) else np.nan, "win": float((tr.ret > 0).mean()) if len(tr) else np.nan,
           "hold": float(tr.days.median()) if len(tr) else np.nan}
    return row


if __name__ == "__main__":
    build_panel()
