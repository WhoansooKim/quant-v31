"""Tier 3 알파 강화 백테스트 — 헤지 사이징 × 레버리지 인버스 × 신호속도.

현재 Tier3 = SH(-1x) 20%, SPY<SMA200 게이팅. 이를 알파원천으로 강화하는 방안 검증.
게이팅(하락국면만 보유)은 유지 — 상승국면 인버스 보유는 감쇠로 파멸적(재검증서 확인).
측정: 하락국면 누적수익, 하락 에피소드 수/승률(whipsaw), 헤지슬리브 MDD.
"""
import yfinance as yf
import pandas as pd
import numpy as np

# 데이터: SPY(추세) + 인버스 3종
syms = ['SPY', 'SH', 'SDS', 'SPXU']
d = yf.download(' '.join(syms), start='2021-01-01', end='2025-12-31',
                group_by='ticker', progress=False)
px = pd.DataFrame({s: d[s]['Close'] for s in syms}).dropna()

def downturn_mask(sma_days):
    sma = px['SPY'].rolling(sma_days).mean()
    m = (px['SPY'] < sma)
    return m[m.index >= '2022-01-01']

def episodes(mask):
    """연속 하락구간(에피소드) 분리 → 각 에피소드 시작/끝."""
    eps = []
    in_ep = False; start = None
    for dt, v in mask.items():
        if v and not in_ep:
            in_ep = True; start = dt
        elif not v and in_ep:
            in_ep = False; eps.append((start, prev))
        prev = dt
    if in_ep:
        eps.append((start, prev))
    return eps

def hedge_perf(inv_sym, sma_days, size):
    """하락국면만 inv_sym 을 size 비중 보유 시 성과."""
    mask = downturn_mask(sma_days)
    sub = px[px.index >= '2022-01-01'].copy()
    ret = sub[inv_sym].pct_change().fillna(0)
    # 하락국면 일에만 size 비중 노출 (나머지 현금=0수익)
    strat_ret = np.where(mask.reindex(sub.index).fillna(False), ret * size, 0.0)
    strat_ret = pd.Series(strat_ret, index=sub.index)
    cum = (1 + strat_ret).prod() - 1
    # 헤지슬리브 MDD
    eq = (1 + strat_ret).cumprod()
    mdd = ((eq - eq.cummax()) / eq.cummax()).min()
    # 에피소드별 (whipsaw)
    eps = episodes(mask.reindex(sub.index).fillna(False))
    ep_rets = []
    for s, e in eps:
        er = (1 + ret.loc[s:e] * size).prod() - 1
        ep_rets.append(er)
    win = sum(1 for x in ep_rets if x > 0)
    return cum, mdd, len(eps), win, np.mean(ep_rets) if ep_rets else 0

print("=== Tier3 강화: 인버스 × 사이징 (SMA200 게이팅, 2022-2025) ===")
print(f"{'인버스':<6}{'배율':>5}{'사이징':>7}{'누적수익':>9}{'슬리브MDD':>9}{'에피소드':>7}{'승':>4}{'에피평균':>8}")
for inv, lev in [('SH', '-1x'), ('SDS', '-2x'), ('SPXU', '-3x')]:
    for size in [0.20, 0.40, 0.60]:
        cum, mdd, neps, win, epavg = hedge_perf(inv, 200, size)
        print(f"{inv:<6}{lev:>5}{size*100:>6.0f}% {cum*100:>+8.1f}% {mdd*100:>+8.1f}% {neps:>7} {win:>3} {epavg*100:>+7.1f}%")

print("\n=== 신호속도 비교 (SH 40% 고정, SMA 일수별) ===")
print(f"{'SMA':>5}{'하락일%':>8}{'누적수익':>9}{'슬리브MDD':>9}{'에피소드':>7}{'승률':>6}")
for sma in [100, 150, 200, 250]:
    cum, mdd, neps, win, epavg = hedge_perf('SH', sma, 0.40)
    mask = downturn_mask(sma)
    downpct = mask.mean() * 100
    wr = win/neps*100 if neps else 0
    print(f"{sma:>5}{downpct:>7.0f}% {cum*100:>+8.1f}% {mdd*100:>+8.1f}% {neps:>7} {wr:>5.0f}%")

print("\n※ 게이팅 유지 필수: 상승국면 인버스 보유는 재검증서 -42.8%(감쇠) 확인. 하락국면만 보유.")
print("※ 레버리지 인버스(-2x/-3x)는 변동성감쇠 심함 — 짧은 급락엔 유리, 긴 횡보하락엔 불리.")
