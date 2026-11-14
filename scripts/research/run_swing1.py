#!/usr/bin/env python
"""§22.AO-70 종목 스윙 1라운드 — 문헌·실전가 규칙 8종, 시점 S&P500, 2012-03~2026-10.
비용 두 조건: 0.30%/편(KIS 0.25%+5bp) · 0.12%/편(우대 0.07%+5bp).
비교: SPY 보유, 추세×3배 코어(lev_lab, 같은 창).
"""
import sys
import numpy as np, pandas as pd
from stock_lab import Panel, simulate, stats

pd.set_option("display.width", 260)
P = Panel()
D = P.df
C, O, H, L, V = (D(x) for x in (P.C, P.O, P.H, P.L, P.V))
T, N = P.C.shape
dv = (C * V)
spy = pd.read_parquet("/home/quant/quant-v31/data/parquet/etf/long_daily.parquet")
spy = spy[spy.symbol == "SPY"].assign(d=lambda x: pd.to_datetime(x.d)).set_index("d").c.reindex(P.dates).ffill()
mk200 = (spy > spy.rolling(200).mean()).to_numpy()
mk140 = (spy > spy.ewm(span=140).mean()).to_numpy()

liq = (dv.rolling(50).mean() >= 20e6) & (C >= 10)          # 실전가 보고서 공통 조건
sma10, sma20, sma50, sma100, sma150, sma200 = (C.rolling(n).mean() for n in (10, 20, 50, 100, 150, 200))
tr_ = pd.concat([H - L, (H - C.shift()).abs(), (L - C.shift()).abs()]).groupby(level=0).max()
atr20 = tr_.rolling(20).mean(); atr42 = tr_.rolling(42).mean()
r21, r63, r126, r252 = (C / C.shift(n) - 1 for n in (21, 63, 126, 252))
hi252, lo252 = C.rolling(252).max(), C.rolling(252).min()
memdf = pd.DataFrame(P.mem, index=P.dates, columns=P.syms)


def xrank(df):
    """그날 구성종목 내 횡단면 백분위."""
    return df.where(memdf).rank(axis=1, pct=True)


month_end = pd.Series(P.dates.month, index=P.dates); month_end = (month_end != month_end.shift(-1)).to_numpy()
week_end = pd.Series(P.dates.isocalendar().week.values, index=P.dates); week_end = (week_end != week_end.shift(-1)).to_numpy()
A = lambda df: df.to_numpy(dtype=float)
B = lambda df: df.fillna(False).to_numpy(dtype=bool)

strategies = {}

# A. 고회전 종목 단기 모멘텀 (Medhat-Schmeling 2022) — 회전율 대용: 21일 거래대금/252일 거래대금 상위 30% 내 1개월 수익 순위
abn = dv.rolling(21).mean() / dv.rolling(252).mean()
sA = r21.where(xrank(abn) >= 0.7).where(liq)
strategies["A 고회전 1M모멘텀 (월)"] = dict(score=A(sA), mode="rebal", rebal_days=month_end, K=10, hold_rank=20)

# B. 업종 모멘텀 + 업종 내 반전 (Moskowitz-Grinblatt; Novy-Marx-Velikov)
sec = pd.Series(P.sector, index=P.syms)
r126m = r126.where(memdf)
sec_ret = r126m.T.groupby(sec).mean().T                        # 날짜×섹터
sec_rank = sec_ret.rank(axis=1, ascending=False)
top_sec = pd.DataFrame({s: sec_rank[sec[s]] <= 3 if sec[s] in sec_rank else False for s in P.syms}, index=P.dates)
rel21 = r21 - r21.where(memdf).T.groupby(sec).transform("mean").T
sB = (-rel21).where(top_sec & liq)
strategies["B 업종모멘텀+업종내반전 (월)"] = dict(score=A(sB), mode="rebal", rebal_days=month_end, K=10, hold_rank=25)

# C. 52주 신고가 근접 + 12-1 모멘텀 (George-Hwang 2004)
sC = (C / hi252).where((C / hi252 >= 0.95) & liq) + 0.1 * xrank(C.shift(21) / C.shift(252) - 1)
strategies["C 52주고점근접+12-1모멘텀 (월)"] = dict(score=A(sC), mode="rebal", rebal_days=month_end, K=10, hold_rank=25)

# D. Clenow Stocks on the Move — 90일 로그회귀 기울기(연율)×R², 주간, SPY>SMA200 일 때만 신규
lc = np.log(C)
x = np.arange(90); xm = x.mean(); sxx = ((x - xm) ** 2).sum()
w = (x - xm) / sxx
slope = lc.rolling(90).apply(lambda y: np.dot(w, y), raw=True)
ym = lc.rolling(90).mean()
r2 = (slope ** 2 * sxx) / (lc.rolling(90).var(ddof=0) * 90)
gap = (O / C.shift() - 1).abs().rolling(90).max()
sD = ((np.exp(slope * 252) - 1) * r2).where((C > sma100) & (gap < 0.15) & liq)
strategies["D Clenow 모멘텀 (주)"] = dict(score=A(sD), mode="rebal", rebal_days=week_end, K=20, hold_rank=40, market_ok=mk200)

# E. Minervini 트렌드 템플릿 + 거래량 돌파 (R1 단순화)
tt = (C > sma50) & (sma50 > sma150) & (sma150 > sma200) & (sma200 > sma200.shift(21)) & (C >= 1.3 * lo252) & (C >= 0.75 * hi252) & (xrank(r252) >= 0.7)
brk = (C >= C.rolling(20).max()) & (V >= 1.5 * V.rolling(50).mean())
tight = (H.rolling(20).max() / L.rolling(20).min() - 1) <= 0.20
sE = xrank(r252).where(tt & brk & tight & liq)
stopE = np.minimum(0.08, 1.5 * atr20 / C)
strategies["E Minervini TT+VCP돌파 (스윙)"] = dict(score=A(sE), mode="swing", K=10, stop=A(stopE), exit_sig=B(C < sma50), market_ok=mk200)

# F. Qullamaggie 돌파 — 1/3/6개월 상위 2%, ADR≥4%, 20일 박스 ≤15%, 박스 상단 돌파, 스톱 1ATR, SMA20 이탈 청산
top2 = (xrank(r21) >= 0.98) | (xrank(r63) >= 0.98) | (xrank(r126) >= 0.98)
adr = ((H / L - 1).rolling(20).mean() >= 0.04)
box = (H.shift(1).rolling(20).max() / L.shift(1).rolling(20).min() - 1) <= 0.15
sF = xrank(r63).where(top2 & adr & box & (C > H.shift(1).rolling(20).max()) & (sma10 > sma10.shift(5)) & liq)
strategies["F Qullamaggie 돌파 (스윙)"] = dict(score=A(sF), mode="swing", K=10, stop=A(atr20 / C), exit_sig=B(C < sma20), market_ok=mk140)

# G. 에피소딕 피벗 (가격만) — 시가 갭 ≥10%, 거래량 ≥3×50일, 직전 60일 수익 ≤20%, 스톱=갭일 저가, SMA20 이탈 청산
gp = (O / C.shift() - 1)
sG = gp.where((gp >= 0.10) & (V >= 3 * V.rolling(50).mean().shift()) & (C.shift() / C.shift(61) - 1 <= 0.20) & (C > O) & liq)
stopG = (1 - L / C).clip(lower=0.02)
strategies["G 에피소딕피벗 갭 (스윙)"] = dict(score=A(sG), mode="swing", K=10, stop=A(stopG), exit_sig=B(C < sma20), market_ok=mk200)

# H. 신고가 추세 (Wilcox-Crittenden/Zarattini) — 데이터 시작 이후 최고 종가, 트레일 10×ATR42
ath = C >= C.cummax()
sH = xrank(r252).where(ath & liq)
strategies["H 사상최고가 추세 (스윙)"] = dict(score=A(sH), mode="swing", K=20, trail=A((10 * atr42 / C).clip(upper=0.5)))

# I. Connors RSI2 (R6, 종목) — 참고
d_ = C.diff(); up = d_.clip(lower=0).ewm(alpha=0.5).mean(); dn = (-d_.clip(upper=0)).ewm(alpha=0.5).mean()
rsi2 = 100 - 100 / (1 + up / dn)
sI = (-rsi2).where((rsi2 < 5) & (C > sma200) & liq)
strategies["I Connors RSI2 종목 (스윙)"] = dict(score=A(sI), mode="swing", K=10, exit_sig=B(C > C.rolling(5).mean()), max_hold=10)

rows = []
for cost in (0.003, 0.0012):
    for name, kw in strategies.items():
        eq, tr = simulate(P, cost=cost, **kw)
        r = stats(name, eq, tr); r["cost"] = cost; rows.append(r)
        print(f"{cost} {name}: CAGR {r['CAGR']:.1%} MDD {r['MDD']:.1%} trades/yr {r['trades/yr']:.0f}", flush=True)
# 기준선
s = spy[(spy.index >= "2012-03-01") & (spy.index <= P.dates[-1])]
eqs = s / s.iloc[0]
rows.append(stats("SPY 보유", eqs, pd.DataFrame(columns=["ret", "days"])) | {"cost": 0})
df = pd.DataFrame(rows)
show = df.copy()
for c in ("CAGR", "H1", "H2", "MDD", "6m>=9%", "6m_med", "med_trade", "win"):
    show[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:.1%}")
show["trades/yr"] = df["trades/yr"].map("{:.0f}".format); show["hold"] = df["hold"].map(lambda v: "" if pd.isna(v) else f"{v:.0f}d")
show["cost"] = df["cost"].map(lambda v: f"{v*100:.2f}%")
print(show.to_string(index=False))
df.to_csv("/home/quant/quant-v31/scripts/research/swing1.csv", index=False)
