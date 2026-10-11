#!/usr/bin/env python
"""15.6년 역사 백테스트 (§22.AO-43).

왜 이게 필요했나: 라이브 청산 130건으로는 거래당 +1%p 효과를 검정할 수 없다
(거래당 표준편차 ~6% → 단일검정 n≈280, 다중비교 보정하면 훨씬 더). 0.92 게이트에서
월 ~5건이므로 수년이 걸린다. **7개월 튜닝이 엣지를 못 만든 이유는 측정 대역폭이
최적화 루프의 요구보다 압도적으로 작았기 때문이다.**

swing_indicators 는 7개월치뿐이었다(collector 가 롤링을 300일로 계산하고 **최신 1일만**
저장한다). 그런데 daily_prices 에는 2011~2026, 1540종목, 524만 봉이 이미 있었다.
hist_indicators 로 소급 계산하니 mom_rank>=0.92 진입이 **6,094건** — 라이브의 47배다.

데이터 전제:
  - hist_prices_adj: 분할 역조정(수집기의 후행 ~435일 창 경계에 생긴 불연속 교정)
  - clean=true: 불연속 직후 200봉 배제(롤링 지표 오염 구간), 전체의 1.0%
  - 유동성 상위 400(일별 dollar_vol_20d) — 라이브 유니버스 규모와 정합
생존편향: 1540종목 중 1252종목이 2026-09 이전에 이력이 끝난다(유니버스를 떠난 종목이
  남아 있다). 완전 point-in-time 은 아니지만 '오늘의 승자만' 모인 데이터는 아니다.
"""
from __future__ import annotations
import sys, argparse, json
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

COMM = 0.5      # % 왕복 (한국투자증권 0.25%/방향, 웹 확인)
HORIZON = 90

RULES = dict(hard_mult=1.5, trail_mult=2.5, activation_r=1.0, be_enabled=True,
             be_trigger_r=1.0, be_buffer=0.002, rsi2_thr=95, rsi2_min_r=2.0,
             rsi2_min_gain=0.03, rsi2_min_hold=8, time_stop=21,
             swing_path=True, fixed_sl=-0.05, fixed_tp=0.50, trend_break=True)


def load(pg, mom_min, liq_top, vol_min):
    with pg.get_conn() as c:
        sig = pd.DataFrame(c.execute("""
            WITH u AS (SELECT time, symbol, atr14, return_20d_rank,
                              row_number() OVER (PARTITION BY time ORDER BY dollar_vol_20d DESC) lr
                       FROM hist_indicators
                       WHERE clean AND trend_aligned AND breakout_5d
                             AND volume_ratio >= %s AND atr14 > 0)
            SELECT time::date AS d, symbol, atr14, return_20d_rank AS mom
            FROM u WHERE lr <= %s AND return_20d_rank >= %s ORDER BY time, symbol
        """, (vol_min, liq_top, mom_min)).fetchall())
        bars = pd.DataFrame(c.execute("""
            SELECT p.symbol, p.time::date AS d, p.open::float AS o, p.close::float AS c,
                   h.sma_50::float AS s50, h.sma_200::float AS s200
            FROM hist_prices_adj p
            LEFT JOIN hist_indicators h ON h.symbol = p.symbol AND h.time = p.time
            ORDER BY p.symbol, p.time""").fetchall())
    return sig, bars


def build_arrays(bars):
    out = {}
    for s, g in bars.groupby("symbol", sort=False):
        g = g.reset_index(drop=True)
        out[s] = {"d": g["d"].values, "o": g["o"].to_numpy(float),
                  "c": g["c"].to_numpy(float),
                  "ta": ((g["c"] > g["s50"]) & (g["s50"] > g["s200"])).to_numpy()}
    return out


def sim(arr, i0, atr, p):
    """i0 = 신호 봉 인덱스. 진입은 다음 봉 시가(신호는 종가에 나온다)."""
    o, c, ta, n = arr["o"], arr["c"], arr["ta"], len(arr["c"])
    if i0 + 1 >= n:
        return None
    ep = o[i0 + 1]
    if not np.isfinite(ep) or ep <= 0:
        return None
    hard = ep - p["hard_mult"] * atr
    stop, hwm, trailing = hard, ep, False
    end = min(i0 + 1 + HORIZON, n)
    for i in range(i0 + 1, end):
        px, hold = c[i], i - i0
        if not np.isfinite(px):
            continue
        gain = px / ep - 1.0
        rm = (px - ep) / atr
        # strategy/swing.py 독립 경로 (exit_manager 와 병렬)
        if p["swing_path"]:
            if gain <= p["fixed_sl"]:
                return (gain * 100, hold, "stop_loss")
            if gain >= p["fixed_tp"]:
                return (gain * 100, hold, "take_profit")
            if p["trend_break"] and not ta[i]:
                return (gain * 100, hold, "trend_break")
        if px <= hard:
            return ((hard / ep - 1) * 100, hold, "hard_stop")
        if rm >= p["rsi2_min_r"] and gain >= p["rsi2_min_gain"] and hold >= p["rsi2_min_hold"]:
            d2 = c[i] - c[i - 1]; d1 = c[i - 1] - c[i - 2] if i >= 2 else 0.0
            g_ = (max(d2, 0) + max(d1, 0)) / 2; l_ = (max(-d2, 0) + max(-d1, 0)) / 2
            r2 = 100.0 if l_ == 0 else 100 - 100 / (1 + g_ / l_)
            if r2 > p["rsi2_thr"]:
                return (gain * 100, hold, "rsi2_overbought")
        if hold >= p["time_stop"]:
            return (gain * 100, hold, "time_stop")
        hwm = max(hwm, px)
        if not trailing and rm >= p["activation_r"]:
            trailing = True
        if p["be_enabled"] and rm >= p["be_trigger_r"]:
            stop = max(stop, ep * (1 + p["be_buffer"]))
        if trailing:
            stop = max(stop, hwm - p["trail_mult"] * atr)
        if px <= stop:
            return ((stop / ep - 1) * 100, hold, "trail_or_be")
    return ((c[end - 1] / ep - 1) * 100, end - 1 - i0, "horizon")


def run(sig, arrs, p):
    idx = {s: {d: i for i, d in enumerate(a["d"])} for s, a in arrs.items()}
    rows = []
    for t in sig.itertuples():
        a = arrs.get(t.symbol)
        if a is None:
            continue
        i0 = idx[t.symbol].get(t.d)
        if i0 is None:
            continue
        r = sim(a, i0, float(t.atr14), p)
        if r:
            rows.append((t.d, t.symbol, t.mom, r[0], r[1], r[2]))
    return pd.DataFrame(rows, columns=["d", "symbol", "mom", "r", "hold", "reason"])


def stats(d, label=""):
    if len(d) == 0:
        return None
    net = d.r - COMM
    w, l = d[d.r > 0], d[d.r <= 0]
    aw = w.r.mean() if len(w) else 0.0
    al = abs(l.r.mean()) if len(l) else 0.0
    H = float(d.hold.median())
    return {"구분": label, "n": len(d), "승률": round(len(w) / len(d) * 100, 1),
            "순중앙": round(float(net.median()), 3), "순평균": round(float(net.mean()), 3),
            "손익비": round(aw / al, 2) if al else None, "보유d": round(H, 1),
            "연@29%": round((365 / H) * float(net.median()) * 0.29, 1) if H else None,
            "연@85%": round((365 / H) * float(net.median()) * 0.85, 1) if H else None,
            "연평균@29%": round((365 / H) * float(net.mean()) * 0.29, 1) if H else None}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mom", type=float, default=0.92)
    ap.add_argument("--liq", type=int, default=400)
    ap.add_argument("--vol", type=float, default=1.0)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--exits", action="store_true")
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()

    pg = PostgresStore(get_config().pg_dsn)
    print(f"신호 적재 (mom>={a.mom}, 유동성상위{a.liq}, volume_ratio>={a.vol}) …")
    sig, bars = load(pg, a.mom if not (a.sweep or a.exits or a.validate) else 0.60, a.liq, a.vol)
    print(f"  신호 {len(sig):,}건 / 봉 {len(bars):,}행 / 종목 {bars.symbol.nunique():,}")
    arrs = build_arrays(bars)

    if a.sweep:
        # 🔴 0.92 는 **출구가 고장난** 상태의 라이브 130건에서 고른 값이다.
        #    출구를 고치면 최적 문턱이 달라질 수 있으므로 양쪽 규칙에서 모두 스윕한다.
        BEST = {**RULES, "trail_mult": 1.0, "swing_path": False,
                "rsi2_min_hold": 999, "time_stop": 60, "be_enabled": False}
        res = []
        for lab, p_ in (("현행출구", RULES), ("수정출구", BEST)):
            for thr in (0.60, 0.70, 0.80, 0.86, 0.90, 0.92, 0.94, 0.96, 0.98):
                st = stats(run(sig[sig.mom >= thr], arrs, p_), f"{lab} mom>={thr}")
                if st:
                    res.append(st)
        print("\n" + pd.DataFrame(res).to_string(index=False))
    elif a.exits:
        s0 = sig[sig.mom >= a.mom]
        res = []
        base = run(s0, arrs, RULES)
        res.append(stats(base, "현행"))
        for be in (1.0, 2.0, 99.0):
            for tm in (1.0, 1.5, 2.5):
                res.append(stats(run(s0, arrs, {**RULES, "be_trigger_r": be, "trail_mult": tm}),
                                 f"be={be if be<99 else 'off'} trail={tm}"))
        for h in (0, 8, 21):
            res.append(stats(run(s0, arrs, {**RULES, "rsi2_min_hold": h}), f"rsi2_hold={h}"))
        res.append(stats(run(s0, arrs, {**RULES, "trend_break": False}), "trend_break off"))
        res.append(stats(run(s0, arrs, {**RULES, "swing_path": False}), "swing경로 off"))
        res.append(stats(run(s0, arrs, {**RULES, "time_stop": 60, "rsi2_min_hold": 60,
                                        "be_enabled": False, "trail_mult": 1.5,
                                        "trend_break": False}), "장기보유+트레일1.5"))
        # 더 촘촘한 트레일 — 1.0 이 부호를 뒤집었으므로 그 아래도 본다
        for tm in (0.5, 0.75, 1.25):
            res.append(stats(run(s0, arrs, {**RULES, "trail_mult": tm}), f"trail={tm}"))
        # 결합: 중앙값을 고치는 trail=1.0 + 평균을 고치는 swing경로 off + rsi2 보유연장
        res.append(stats(run(s0, arrs, {**RULES, "trail_mult": 1.0, "swing_path": False}),
                         "★ trail=1.0 + swing off"))
        res.append(stats(run(s0, arrs, {**RULES, "trail_mult": 1.0, "swing_path": False,
                                        "rsi2_min_hold": 21, "time_stop": 60}),
                         "★ trail=1.0 + swing off + 보유연장"))
        res.append(stats(run(s0, arrs, {**RULES, "trail_mult": 1.0, "swing_path": False,
                                        "rsi2_min_hold": 999, "time_stop": 60,
                                        "be_enabled": False}),
                         "★ trail=1.0만 (rsi2·본전·swing 전부off)"))
        res.append(stats(run(s0, arrs, {**RULES, "trail_mult": 1.5, "swing_path": False,
                                        "rsi2_min_hold": 999, "time_stop": 60,
                                        "be_enabled": False}),
                         "★ trail=1.5만 (동일, 폭만 넓게)"))
        print("\n" + pd.DataFrame([r for r in res if r]).to_string(index=False))
    else:
        d = run(sig, arrs, RULES)
        print("\n" + pd.DataFrame([stats(d, f"mom>={a.mom} 전구간")]).to_string(index=False))
        d["yr"] = pd.to_datetime(d.d).dt.year
        per = [stats(g, str(y)) for y, g in d.groupby("yr")]
        print("\n연도별:")
        print(pd.DataFrame([p for p in per if p]).to_string(index=False))
        print("\n청산 사유:")
        print(d.reason.value_counts().to_string())

    if getattr(a, "validate", False):
        # 과최적화·중복표본 검증. 이 셋을 통과하지 않으면 적용하지 않는다.
        s0 = sig[sig.mom >= a.mom]
        BEST = {**RULES, "trail_mult": 1.0, "swing_path": False,
                "rsi2_min_hold": 999, "time_stop": 60, "be_enabled": False}
        cfgs = {"현행": RULES, "★trail=1.0만": BEST,
                "trail=0.5만": {**BEST, "trail_mult": 0.5},
                "trail=1.5만": {**BEST, "trail_mult": 1.5}}
        out = {k: run(s0, arrs, v) for k, v in cfgs.items()}

        print("\n【1】기간 분할 — 전반에서 고른 규칙이 후반에도 되는가 (out-of-sample)")
        rows = []
        for k, d in out.items():
            d = d.copy(); d["dt"] = pd.to_datetime(d.d)
            for lab, m in (("2011~2018", d.dt < "2019-01-01"),
                           ("2019~2026", d.dt >= "2019-01-01")):
                st = stats(d[m], f"{k} / {lab}")
                if st: rows.append(st)
        print(pd.DataFrame(rows).to_string(index=False))

        print("\n【2】블록 부트스트랩 — 거래가 시간상 겹치므로 월 단위 블록으로 재표집")
        rng = np.random.default_rng(11)
        for k, d in out.items():
            d = d.copy(); d["m"] = pd.to_datetime(d.d).dt.to_period("M")
            g = {p: v.r.values - COMM for p, v in d.groupby("m")}
            keys = list(g)
            means = np.empty(3000)
            for i in range(3000):
                pick = rng.choice(len(keys), len(keys), replace=True)
                means[i] = np.concatenate([g[keys[j]] for j in pick]).mean()
            lo, hi = np.percentile(means, [2.5, 97.5])
            H = float(d.hold.median())
            print(f"  {k:<14} 순평균 {d.r.mean()-COMM:+.3f}%  월블록CI [{lo:+.3f}, {hi:+.3f}]"
                  f"  → 연평균@29% [{(365/H)*lo*0.29:+.1f}, {(365/H)*hi*0.29:+.1f}]"
                  + ("  ✅ CI>0" if lo > 0 else "  ❌ 0 포함"))

        print("\n【3】연도별 — 특정 장세 의존인가")
        d = out["★trail=1.0만"].copy(); d["yr"] = pd.to_datetime(d.d).dt.year
        rows = [stats(gg, str(y)) for y, gg in d.groupby("yr")]
        r = pd.DataFrame([x for x in rows if x])
        print(r[["구분","n","승률","순중앙","순평균","손익비","연평균@29%"]].to_string(index=False))
        neg = (r["순평균"] < 0).sum()
        print(f"\n  순평균이 음수인 해: {neg}/{len(r)}  "
              f"(현행 규칙은 {(pd.DataFrame([x for x in [stats(gg,str(y)) for y,gg in out['현행'].assign(yr=pd.to_datetime(out['현행'].d).dt.year).groupby('yr')] if x])['순평균']<0).sum()}/{len(r)})")
