#!/usr/bin/env python
"""§22.AO-66 정직한 러너 — 체결 현실화 후 기준선 · 핵심 결정 재측정 · 지수 대비 판정.

배경(§22.AO-65): hist_portfolio 는 스톱을 스톱가에 체결해 CAGR 을 16.21 → 7.67%(갭 시가 체결)로
부풀리고 있었다. §22.AO-43~64 의 결정(trail 1.0 · rsi2 off · hard 1.5 …)은 전부 그 가정 위에서 내렸다.

체결 모델(라이브 2026-08-01~ 스톱청산 49건 실측):
  - 갭(시가 ≤ 스톱) 35% — 시가 대비 +0.40% → 시가 체결
  - 비갭 — 스톱가 대비 중앙 −0.55% → stop_slip=0.0055
  - 진입·기타 청산 편도 5bp(§22.AO-60), 수수료 0.25%/방향(기존)
  - 장중 이탈: 라이브는 하루 4회 확인 → "close"(낙관)·"low"(비관) 두 경계 사이
판정: 두 경계 · 전반/후반 모두 같은 방향일 때만 채택. 거래당 중앙값 병기. MDD 는 참고만.
지수 비교: SPY/QQQ 매수보유(100%) 와 **같은 평균 투자율**의 SPY+현금(노출 맞춤).
"""
from __future__ import annotations
import sys, time
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
sys.path.insert(0, "/home/quant/quant-v31/scripts")
from hist_backtest import load, build_arrays
from hist_portfolio import portfolio
from measure_sector_cap import LIVE, MAX_POS, DEPLOY, stats
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

REAL = dict(gap_fill=True, stop_slip=0.0055, slip=0.0005)
RUNNERS = {
    "R0 기존(스톱가)": dict(),
    "R1 갭시가": dict(gap_fill=True),
    "R2 현실·종가판정": dict(REAL, touch="close"),
    "R3 현실·저가판정": dict(REAL, touch="low"),
}
# 현행 = LIVE (trail 1.0 · hard 1.5 · rsi2 off(999) · time 60 · BE off · activation 1R)
CONFIGS = {
    "현행": {},
    "rsi2 on(hold0)": {"rsi2_min_hold": 0},
    "rsi2 on(hold8)": {"rsi2_min_hold": 8},
    "trail 1.5": {"trail_mult": 1.5},
    "trail 2.5": {"trail_mult": 2.5},
    "hard 1.0": {"hard_mult": 1.0},
    "hard 2.0": {"hard_mult": 2.0},
    "hard 2.5": {"hard_mult": 2.5},
    "hard 3.0": {"hard_mult": 3.0},
    "BE on": {"be_enabled": True},
    "time 21": {"time_stop": 21},
}


def bench(pg, d0, d1, deploy):
    with pg.get_conn() as c:
        b = pd.DataFrame(c.execute(
            """SELECT symbol, time::date d, close::float c FROM hist_prices_adj
               WHERE symbol IN ('SPY','QQQ') AND time::date BETWEEN %s AND %s ORDER BY time""",
            (d0, d1)).fetchall())
    out = {}
    for s, g in b.groupby("symbol"):
        g = g.set_index(pd.to_datetime(g.d)).c
        yrs = (g.index[-1] - g.index[0]).days / 365.25
        out[f"{s} 보유"] = ((g.iloc[-1] / g.iloc[0]) ** (1 / yrs) - 1) * 100
        if s == "SPY":   # 같은 노출: 매일 deploy 비중으로 리밸런싱, 나머지 현금 0%
            r = g.pct_change().fillna(0) * deploy
            out[f"SPY×{deploy:.0%} 노출맞춤"] = ((1 + r).prod() ** (1 / yrs) - 1) * 100
    return out


if __name__ == "__main__":
    t0 = time.time()
    pg = PostgresStore(get_config().pg_dsn)
    with pg.get_conn() as c:
        uni = pd.DataFrame(c.execute(
            "SELECT symbol, nullif(sector,'') sector FROM swing_universe").fetchall())
    so = dict(zip(uni.symbol, uni.sector))
    sig, bars = load(pg, 0.60, 300, 1.0, universe=list(uni.symbol))
    px = bars[["symbol", "d", "c"]].rename(columns={"c": "px"})
    sig = sig.merge(px, on=["symbol", "d"], how="left")
    sig = sig[(sig.px >= 10) & (sig.px <= 250)]
    arrs = build_arrays(bars)
    dates = np.array(sorted(sig.d.unique())); mid = dates[len(dates) // 2]
    halves = {"전체": sig, "전반": sig[sig.d < mid], "후반": sig[sig.d >= mid]}
    base = dict(max_pos=MAX_POS, target_deploy=DEPLOY, sector_of=so, max_per_sector=3)
    print(f"신호 {len(sig):,} · {dates[0]}~{dates[-1]} · 반분 {mid} · 로드 {time.time()-t0:.0f}s", flush=True)

    def run(cfg, rk, s_):
        return portfolio(s_, arrs, {**LIVE, **cfg}, **base, **RUNNERS[rk])

    # ── 1) 러너별 현행 기준선 + 체결 구성 sanity
    print("\n━━ 1) 러너별 현행 기준선 ━━", flush=True)
    rows = []
    for rk in RUNNERS:
        r = {"runner": rk}
        for hn, s_ in halves.items():
            eq, tr = run({}, rk, s_)
            st = stats(eq, tr, rk)
            r[f"{hn}"] = st["CAGR"]
            if hn == "전체":
                r.update(sharpe=st["sharpe"], med=st["med_ret"], mean=st["mean_ret"],
                         trades=st["trades"], deploy=st["deploy"], **{"MDD(참고)": st["MDD(참고)"]})
                stp = tr[tr.reason.isin(["hard_stop", "trail_or_be"])]
                r["승률"] = round((tr.ret > 0).mean() * 100, 1)
                r["스톱청산%"] = round(len(stp) / len(tr) * 100, 1)
                dep = eq.deployed.mean()
        rows.append(r)
    print(pd.DataFrame(rows).to_string(index=False), flush=True)
    with pg.get_conn() as c:   # 라이브 대조값은 DB 에서 읽는다(코드 상수 금지)
        lv = c.execute("""SELECT count(*) n, avg((realized_pct>0)::int)*100 win,
                 avg((exit_reason IN ('hard_stop','atr_trailing_stop','stop_loss'))::int)*100 stp
                 FROM swing_positions WHERE status='closed' AND side='BUY'
                 AND exit_time >= '2026-08-01'""").fetchone()
    print(f"  라이브 대조(8/1~, n={lv['n']}, 정책 빈티지 혼재): 승률 {lv['win']:.1f}% · "
          f"스톱청산 {lv['stp']:.1f}%")

    bm = bench(pg, dates[0], dates[-1], round(dep, 2))
    print("\n지수 같은 창:", " · ".join(f"{k} {v:.2f}%" for k, v in bm.items()), flush=True)

    # ── 2) 핵심 결정 재측정 (R2·R3 두 경계)
    print("\n━━ 2) 결정 재측정 ━━", flush=True)
    rows = []
    for ck, cfg in CONFIGS.items():
        r = {"config": ck}
        for rk in ("R2 현실·종가판정", "R3 현실·저가판정"):
            tag = "R2" if rk.startswith("R2") else "R3"
            for hn, s_ in halves.items():
                eq, tr = run(cfg, rk, s_)
                st = stats(eq, tr, ck)
                r[f"{tag} {hn}"] = st["CAGR"]
                if hn == "전체":
                    r[f"{tag} med"] = st["med_ret"]; r[f"{tag} 샤프"] = st["sharpe"]
        rows.append(r)
        print(f"  done {ck} ({time.time()-t0:.0f}s)", flush=True)
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(df.to_string(index=False))
    df.to_csv("/home/quant/quant-v31/scripts/honest_runner_grid.csv", index=False)

    # 채택 후보: 두 러너 × 두 반기 모두 현행보다 나은 것
    cur = df[df.config == "현행"].iloc[0]
    ks = [f"{t} {h}" for t in ("R2", "R3") for h in ("전반", "후반")]
    win = df[(df[ks] > cur[ks].values).all(axis=1)]
    print("\n4경계 모두 현행 승:", ", ".join(win.config) or "없음", flush=True)
