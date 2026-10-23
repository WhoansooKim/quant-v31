#!/usr/bin/env python
"""섹터 상한 A/B — 라이브 정합 포트폴리오(5슬롯 · 총노출 45% · 상위300 · mom>=0.60).

계기: 2026-10-23 PG·CL·KMB(생활용품 3종) 동시 보유, 계좌 25.5% 가 한 섹터.
질문: 섹터당 보유 상한(1/2/3)이 이 시스템의 수익·위험을 바꾸는가?

판정 원칙
- 거래당 우위(중앙값 우선)와 CAGR 을 같이 본다. MDD 는 참고만(수익이 다르면 무효).
- 시간 분할 홀드아웃(전반/후반) 양쪽에서 같은 방향이어야 채택.
- 섹터는 **현재** GICS 를 과거에 소급 적용한다(분류 변경 미반영 — 한계로 명시).
- 가격 필터 $10~250 은 수정주가 종가로 근사(dualsort_measure.py 와 동일 방식).
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
sys.path.insert(0, "/home/quant/quant-v31/scripts")
from hist_backtest import load, build_arrays, RULES
from hist_portfolio import portfolio
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

# 라이브 config 와 대조 (2026-10-23 swing_config 조회값)
LIVE = {**RULES, "trail_mult": 1.0, "swing_path": False, "rsi2_min_hold": 999,
        "time_stop": 60, "be_enabled": False}          # hard 1.5 · activation 1R
MAX_POS, DEPLOY = 5, 0.45                               # 포지션당 ~9% · 총노출 45%


def stats(eq, tr, lab):
    e = eq.copy(); e["dt"] = pd.to_datetime(e.d)
    yrs = (e.dt.iloc[-1] - e.dt.iloc[0]).days / 365.25
    cagr = ((e.nav.iloc[-1] / e.nav.iloc[0]) ** (1 / yrs) - 1) * 100
    m = e.set_index("dt").nav.resample("ME").last().pct_change().dropna()
    sharpe = m.mean() / m.std() * np.sqrt(12) if m.std() else 0
    dd = ((e.nav / e.nav.cummax() - 1) * 100).min()
    return {"variant": lab, "CAGR": round(cagr, 2), "sharpe": round(float(sharpe), 2),
            "MDD(참고)": round(dd, 1), "worst_m": round(m.min() * 100, 1),
            "trades": len(tr), "med_ret": round(tr.ret.median(), 3),
            "mean_ret": round(tr.ret.mean(), 3), "deploy": round(e.deployed.mean() * 100)}


if __name__ == "__main__":
    pg = PostgresStore(get_config().pg_dsn)
    with pg.get_conn() as c:
        uni = pd.DataFrame(c.execute(
            "SELECT symbol, nullif(sector,'') sector FROM swing_universe").fetchall())
    sector_of = dict(zip(uni.symbol, uni.sector))
    sig, bars = load(pg, 0.60, 300, 1.0, universe=list(uni.symbol))
    px = bars[["symbol", "d", "c"]].rename(columns={"c": "px"})
    sig = sig.merge(px, on=["symbol", "d"], how="left")
    sig = sig[(sig.px >= 10) & (sig.px <= 250)]
    print(f"신호 {len(sig):,}건 · {sig.d.min()} ~ {sig.d.max()} · 섹터결손 "
          f"{sig.symbol.map(sector_of).isna().mean():.1%}", flush=True)
    arrs = build_arrays(bars)

    dates = np.array(sorted(sig.d.unique()))
    mid = dates[len(dates) // 2]
    halves = {"전체": sig, "전반": sig[sig.d < mid], "후반": sig[sig.d >= mid]}

    rows = []
    for cap in (() if "--robust-only" in sys.argv else (None, 3, 2, 1)):
        lab = "상한 없음(현행)" if cap is None else f"섹터당 ≤{cap}"
        for hn, s_ in halves.items():
            eq, tr = portfolio(s_, arrs, LIVE, max_pos=MAX_POS, target_deploy=DEPLOY,
                               sector_of=sector_of, max_per_sector=cap)
            r = stats(eq, tr, lab); r["구간"] = hn; rows.append(r)
        print(f"  done {lab}", flush=True)

    df = pd.DataFrame(rows)
    for hn in (halves if rows else ()):
        print(f"\n━━ {hn} ━━")
        print(df[df.구간 == hn].drop(columns="구간").to_string(index=False))


    # 강건성: 3등분 + 슬롯 수 변경(4/6) — 상한 효과가 분할·슬롯에 따라 뒤집히는지
    print("\n━━ 강건성 ━━", flush=True)
    t1, t2 = dates[len(dates) // 3], dates[2 * len(dates) // 3]
    thirds = {"1/3": sig[sig.d < t1], "2/3": sig[(sig.d >= t1) & (sig.d < t2)], "3/3": sig[sig.d >= t2]}
    rob = []
    for cap in (None, 3, 2):
        lab = "없음" if cap is None else f"≤{cap}"
        r = {"variant": lab}
        for hn, s_ in thirds.items():
            eq, tr = portfolio(s_, arrs, LIVE, max_pos=MAX_POS, target_deploy=DEPLOY,
                               sector_of=sector_of, max_per_sector=cap)
            r[hn] = stats(eq, tr, lab)["CAGR"]
        for mp in (4, 6):
            eq, tr = portfolio(sig, arrs, LIVE, max_pos=mp, target_deploy=DEPLOY,
                               sector_of=sector_of, max_per_sector=cap)
            r[f"{mp}슬롯"] = stats(eq, tr, lab)["CAGR"]
        rob.append(r); print(f"  done {lab}", flush=True)
    print(pd.DataFrame(rob).to_string(index=False))
