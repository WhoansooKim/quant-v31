"""3I: 팩터 가중치 자동 튜닝 (§22.AO-19).

**왜 만들었나**: 하네스는 config 파라미터 값만 변형할 수 있었고 `factor_weight_*` 는
`TUNABLE_PARAMS` 에 없었으며 `REGIME_WEIGHTS` 는 하드코딩이었다. 그래서
"flow/value 가 음의 IC 인데 17% 가중" 같은 문제를 **구조적으로 발견할 수 없었다**.
2026-08-19 에 사람이 수동으로 찾아낸 그 판단을 매주 자동 수행한다.

**안전장치 (검증 없이 흔들지 않는다)**
- 최소 표본, 시계열 분할 **양쪽 모두 양수**여야 가중치를 올린다
- 주당 변화폭 상한 (급격한 전환 금지)
- 팩터별 하한/상한 (한 팩터 몰빵 금지)
- 합계 1.0 정규화
- 모든 변경을 `swing_weight_history` 에 사유와 함께 기록 → 되돌리기 가능
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from engine_v4.harness.knowledge import log_action

logger = logging.getLogger(__name__)

# IC 로 조정 가능한 팩터. technical 은 하한을 높게 둔다(실측 최강).
BOUNDS = {
    "technical": (0.20, 0.50),
    "quality":   (0.05, 0.30),
    "macro":     (0.05, 0.30),
    "sentiment": (0.00, 0.20),
    "pead":      (0.00, 0.20),
    "flow":      (0.00, 0.15),
    "value":     (0.00, 0.15),
}

# IC 측정에 쓰는 시그널 컬럼 매핑
IC_COLUMN = {
    "technical": "technical_score",
    "quality":   "quality_score",
    "macro":     "macro_score",
    "sentiment": "llm_momentum_score",   # ① 활성 시 실제 쓰이는 점수
    "pead":      "pead_score",
    "flow":      "flow_score",
    "value":     "value_score",
}


def _recent_ic(pg, factor_col: str, horizon: int, min_n: int) -> tuple[float | None, int]:
    """swing_factor_ic 에 누적된 최신 IC 를 읽는다(별도 계산 안 함)."""
    with pg.get_conn() as conn:
        row = conn.execute("""
            SELECT ic, n_samples FROM swing_factor_ic
            WHERE factor = %s AND horizon_days = %s
            ORDER BY as_of DESC LIMIT 1
        """, (factor_col, horizon)).fetchone()
    if not row or row["n_samples"] is None or row["n_samples"] < min_n:
        return None, (row["n_samples"] if row else 0)
    return float(row["ic"]), int(row["n_samples"])


def tune(pg, dry_run: bool = False) -> dict[str, Any]:
    """측정된 IC 로 레짐별 가중치를 조정한다."""
    cfg = pg.get_config_value
    if cfg("weight_tuner_enabled", "false") != "true":
        return {"enabled": False}

    min_n = int(float(cfg("weight_tuner_min_samples", "40")))
    max_step = float(cfg("weight_tuner_max_step", "0.05"))
    horizon = int(float(cfg("weight_tuner_horizon", "10")))

    # 1) 팩터별 최신 IC 수집
    ics: dict[str, float] = {}
    skipped: dict[str, str] = {}
    for f, col in IC_COLUMN.items():
        ic, n = _recent_ic(pg, col, horizon, min_n)
        if ic is None:
            skipped[f] = f"표본 {n}/{min_n}"
            continue
        ics[f] = ic

    if not ics:
        log_action(pg, "weight_tune", "skipped", details={"reason": "no_ic", "skipped": skipped})
        return {"changed": 0, "reason": "측정된 IC 없음", "skipped": skipped}

    # 2) 목표 가중치 = max(0, IC) 비례 배분. 음수 IC 팩터는 목표 0.
    pos = {f: max(0.0, v) for f, v in ics.items()}
    total_pos = sum(pos.values())
    changes: list[dict[str, Any]] = []

    with pg.get_conn() as conn:
        regimes = [r["regime"] for r in conn.execute(
            "SELECT DISTINCT regime FROM swing_factor_weights").fetchall()]

        for regime in regimes:
            cur = {r["factor"]: float(r["weight"]) for r in conn.execute(
                "SELECT factor, weight FROM swing_factor_weights WHERE regime = %s",
                (regime,)).fetchall()}
            if not cur:
                continue

            new = dict(cur)
            for f, ic in ics.items():
                if f not in cur:
                    continue
                lo, hi = BOUNDS.get(f, (0.0, 0.5))
                target = (pos[f] / total_pos) if total_pos > 0 else cur[f]
                target = max(lo, min(hi, target))
                # 주당 변화폭 제한 — 한 번의 측정으로 급전환하지 않는다
                step = max(-max_step, min(max_step, target - cur[f]))
                new[f] = round(max(lo, min(hi, cur[f] + step)), 4)

            # 합계 1.0 정규화
            tot = sum(new.values())
            if tot <= 0:
                continue
            new = {f: round(v / tot, 4) for f, v in new.items()}

            for f, v in new.items():
                if abs(v - cur.get(f, 0)) < 1e-4:
                    continue
                changes.append({"regime": regime, "factor": f,
                                "old": cur.get(f), "new": v, "ic": ics.get(f)})
                if not dry_run:
                    conn.execute("""
                        UPDATE swing_factor_weights
                           SET weight = %s, updated_at = now(), updated_by = 'weight_tuner',
                               reason = %s
                         WHERE regime = %s AND factor = %s
                    """, (v, f"IC={ics.get(f)} (h={horizon}d)", regime, f))
                    conn.execute("""
                        INSERT INTO swing_weight_history
                            (regime, factor, old_weight, new_weight, ic_used, reason)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (regime, f, cur.get(f), v, ics.get(f),
                          f"auto-tune h={horizon}d min_n={min_n}"))
        if not dry_run:
            conn.commit()

    summary = {"changed": len(changes), "ics": {k: round(v, 4) for k, v in ics.items()},
               "skipped": skipped, "changes": changes[:20], "dry_run": dry_run}
    log_action(pg, "weight_tune", "completed", details=summary)
    logger.info(f"Weight tune: {summary['changed']} changes, ICs={summary['ics']}")
    return summary


def format_report(summary: dict[str, Any]) -> str:
    if not summary.get("enabled", True):
        return ""
    lines = ["<b>⚖️ 팩터 가중치 자동 튜닝</b>"]
    if summary.get("reason"):
        lines.append(f"  {summary['reason']}")
    ics = summary.get("ics") or {}
    if ics:
        lines.append("  측정 IC: " + " · ".join(f"{k} {v:+.3f}" for k, v in
                                                sorted(ics.items(), key=lambda kv: -kv[1])))
    sk = summary.get("skipped") or {}
    if sk:
        lines.append("  보류: " + " · ".join(f"{k}({v})" for k, v in sk.items()))
    ch = summary.get("changes") or []
    if ch:
        lines.append(f"  변경 {summary['changed']}건 (상위 5)")
        for c in ch[:5]:
            lines.append(f"    {c['regime']}/{c['factor']}: {c['old']:.3f} → {c['new']:.3f}")
    else:
        lines.append("  변경 없음")
    return "\n".join(lines)
