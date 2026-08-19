"""주간 팩터 IC 자동 측정 (§22.AO-15).

목적: ①LLM 모멘텀 A/B · ②교집합 게이트 · ③PEAD 가 실제로 작동하는지
**표본이 쌓이는 대로 자동 확인**한다. 수동 스크립트에 의존하면 사후 대처가 반복된다.

미래참조 없음: `swing_signals` 에 **당시 저장된** 점수만 쓰고, 수익은 시그널 이후
`daily_prices` 실제 종가로 계산한다.
"""

from __future__ import annotations

import logging
from datetime import date
from statistics import mean
from typing import Any

logger = logging.getLogger(__name__)

HORIZONS = (5, 10, 20)

# 측정 대상 — 기존 팩터 + 오늘 추가한 신규 신호
FACTORS = [
    "composite_score",
    "technical_score",
    "sentiment_score",      # ① A/B 대조군 (naive 감성)
    "llm_momentum_score",   # ① A/B 실험군 (모멘텀 조건화)
    "quality_score",
    "value_score",
    "flow_score",
    "macro_score",
    "return_20d_rank",      # ② 교집합의 핵심 화면
]

_SQL = """
SELECT s.symbol, s.time::date AS d, s.entry_price,
       {cols},
       (SELECT p.close FROM daily_prices p
         WHERE p.symbol = s.symbol AND p.time::date > s.time::date
         ORDER BY p.time LIMIT 1 OFFSET %s) AS px_fwd
FROM swing_signals s
WHERE s.entry_price > 0
"""


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """순위상관. 동점은 평균순위."""
    n = len(xs)
    if n < 3:
        return None

    def rank(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            for k in range(i, j + 1):
                r[idx[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def compute_and_store(pg, as_of: date | None = None) -> dict[str, Any]:
    """전 팩터 × 전 horizon IC 를 계산해 swing_factor_ic 에 저장."""
    as_of = as_of or date.today()
    min_n = int(float(pg.get_config_value("factor_ic_min_samples", "15")))
    cols = ", ".join(f"s.{f}" for f in FACTORS)
    out: dict[str, Any] = {"as_of": as_of.isoformat(), "horizons": {}}

    for h in HORIZONS:
        with pg.get_conn() as conn:
            rows = [r for r in conn.execute(_SQL.format(cols=cols), (h - 1,)).fetchall()
                    if r["px_fwd"]]
        if len(rows) < min_n:
            out["horizons"][h] = {"skipped": f"n={len(rows)} < {min_n}"}
            continue

        rets = [(float(r["px_fwd"]) - float(r["entry_price"])) / float(r["entry_price"])
                for r in rows]
        per_factor: dict[str, Any] = {}
        for f in FACTORS:
            pairs = [(float(r[f]), ret) for r, ret in zip(rows, rets) if r[f] is not None]
            if len(pairs) < min_n:
                continue
            ic = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if ic is None:
                continue
            per_factor[f] = {"ic": round(ic, 4), "n": len(pairs)}
            with pg.get_conn() as conn:
                conn.execute("""
                    INSERT INTO swing_factor_ic
                        (as_of, horizon_days, factor, ic, n_samples, mean_return, computed_at)
                    VALUES (%s,%s,%s,%s,%s,%s, now())
                    ON CONFLICT (as_of, horizon_days, factor) DO UPDATE SET
                        ic = EXCLUDED.ic, n_samples = EXCLUDED.n_samples,
                        mean_return = EXCLUDED.mean_return, computed_at = now()
                """, (as_of, h, f, round(ic, 4), len(pairs), round(mean(rets), 6)))
                conn.commit()

        # ② 교집합 게이트 — IC 가 아니라 '통과분 성적'으로 본다(순위지표로는 부적합, §22.AO-12)
        mom_min = float(pg.get_config_value("intersection_momentum_min", "0.70"))
        tech_min = float(pg.get_config_value("intersection_technical_min", "60"))

        def passes(r):
            rk, tc = r["return_20d_rank"], r["technical_score"]
            return (rk is not None and float(rk) >= mom_min
                    and tc is not None and float(tc) >= tech_min)

        gated = [ret for r, ret in zip(rows, rets) if passes(r)]
        ungated = [ret for r, ret in zip(rows, rets) if not passes(r)]
        gate = None
        if gated and ungated:
            gate = {
                "n_pass": len(gated),
                "mean_pass": round(mean(gated), 4),
                "win_pass": round(sum(1 for x in gated if x > 0) / len(gated), 3),
                "mean_fail": round(mean(ungated), 4),
                "edge": round(mean(gated) - mean(ungated), 4),
            }

        out["horizons"][h] = {"n": len(rows), "mean_return": round(mean(rets), 4),
                              "factors": per_factor, "intersection_gate": gate}
    return out


def format_report(result: dict[str, Any]) -> str:
    """텔레그램용 HTML 요약."""
    lines = [f"<b>📐 주간 팩터 IC ({result['as_of']})</b>"]
    for h, blk in result.get("horizons", {}).items():
        if "skipped" in blk:
            lines.append(f"\n<b>{h}일</b>: 표본부족 ({blk['skipped']})")
            continue
        lines.append(f"\n<b>{h}일 전방</b> (n={blk['n']}, 평균 {blk['mean_return']:+.2%})")
        fs = blk.get("factors", {})
        for f, v in sorted(fs.items(), key=lambda kv: -kv[1]["ic"]):
            mark = ""
            if f == "llm_momentum_score":
                mark = " ①"
            elif f == "sentiment_score":
                mark = " ①대조"
            lines.append(f"  {f.replace('_score','').replace('return_20d_rank','momentum')}"
                         f": {v['ic']:+.3f} (n={v['n']}){mark}")
        g = blk.get("intersection_gate")
        if g:
            lines.append(f"  ② 교집합: 통과 {g['n_pass']}건 {g['mean_pass']:+.2%} "
                         f"승률 {g['win_pass']:.0%} / 미통과 {g['mean_fail']:+.2%} "
                         f"→ 차이 {g['edge']:+.2%}")
    return "\n".join(lines)
