"""승인 게이트별 기여도 측정 (§SESSION_PICKUP §2-②).

기각 사유가 DB에 저장되지 않으므로 **게이트를 재계산**해 귀속시킨다.
핵심 질문: 각 게이트가 거른 신호의 선행수익률이 통과분보다 **낮은가**?
낮으면 게이트가 제 일을 한 것이고, 높으면 그 게이트가 가치를 파괴하고 있다.
"""
import numpy as np, pandas as pd
from scipy.stats import mannwhitneyu
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

pg = PostgresStore(get_config().pg_dsn)
with pg.get_conn() as c:
    sig = pd.DataFrame(c.execute("""
        SELECT signal_id, symbol, time::date AS d, status,
               composite_score::float AS comp, return_20d_rank::float AS mom,
               technical_score::float AS tech, macro_score::float AS macro,
               llm_score AS llm
        FROM swing_signals
        WHERE signal_type='ENTRY' AND composite_score IS NOT NULL
        ORDER BY time""").fetchall())
    px = pd.DataFrame(c.execute("""
        SELECT symbol, time::date AS d, close::float AS close
        FROM daily_prices WHERE time > '2026-01-01'""").fetchall())
    cfg = {r["key"]: r["value"] for r in c.execute(
        "SELECT key, value FROM swing_config WHERE key LIKE 'auto_approve%%' OR key LIKE 'intersection%%'").fetchall()}

SMIN = float(cfg.get("auto_approve_score_min", 61))
SMAX = float(cfg.get("auto_approve_score_max", 85))
MMIN = float(cfg.get("auto_approve_macro_min", 30))
IMOM = float(cfg.get("intersection_momentum_min", 0.70))
ITEC = float(cfg.get("intersection_technical_min", 60))
print(f"게이트 설정: score [{SMIN},{SMAX}] · macro>={MMIN} · 교집합 mom>={IMOM} AND tech>={ITEC}")

# 선행수익률 (거래일 기준)
px = px.drop_duplicates(['symbol','d']).sort_values(['symbol','d'])
out=[]
for s,g in px.groupby('symbol'):
    g=g.reset_index(drop=True)
    for h in (5,20):
        g[f'f{h}'] = g['close'].shift(-h)/g['close'] - 1
    out.append(g)
px=pd.concat(out)
df = sig.merge(px[['symbol','d','f5','f20']], on=['symbol','d'], how='left')
df = df.dropna(subset=['f20'])
print(f"표본: 시그널 {len(sig)} → 선행수익률 산출 가능 {len(df)}\n")

# ── 게이트별 통과/탈락 판정 ──
gates = {
    "score_min (<%g)"      % SMIN: df.comp <  SMIN,
    "score_max (>%g)"      % SMAX: df.comp >  SMAX,
    "macro (<%g)"          % MMIN: df.macro.fillna(99) < MMIN,
    "교집합 momentum (<%g)"% IMOM: df.mom.fillna(0) < IMOM,
    "교집합 technical (<%g)"% ITEC: df.tech.fillna(0) < ITEC,
}
print(f"{'게이트':26}{'거른수':>7}{'거른것 중앙':>13}{'통과 중앙':>11}{'차이':>9}{'p값':>8}  판정")
for name, fail in gates.items():
    a = df.loc[fail, 'f20']; b = df.loc[~fail, 'f20']
    if len(a) < 5 or len(b) < 5:
        print(f"{name:26}{len(a):7}   표본부족"); continue
    diff = a.median()*100 - b.median()*100
    try: _, p = mannwhitneyu(a, b, alternative='two-sided')
    except Exception: p = float('nan')
    # 거른 것이 통과분보다 수익이 낮아야(diff<0) 게이트가 제 일을 한 것
    verdict = "✅ 유익" if diff < -1 else ("🔴 가치파괴" if diff > 1 else "⚪ 무의미")
    print(f"{name:26}{len(a):7}{a.median()*100:12.2f}%{b.median()*100:10.2f}%{diff:+8.2f}%{p:8.3f}  {verdict}")

# ── 교집합 게이트 전체 (AND 조건) ──
print()
isec_fail = (df.mom.fillna(0) < IMOM) | (df.tech.fillna(0) < ITEC)
a, b = df.loc[isec_fail,'f20'], df.loc[~isec_fail,'f20']
_, p = mannwhitneyu(a,b,alternative='two-sided')
print(f"{'교집합 게이트 전체(OR탈락)':26}{len(a):7}{a.median()*100:12.2f}%{b.median()*100:10.2f}%"
      f"{a.median()*100-b.median()*100:+8.2f}%{p:8.3f}")
print(f"  거른 것 평균 {a.mean()*100:+.2f}% vs 통과 평균 {b.mean()*100:+.2f}%  승률 {(a>0).mean()*100:.1f}% vs {(b>0).mean()*100:.1f}%")

# ── 전 게이트 통과 vs 실제 체결 ──
print()
allpass = ~(isec_fail | (df.comp<SMIN) | (df.comp>SMAX) | (df.macro.fillna(99)<MMIN))
ex = df.status=='executed'
for lab, m in [("전 게이트 통과", allpass), ("실제 체결", ex),
               ("통과했지만 미체결", allpass & ~ex), ("탈락인데 체결", ~allpass & ex)]:
    v = df.loc[m,'f20']
    if len(v): print(f"  {lab:20} n={len(v):3}  중앙 {v.median()*100:+6.2f}%  평균 {v.mean()*100:+6.2f}%  승률 {(v>0).mean()*100:5.1f}%")
