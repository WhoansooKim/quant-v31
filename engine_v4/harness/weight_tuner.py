"""3I: 팩터 가중치 자동 튜닝 (§22.AO-19).

**왜 만들었나**: 하네스는 config 파라미터 값만 변형할 수 있었고 `factor_weight_*` 는
`TUNABLE_PARAMS` 에 없었으며 `REGIME_WEIGHTS` 는 하드코딩이었다. 그래서
"flow/value 가 음의 IC 인데 17% 가중" 같은 문제를 **구조적으로 발견할 수 없었다**.
2026-08-19 에 사람이 수동으로 찾아낸 그 판단을 매주 자동 수행한다.

**안전장치 (검증 없이 흔들지 않는다)**
- **측정된 팩터만** 재배분에 참여한다 (§22.AO-50 — 아래)
- 주당 변화폭 상한 (급격한 전환 금지)
- 팩터별 하한/상한 (한 팩터 몰빵 금지)
- 합계 1.0 정규화
- 모든 변경을 `swing_weight_history` 에 사유와 함께 기록 → 되돌리기 가능

🔴 §22.AO-50 — 이 모듈은 2026-08~10 두 달간 **무효한 IC** 로 라이브 가중치를 움직였다
(`swing_weight_history` 231건). 읽던 `swing_factor_ic.ic` 가 전 구간 풀링·원시수익·
중복포함·EXIT혼입이었고, `llm_momentum` 의 경우 저장값 +0.1372 가 바로잡으면
p=0.534 였다. 그 값이 `ic_used=0.1372` 로 sentiment 가중을 0.2031→0.1665 로 내렸다.

규칙을 두 군데 바꿨다:
  1) **문턱을 `n_samples` 에서 날짜·CI 로 옮겼다.** 유효표본은 신호 수가 아니라 날짜 수다.
     `method='xsec_excess'` 인 행만 쓰고, **날짜블록 부트스트랩 CI 가 0 을 제외**하고
     횡단면 추정량과 **부호가 일치**해야 재배분에 참여한다.
  2) **미측정은 '가중 0' 이 아니라 '유지'다.** 이전 규칙은 `target ∝ max(0, IC)` 였으므로
     측정되지 않은 팩터(IC≈0)를 "쓸모없는 팩터"와 같게 취급해 목표를 0 으로 끌어내렸다.
     측정 실패와 효과 없음은 같은 숫자로 나타나지만 같은 뜻이 아니다.
  ⚠️ 위 docstring 의 "시계열 분할 양쪽 모두 양수" 는 **구현된 적이 없다** — 문구만 있었다.
     지금은 CI 조건이 그 역할을 한다.
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
    # momentum 은 technical 과 rank 를 공유(중복 계상)하므로 상한을 보수적으로 둔다
    "momentum":  (0.00, 0.25),
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
    "momentum":  "return_20d_rank",      # §22.AO-26 C — factor_ic 가 이미 측정 중(n=157@10d)

    "quality":   "quality_score",
    "macro":     "macro_score",
    "sentiment": "llm_momentum_score",   # ① 활성 시 실제 쓰이는 점수
    "pead":      "pead_score",
    "flow":      "flow_score",
    "value":     "value_score",
}


def _recent_ic(pg, factor_col: str, horizon: int, min_dates: int,
               require_ci: bool = True) -> tuple[float | None, str]:
    """swing_factor_ic 의 최신 행을 읽어 **재배분에 쓸 수 있는지** 판정한다.

    반환 `(ic, 사유)` — ic 가 None 이면 그 팩터는 이번 주 **가중치를 유지**한다.
    쓰는 점추정은 풀링(초과수익)이다(검정력), 쓸 자격은 CI 와 횡단면 부호 일치가 준다(편향).
    """
    with pg.get_conn() as conn:
        row = conn.execute("""
            SELECT ic, ic_xsec, pooled_lo, pooled_hi, n_samples, n_dates,
                   n_valid_dates, method
              FROM swing_factor_ic
             WHERE factor = %s AND horizon_days = %s
             ORDER BY as_of DESC LIMIT 1
        """, (factor_col, horizon)).fetchone()
    if not row:
        return None, "측정 없음"
    if (row["method"] or "pooled_raw") != "xsec_excess":
        return None, "구 방식(§22.AO-50 이전) — 무효"
    nd = row["n_dates"] or 0
    if nd < min_dates:
        return None, f"날짜 {nd}/{min_dates}"
    if row["ic"] is None:
        return None, "IC 계산불가"
    ic = float(row["ic"])
    lo, hi = row["pooled_lo"], row["pooled_hi"]
    if require_ci:
        if lo is None or hi is None:
            return None, "CI 없음"
        if not (float(lo) > 0 or float(hi) < 0):
            return None, f"CI∋0 [{float(lo):+.3f},{float(hi):+.3f}]"
        xs = row["ic_xsec"]
        if xs is not None:
            xs = float(xs)
            if xs == 0.0:
                return None, "횡단면 0.000 (정보 없음)"
            if (xs > 0) != (ic > 0):
                return None, f"횡단면 {xs:+.3f} 과 부호 불일치"
    return ic, f"IC {ic:+.3f} 날짜 {nd}"


def tune(pg, dry_run: bool = False) -> dict[str, Any]:
    """측정된 IC 로 레짐별 가중치를 조정한다."""
    cfg = pg.get_config_value
    if cfg("weight_tuner_enabled", "false") != "true":
        return {"enabled": False}

    min_dates = int(float(cfg("weight_tuner_min_dates", "20")))
    max_step = float(cfg("weight_tuner_max_step", "0.05"))
    horizon = int(float(cfg("weight_tuner_horizon", "10")))
    require_ci = cfg("weight_tuner_require_ci", "true") == "true"

    # 1) 팩터별 최신 IC 수집 — 측정된 것만 참여, 나머지는 유지
    ics: dict[str, float] = {}
    skipped: dict[str, str] = {}
    for f, col in IC_COLUMN.items():
        ic, why = _recent_ic(pg, col, horizon, min_dates, require_ci)
        if ic is None:
            skipped[f] = why
            continue
        ics[f] = ic

    if not ics:
        log_action(pg, "weight_tune", "skipped", details={"reason": "no_ic", "skipped": skipped})
        return {"changed": 0, "reason": "측정된 IC 없음", "skipped": skipped}

    # 2) 목표 가중치 = max(0, IC) 비례 배분. 음수 IC 팩터는 목표 0.
    # 🔴 미해결 결함(§22.AO-52): `ics` 는 여기서 **한 번** 계산되어 아래 레짐 루프의
    #    4개 레짐에 **같은 절대 목표**로 적용된다. 측정 팩터가 flow/value(0) 를 뺀
    #    전부였던 2026-08~10 에는 budget=1.0 이 되어 네 레짐이 한 점으로 수렴했고,
    #    technical 0.42/0.32/0.28/0.38 → 전부 0.2252 로 **레짐 분화가 소멸**했다.
    #    `regime_adaptive_weights=true` 가 두 달간 장식이었다.
    #    지금은 momentum 만 게이트를 통과해 잠재적이지만, **통과 팩터가 2개가 되면
    #    다시 평탄화된다.** 레짐별 IC 는 측정 불가다(swing_signals 에 regime 열 없음,
    #    하루 2.13건을 4분할 → 횡단면 정보 0). 올바른 수정은 절대 목표가 아니라
    #    각 레짐의 **사전값 기준 배수**로 움직이는 것 — 설계 결정이 필요해 미구현.
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
            # 🔴 미측정 팩터의 현재 가중은 '예산 밖'으로 둔다 — 건드리지 않는다.
            budget = max(0.0, 1.0 - sum(w for f, w in cur.items() if f not in ics))
            for f, ic in ics.items():
                if f not in cur:
                    continue
                lo, hi = BOUNDS.get(f, (0.0, 0.5))
                if ic <= 0:
                    target = lo      # 측정된 음의 IC — 하한까지 내린다
                else:
                    target = (budget * pos[f] / total_pos) if total_pos > 0 else cur[f]
                target = max(lo, min(hi, target))
                # 주당 변화폭 제한 — 한 번의 측정으로 급전환하지 않는다
                step = max(-max_step, min(max_step, target - cur[f]))
                new[f] = round(max(lo, min(hi, cur[f] + step)), 4)

            # 합계 1.0 정규화.
            # 🔴 '유지'는 **상대비중 유지**를 뜻한다. 측정된 팩터를 상한까지 내리면
            #    남는 예산이 생기고(momentum 현재 0.2634 > 상한 0.25), 그건 어딘가로
            #    가야 한다. 비례 정규화는 유지 팩터들의 **서로 간 비율**을 정확히 보존하므로
            #    IC 로 재배분하는 것과 다르다 — 변경 기록에 사유를 구분해 남긴다.
            tot = sum(new.values())
            if tot <= 0:
                continue
            if abs(tot - 1.0) > 1e-4:
                new = {f: round(v / tot, 4) for f, v in new.items()}

            for f, v in new.items():
                if abs(v - cur.get(f, 0)) < 1e-4:
                    continue
                why = ("IC 재배분" if f in ics
                       else "정규화(상대비중 유지)")
                changes.append({"regime": regime, "factor": f, "old": cur.get(f),
                                "new": v, "ic": ics.get(f), "why": why})
                if not dry_run:
                    conn.execute("""
                        UPDATE swing_factor_weights
                           SET weight = %s, updated_at = now(), updated_by = 'weight_tuner',
                               reason = %s
                         WHERE regime = %s AND factor = %s
                    """, (v, f"{why} IC={ics.get(f)} (h={horizon}d)", regime, f))
                    conn.execute("""
                        INSERT INTO swing_weight_history
                            (regime, factor, old_weight, new_weight, ic_used, reason)
                        VALUES (%s,%s,%s,%s,%s,%s)
                    """, (regime, f, cur.get(f), v, ics.get(f),
                          f"auto-tune h={horizon}d min_dates={min_dates} "
                          f"xsec_excess+CI · {why} (§22.AO-50)"))
        if not dry_run:
            conn.commit()

    summary = {"changed": len(changes), "ics": {k: round(v, 4) for k, v in ics.items()},
               "skipped": skipped, "changes": changes[:20], "dry_run": dry_run,
               "held": sorted(skipped)}
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
        lines.append("  <b>유지</b>(미측정 — 가중 0 으로 끌어내리지 않는다): "
                     + " · ".join(f"{k}({v})" for k, v in sk.items()))
    ch = summary.get("changes") or []
    if ch:
        byic = [c for c in ch if c.get("ic") is not None]
        lines.append(f"  변경 {summary['changed']}건 "
                     f"(IC 재배분 {len(byic)}건, 나머지는 정규화)")
        for c in (byic or ch)[:5]:
            tag = "" if c.get("ic") is None else f" (IC {c['ic']:+.3f})"
            lines.append(f"    {c['regime']}/{c['factor']}: "
                         f"{c['old']:.4f} → {c['new']:.4f}{tag}")
    else:
        lines.append("  변경 없음")
    return "\n".join(lines)
