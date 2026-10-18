#!/usr/bin/env python
"""저회전 구성 탐색 — 수수료를 넣고 회전율–순수익 전선을 그린다 (§22.AO-53).

왜: `runner.py` 가 비용 0 이었던 탓에 하네스는 고회전 변이를 계속 골랐다.
수수료 드래그 = 회전수 × 종목비중 × 왕복 0.50% 이므로 **회전율에 비례**한다.
비용을 넣은 뒤 전선이 어디로 움직이는지 본다.

도구: hist_portfolio.portfolio (15.6년 · 1,540종목 · 체결마다 0.25%/편도).
`runner.py` 가 아니라 이걸 쓰는 이유 — DB 기반이라 1초/회이고 구간이 15.6년이다.

사전등록:
  · 주 지표는 **net CAGR**. gross 는 드래그를 보이기 위해서만 병기한다.
  · 사다리는 보유기간을 늘리는 방향으로만 단조 구성한다(사후 선택 여지 축소).
  · 스윕은 탐색이다. 상위 후보는 **시간 분할 홀드아웃**(전반/후반)으로 재검하고,
    양쪽 모두에서 현행을 이기지 못하면 채택하지 않는다.
  · MDD 는 판정에 쓰지 않는다(수익이 다르면 낙폭 비교는 무효 — 기존 규칙).
"""
from __future__ import annotations
import sys, pickle, argparse
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
sys.path.insert(0, "/home/quant/quant-v31/scripts")
import hist_portfolio as hp
from hist_backtest import RULES

CACHE = "/tmp/claude-1000/-home-quant-quant-v31/1c3ff766-ddc4-4797-9f86-6d7dedcbf87e/scratchpad/hist.pkl"

# ── 기준선 = **라이브 swing_config 현재값** (2026-10-18 확인) ──────────────
# 🔴 기준선을 두 번 틀렸다. ① hist_backtest.RULES 는 §22.AO-43 **이전** 설정이다.
#    ② swing_path=True 도 틀렸다 — `swing_legacy_exit_enabled=false`(2026-10-11)로
#    고정 −5% 손절 + SMA50 trend_break 병렬 출구는 **이미 꺼져 있다**.
#    기준선을 틀리면 개선폭이 통째로 부풀려진다. DB 값을 직접 읽어 맞췄다:
#      swing_legacy_exit_enabled=false · atr_trailing_multiplier=1.0
#      breakeven_enabled=false · rsi2_exit_min_hold_days=999 · time_stop_days=60
#      atr_hard_stop_multiplier=1.5 · position_pct=0.10 · max_total_exposure_pct=0.45
LIVE = dict(trail_mult=1.0, be_enabled=False, rsi2_min_hold=999, time_stop=60,
            hard_mult=1.5, swing_path=False)

# 사다리: 라이브에서 출발해 **보유기간을 늘리는 방향으로만** 단조 변경한다.
# 회전율을 줄이는 레버는 트레일 폭과 시간청산 둘뿐이다(나머지는 이미 꺼져 있다).
LADDER = [
    ("R0 구정책(AO-43전)", dict(trail_mult=2.5, be_enabled=True, rsi2_min_hold=8,
                                time_stop=21, hard_mult=1.5, swing_path=True)),
    ("R1 병렬출구 복원",    dict(**{**LIVE, "swing_path": True})),
    ("L0 현행=라이브",     dict(**LIVE)),
    ("L1 트레일1.5",       dict(**{**LIVE, "trail_mult": 1.5})),
    ("L2 트레일2.5",       dict(**{**LIVE, "trail_mult": 2.5})),
    ("L3 트레일4.0",       dict(**{**LIVE, "trail_mult": 4.0})),
    ("L4 트레일2.5+120일", dict(**{**LIVE, "trail_mult": 2.5, "time_stop": 120})),
    ("L5 트레일4.0+120일", dict(**{**LIVE, "trail_mult": 4.0, "time_stop": 120})),
]


def metrics(eq, tr, gross=False):
    eq = eq.copy(); eq["dt"] = pd.to_datetime(eq.d)
    yrs = (eq.dt.iloc[-1] - eq.dt.iloc[0]).days / 365.25
    cagr = ((eq.nav.iloc[-1] / eq.nav.iloc[0]) ** (1 / yrs) - 1) * 100
    dd = ((eq.nav / eq.nav.cummax() - 1) * 100).min()
    r = eq.set_index("dt").nav.resample("ME").last().pct_change().dropna()
    ann = eq.set_index("dt").nav.resample("YE").last().pct_change().dropna() * 100
    return dict(CAGR=round(cagr, 2), MDD=round(dd, 1),
                샤프=round(float(r.mean() / r.std() * np.sqrt(12)) if r.std() else 0, 2),
                거래=len(tr), 회전=round(len(tr) / yrs), 보유=round(tr.hold.mean(), 1) if len(tr) else 0,
                투자율=round(eq.deployed.mean() * 100), 음수해=f"{(ann<0).sum()}/{len(ann)}",
                최악년=round(ann.min(), 1) if len(ann) else 0)


def run(sig, arrs, rules, max_pos, deploy):
    """같은 설정을 수수료 0 / 0.25% 두 번 돌려 드래그를 분리한다."""
    out = {}
    for tag, comm in (("gross", 0.0), ("net", 0.0025)):
        hp.SIDE_COMM = comm
        eq, tr = hp.portfolio(sig, arrs, rules, max_pos=max_pos, target_deploy=deploy)
        out[tag] = metrics(eq, tr)
    hp.SIDE_COMM = 0.0025
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mom", type=float, default=0.92)
    ap.add_argument("--deploy", type=float, default=0.45)
    ap.add_argument("--holdout", action="store_true")
    a = ap.parse_args()

    sig, arrs = pickle.load(open(CACHE, "rb"))
    sig = sig[sig.mom >= a.mom]
    print(f"신호 {len(sig):,}건 (mom>={a.mom}) · 투자율상한 {a.deploy:.0%} · 체결비용 0.25%/편도\n")

    rows = []
    for mp in (4, 8, 20):
        for name, over in LADDER:
            r = run(sig, arrs, {**RULES, **over}, mp, a.deploy)
            rows.append({"슬롯": mp, "종목비중": f"{a.deploy/mp:.1%}", "구성": name,
                         "회전/년": r["net"]["회전"], "보유일": r["net"]["보유"],
                         "gross": r["gross"]["CAGR"], "net": r["net"]["CAGR"],
                         "드래그": round(r["gross"]["CAGR"] - r["net"]["CAGR"], 2),
                         "샤프": r["net"]["샤프"], "MDD": r["net"]["MDD"],
                         "음수해": r["net"]["음수해"], "투자율": r["net"]["투자율"]})
            print(f"  {mp:2d}슬롯 {name:16s} 회전{rows[-1]['회전/년']:5d}/년 "
                  f"보유{rows[-1]['보유일']:5.1f}일  gross{rows[-1]['gross']:+7.2f}% "
                  f"→ net{rows[-1]['net']:+7.2f}%  (드래그 {rows[-1]['드래그']:5.2f}%p)")
    df = pd.DataFrame(rows).sort_values("net", ascending=False)
    print("\n═══ net CAGR 순 ═══")
    print(df.to_string(index=False))

    if a.holdout:
        print("\n═══ 시간분할 홀드아웃 (전반 2011~2018 / 후반 2019~2026) ═══")
        print("  탐색에서 고른 것이 다른 구간에서도 서는지 본다. 한쪽만 이기면 채택하지 않는다.")
        top = df.head(5)
        import datetime as dt
        cut = dt.date(2019, 1, 1)
        s1, s2 = sig[sig.d < cut], sig[sig.d >= cut]
        base = {}
        for half, s_ in (("전반", s1), ("후반", s2)):
            for mp in sorted(top["슬롯"].unique()):
                base[(half, mp)] = run(s_, arrs, {**RULES, **LIVE}, mp, a.deploy)["net"]["CAGR"]
        out = []
        for _, t in top.iterrows():
            over = dict(LADDER[[n for n, _ in LADDER].index(t["구성"])][1])
            row = {"슬롯": t["슬롯"], "구성": t["구성"], "전구간net": t["net"]}
            for half, s_ in (("전반", s1), ("후반", s2)):
                v = run(s_, arrs, {**RULES, **over}, t["슬롯"], a.deploy)["net"]["CAGR"]
                row[half] = v
                row[half + "Δ현행"] = round(v - base[(half, t["슬롯"])], 2)
            row["양쪽우위"] = "✅" if (row["전반Δ현행"] > 0 and row["후반Δ현행"] > 0) else "🔴"
            out.append(row)
        print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    main()
