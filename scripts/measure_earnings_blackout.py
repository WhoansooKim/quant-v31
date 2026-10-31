#!/usr/bin/env python
"""실적 블랙아웃 A/B (§22.AO-65) — 라이브 정합 포트폴리오(5슬롯 · 총노출 45% · 상위300 ·
mom>=0.60 · $10~250 · 섹터당 3 · 수수료 · 현행 출구).

계기: 2026-10-29 NOW −27.6%. 10/28 장후 실적 미스 → 다음날 시가 $120.91 이 hard stop
$147.96 를 건너뛰었다. 엔진에 실적일 진입차단·보유청산이 없다.

🔴 측정 전 러너 결함: hist_portfolio 는 종가가 스톱을 깨면 **스톱 가격에** 체결했다 → 갭 손실이
   구조적으로 0 이고, 블랙아웃의 이득도 0 으로 보인다. gap_fill=True(시가가 스톱 아래면 시가 체결)를
   먼저 기준선으로 세운 뒤 블랙아웃을 비교한다. 두 기준선의 차이 자체가 기존 백테스트의 과대평가분이다.

실적일: SEC 8-K Item 2.02 접수시각 → 갭 반영 거래일 (scripts/fetch_earnings_edgar.py).
  한계: 2.02 는 실적 외 '잠정 실적/영업 업데이트'도 포함(예: EOG) → 블랙아웃이 약간 과잉 배제.
        실적일은 수주 전 공지되므로 미래 정보 누출은 아니지만, 라이브는 Finnhub 캘린더에 의존한다.
판정: 거래당 중앙값 + CAGR, 전반/후반 같은 방향일 때만 채택. MDD 는 참고만.
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
sys.path.insert(0, "/home/quant/quant-v31/scripts")
from hist_backtest import load, build_arrays, RULES
from hist_portfolio import portfolio
from measure_sector_cap import LIVE, MAX_POS, DEPLOY, stats
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

EARN = "/home/quant/quant-v31/data/parquet/earnings/edgar_8k202.parquet"


def earn_index(arrs):
    e = pd.read_parquet(EARN)
    out = {}
    for s, g in e.groupby("symbol"):
        a = arrs.get(s)
        if a is None: continue
        d = pd.to_datetime(pd.Series(a["d"])).values.astype("datetime64[D]")
        gd = pd.to_datetime(g.gap_day).values.astype("datetime64[D]")
        j = np.searchsorted(d, gd)
        ok = (j < len(d)) & (d[np.minimum(j, len(d) - 1)] == gd)
        out[s] = set(j[ok].tolist())
    return out


def straddle(tr, ei):
    """보유 중(진입봉 다음 ~ 청산봉) 갭이 있었던 거래."""
    # data_end 청산(상장폐지 등)은 봉 인덱스가 없다 → 실적 무관으로 둔다
    return np.array([np.isfinite(r.i_entry) and
                     any(k in ei.get(r.sym, ()) for k in range(int(r.i_entry) + 1, int(r.i_exit) + 1))
                     for r in tr.itertuples()])


if __name__ == "__main__" and "--decompose" in sys.argv:
    # 갭체결 분해 + 트레일 배수 재확인 — §22.AO-43 의 trail 1.0 이 스톱가 체결 가정의 산물인지
    pg = PostgresStore(get_config().pg_dsn)
    with pg.get_conn() as c:
        uni = pd.DataFrame(c.execute(
            "SELECT symbol, nullif(sector,'') sector FROM swing_universe").fetchall())
    sector_of = dict(zip(uni.symbol, uni.sector))
    sig, bars = load(pg, 0.60, 300, 1.0, universe=list(uni.symbol))
    px = bars[["symbol", "d", "c"]].rename(columns={"c": "px"})
    sig = sig.merge(px, on=["symbol", "d"], how="left")
    sig = sig[(sig.px >= 10) & (sig.px <= 250)]
    arrs = build_arrays(bars)
    dates = np.array(sorted(sig.d.unique())); mid = dates[len(dates) // 2]
    halves = {"전체": sig, "전반": sig[sig.d < mid], "후반": sig[sig.d >= mid]}
    base = dict(max_pos=MAX_POS, target_deploy=DEPLOY, sector_of=sector_of, max_per_sector=3)
    rows = []
    for tm in (1.0, 1.5, 2.5):
        for gf in (False, "hard", "trail", True):
            p_ = {**LIVE, "trail_mult": tm}
            r = {"trail": tm, "gap_fill": str(gf)}
            for hn, s_ in halves.items():
                eq, tr = portfolio(s_, arrs, p_, **base, gap_fill=gf)
                st = stats(eq, tr, "")
                r[f"{hn} CAGR"] = st["CAGR"]; r[f"{hn} med"] = st["med_ret"]
            eq, tr = portfolio(sig, arrs, p_, **base, gap_fill=gf)
            r["sharpe"] = stats(eq, tr, "")["sharpe"]
            r["갭청산 비중"] = round(((tr.reason.isin(["hard_stop", "trail_or_be"])) &
                                   (tr.ret < 0)).mean() * 100, 1)
            rows.append(r); print(f"  done trail {tm} gap {gf}", flush=True)
    print(pd.DataFrame(rows).to_string(index=False))
    sys.exit(0)

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
    arrs = build_arrays(bars)
    ei = earn_index(arrs)
    cov = sig.symbol.isin(ei.keys()).mean()
    print(f"신호 {len(sig):,}건 · {sig.d.min()} ~ {sig.d.max()} · 실적일 보유 종목 비중 {cov:.1%}",
          flush=True)

    base = dict(max_pos=MAX_POS, target_deploy=DEPLOY, sector_of=sector_of, max_per_sector=3)
    V = {
        "A 기존러너(스톱가 체결)": dict(),
        "B 갭체결(=정직한 현행)": dict(gap_fill=True),
        "C B+진입차단 5봉": dict(gap_fill=True, earn_idx=ei, blackout=5),
        "D B+진입차단 10봉": dict(gap_fill=True, earn_idx=ei, blackout=10),
        "E B+진입차단 20봉": dict(gap_fill=True, earn_idx=ei, blackout=20),
        "F B+실적전 청산": dict(gap_fill=True, earn_idx=ei, pre_exit=True),
        "G B+차단10+실적전청산": dict(gap_fill=True, earn_idx=ei, blackout=10, pre_exit=True),
    }
    dates = np.array(sorted(sig.d.unique()))
    mid = dates[len(dates) // 2]
    halves = {"전체": sig, "전반": sig[sig.d < mid], "후반": sig[sig.d >= mid]}

    rows, full_tr = [], {}
    for lab, kw in V.items():
        for hn, s_ in halves.items():
            eq, tr = portfolio(s_, arrs, LIVE, **base, **kw)
            r = stats(eq, tr, lab); r["구간"] = hn; rows.append(r)
            if hn == "전체": full_tr[lab] = tr
        print(f"  done {lab}", flush=True)
    df = pd.DataFrame(rows)
    for hn in halves:
        print(f"\n━━ {hn} ━━")
        print(df[df.구간 == hn].drop(columns="구간").to_string(index=False))

    # 거래 수준: 기준선 B 에서 실적을 끼고 보유한 거래는 무엇이 다른가
    tr = full_tr["B 갭체결(=정직한 현행)"]
    m = straddle(tr, ei)
    print("\n━━ 거래 수준 (B, 전체) — 보유 중 실적 갭 유무 ━━")
    for name, g in (("실적 낌", tr[m]), ("안 낌", tr[~m])):
        print(f"  {name:4s} n={len(g):5d} ({len(g)/len(tr):.1%}) · 중앙 {g.ret.median():+.3f}% · "
              f"평균 {g.ret.mean():+.3f}% · p5 {g.ret.quantile(.05):+.2f}% · "
              f"−15% 이하 {(g.ret <= -15).mean():.2%} · 승률 {(g.ret > 0).mean():.1%}")
    # 부트스트랩: 중앙값 차(낌 − 안낌)
    rng = np.random.default_rng(7)
    a_, b_ = tr[m].ret.values, tr[~m].ret.values
    bs = [np.median(rng.choice(a_, len(a_))) - np.median(rng.choice(b_, len(b_))) for _ in range(2000)]
    print(f"  중앙값 차 {np.median(a_)-np.median(b_):+.3f}%p · 95% CI "
          f"[{np.percentile(bs,2.5):+.3f}, {np.percentile(bs,97.5):+.3f}]")
    # 실적 갭 체결 손실 상위
    gx = tr[m & (tr.ret <= -15)].sort_values("ret").head(8)
    print("  최악 실적 보유 거래:", ", ".join(f"{r.sym} {r.d} {r.ret:+.1f}%" for r in gx.itertuples()))
