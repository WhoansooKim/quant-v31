"""생존편향 정량화 (§22.AO-57).

확인된 사실: hist_prices_adj 1,540종목 중 **2026 이전에 이력이 끝나는 종목이 0개**다.
즉 풀은 "2026 에 존재하던 종목" 에서 뽑혔고 15년간 상장폐지가 하나도 없다 — 전형적
생존편향이다. 상폐 데이터는 유료라 직접 보정이 불가(§22.AO-25 무료 경로).
→ 직접 측정 대신 **노출량**을 재고 **민감도 한계**를 계산한다.
"""
import sys, pickle
sys.path.insert(0,"/home/quant/quant-v31"); sys.path.insert(0,"/home/quant/quant-v31/scripts")
import numpy as np, pandas as pd
sys.argv=['x']
import turnover_sweep as ts, hist_portfolio as hp
from hist_backtest import RULES

sig, arrs = pickle.load(open(ts.CACHE,"rb"))
px = {s_: dict(zip(a["d"], a["c"])) for s_, a in arrs.items()}
sig = sig.copy(); sig["close"] = [px.get(r.symbol,{}).get(r.d, np.nan) for r in sig.itertuples()]
base = sig[(sig.mom>=0.60)&(sig.close.between(10,250))]
hp.SIDE_COMM = 0.0025
eq, tr = hp.portfolio(base, arrs, {**RULES, **ts.LIVE}, max_pos=4, target_deploy=0.45)
yrs = (pd.to_datetime(eq.d.iloc[-1]) - pd.to_datetime(eq.d.iloc[0])).days/365.25
tpy = len(tr)/yrs; PP = 0.45/4

print("── 1) 풀이 '승자만' 인가 — 보유 종목의 최악 낙폭 ──")
worst = []
for s_, a in arrs.items():
    c = a["c"][np.isfinite(a["c"])]
    if len(c) > 250:
        worst.append((s_, (c/np.maximum.accumulate(c) - 1).min()))
w = pd.DataFrame(worst, columns=["sym","mdd"])
for thr in (-0.5, -0.7, -0.8, -0.9):
    print(f"   역사상 최대낙폭 {thr*100:.0f}% 이하 종목: {(w.mdd<=thr).sum():4d} / {len(w)} "
          f"({(w.mdd<=thr).mean()*100:.1f}%)")
print(f"   → 풀에 대형 하락 종목은 있다. 없는 것은 **사라진** 종목이다(상폐 0건).")

print("\n── 2) 전략이 실제로 '죽어가는 종목'을 사는가 ──")
print(f"   진입 조건: close>SMA50>SMA200 · 5일 돌파 · mom랭크≥0.60 · 유동성 상위400")
print(f"   거래 {len(tr)}건 수익률 분위:")
q = tr.ret.quantile([0.001,0.01,0.05,0.25,0.5]).round(2)
print("   " + "  ".join(f"p{int(k*1000)/10:g}={v:+.1f}%" for k,v in q.items()))
print(f"   −30% 이하 {(tr.ret<=-30).sum()}건 ({(tr.ret<=-30).mean()*100:.2f}%) · "
      f"−50% 이하 {(tr.ret<=-50).sum()}건 · 최악 {tr.ret.min():+.1f}%")
print(f"   하드스톱 1.5×ATR 이 왜 중요한가: 청산사유 분포 {dict(tr.reason.value_counts())}")

print("\n── 3) 민감도 한계 — 몇 %가 '갭하락 상폐' 여야 엣지가 사라지나 ──")
print(f"   회전 {tpy:.0f}건/년 · 종목비중 {PP:.1%} · 정상 손절 ≈ −5%")
print(f"   {'갭손실':>8s} {'f=0.5%':>9s} {'f=1%':>9s} {'f=2%':>9s} {'f=5%':>9s}   (연 CAGR 비용)")
for gap in (-0.30, -0.50, -0.80, -1.00):
    row = [tpy*PP*f*(abs(gap)-0.05)*100 for f in (0.005,0.01,0.02,0.05)]
    print(f"   {gap*100:7.0f}% " + " ".join(f"{v:8.2f}%p" for v in row))
print(f"   현재 추정 net CAGR +22.39% · 목표 18% → 여유 4.39%p")
print(f"   → −50% 갭이 진입의 **1.2%** 에서 일어나면 여유가 사라진다")
print(f"      (15년 {len(tr)}거래 중 {int(len(tr)*0.012)}건)")

print("\n── 4) 유동성 상위 400 이 노출을 얼마나 줄이나 ──")
print(f"   전략은 일별 달러거래대금 상위 400 만 본다 = 대형주.")
print(f"   상폐는 소형주에 집중되므로 이 필터가 생존편향 노출의 주된 방어막이다.")
print(f"   실측 진입 종목의 거래대금 순위 분포를 보려면 hist_indicators 재조회 필요 — 아래.")
