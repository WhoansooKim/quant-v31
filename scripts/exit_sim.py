#!/usr/bin/env python
"""출구 규칙 경로 시뮬레이터 (§22.AO-43).

왜 필요한가: `atr_trailing_stop` 23건이 MFE 중앙 +5.48% 를 찍고 실현 −0.33% 로 끝났다.
코드를 읽으면 breakeven_trigger_r 과 atr_trailing_activation_r 이 둘 다 1.0 이라
+1R~+2.5R 구간에서는 **본전 스톱이 트레일을 항상 이긴다**(effective_sl=max(...)).
즉 이름은 트레일링인데 실제로는 본전 청산이다.

반사실 평균에 두 번 속았으므로(§22.AO-29, AO-41) 여기서는 **실제 일봉 경로**에
규칙을 집행한다. 청산일이 바뀌면 경로가 실제 청산 이후로 연장되므로 진입 후 90일까지 본다.

🔴 신뢰 조건: 현행 설정으로 **실제 실현값을 재현**해야 한다. 재현 실패 시 대안 비교는 무의미하다.
   엔진은 하루 1회 종가로 판정하므로(jobs.py:645) 스톱도 종가 기준으로 집행한다
   (장중 저가 기준이 아니다 — 실제 동작과 일치시키는 것이 목적).
"""
from __future__ import annotations
import sys, json, argparse
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

HORIZON_DAYS = 90
COMMISSION_ROUNDTRIP = 0.5  # % — 한국투자증권 0.25%/방향 (웹 확인, 2026-10)


def rsi2(closes: list[float]) -> float | None:
    """exit_manager.calc_rsi 와 동일한 단순 SMA 방식 (period=2)."""
    if len(closes) < 3:
        return None
    d = [closes[i] - closes[i - 1] for i in range(1, len(closes))][-2:]
    g = sum(x for x in d if x > 0) / 2
    l = sum(-x for x in d if x < 0) / 2
    if l == 0:
        return 100.0
    return 100 - (100 / (1 + g / l))


def load(pg):
    with pg.get_conn() as c:
        pos = pd.DataFrame(c.execute("""
            SELECT p.position_id, p.symbol, p.entry_time::date AS entry_date,
                   p.entry_price::float AS entry_price, p.entry_atr::float AS atr,
                   (p.realized_pct*100)::float AS actual_r, p.hold_days AS actual_hold,
                   p.exit_reason AS actual_reason, s.return_20d_rank::float AS mom,
                   p.exit_time::date AS exit_date
            FROM swing_positions p
            LEFT JOIN swing_signals s ON s.signal_id = p.signal_id
            WHERE p.status='closed' AND p.entry_atr IS NOT NULL AND p.entry_atr > 0
            ORDER BY p.entry_time""").fetchall())
        syms = tuple(pos.symbol.unique())
        bars = pd.DataFrame(c.execute("""
            SELECT p.symbol, p.time::date AS d, p.close::float AS close,
                   i.trend_aligned
            FROM daily_prices p
            LEFT JOIN swing_indicators i
                   ON i.symbol = p.symbol AND i.time::date = p.time::date
            WHERE p.symbol = ANY(%s) ORDER BY p.symbol, p.time""",
            (list(syms),)).fetchall())
    by = {s: g.reset_index(drop=True) for s, g in bars.groupby("symbol")}
    return pos, by


def simulate_one(row, bars, p) -> dict:
    """한 포지션에 규칙을 집행한다. p = 규칙 파라미터 dict."""
    ep, atr = row.entry_price, row.atr
    fut = bars[bars.d > row.entry_date].reset_index(drop=True)
    if fut.empty:
        return {"r": None}
    hist = bars[bars.d <= row.entry_date].close.tolist()

    hard_stop = ep - p["hard_mult"] * atr
    stop = hard_stop
    hwm = ep
    trailing = False

    for i, b in fut.iterrows():
        if i >= HORIZON_DAYS:
            break
        px, hold = b.close, i + 1
        closes = hist + fut.close.tolist()[: i + 1]
        r_mult = (px - ep) / atr
        gain = (px - ep) / ep

        # ── strategy/swing.py 의 독립 출구 3조건 (exit_manager 와 병렬로 돈다) ──
        # 두 경로가 같은 포지션을 각자 판정하므로 실제로는 '먼저 발동한 쪽'이 이긴다.
        if p["swing_path"]:
            if gain <= p["fixed_sl"]:
                return {"r": (px / ep - 1) * 100, "hold": hold, "reason": "stop_loss"}
            if gain >= p["fixed_tp"]:
                return {"r": (px / ep - 1) * 100, "hold": hold, "reason": "take_profit"}
            if p["trend_break"] and b.trend_aligned is False:
                return {"r": (px / ep - 1) * 100, "hold": hold, "reason": "trend_break"}

        # L2 하드 스톱 (최우선, exit_manager 와 동일 순서)
        if px <= hard_stop:
            return {"r": (hard_stop / ep - 1) * 100, "hold": hold, "reason": "hard_stop"}

        # L4 RSI(2) — 수익/보유일 게이트 통과 후에만
        if (r_mult >= p["rsi2_min_r"] and gain >= p["rsi2_min_gain"]
                and hold >= p["rsi2_min_hold"]):
            v = rsi2(closes)
            if v is not None and v > p["rsi2_thr"]:
                return {"r": (px / ep - 1) * 100, "hold": hold, "reason": "rsi2_overbought"}

        # L3 시간 정지
        if hold >= p["time_stop"]:
            return {"r": (px / ep - 1) * 100, "hold": hold, "reason": "time_stop"}

        # L1 트레일 / 본전
        hwm = max(hwm, px)
        if not trailing and r_mult >= p["activation_r"]:
            trailing = True
        if p["be_enabled"] and r_mult >= p["be_trigger_r"]:
            stop = max(stop, ep * (1 + p["be_buffer"]))
        if p["partial_r"] and r_mult >= p["partial_r"]:
            pass  # 부분청산은 이 모형 범위 밖 — 전량 모형으로 비교한다
        if trailing:
            stop = max(stop, hwm - p["trail_mult"] * atr)
        if px <= stop:
            return {"r": (stop / ep - 1) * 100, "hold": hold, "reason": "trail_or_be"}

    last = fut.iloc[min(len(fut), HORIZON_DAYS) - 1]
    return {"r": (last.close / ep - 1) * 100, "hold": HORIZON_DAYS, "reason": "horizon"}


CURRENT = dict(hard_mult=1.5, trail_mult=2.5, activation_r=1.0, be_enabled=True,
               be_trigger_r=1.0, be_buffer=0.002, rsi2_thr=95, rsi2_min_r=2.0,
               rsi2_min_gain=0.03, rsi2_min_hold=8, time_stop=21, partial_r=None,
               swing_path=True, fixed_sl=-0.05, fixed_tp=0.50, trend_break=True)


def run(pos, by, p, subset=None):
    rows = []
    for row in pos.itertuples():
        if subset is not None and not subset(row):
            continue
        b = by.get(row.symbol)
        if b is None:
            continue
        out = simulate_one(row, b, p)
        if out["r"] is None:
            continue
        rows.append({"pid": row.position_id, "symbol": row.symbol, "mom": row.mom,
                     "sim_r": out["r"], "sim_hold": out["hold"], "sim_reason": out["reason"],
                     "actual_r": row.actual_r, "actual_hold": row.actual_hold,
                     "actual_reason": row.actual_reason})
    return pd.DataFrame(rows)


def stats(d, col="sim_r", hold="sim_hold"):
    w, l = d[d[col] > 0], d[d[col] <= 0]
    aw = w[col].mean() if len(w) else 0.0
    al = abs(l[col].mean()) if len(l) else 0.0
    net = d[col] - COMMISSION_ROUNDTRIP
    H = d[hold].median()
    return {"n": len(d), "win_rate": round(len(w) / len(d) * 100, 1),
            "median": round(d[col].median(), 3), "mean": round(d[col].mean(), 3),
            "avg_win": round(aw, 2), "avg_loss": round(al, 2),
            "payoff": round(aw / al, 2) if al else None,
            "net_median": round(net.median(), 3), "net_mean": round(net.mean(), 3),
            "hold_median": round(float(H), 1),
            "annual_at_29": round((365 / H) * net.median() * 0.29, 1) if H else None,
            "annual_at_85": round((365 / H) * net.median() * 0.85, 1) if H else None}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--grid", action="store_true")
    ap.add_argument("--mom", type=float, default=None)
    ap.add_argument("--since", type=str, default=None,
                    help="이 날짜 이후 청산된 거래만 (설정 고정 구간 검증용)")
    a = ap.parse_args()

    pg = PostgresStore(get_config().pg_dsn)
    pos, by = load(pg)
    import datetime as _dt
    _since = _dt.date.fromisoformat(a.since) if a.since else None
    def sub(r):
        if a.mom is not None and (r.mom is None or pd.isna(r.mom) or r.mom < a.mom):
            return False
        if _since is not None and (r.exit_date is None or r.exit_date <= _since):
            return False
        return True

    if a.validate:
        d = run(pos, by, CURRENT, sub)
        print(f"재현 검증 — 현행 설정으로 n={len(d)} 시뮬레이션\n")
        act, sim = stats(d, "actual_r", "actual_hold"), stats(d)
        print(f"{'지표':<14}{'실제':>12}{'시뮬':>12}{'차이':>12}")
        for k in ("n", "win_rate", "median", "mean", "avg_win", "avg_loss", "payoff", "hold_median"):
            av, sv = act[k], sim[k]
            df = f"{sv-av:+.2f}" if isinstance(av, (int, float)) and isinstance(sv, (int, float)) else "-"
            print(f"{k:<14}{av:>12}{sv:>12}{df:>12}")
        corr = d[["sim_r", "actual_r"]].corr().iloc[0, 1]
        agree = (d.sim_reason.str.replace("trail_or_be", "atr_trailing_stop")
                 == d.actual_reason).mean()
        print(f"\n거래별 상관 r={corr:.3f}   청산사유 일치율 {agree*100:.0f}%")
        print("\n실제 청산사유별 시뮬 사유 분포:")
        print(pd.crosstab(d.actual_reason, d.sim_reason))

    if a.grid:
        # 규칙 대안 비교. 기준선 = 현행 규칙을 같은 표본에 집행한 것(실제 역사가 아니다 —
        # 과거 거래는 다른 설정에서 체결됐으므로 역사와의 비교는 규칙 비교가 아니다).
        rng = np.random.default_rng(42)

        def boot(x, n=4000):
            x = np.asarray(x, float)
            m = rng.choice(x, (n, len(x)), replace=True)
            q = np.percentile(np.median(m, axis=1), [2.5, 97.5])
            return round(q[0], 2), round(q[1], 2)

        base = run(pos, by, CURRENT, sub)
        bs = stats(base)
        print(f"기준선(현행 규칙, n={bs['n']}): 순중앙 {bs['net_median']:+.2f}%  "
              f"손익비 {bs['payoff']}  보유 {bs['hold_median']}d  "
              f"연@29% {bs['annual_at_29']}  연@85% {bs['annual_at_85']}\n")

        cands = []
        for be in (1.0, 2.0, 3.0, 99.0):
            for tm in (1.0, 1.5, 2.0, 2.5):
                cands.append((f"be={be if be<99 else 'off'} trail={tm}",
                              {**CURRENT, "be_trigger_r": be, "trail_mult": tm}))
        for h in (0, 8, 21):
            cands.append((f"rsi2_hold={h}", {**CURRENT, "rsi2_min_hold": h}))
        for tb in (True, False):
            cands.append((f"trend_break={tb}", {**CURRENT, "trend_break": tb}))
        cands.append(("swing경로 전체off", {**CURRENT, "swing_path": False}))
        # 진단에서 나온 결합안: 본전 해제 + 트레일 즉시 + 추세이탈 제거
        cands.append(("결합: be=off trail=1.0 tb=off",
                      {**CURRENT, "be_trigger_r": 99.0, "trail_mult": 1.0, "trend_break": False}))
        cands.append(("결합: be=2R trail=1.5 tb=off",
                      {**CURRENT, "be_trigger_r": 2.0, "trail_mult": 1.5, "trend_break": False}))

        rows = []
        for lab, p in cands:
            d = run(pos, by, p, sub)
            if len(d) == 0:
                continue
            s = stats(d)
            net = (d.sim_r - COMMISSION_ROUNDTRIP).values
            lo, hi = boot(net)
            # 기준선과 짝지은 차이 (같은 포지션이므로 쌍대비교가 가능하다)
            mg = (base[["pid", "sim_r"]].rename(columns={"sim_r": "rb"})
                  .merge(d[["pid", "sim_r"]].rename(columns={"sim_r": "rc"}), on="pid"))
            diff = (mg.rc - mg.rb).values
            # 과반 거래는 하드스톱/RSI2 로 먼저 끝나 트레일·본전 변경의 영향을 받지 않는다.
            # 전체 쌍대 중앙값은 그 0 들에 지배되어 항상 0 이 된다 → **영향받은 거래만** 본다.
            aff = diff[np.abs(diff) > 1e-9]
            n_aff = len(aff)
            dlo, dhi = boot(aff) if n_aff >= 5 else (None, None)
            rows.append({"규칙": lab, "n": s["n"], "순중앙": s["net_median"],
                         "CI": f"[{lo},{hi}]", "승률": s["win_rate"], "손익비": s["payoff"],
                         "보유d": s["hold_median"], "연@29%": s["annual_at_29"],
                         "연@85%": s["annual_at_85"],
                         "영향n": n_aff,
                         "영향중앙차": round(float(np.median(aff)), 2) if n_aff else 0.0,
                         "차CI": f"[{dlo},{dhi}]" if dlo is not None else "n<5"})
        r = pd.DataFrame(rows).sort_values("연@29%", ascending=False)
        print(r.to_string(index=False))
        print(f"\n⚠️ {len(cands)}개 조합을 탐색했다 — 최량값은 선택편향이 있다. "
              f"쌍대차 CI 가 0 을 포함하면 효과 미확인으로 본다.")
