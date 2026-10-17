#!/usr/bin/env python
"""llm_momentum IC 실측 — 라이브 IC 작업의 결함을 같은 데이터로 대조한다 (§22.AO-49).

왜 별도 스크립트인가: `engine_v4/analysis/factor_ic.py` 가 매주 저장하는 IC 는
**전 구간 풀링 Spearman** 이다. 결함 4개:
  1) **날짜를 섞어 한 번에 상관을 낸다.** 같은 날 종목들은 시장 전체 움직임을
     공유하므로 유효표본은 신호 수가 아니라 **날짜 수**다. n_samples=65 는 날짜 21개다.
  2) **시장조정이 없다.** 원시 전방수익을 쓰면 "점수가 높던 주가 좋은 주였다"가
     팩터 예측력으로 기록된다.
  3) **중복을 센다.** `swing_signals` 에 같은 (종목,날짜) ENTRY 가 2건씩 들어 있다
     (117행 → 고유 98행). 중복은 표본수를 부풀리고 순열검정의 교환가능성을 깬다.
  4) **분산 없는 날짜를 센다.** llm_momentum 은 80.8% 가 정확히 50(중립)이라
     날짜 21개 중 **5개**에서만 횡단면에 변동이 있다. 나머지 16일은 전 종목이
     같은 점수 → 순위를 매길 수 없는데도 풀링 상관에는 기여한다.

이 스크립트는 중복을 제거하고, SPY 로 조정하고, **날짜별 횡단면 IC** 와
**날짜내 순열검정**(같은 날 라벨만 섞어 시장 움직임을 상수로 둔다)을 돌린다.

사전등록: 주 판정 = 10일(기존 코드 PRIMARY_HORIZON) · 시장조정 · 날짜내 순열검정.
          5·20일과 풀링값은 보조. 보조에서 나온 것은 가설이지 근거가 아니다.
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

HORIZONS = (5, 10, 20)
PRIMARY = 10
BENCH = "SPY"


def load(pg, factor: str):
    with pg.get_conn() as c:
        sig = pd.DataFrame(c.execute(f"""
            SELECT s.time::date AS d, s.symbol, s.entry_price::float AS px0,
                   s.{factor}::float AS sc,
                   (s.factor_detail->'llm_momentum'->>'relevant') AS rel,
                   (s.factor_detail->'llm_momentum'->>'direction') AS dir
            FROM swing_signals s
            WHERE s.{factor} IS NOT NULL AND s.entry_price > 0
              AND s.signal_type = 'ENTRY'
            ORDER BY s.time""").fetchall())
        px = pd.DataFrame(c.execute("""
            SELECT symbol, time::date AS d, close::float AS c FROM daily_prices
            WHERE symbol = ANY(%s) AND time::date >= %s - 10
            ORDER BY symbol, time""",
            (list(sorted(set(sig.symbol) | {BENCH})), sig.d.min())).fetchall())
    dup = len(sig) - len(sig.drop_duplicates(["d", "symbol"]))
    sig = sig.drop_duplicates(["d", "symbol"]).reset_index(drop=True)

    cal = np.array(sorted(px.d.unique()))
    pxw = px.pivot(index="d", columns="symbol", values="c").reindex(cal)
    pos = {d: i for i, d in enumerate(cal)}
    rows = []
    for r in sig.itertuples():
        i = pos.get(r.d)
        if i is None:
            continue
        rec = {"d": r.d, "symbol": r.symbol, "sc": r.sc, "rel": r.rel, "dir": r.dir}
        for h in HORIZONS:
            rec[f"m{h}"] = np.nan
            j = i + h
            if j < len(cal) and r.symbol in pxw:
                p1 = pxw[r.symbol].iloc[j]
                b0, b1 = pxw[BENCH].iloc[i], pxw[BENCH].iloc[j]
                if pd.notna(p1) and pd.notna(b0) and pd.notna(b1) and b0 > 0:
                    rec[f"m{h}"] = (p1 / r.px0 - 1.0) - (b1 / b0 - 1.0)
        rows.append(rec)
    return pd.DataFrame(rows), dup


def spearman(x, y):
    if len(x) < 3:
        return np.nan
    rx, ry = pd.Series(x).rank().values, pd.Series(y).rank().values
    if np.std(rx) == 0 or np.std(ry) == 0:
        return np.nan           # 전 종목 같은 점수 — 순위를 매길 수 없다
    return float(np.corrcoef(rx, ry)[0, 1])


def permutation(sub, col, hi_cut, rng, reps=10000):
    """날짜내 라벨 순열 — 시장 움직임은 상수로 두고 라벨의 정보량만 남긴다."""
    ok = [d for d in sub.d.unique()
          if ((sub.d == d) & (sub.sc >= hi_cut)).sum()
          and ((sub.d == d) & (sub.sc < hi_cut)).sum()]
    if len(ok) < 2:
        return None
    ps = sub[sub.d.isin(ok)]

    def diff(lab):
        a, b = ps[col].values[lab >= hi_cut], ps[col].values[lab < hi_cut]
        return np.median(a) - np.median(b) if len(a) and len(b) else np.nan

    base, cnt, tot = diff(ps.sc.values), 0, 0
    for _ in range(reps):
        lab = ps.sc.values.copy()
        for d in ok:
            m = ps.d.values == d
            lab[m] = rng.permutation(lab[m])
        v = diff(lab)
        if not np.isnan(v):
            tot += 1
            cnt += abs(v) >= abs(base)
    return {"dates": len(ok), "n": len(ps), "diff": base, "p": cnt / tot, "ok": ok}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", default="llm_momentum_score")
    ap.add_argument("--hi-cut", type=float, default=75.0, help="상위 버킷 하한")
    ap.add_argument("--loo", action="store_true", help="날짜 하나씩 빼고 재검정")
    a = ap.parse_args()
    rng = np.random.default_rng(23)
    pg = PostgresStore(get_config().pg_dsn)
    df, dup = load(pg, a.factor)

    print(f"팩터 {a.factor} — 고유 (종목,날짜) {len(df)}건 "
          f"/ 날짜 {df.d.nunique()}개 / 종목 {df.symbol.nunique()}개 "
          f"(중복 {dup}건 제거)\n")
    print("점수 분포:")
    for s, g in df.groupby("sc"):
        print(f"  {s:>6.1f}점 {len(g):>3}건 ({len(g)/len(df):5.1%}) 날짜 {g.d.nunique():>2}개")
    if "rel" in df and df.rel.notna().any():
        nf = int((df.rel == "false").sum())
        print(f"  → ①관련성 기각 {nf}/{len(df)} ({nf/len(df):.1%}) 는 강제 중립 50")
    print()

    for h in HORIZONS:
        col = f"m{h}"
        sub = df.dropna(subset=[col])
        tag = " ← 주 판정" if h == PRIMARY else ""
        print("=" * 72)
        print(f"[{h}일 · 시장조정]{tag}  n={len(sub)} 날짜 {sub.d.nunique()}개")
        if len(sub) < 10:
            print("  표본부족\n")
            continue
        per = np.array([v for v in (spearman(g.sc.values, g[col].values)
                                    for _, g in sub.groupby("d")) if not np.isnan(v)])
        print(f"  풀링 Spearman {spearman(sub.sc.values, sub[col].values):+.4f}  "
              f"(라이브 작업이 저장하는 값 — 위 결함 1·2·3·4)")
        print(f"  날짜별 횡단면 IC: 변동있는 날짜 {len(per)}/{sub.d.nunique()} · "
              f"중앙 {np.median(per) if len(per) else float('nan'):+.4f}")
        r = permutation(sub, col, a.hi_cut, rng)
        if r is None:
            print("  순열검정 불가 — 두 버킷이 같은 날 공존하는 날짜 2개 미만")
        else:
            print(f"  날짜내 순열검정: 공존날짜 {r['dates']}개 (n={r['n']}) "
                  f"중앙값차이 {r['diff']:+.2%} · p = {r['p']:.3f}")
            if a.loo and r["dates"] >= 3:
                print("    날짜 하나씩 제외:")
                for d in r["ok"]:
                    r2 = permutation(sub[sub.d != d], col, a.hi_cut, rng, reps=4000)
                    if r2:
                        print(f"      −{d} → {r2['dates']}날짜 "
                              f"{r2['diff']:+7.2%} p={r2['p']:.3f}")
        print()

    print("=" * 72)
    print("참고 — 신호 모집단 전체의 시장대비 성적 (점수와 무관):")
    for h in HORIZONS:
        s = df.dropna(subset=[f"m{h}"])
        if len(s):
            print(f"  {h:>2}일: n={len(s):>3} 날짜 {s.d.nunique():>2} "
                  f"중앙 {np.median(s[f'm{h}']):+6.2%} SPY상회 {(s[f'm{h}']>0).mean():5.1%}")


if __name__ == "__main__":
    main()
