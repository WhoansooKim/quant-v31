#!/usr/bin/env python
"""포트폴리오 백테스트 — 거래당 엣지를 '실제로 받는 연수익'으로 환산 (§22.AO-43).

거래 단위 통계는 모든 신호를 다 잡는다고 가정한다. 실제로는 max_positions=20 슬롯이고
mom>=0.92 신호가 하루 ~15건 나오므로 **선택**이 생기고 자본이 묶인다. 그 제약을 넣는다.
수수료 0.25%/방향을 체결마다 실제로 차감하고 자본을 복리로 굴린다.
"""
from __future__ import annotations
import sys, argparse
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
sys.path.insert(0, "/home/quant/quant-v31/scripts")
from hist_backtest import load, build_arrays, RULES
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

SIDE_COMM = 0.0025


def spy_regime(pg):
    """시장 레짐 — SPY 종가 > SMA200 인 날만 신규 진입 허용.
    백테스트에 macro_score 이력이 없으므로(라이브 7개월분뿐) 가장 단순하고
    사후선택 여지가 없는 대리지표를 쓴다."""
    with pg.get_conn() as c:
        d = pd.DataFrame(c.execute("""
            SELECT time::date AS d, close::float AS c FROM hist_prices_adj
            WHERE symbol='SPY' ORDER BY time""").fetchall())
    d["s200"] = d.c.rolling(200).mean()
    return {r.d: bool(r.c > r.s200) for r in d.dropna().itertuples()}


def portfolio(sig, arrs, p, max_pos=20, start_cash=10000.0, min_notional=5.0,
              regime=None, target_deploy=1.0):
    dates = np.array(sorted(sig.d.unique()))
    by_date = {d: g.sort_values("mom", ascending=False) for d, g in sig.groupby("d")}
    idx = {s: {d: i for i, d in enumerate(a["d"])} for s, a in arrs.items()}

    cash, equity_log, open_pos, trades = start_cash, [], [], []
    for day in dates:
        # ── 1. 보유 포지션 청산 판정 (당일 종가)
        still = []
        for pos in open_pos:
            a = arrs[pos["sym"]]
            i = idx[pos["sym"]].get(day)
            if i is None:
                still.append(pos); continue
            px, ep, atr = a["c"][i], pos["ep"], pos["atr"]
            if not np.isfinite(px):
                still.append(pos); continue
            hold = i - pos["i_entry"]
            gain, rm = px / ep - 1.0, (px - ep) / atr
            why = None
            if p["swing_path"]:
                if gain <= p["fixed_sl"]: why, xp = "stop_loss", px
                elif gain >= p["fixed_tp"]: why, xp = "take_profit", px
                elif p["trend_break"] and not a["ta"][i]: why, xp = "trend_break", px
            if why is None and px <= pos["hard"]:
                why, xp = "hard_stop", pos["hard"]
            if why is None and rm >= p["rsi2_min_r"] and gain >= p["rsi2_min_gain"] \
                    and hold >= p["rsi2_min_hold"]:
                d2 = a["c"][i] - a["c"][i-1]; d1 = a["c"][i-1] - a["c"][i-2] if i >= 2 else 0.0
                g_ = (max(d2,0)+max(d1,0))/2; l_ = (max(-d2,0)+max(-d1,0))/2
                r2 = 100.0 if l_ == 0 else 100 - 100/(1+g_/l_)
                if r2 > p["rsi2_thr"]: why, xp = "rsi2_overbought", px
            if why is None and hold >= p["time_stop"]:
                why, xp = "time_stop", px
            if why is None:
                pos["hwm"] = max(pos["hwm"], px)
                if not pos["tr"] and rm >= p["activation_r"]: pos["tr"] = True
                if p["be_enabled"] and rm >= p["be_trigger_r"]:
                    pos["stop"] = max(pos["stop"], ep*(1+p["be_buffer"]))
                if pos["tr"]:
                    pos["stop"] = max(pos["stop"], pos["hwm"] - p["trail_mult"]*atr)
                if px <= pos["stop"]: why, xp = "trail_or_be", pos["stop"]
            if why:
                proceeds = pos["qty"] * xp * (1 - SIDE_COMM)
                cash += proceeds
                trades.append({"d": day, "sym": pos["sym"], "hold": hold,
                               "ret": (xp/ep-1)*100, "reason": why,
                               "pnl": proceeds - pos["cost"]})
            else:
                still.append(pos)
        open_pos = still

        # ── 2. 신규 진입 (다음 봉 시가) — mom 높은 순
        free = max_pos - len(open_pos)
        if regime is not None and not regime.get(day, True):
            free = 0          # 레짐 OFF — 신규 진입 금지(청산은 계속 집행된다)
        if free > 0 and day in by_date:
            held = {q["sym"] for q in open_pos}
            nav = cash + sum(q["qty"]*arrs[q["sym"]]["c"][idx[q["sym"]].get(day, q["i_entry"])]
                             for q in open_pos if idx[q["sym"]].get(day) is not None)
            # 투자율 상한 — 낙폭 조절 장치. 레짐 필터는 효과가 없었으므로(−65.6%→−64.9%)
            # 낙폭은 하락장이 아니라 모멘텀 팩터 급반전에서 온다 → 노출 크기로만 줄인다.
            budget = nav * target_deploy / max_pos
            for t in by_date[day].itertuples():
                if free <= 0: break
                if t.symbol in held: continue
                a = arrs.get(t.symbol); 
                if a is None: continue
                i0 = idx[t.symbol].get(day)
                if i0 is None or i0+1 >= len(a["o"]): continue
                ep = a["o"][i0+1]
                if not np.isfinite(ep) or ep <= 0: continue
                spend = min(budget, cash)
                if spend < min_notional: continue
                qty = spend / (ep*(1+SIDE_COMM))
                cost = qty*ep*(1+SIDE_COMM)
                cash -= cost
                open_pos.append({"sym": t.symbol, "ep": ep, "atr": float(t.atr14),
                                 "qty": qty, "cost": cost, "i_entry": i0+1,
                                 "hard": ep - p["hard_mult"]*float(t.atr14),
                                 "stop": ep - p["hard_mult"]*float(t.atr14),
                                 "hwm": ep, "tr": False})
                free -= 1; held.add(t.symbol)

        mv = sum(q["qty"]*arrs[q["sym"]]["c"][idx[q["sym"]][day]]
                 for q in open_pos if idx[q["sym"]].get(day) is not None)
        equity_log.append({"d": day, "nav": cash+mv, "cash": cash,
                           "n_pos": len(open_pos), "deployed": mv/(cash+mv) if cash+mv else 0})
    return pd.DataFrame(equity_log), pd.DataFrame(trades)


def report(eq, tr, label):
    eq = eq.copy(); eq["dt"] = pd.to_datetime(eq.d)
    yrs = (eq.dt.iloc[-1]-eq.dt.iloc[0]).days/365.25
    tot = eq.nav.iloc[-1]/eq.nav.iloc[0]
    cagr = (tot**(1/yrs)-1)*100
    peak = eq.nav.cummax(); dd = ((eq.nav/peak-1)*100).min()
    rets = eq.set_index("dt").nav.resample("ME").last().pct_change().dropna()
    sharpe = (rets.mean()/rets.std()*np.sqrt(12)) if rets.std() else 0
    ann = eq.set_index("dt").nav.resample("YE").last().pct_change().dropna()*100
    print(f"\n━━ {label} ━━")
    print(f"  기간 {eq.dt.iloc[0].date()} ~ {eq.dt.iloc[-1].date()} ({yrs:.1f}년)  거래 {len(tr):,}건")
    print(f"  최종 {eq.nav.iloc[-1]:,.0f} / 시작 {eq.nav.iloc[0]:,.0f}  총 {(tot-1)*100:+.0f}%")
    print(f"  **CAGR {cagr:+.1f}%**   최대낙폭 {dd:.1f}%   샤프(월) {sharpe:.2f}")
    print(f"  평균 투자율 {eq.deployed.mean()*100:.0f}%  평균 보유종목 {eq.n_pos.mean():.1f}")
    print(f"  연수익 음수 해 {(ann<0).sum()}/{len(ann)}  최악 {ann.min():+.1f}%  최고 {ann.max():+.1f}%")
    return {"label": label, "CAGR": round(cagr,1), "MDD": round(dd,1),
            "샤프": round(float(sharpe),2), "투자율": round(eq.deployed.mean()*100),
            "거래수": len(tr), "음수해": f"{(ann<0).sum()}/{len(ann)}"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mom", type=float, default=0.92)
    ap.add_argument("--maxpos", type=int, default=20)
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()
    pg = PostgresStore(get_config().pg_dsn)
    sig, bars = load(pg, 0.60, 400, 1.0)
    print(f"신호 {len(sig):,}건")
    arrs = build_arrays(bars)
    BEST = {**RULES, "trail_mult": 1.0, "swing_path": False,
            "rsi2_min_hold": 999, "time_stop": 60, "be_enabled": False}
    if a.sweep:
        # 문턱은 **포트폴리오 단위**로 골라야 한다. 거래당 수익은 문턱이 높을수록 단조증가하지만
        # (수정출구 0.60→0.98 에서 +1.141%→+2.083%), 신호가 줄면 20슬롯이 안 차서 투자율이
        # 떨어진다. 둘의 곱이 실제 CAGR 이다.
        BEST_ = {**RULES, "trail_mult": 1.0, "swing_path": False,
                 "rsi2_min_hold": 999, "time_stop": 60, "be_enabled": False}
        rows = []
        for thr in (0.70, 0.86, 0.92, 0.94, 0.96, 0.98):
            s_ = sig[sig.mom >= thr]
            for dep in (0.45, 1.00):
                eq, tr = portfolio(s_, arrs, BEST_, max_pos=a.maxpos, target_deploy=dep)
                rows.append(report(eq, tr, f"mom>={thr} / 투자율상한{int(dep*100)}%"))
        print("\n" + pd.DataFrame(rows).to_string(index=False))
        import sys as _s; _s.exit(0)

    # ── config 만으로 가능한 것 vs 코드 변경이 필요한 것을 분리 측정 ──
    #    config: atr_trailing_multiplier, breakeven_enabled, rsi2_exit_min_hold_days, time_stop_days
    #    코드  : strategy/swing.py 의 독립 출구(고정 −5% 손절 · SMA50 trend_break)
    CFG_ONLY = {**RULES, "trail_mult": 1.0, "be_enabled": False,
                "rsi2_min_hold": 999, "time_stop": 60}      # swing_path 는 그대로 True
    rows = []
    for lab, p_, dep in (("A. 현행 전부", RULES, 0.29),
                         ("B. config만 (지금 적용가능) @29%", CFG_ONLY, 0.29),
                         ("C. config만 @55%", CFG_ONLY, 0.55),
                         ("D. config+코드(swing경로off) @29%", BEST, 0.29),
                         ("E. config+코드 @45%", BEST, 0.45),
                         ("F. config+코드 @55%", BEST, 0.55)):
        eq, tr = portfolio(sig, arrs, p_, max_pos=a.maxpos, target_deploy=dep)
        rows.append(report(eq, tr, lab))
    print("\n" + pd.DataFrame(rows).to_string(index=False))
    print("\n【§22.AO-26 A-1 해소】 rsi2 보유일 하한 — 라이브 7개월 표본 3건으로 판정불가였다")
    rows2 = []
    for h in (0, 8, 21, 60, 999):
        eq, tr = portfolio(sig, arrs, {**BEST, "rsi2_min_hold": h},
                           max_pos=a.maxpos, target_deploy=0.55)
        rows2.append(report(eq, tr, f"rsi2_exit_min_hold_days={h if h<999 else 'off'}"))
    print("\n" + pd.DataFrame(rows2).to_string(index=False))
    import sys as _s; _s.exit(0)
    for dep in (0.25, 0.40, 0.55, 0.70, 0.85, 1.00):
        eq, tr = portfolio(sig, arrs, BEST, max_pos=a.maxpos, target_deploy=dep)
        rows.append(report(eq, tr, f"★trail=1.0 / 투자율상한 {int(dep*100)}%"))
    eq, tr = portfolio(sig, arrs, RULES, max_pos=a.maxpos, target_deploy=0.29)
    rows.append(report(eq, tr, "현행규칙 / 투자율 29% (= 지금)"))
    print("\n" + pd.DataFrame(rows).to_string(index=False))
