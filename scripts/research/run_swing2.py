#!/usr/bin/env python
"""§22.AO-70 종목 스윙 2라운드 — 체계적 문헌조사(part1) 후보 + 실적일(EDGAR) 기반 재측정.
 J Avramov-Kaplanski-Subrahmanyam 2021: MA(21)/MA(200) 비율 상위 (월)
 K Dai-Medhat-Novy-Marx-Rizova 2024 / Blitz 2023: 실적창·업종모멘텀 제거 + 저회전 조건 1개월 반전 (월)
 L Blitz 2023 composite: J·A·K 순위 합 (월, 한 번의 리밸런스로 비용 공유)
 G2 에피소딕 피벗(실적일 한정): 8-K 2.02 반응일 갭 ≥5%, 거래량 ≥2×, 스톱=갭일 저가, SMA20 이탈/40일
 F2 Qullamaggie 완화: 3개월 상위 5%, 15일 박스 ≤25%, 15일 고점 돌파, 스톱=돌파일 저가, SMA20 이탈
시점 S&P500 · t+1 시가 · 0.30% / 0.12% 편도. 2012-03~2026-10.
"""
import numpy as np, pandas as pd
from stock_lab import Panel, simulate, stats

pd.set_option("display.width", 260)
P = Panel(); D = P.df
C, O, H, L, V = (D(x) for x in (P.C, P.O, P.H, P.L, P.V))
memdf = pd.DataFrame(P.mem, index=P.dates, columns=P.syms)
dv = C * V
liq = (dv.rolling(50).mean() >= 20e6) & (C >= 10)
xr = lambda df: df.where(memdf).rank(axis=1, pct=True)
A = lambda df: df.to_numpy(dtype=float)
B = lambda df: df.fillna(False).to_numpy(dtype=bool)
me = pd.Series(P.dates.month, index=P.dates); me = (me != me.shift(-1)).to_numpy()
spy = pd.read_parquet("/home/quant/quant-v31/data/parquet/etf/long_daily.parquet")
spy = spy[spy.symbol == "SPY"].assign(d=lambda x: pd.to_datetime(x.d)).set_index("d").c.reindex(P.dates).ffill()
mk200 = (spy > spy.rolling(200).mean()).to_numpy()
sma20 = C.rolling(20).mean()
r21, r63 = C / C.shift(21) - 1, C / C.shift(63) - 1
sec = pd.Series(P.sector, index=P.syms)

# 실적 반응일: 8-K 2.02 acceptance 가 16:00 ET 이후면 다음 거래일, 이전이면 당일
ed = pd.read_parquet("/home/quant/quant-v31/data/pit/earn_dates.parquet")
ed["acc"] = pd.to_datetime(ed.accept_time.str[:19], errors="coerce")
ed["day"] = pd.to_datetime(ed.filing_date)
ed.loc[ed.acc.dt.hour >= 16, "day"] += pd.Timedelta(days=1)
earn = pd.DataFrame(False, index=P.dates, columns=P.syms)
pos = P.dates.searchsorted(ed.day)
col = {s: j for j, s in enumerate(P.syms)}
E = earn.to_numpy()
for p_, s in zip(pos, ed.symbol):
    j = col.get(s)
    if j is not None and p_ < len(P.dates):
        E[p_, j] = True
earn = pd.DataFrame(E, index=P.dates, columns=P.syms)
print("earnings reaction days:", int(E.sum()), "symbols with any:", int(E.any(0).sum()))
earn_win21 = earn.rolling(21, min_periods=1).max().astype(bool)

S = {}
# J
maratio = C.rolling(21).mean() / C.rolling(200).mean()
sJ = maratio.where(liq)
S["J MA21/MA200 비율 (월)"] = dict(score=A(sJ), mode="rebal", rebal_days=me, K=10, hold_rank=30)
# K
rel21 = r21 - r21.where(memdf).T.groupby(sec).transform("mean").T
abn = dv.rolling(21).mean() / dv.rolling(252).mean()
sK = (-rel21).where(liq & ~earn_win21 & (xr(abn) <= 0.5))
S["K 정제 반전(실적창 제외·저회전, 월)"] = dict(score=A(sK), mode="rebal", rebal_days=me, K=10, hold_rank=30)
# A (재사용) + L 합성
sA = r21.where(xr(abn) >= 0.7)
comp = (xr(sJ).fillna(0) + xr(sA).fillna(0) + xr(sK).fillna(0)).where(liq)
S["L 합성 J+A+K (월)"] = dict(score=A(comp), mode="rebal", rebal_days=me, K=10, hold_rank=30)
# G2
gp = O / C.shift() - 1
volx = V / V.rolling(50).mean().shift()
sG2 = gp.where(earn & (gp >= 0.05) & (volx >= 2) & (C > O * 0.99) & liq)
stopG2 = (1 - L / C).clip(lower=0.02, upper=0.15)
S["G2 실적일 갭업 EP (스윙)"] = dict(score=A(sG2), mode="swing", K=10, stop=A(stopG2), exit_sig=B(C < sma20), max_hold=40, market_ok=mk200)
# F2
box = (H.shift(1).rolling(15).max() / L.shift(1).rolling(15).min() - 1) <= 0.25
brk = C > H.shift(1).rolling(15).max()
sF2 = xr(r63).where((xr(r63) >= 0.95) & box & brk & liq)
stopF2 = (1 - L / C).clip(lower=0.02, upper=0.10)
S["F2 Qullamaggie 완화 (스윙)"] = dict(score=A(sF2), mode="swing", K=10, stop=A(stopF2), exit_sig=B(C < sma20), market_ok=mk200)


# P 실적 전 프리미엄 (Gao-Hu-Zhang 2025): 발표 8~12 거래일 전 진입, 7일 보유 → 발표 전 청산. 불확실성=60일 실현변동성.
#   ⚠️ 발표일은 사후 8-K 날짜(예정일 공지는 보통 2~4주 전) — 약한 룩어헤드, 결과는 상한으로 읽는다.
fut = sum(earn.shift(-k).fillna(False).astype(int) for k in range(8, 13)) > 0
rv60 = C.pct_change().rolling(60).std()
sP = xr(rv60).where(fut & liq)
S["P 실적 전 프리미엄 (7일)"] = dict(score=A(sP), mode="swing", K=10, max_hold=7)
# Q 실적일 수익 드리프트 롱 (Meursault 2023): 반응일 초과수익(SPY 대비) ≥ +4% 상위, 60일 보유, 스톱 15%
spy_r = spy.pct_change()
ear = C.pct_change().sub(spy_r, axis=0)
sQ = ear.where(earn & (ear >= 0.04) & liq)
S["Q 실적일 수익 드리프트 (60일)"] = dict(score=A(sQ), mode="swing", K=10, max_hold=60, stop=0.15)

rows = []
for cost in (0.003, 0.0012):
    for name, kw in S.items():
        eq, tr = simulate(P, cost=cost, **kw)
        r = stats(name, eq, tr); r["cost"] = cost; rows.append(r)
s = spy["2012-03-01":P.dates[-1]]
rows.append(stats("SPY 보유", s / s.iloc[0], pd.DataFrame(columns=["ret", "days"])) | {"cost": 0})
df = pd.DataFrame(rows)
show = df.copy()
for c in ("CAGR", "H1", "H2", "MDD", "6m>=9%", "6m_med", "med_trade", "win"):
    show[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:.1%}")
show["trades/yr"] = df["trades/yr"].map("{:.0f}".format); show["hold"] = df["hold"].map(lambda v: "" if pd.isna(v) else f"{v:.0f}d")
show["cost"] = df["cost"].map(lambda v: f"{v*100:.2f}%")
print(show.to_string(index=False))
df.to_csv("/home/quant/quant-v31/scripts/research/swing2.csv", index=False)
