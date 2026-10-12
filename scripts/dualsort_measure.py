#!/usr/bin/env python
"""dual_sort 측정 — 거른 37% 가 통과한 쪽보다 나았는가 (§22.AO-46).

배경: `strategy/swing.py:_apply_dual_sort` 가 라이브 진입 공급의 **63%** 를 거른다
(월 21.2 → 7.9건). 공급 자체는 수익을 올리지 않는다 — 슬롯이 늘면 수익은 내려간다
(§22.AO-45). 문제는 **선택**이다: dual_sort 가 잘못된 쪽을 거르고 있으면 거래당 엣지를
깎고 있는 것이다. 라이브 n=130 으로는 검정 불가라 15년 소급이 필요했다.

규칙 재현 (라이브와 **같은 식**이어야 측정이 의미가 있다):
  value = _quick_value_score(pe_ttm, pb, fcf_yield, ev_ebitda)   0~1, 결손이면 0.5
  combined = mom × dual_sort_momentum_weight + value × dual_sort_value_weight
  통과 = combined >= dual_sort_threshold
  라이브 현재값: 가중 0.5/0.5, 문턱 0.5 → **mom + value >= 1.0**

🔴 선행 참조 편향(lookahead) 방지: 분기 재무는 기간종료일 기준으로 들어오지만 공시는
   그 뒤다. `--lag` 일(기본 60)을 더한 날짜부터만 그 분기 값을 쓴다. 45/60/90 민감도 확인.
"""
from __future__ import annotations
import argparse, sys
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
sys.path.insert(0, "/home/quant/quant-v31/scripts")
from hist_backtest import build_arrays, sim, RULES, COMM
from hist_portfolio import portfolio
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

BEST = {**RULES, "trail_mult": 1.0, "swing_path": False,
        "rsi2_min_hold": 999, "time_stop": 60, "be_enabled": False}


def value_score(pe, pb, fcfy, ev, use: set[str]) -> float:
    """engine_v4/strategy/swing.py:_quick_value_score 의 축자 재현.
    🔴 분모(total)가 **사용가능한 지표에만** 쌓인다 — 지표가 하나뿐이고 그게 유리하면 1.0
       이 나온다. 이게 결함인지 아닌지는 측정이 답한다(use 로 지표 집합을 바꿔 본다)."""
    score = total = 0.0
    if "pe" in use and pe is not None and pe > 0:
        score += 30 if pe < 15 else 20 if pe < 20 else 10 if pe < 30 else 0
        total += 30
    if "pb" in use and pb is not None and pb > 0:
        score += 25 if pb < 2 else 15 if pb < 3 else 10 if pb < 5 else 0
        total += 25
    if "fcf" in use and fcfy is not None:
        score += 25 if fcfy > 5 else 15 if fcfy > 3 else 10 if fcfy > 1 else 0
        total += 25
    if "ev" in use and ev is not None and ev > 0:
        score += 20 if ev < 10 else 12 if ev < 15 else 5 if ev < 20 else 0
        total += 20
    return (score / total) if total > 0 else 0.5


def load_all(pg, lag: int):
    with pg.get_conn() as c:
        print("바 적재...", flush=True)
        bars = pd.DataFrame(c.execute("""
            SELECT p.symbol, p.time::date AS d, p.open::float AS o, p.close::float AS c,
                   h.sma_50::float AS s50, h.sma_200::float AS s200
            FROM hist_prices_adj p LEFT JOIN hist_indicators h
              ON h.symbol=p.symbol AND h.time=p.time ORDER BY p.symbol, p.time""").fetchall())
        print("신호 적재 (three조건 전체 — dual_sort 의 판단 대상)...", flush=True)
        sig = pd.DataFrame(c.execute("""
            WITH u AS (SELECT i.time, i.symbol, i.atr14, i.return_20d_rank,
                              p.close::float AS px,
                              row_number() OVER (PARTITION BY i.time
                                                 ORDER BY i.dollar_vol_20d DESC) lr
                       FROM hist_indicators i JOIN hist_prices_adj p
                         ON p.symbol=i.symbol AND p.time=i.time
                       WHERE i.clean AND i.trend_aligned AND i.breakout_5d
                             AND i.volume_ratio >= 1.0 AND i.atr14 > 0)
            SELECT time::date AS d, symbol, atr14, return_20d_rank AS mom, px
            FROM u WHERE lr <= 200 ORDER BY symbol, time""").fetchall())
        print("재무 적재...", flush=True)
        fun = pd.DataFrame(c.execute("""
            SELECT symbol, period, pe_ttm::float AS pe, pb::float AS pb,
                   fcf_per_share::float AS fcfps, ev_ebitda::float AS ev
            FROM hist_fundamentals ORDER BY symbol, period""").fetchall())
    return bars, sig, fun


def attach_value(sig: pd.DataFrame, fun: pd.DataFrame, lag: int, use: set[str]):
    """신호일 기준 **공시 가능한** 최신 분기 재무를 붙인다 (merge_asof, backward)."""
    fun = fun.copy()
    fun["eff"] = pd.to_datetime(fun["period"]) + pd.Timedelta(days=lag)
    sig = sig.copy()
    sig["dt"] = pd.to_datetime(sig["d"])
    out = []
    for symbol, g in sig.groupby("symbol", sort=False):
        f = fun[fun.symbol == symbol]
        g = g.sort_values("dt")
        if len(f) == 0:
            g["pe"] = g["pb"] = g["fcfps"] = g["ev"] = np.nan
        else:
            g = pd.merge_asof(g, f.sort_values("eff")[["eff","pe","pb","fcfps","ev"]],
                              left_on="dt", right_on="eff", direction="backward")
        out.append(g)
    sig = pd.concat(out, ignore_index=True)
    # fcf_yield(%) = 주당FCF / 주가 × 100 — 라이브의 freeCashFlowYieldTTM 과 같은 의미
    sig["fcfy"] = np.where(sig.px > 0, sig.fcfps / sig.px * 100.0, np.nan)
    sig["value"] = [value_score(
        None if pd.isna(r.pe) else r.pe, None if pd.isna(r.pb) else r.pb,
        None if pd.isna(r.fcfy) else r.fcfy, None if pd.isna(r.ev) else r.ev, use)
        for r in sig.itertuples()]
    return sig


def trade_level(sig, arrs, m_w, v_w, thr):
    """mom>=0.92 신호를 전부 시뮬레이션하고 dual_sort 통과/기각으로 나눠 비교."""
    idx = {s: {d: i for i, d in enumerate(a["d"])} for s, a in arrs.items()}
    s = sig[sig.mom >= 0.92].copy()
    s["comb"] = s.mom * m_w + s.value * v_w
    s["passed"] = s.comb >= thr        # 'pass' 는 예약어 — itertuples 가 _N 으로 바꿔 버린다
    rows = []
    for r in s.itertuples():
        a = arrs.get(r.symbol)
        if a is None: continue
        i0 = idx[r.symbol].get(r.d)
        if i0 is None: continue
        t = sim(a, i0, float(r.atr14), BEST)
        if t is None: continue
        rows.append({"passed": bool(r.passed), "net": t[0] - COMM,
                     "value": r.value, "mom": r.mom, "hold": t[1], "why": t[2]})
    return pd.DataFrame(rows)


def boot_ci(a, b, n=4000, seed=42):
    rng = np.random.default_rng(seed)
    d = [np.median(rng.choice(a, len(a))) - np.median(rng.choice(b, len(b))) for _ in range(n)]
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--lag", type=int, default=60)
    ap.add_argument("--use", default="pe,pb")   # 라이브 감사: fcfYield·evEbitda 가용률 0.0%
    ap.add_argument("--mw", type=float, default=0.5)
    ap.add_argument("--vw", type=float, default=0.5)
    ap.add_argument("--thr", type=float, default=0.5)
    ap.add_argument("--maxpos", type=int, default=5)
    ap.add_argument("--deploy", type=float, default=0.45)
    a = ap.parse_args()
    use = set(a.use.split(","))
    pg = PostgresStore(get_config().pg_dsn)
    bars, sig, fun = load_all(pg, a.lag)
    print(f"신호 {len(sig):,}  재무 {len(fun):,}행 / {fun.symbol.nunique():,}종목", flush=True)
    arrs = build_arrays(bars)
    sig = attach_value(sig, fun, a.lag, use)

    cov = sig.value.notna().mean()
    neutral = (sig.value == 0.5).mean()
    print(f"\n━━ value 점수 분포 (lag={a.lag}일, 지표={sorted(use)}) ━━")
    print(f"  결손 중립(0.5) 비율 {neutral*100:.1f}%")
    print(sig.value.describe().round(3).to_string())

    print("\n━━ 거래 단위: dual_sort 통과 vs 기각 (mom>=0.92) ━━", flush=True)
    tl = trade_level(sig, arrs, a.mw, a.vw, a.thr)
    p, q = tl[tl.passed].net.values, tl[~tl.passed].net.values
    print(f"  통과 n={len(p):,}  중앙 {np.median(p):+.3f}%  평균 {p.mean():+.3f}%  승률 {(p>0).mean()*100:.1f}%")
    print(f"  기각 n={len(q):,}  중앙 {np.median(q):+.3f}%  평균 {q.mean():+.3f}%  승률 {(q>0).mean()*100:.1f}%")
    if len(p) > 30 and len(q) > 30:
        lo, hi = boot_ci(p, q)
        print(f"  중앙값 차이(통과 − 기각) 95%CI = [{lo:+.3f}, {hi:+.3f}]%p"
              f"  → {'dual_sort 가 좋은 쪽을 고른다' if lo > 0 else ('dual_sort 가 나쁜 쪽을 고른다' if hi < 0 else '구별력 없음')}")

    print("\n━━ 포트폴리오: 라이브 파이프라인 재현 (dual_sort on/off) ━━", flush=True)
    base = sig[(sig.px >= 10) & (sig.px <= 250)]
    rows = []
    for lab, sel in (("dual_sort OFF (mom>=0.92 만)", base[base.mom >= 0.92]),
                     ("dual_sort ON  (라이브 현행)",
                      base[(base.mom * a.mw + base.value * a.vw >= a.thr) & (base.mom >= 0.92)])):
        eq, tr = portfolio(sel, arrs, BEST, max_pos=a.maxpos, target_deploy=a.deploy)
        e = eq.copy(); e["dt"] = pd.to_datetime(e.d)
        yrs = (e.dt.iloc[-1] - e.dt.iloc[0]).days / 365.25
        per = np.array([((g.nav/g.nav.cummax()-1)*100).min() for _, g in e.groupby(e.dt.dt.year)])
        r = e.set_index("dt").nav.resample("ME").last().pct_change().dropna()
        rows.append({"설정": lab, "신호수": len(sel), "거래": len(tr),
                     "CAGR": round(((e.nav.iloc[-1]/e.nav.iloc[0])**(1/yrs)-1)*100, 1),
                     "최대낙폭": round(float(((e.nav/e.nav.cummax()-1)*100).min()), 1),
                     "연낙폭평균": round(float(per.mean()), 1),
                     "샤프": round(float(r.mean()/r.std()*np.sqrt(12)), 2)})
        print(rows[-1], flush=True)
    print("\n" + pd.DataFrame(rows).to_string(index=False))
