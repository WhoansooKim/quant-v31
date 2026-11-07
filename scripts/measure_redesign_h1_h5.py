#!/usr/bin/env python
"""§22.AO-68 재설계 가설 H1~H5 — 현실 체결 · 같은 창 · 전반/후반 · 노출맞춤 SPY 대조.

사용자 결정(2026-11-07): 레버리지 3배까지 허용 · KIS 0.25%/편 유지 · H1~H5 전부 측정.
배경: 내부 진단 + 학술/실무/비용 조사 → 고회전 개별종목 스윙은 0.25%/편에서 18% 근거 없음.
     18% 가 측정된 구조는 저회전 추세필터 + 레버리지/모멘텀 집중뿐 (에이전트 1차 계산은 종가 체결).

체결 모델 (모든 가설 공통):
  - 신호는 t 일 종가로 판정, 체결은 t+1 일 **시가** (같은 종가 체결 가정 제거)
  - 비용: 거래금액 × (0.25% 수수료 + 0.05% 슬리피지) — §22.AO-60 실측 5bp
  - 현금 = BIL 보유(매매 시 같은 비용 부담). 2012~2021 BIL 수익 ≈ 0
판정: 전체·전반·후반 CAGR 모두 18% 근처 + 노출맞춤 SPY(같은 평균 노출, 비용 0, 일간 리밸런스) 초과.
     MDD 는 참고만(수익이 다른 전략끼리 낙폭 비교는 판정에 쓰지 않는다).
H3 경고: hist_prices_adj 유니버스는 **현재 상장 종목**(생존편향) → H3 수치는 상한으로 읽는다.
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

ETF = "/home/quant/quant-v31/data/parquet/etf/etf_daily.parquet"
COST = 0.0025 + 0.0005
START, END = pd.Timestamp("2012-03-01"), pd.Timestamp("2026-10-09")   # 종목 데이터 종료일에 맞춤
LEV = {"SPY": 1, "QQQ": 1, "SSO": 2, "QLD": 2, "UPRO": 3, "TQQQ": 3}
BASE = {"SSO": "SPY", "UPRO": "SPY", "QLD": "QQQ", "TQQQ": "QQQ", "SPY": "SPY", "QQQ": "QQQ"}


def load_etf():
    e = pd.read_parquet(ETF); e["d"] = pd.to_datetime(e.d)
    return e.pivot(index="d", columns="symbol", values="o"), e.pivot(index="d", columns="symbol", values="c")


def load_stocks(pg):
    with pg.get_conn() as c:
        df = pd.DataFrame(c.execute(
            """SELECT symbol, time::date d, open::float o, close::float c, volume::float v
               FROM hist_prices_adj WHERE time >= '2010-12-01'""").fetchall())
    df["d"] = pd.to_datetime(df.d)
    df = df[~df.symbol.isin(list(LEV) + ["BIL", "SH", "GLD", "TLT"])]
    return (df.pivot(index="d", columns="symbol", values="o"),
            df.pivot(index="d", columns="symbol", values="c"),
            df.pivot(index="d", columns="symbol", values="v"))


def simulate(O, C, targets, dates, cash="BIL"):
    """targets: {decision_date: {sym: weight}} (합 ≤ 1, 나머지는 cash). t 종가 판정 → t+1 시가 체결.
    가격 결손(거래정지·상장폐지 직전 공백)은 마지막 유효가로 평가한다(ffill) — NaN 전파 방지."""
    O = O.reindex(dates).ffill(); C = C.reindex(dates).ffill()
    sh, eq, traded, expo = {}, [], 0.0, []
    V0 = 1.0; cashv = V0; pending = None
    for i, d in enumerate(dates):
        o, c = O.loc[d], C.loc[d]
        if pending is not None:
            V = cashv + sum(n * o[s] for s, n in sh.items() if np.isfinite(o[s]))
            w = dict(pending); w[cash] = w.get(cash, 0) + max(0.0, 1 - sum(pending.values()))
            new = {}
            for s, wt in w.items():
                if wt <= 0: continue
                px = o.get(s, np.nan)
                if not np.isfinite(px):           # 시가 결손 → 기존 보유 유지
                    if s in sh: new[s] = sh[s]
                    continue
                new[s] = wt * V / px
            # 결손으로 유지한 종목 외 매도분 포함 거래금액
            allsyms = set(sh) | set(new)
            tv = sum(abs(new.get(s, 0) - sh.get(s, 0)) * o[s] for s in allsyms if np.isfinite(o.get(s, np.nan)))
            cost = tv * COST; traded += tv
            sh = new; cashv = 0.0
            # 비용은 현금 비중에서 차감(현금 없으면 비례 축소)
            Vn = sum(n * o[s] for s, n in sh.items() if np.isfinite(o[s]))
            k = (Vn - cost) / Vn if Vn > 0 else 1.0
            sh = {s: n * k for s, n in sh.items()}
            pending = None
        val = sum(n * (c[s] if np.isfinite(c[s]) else o[s]) for s, n in sh.items()) + cashv
        eq.append(val)
        expo.append(sum(n * c[s] * LEV.get(s, 1) for s, n in sh.items()
                        if s != cash and np.isfinite(c[s])) / val if val > 0 else 0)
        if d in targets:
            pending = targets[d]
    eq = pd.Series(eq, index=dates)
    yrs = (dates[-1] - dates[0]).days / 365.25
    return eq, traded / np.mean(eq.values) / yrs, float(np.mean(expo))


def cagr(eq):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100


def mdd(eq):
    return ((eq / eq.cummax()) - 1).min() * 100


def matched(Cetf, dates, e, base="SPY"):
    r = Cetf[base].reindex(dates).pct_change().fillna(0)
    b = Cetf["BIL"].reindex(dates).pct_change().fillna(0)
    return (1 + e * r + (1 - e) * b).cumprod()


def trend_targets(Cetf, dates, sym, band=0.02, filt=True):
    base = BASE[sym]; px = Cetf[base]; sma = px.rolling(200).mean()
    on, tg = None, {}
    for d in dates:
        if not filt:
            st = True
        else:
            x, m = px.get(d, np.nan), sma.get(d, np.nan)
            if on is None: st = x > m
            elif on: st = not (x < m * (1 - band))
            else: st = x > m * (1 + band)
        if st != on:
            tg[d] = {sym: 1.0} if st else {}
            on = st
    return tg


def month_ends(dates):
    s = pd.Series(dates, index=dates)
    return set(s.groupby([s.index.year, s.index.month]).max())


def momentum_targets(Ost, Cst, Vst, Cetf, dates, n=10, hold_rank=30, look=252, skip=21,
                     top_liq=500, filt=True, minpx=10.0):
    me = month_ends(dates)
    dv = (Cst * Vst).rolling(63).mean()
    mom = Cst.shift(skip) / Cst.shift(look) - 1
    spy = Cetf["SPY"]; sma = spy.rolling(200).mean()
    held, tg = [], {}
    for d in dates:
        if d not in me: continue
        if filt and not (spy[d] > sma[d]):
            if held or not tg: tg[d] = {}
            held = []; continue
        liq = dv.loc[d].dropna()
        ok = liq[(Cst.loc[d].reindex(liq.index) >= minpx)].nlargest(top_liq).index
        m = mom.loc[d, ok].dropna().sort_values(ascending=False)
        rank = {s: k for k, s in enumerate(m.index, 1)}
        keep = [s for s in held if rank.get(s, 10**9) <= hold_rank]
        add = [s for s in m.index if s not in keep][: max(0, n - len(keep))]
        new = keep + add
        if set(new) != set(held) or not tg or d == min(me):
            tg[d] = {s: 1.0 / n for s in new}
        held = new
    return tg


def sector_targets(Cetf, dates, k=3):
    secs = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC"]
    me = month_ends(dates); tg = {}
    sc = sum(Cetf[secs] / Cetf[secs].shift(L) - 1 for L in (63, 126, 252)) / 3
    sma = Cetf[secs].rolling(200).mean()
    for d in dates:
        if d not in me: continue
        s = sc.loc[d].dropna().sort_values(ascending=False).head(k)
        tg[d] = {x: 1.0 / k for x in s.index if Cetf.loc[d, x] > sma.loc[d, x]}
    return tg


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    Oe, Ce = load_etf()
    pg = PostgresStore(get_config().pg_dsn)
    Os, Cs, Vs = load_stocks(pg)
    O = Oe.join(Os, how="outer"); C = Ce.join(Cs, how="outer")
    dates = Ce.index[(Ce.index >= START) & (Ce.index <= END) & Ce["SPY"].notna()]
    mid = dates[len(dates) // 2]
    print(f"창 {dates[0].date()} ~ {dates[-1].date()} · 반분 {mid.date()} · 비용 {COST*100:.2f}%/편 · 다음날 시가 체결")

    S = {}
    for sym in ("SPY", "QQQ", "SSO", "QLD", "UPRO", "TQQQ"):
        S[f"보유 {sym}"] = trend_targets(Ce, dates, sym, filt=False)
    for sym in ("SPY", "QQQ", "SSO", "QLD", "UPRO", "TQQQ"):
        S[f"H1/2 {sym} 200일선 밴드2%"] = trend_targets(Ce, dates, sym, band=0.02)
    for sym in ("SSO", "QLD"):
        S[f"H1/2 {sym} 200일선 밴드0%"] = trend_targets(Ce, dates, sym, band=0.0)
    S["H3 모멘텀 상위10 +필터"] = momentum_targets(Os, Cs, Vs, Ce, dates, n=10)
    S["H3 모멘텀 상위20 +필터"] = momentum_targets(Os, Cs, Vs, Ce, dates, n=20, hold_rank=50)
    S["H3 모멘텀 상위10 무필터"] = momentum_targets(Os, Cs, Vs, Ce, dates, n=10, filt=False)
    S["H4 섹터 상위3"] = sector_targets(Ce, dates)

    rows, curves = [], {}
    for name, tg in S.items():
        eq, turn, e = simulate(O, C, tg, dates)
        curves[name] = eq
        base = "QQQ" if ("QQQ" in name or "QLD" in name) else "SPY"
        mb = matched(Ce, dates, e, base)
        mbs = matched(Ce, dates, e, "SPY")
        rows.append({"전략": name, "전체": cagr(eq), "전반": cagr(eq[:mid]), "후반": cagr(eq[mid:]),
                     "노출": e, "왕복/년": turn / 2, f"노출맞춤SPY": cagr(mbs),
                     "초과(vsSPY)": cagr(eq) - cagr(mbs),
                     "초과전반": cagr(eq[:mid]) - cagr(mbs[:mid]), "초과후반": cagr(eq[mid:]) - cagr(mbs[mid:]),
                     "MDD(참고)": mdd(eq)})
        print(f"  done {name}", flush=True)

    # H5: 두 슬리브 반반(별도 계좌처럼 운용, 교차 리밸런스 없음)
    for a in ("H1/2 SSO 200일선 밴드2%", "H1/2 QLD 200일선 밴드2%", "H1/2 UPRO 200일선 밴드2%"):
        b = "H3 모멘텀 상위10 +필터"
        eq = 0.5 * curves[a] / curves[a].iloc[0] + 0.5 * curves[b] / curves[b].iloc[0]
        ra = next(r for r in rows if r["전략"] == a); rb = next(r for r in rows if r["전략"] == b)
        e = (ra["노출"] + rb["노출"]) / 2
        mbs = matched(Ce, dates, e, "SPY")
        rows.append({"전략": f"H5 ½{a.split()[1]}+½H3", "전체": cagr(eq), "전반": cagr(eq[:mid]),
                     "후반": cagr(eq[mid:]), "노출": e, "왕복/년": (ra["왕복/년"] + rb["왕복/년"]) / 2,
                     "노출맞춤SPY": cagr(mbs), "초과(vsSPY)": cagr(eq) - cagr(mbs),
                     "초과전반": cagr(eq[:mid]) - cagr(mbs[:mid]), "초과후반": cagr(eq[mid:]) - cagr(mbs[mid:]),
                     "MDD(참고)": mdd(eq)})
        curves[f"H5 ½{a.split()[1]}+½H3"] = eq

    df = pd.DataFrame(rows).round(2)
    print(df.to_string(index=False))
    df.to_csv("/home/quant/quant-v31/scripts/redesign_h1_h5.csv", index=False)

    # 연도별 (주요 후보)
    keys = ["보유 SPY", "보유 QQQ", "H1/2 SSO 200일선 밴드2%", "H1/2 QLD 200일선 밴드2%",
            "H1/2 UPRO 200일선 밴드2%", "H1/2 TQQQ 200일선 밴드2%", "H3 모멘텀 상위10 +필터", "H4 섹터 상위3"]
    yr = pd.DataFrame({k: curves[k].groupby(curves[k].index.year).last() for k in keys})
    yr = (yr / yr.shift(1) - 1) * 100
    first = pd.DataFrame({k: [curves[k].groupby(curves[k].index.year).last().iloc[0] / curves[k].iloc[0] * 100 - 100]
                          for k in keys}, index=[dates[0].year])
    yr.iloc[0] = first.iloc[0]
    print("\n연도별 수익률(%)\n", yr.round(1).to_string())
    print("\n18% 미달 연도 수:", {k: int((yr[k] < 18).sum()) for k in keys})
