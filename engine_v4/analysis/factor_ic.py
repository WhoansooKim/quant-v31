"""주간 팩터 IC 자동 측정 (§22.AO-15, 측정 방식 전면 교체 §22.AO-50).

목적: ①LLM 모멘텀 A/B · ②교집합 게이트 · ③PEAD 가 실제로 작동하는지
**표본이 쌓이는 대로 자동 확인**한다. 수동 스크립트에 의존하면 사후 대처가 반복된다.

미래참조 없음: `swing_signals` 에 **당시 저장된** 점수만 쓰고, 수익은 시그널 이후
`daily_prices` 실제 종가로 계산한다.

🔴 §22.AO-50 — 이전 구현의 측정 결함 4개. 전부 IC 를 **과대**하게 만들었다
(`llm_momentum` 10일 저장값 +0.1372 → 바로잡으면 날짜내 순열검정 p=0.534):
  1) **전 구간 풀링 Spearman 이었다.** 날짜를 섞어 한 번에 상관을 냈다. 같은 날 종목들은
     시장 전체 움직임을 공유하므로 유효표본은 신호 수가 아니라 **날짜 수**다.
     저장된 `n_samples=65` 의 실체는 날짜 21개였다.
  2) **시장조정이 없었다.** 원시 전방수익을 쓰면 "점수가 높던 주가 좋은 주였다"가
     팩터 예측력으로 기록된다.
  3) **중복을 셌다.** 같은 (종목, 날짜) ENTRY 가 2건씩 들어 있다(117행 → 고유 93행).
     표본수가 부풀고 날짜내 순열검정의 교환가능성이 깨진다.
  4) **EXIT 시그널을 섞었다.** `entry_price>0` 만 걸러 EXIT 174건이 함께 들어갔다.
     진입 팩터의 예측력을 재는 표본이 아니다.
  5) **분산 없는 날짜를 셌다.** `llm_momentum` 은 77%가 정확히 50(중립)이라 날짜 21개 중
     **5개**에서만 횡단면에 변동이 있다. 순위를 매길 수 없는 16일이 풀링 상관에 기여했다.

그 결과 `verdicts()` 가 "✅ 검증됨" 과 "① 적용: llm_momentum_active=true" 를 알림으로
보냈고, 그 플래그는 **이미 true** 였으며(태어난 날부터), 같은 IC 가 `weight_tuner` 를 통해
**실제 라이브 가중치**를 매주 움직여 왔다(`swing_weight_history` 231건, ic_used=0.1372).

지금 구현:
  - 중복제거(`DISTINCT ON (symbol, 날짜)`) · ENTRY 만 · SPY 초과수익
  - **날짜별 횡단면 IC** 를 먼저 내고 그 **중앙값**을 주 지표로 삼는다(`ic_xsec`)
  - **날짜블록 부트스트랩** 95%CI (`ic_lo`/`ic_hi`) — 날짜를 복원추출한다
  - 판정 문턱은 `n_samples` 가 아니라 **`n_valid_dates`**(변동있는 날짜 수)에 걸린다
  - `ic` 열은 옛 풀링값을 그대로 유지한다(과거 행과의 비교용). 주 지표는 `ic_xsec`.
"""

from __future__ import annotations

import logging
from datetime import date
from statistics import mean, median
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

HORIZONS = (5, 10, 20)
BENCH = "SPY"

# 측정 대상 — 기존 팩터 + 신규 신호
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
    "pead_score",           # ③ PEAD
]

# ─── 검증 기준 (§22.AO-17, 문턱 교체 §22.AO-50) ─────────────
# 사람이 IC 표를 매주 해석하게 두면 결국 놓친다. 기준을 코드에 박아두고 판정을 자동화한다.
# 🔴 사전등록: 주 판정은 **10일 · 시장조정 · 날짜별 횡단면 IC 중앙값**이고,
#    유의성은 **날짜블록 부트스트랩 95%CI 가 0 을 제외하는지**로 본다.
#    사후에 유의해진 horizon 은 가설이지 근거가 아니다(§22.AO-49 의 5일 p=0.007 건).
MIN_VALID_DATES = 10        # 변동있는 날짜가 이 수 미만이면 '측정중' — 표본수가 아니라 날짜다
PRIMARY_HORIZON = 10        # 판정 기준 horizon (사전등록)
LLM_EDGE_MIN = 0.05         # ① llm_momentum 이 sentiment 를 이겨야 하는 최소 폭
PEAD_IC_MIN = 0.05          # ③ pead 최소 IC
STABLE_HORIZONS = 2         # 3개 horizon 중 몇 개에서 양수여야 '안정'으로 보는가
BOOT_REPS = 2000
BOOT_SEED = 20261018        # 고정 — 같은 데이터면 같은 CI 가 나와야 한다


def _ic_of(result: dict[str, Any], h: int, f: str) -> dict[str, Any] | None:
    blk = (result.get("horizons") or {}).get(h) or {}
    return (blk.get("factors") or {}).get(f)


def verdicts(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """①③ 검증 판정. 기준 미달/표본부족을 명시적으로 구분한다.

    🔴 §22.AO-50: 문턱을 `n_samples` 에서 `n_valid_dates` 로 바꾸고, 유의성 조건으로
    **CI 가 0 을 제외**할 것을 요구한다. 이전 판정은 77% 동점·변동날짜 5/21 인 팩터에
    "✅ 검증됨" 을 냈다.
    """
    out: dict[str, dict[str, Any]] = {}
    flags = result.get("flags") or {}

    def judge(key: str, factor: str, ic_min: float,
              control: str | None = None, edge_min: float = 0.0,
              flag: str | None = None) -> None:
        v = _ic_of(result, PRIMARY_HORIZON, factor)
        vd = (v or {}).get("valid_dates", 0)
        if v is None or vd < MIN_VALID_DATES:
            den = result.get("density") or {}
            why = ""
            if den.get("per_date"):
                why = (f" · 🔴 구조적 한계: 신호가 하루 {den['per_date']}건이고 "
                       f"{den['dates']}일 중 {den['single']}일이 1건이다 — "
                       f"1건인 날은 횡단면 정보가 0 이므로 표본이 쌓여도 해소되지 않는다")
            out[key] = {"status": "측정중",
                        "detail": (f"변동있는 날짜 {vd}/{MIN_VALID_DATES} "
                                   f"(신호 수가 아니라 날짜가 분모다){why}")}
            return
        pos = sum(1 for h in HORIZONS
                  if ((_ic_of(result, h, factor) or {}).get("ic_xsec") or 0) > 0)
        lo = v.get("ic_lo")
        sig_ok = lo is not None and lo > 0
        parts = [f"IC {v['ic_xsec']:+.3f} 95%CI [{v['ic_lo']:+.3f}, {v['ic_hi']:+.3f}]",
                 f"변동날짜 {vd}/{v['n_dates']}", f"양수 {pos}/3"]
        ok = sig_ok and v["ic_xsec"] >= ic_min and pos >= STABLE_HORIZONS
        if control is not None:
            c = _ic_of(result, PRIMARY_HORIZON, control)
            cic = (c or {}).get("ic_xsec")
            edge = v["ic_xsec"] - (cic if cic is not None else 0.0)
            parts.append(f"대조 {control.replace('_score','')} "
                         f"{'n/a' if cic is None else f'{cic:+.3f}'} → 차이 {edge:+.3f}"
                         f" (기준 {edge_min:+.2f})")
            ok = ok and edge >= edge_min
        if not sig_ok:
            parts.append("🔴 CI 가 0 을 포함 — 측정되지 않았다")
        # 두 추정량(횡단면·풀링)이 어긋나면 어느 쪽도 믿지 않는다
        pic, plo = v.get("ic_pooled"), v.get("pooled_lo")
        if pic is not None:
            agree = (pic > 0) == (v["ic_xsec"] > 0) and (plo is None or plo > 0)
            parts.append(f"풀링 {pic:+.3f}"
                         + ("" if plo is None else f" [{plo:+.3f}, {v['pooled_hi']:+.3f}]"))
            if not agree:
                parts.append("⚠️ 횡단면·풀링 불일치 — 판정 보류")
                ok = False
        out[key] = {"status": "✅ 검증됨" if ok else "❌ 기준미달",
                    "detail": " · ".join(parts), "actionable": ok}
        # 🔴 이미 켜져 있는 플래그를 켜라고 권고하지 않는다 (§22.AO-49)
        if flag:
            out[key]["flag"] = flag
            out[key]["flag_on"] = bool(flags.get(flag))
            if out[key].get("actionable") and flags.get(flag):
                out[key]["actionable"] = False
                out[key]["detail"] += f" · ⚠️ {flag} 는 이미 true (관찰 기간 없음)"

    judge("①LLM모멘텀", "llm_momentum_score", 0.0,
          control="sentiment_score", edge_min=LLM_EDGE_MIN, flag="llm_momentum_active")
    judge("③PEAD", "pead_score", PEAD_IC_MIN, flag="pead_active")
    return out


# 🔴 중복제거 + ENTRY 한정 + SPY 초과수익. 파라미터 순서: (h-1, BENCH, BENCH, h-1)
_SQL = """
WITH sig AS (
    SELECT DISTINCT ON (s.symbol, s.time::date)
           s.symbol, s.time::date AS d, s.entry_price, {cols}
    FROM swing_signals s
    WHERE s.entry_price > 0 AND s.signal_type = 'ENTRY'
    ORDER BY s.symbol, s.time::date, s.time
)
SELECT sig.*,
       (SELECT p.close FROM daily_prices p
          WHERE p.symbol = sig.symbol AND p.time::date > sig.d
          ORDER BY p.time LIMIT 1 OFFSET %s) AS px_fwd,
       (SELECT p.close FROM daily_prices p
          WHERE p.symbol = %s AND p.time::date <= sig.d
          ORDER BY p.time DESC LIMIT 1) AS b0,
       (SELECT p.close FROM daily_prices p
          WHERE p.symbol = %s AND p.time::date > sig.d
          ORDER BY p.time LIMIT 1 OFFSET %s) AS b1
FROM sig
"""


def _spearman(xs, ys) -> float | None:
    """순위상관. 동점은 평균순위. 한쪽이 전부 동점이면 **정의되지 않는다**(None)."""
    if len(xs) < 3:
        return None
    rx = _rank(list(xs))
    ry = _rank(list(ys))
    mx, my = mean(rx), mean(ry)
    sx = sum((a - mx) ** 2 for a in rx)
    sy = sum((b - my) ** 2 for b in ry)
    if sx == 0 or sy == 0:
        return None     # 🔴 전 종목 같은 점수 — 순위를 매길 수 없는 날이다
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return num / (sx * sy) ** 0.5


def _rank(v: list[float]) -> list[float]:
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


def _block_ci_pooled(dates: list[Any], xs: list[float],
                     ys: list[float]) -> tuple[float | None, float | None]:
    """풀링 Spearman 의 **날짜블록** 부트스트랩 CI.

    왜 풀링도 같이 보는가: 이 시스템의 신호는 **하루 2.1건**이고 97일 중 **58일이 1건**이다.
    1건인 날은 횡단면 정보가 0 이므로 `ic_xsec` 는 표본의 대부분을 버린다. 풀링은 전부 쓰지만
    날짜 간 교란(섹터·레짐)이 점추정에 남는다 → **검정력은 높고 편향에 취약한 보조 추정량**이다.
    두 추정량이 어긋나면 어느 쪽도 믿지 않는다.
    """
    uq = sorted(set(dates))
    if len(uq) < 10:
        return None, None
    rng = np.random.default_rng(BOOT_SEED)
    idx: dict[Any, list[int]] = {}
    for i, d in enumerate(dates):
        idx.setdefault(d, []).append(i)
    vals = []
    for _ in range(BOOT_REPS):
        sel: list[int] = []
        for d in rng.choice(np.array(uq, dtype=object), size=len(uq), replace=True):
            sel.extend(idx[d])
        ic = _spearman([xs[i] for i in sel], [ys[i] for i in sel])
        if ic is not None:
            vals.append(ic)
    if len(vals) < BOOT_REPS * 0.5:
        return None, None
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def _block_ci(per_date: list[float]) -> tuple[float | None, float | None]:
    """날짜별 IC 중앙값의 95%CI. 날짜를 복원추출한다 — 블록이 날짜다."""
    if len(per_date) < 3:
        return None, None
    rng = np.random.default_rng(BOOT_SEED)
    arr = np.asarray(per_date, dtype=float)
    meds = np.median(rng.choice(arr, size=(BOOT_REPS, len(arr)), replace=True), axis=1)
    return float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))


def compute_and_store(pg, as_of: date | None = None) -> dict[str, Any]:
    """전 팩터 × 전 horizon IC 를 계산해 swing_factor_ic 에 저장."""
    as_of = as_of or date.today()
    min_n = int(float(pg.get_config_value("factor_ic_min_samples", "15")))
    cols = ", ".join(f"s.{f}" for f in FACTORS)
    out: dict[str, Any] = {"as_of": as_of.isoformat(), "horizons": {},
                           "flags": {k: pg.get_config_value(k, "false") == "true"
                                     for k in ("llm_momentum_active", "pead_active")}}

    for h in HORIZONS:
        with pg.get_conn() as conn:
            raw = conn.execute(_SQL.format(cols=cols),
                               (h - 1, BENCH, BENCH, h - 1)).fetchall()
        rows, no_bench = [], 0
        for r in raw:
            if not r["px_fwd"]:
                continue
            ret = (float(r["px_fwd"]) - float(r["entry_price"])) / float(r["entry_price"])
            if r["b0"] and r["b1"] and float(r["b0"]) > 0:
                ex = ret - (float(r["b1"]) / float(r["b0"]) - 1.0)
            else:
                no_bench += 1
                continue    # 🔴 시장조정 못 하면 버린다 — 조정 없는 수익을 섞지 않는다
            rows.append((r, ret, ex))
        if no_bench:
            logger.warning(f"factor_ic h={h}: {BENCH} 가격 결손으로 {no_bench}건 제외")
        if len(rows) < min_n:
            out["horizons"][h] = {"skipped": f"n={len(rows)} < {min_n}"}
            continue

        dates = sorted({r["d"] for r, _, _ in rows})
        if h == PRIMARY_HORIZON:
            cnt: dict[Any, int] = {}
            for r, _, _ in rows:
                cnt[r["d"]] = cnt.get(r["d"], 0) + 1
            out["density"] = {"signals": len(rows), "dates": len(dates),
                              "per_date": round(len(rows) / max(len(dates), 1), 2),
                              "single": sum(1 for v in cnt.values() if v == 1)}
        per_factor: dict[str, Any] = {}
        for f in FACTORS:
            usable = [(r, ex) for r, _, ex in rows if r[f] is not None]
            if len(usable) < min_n:
                continue
            by_date: dict[Any, list[tuple[float, float]]] = {}
            for r, ex in usable:
                by_date.setdefault(r["d"], []).append((float(r[f]), ex))
            per_date = []
            for d in sorted(by_date):
                pairs = by_date[d]
                ic = _spearman([p[0] for p in pairs], [p[1] for p in pairs])
                if ic is not None:
                    per_date.append(ic)
            fx = [float(r[f]) for r, _ in usable]
            fy = [ex for _, ex in usable]
            fd = [r["d"] for r, _ in usable]
            pooled = _spearman(fx, fy)
            p_lo, p_hi = _block_ci_pooled(fd, fx, fy)
            if not per_date:
                # 전 날짜에서 순위를 매길 수 없었다 — 기록은 남기되 판정에 못 쓴다
                per_factor[f] = {"ic_xsec": None, "valid_dates": 0,
                                 "n_dates": len(by_date), "n": len(usable),
                                 "ic_pooled": None if pooled is None else round(pooled, 4),
                                 "pooled_lo": None if p_lo is None else round(p_lo, 4),
                                 "pooled_hi": None if p_hi is None else round(p_hi, 4)}
                continue
            ic_x = float(median(per_date))
            lo, hi = _block_ci(per_date)
            med_ex = float(median([ex for _, ex in usable]))
            per_factor[f] = {
                "ic_xsec": round(ic_x, 4),
                "ic_lo": None if lo is None else round(lo, 4),
                "ic_hi": None if hi is None else round(hi, 4),
                "ic_pooled": None if pooled is None else round(pooled, 4),
                "pooled_lo": None if p_lo is None else round(p_lo, 4),
                "pooled_hi": None if p_hi is None else round(p_hi, 4),
                "valid_dates": len(per_date), "n_dates": len(by_date),
                "n": len(usable), "median_excess": round(med_ex, 6),
            }
            with pg.get_conn() as conn:
                conn.execute("""
                    INSERT INTO swing_factor_ic
                        (as_of, horizon_days, factor, ic, ic_xsec, ic_lo, ic_hi,
                         pooled_lo, pooled_hi,
                         n_samples, n_dates, n_valid_dates, mean_return, median_excess,
                         method, computed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'xsec_excess', now())
                    ON CONFLICT (as_of, horizon_days, factor) DO UPDATE SET
                        ic = EXCLUDED.ic, ic_xsec = EXCLUDED.ic_xsec,
                        ic_lo = EXCLUDED.ic_lo, ic_hi = EXCLUDED.ic_hi,
                        pooled_lo = EXCLUDED.pooled_lo, pooled_hi = EXCLUDED.pooled_hi,
                        n_samples = EXCLUDED.n_samples, n_dates = EXCLUDED.n_dates,
                        n_valid_dates = EXCLUDED.n_valid_dates,
                        mean_return = EXCLUDED.mean_return,
                        median_excess = EXCLUDED.median_excess,
                        method = 'xsec_excess', computed_at = now()
                """, (as_of, h, f,
                      None if pooled is None else round(pooled, 4), round(ic_x, 4),
                      None if lo is None else round(lo, 4),
                      None if hi is None else round(hi, 4),
                      None if p_lo is None else round(p_lo, 4),
                      None if p_hi is None else round(p_hi, 4),
                      len(usable), len(by_date), len(per_date),
                      round(mean([ret for _, ret, _ in rows]), 6), round(med_ex, 6)))
                conn.commit()   # 🔴 get_conn 은 커밋 없이 닫는다

        # ② 교집합 게이트 — IC 가 아니라 '통과분 성적'으로 본다(순위지표로는 부적합, §22.AO-12)
        mom_min = float(pg.get_config_value("intersection_momentum_min", "0.70"))
        tech_min = float(pg.get_config_value("intersection_technical_min", "60"))

        def passes(r):
            rk, tc = r["return_20d_rank"], r["technical_score"]
            return (rk is not None and float(rk) >= mom_min
                    and tc is not None and float(tc) >= tech_min)

        gated = [ex for r, _, ex in rows if passes(r)]
        ungated = [ex for r, _, ex in rows if not passes(r)]
        gate = None
        if gated and ungated:
            gate = {
                "n_pass": len(gated),
                "median_pass": round(median(gated), 4),
                "win_pass": round(sum(1 for x in gated if x > 0) / len(gated), 3),
                "median_fail": round(median(ungated), 4),
                "edge": round(median(gated) - median(ungated), 4),
            }

        out["horizons"][h] = {
            "n": len(rows), "n_dates": len(dates),
            "median_excess": round(median([ex for _, _, ex in rows]), 4),
            "beat_bench": round(sum(1 for _, _, ex in rows if ex > 0) / len(rows), 3),
            "factors": per_factor, "intersection_gate": gate,
        }
    return out


def format_report(result: dict[str, Any]) -> str:
    """텔레그램용 HTML 요약. 판정을 맨 앞에 둔다 — IC 표를 매주 해석하게 두지 않는다."""
    v = verdicts(result)
    lines = [f"<b>📐 주간 팩터 IC ({result['as_of']})</b>",
             "<i>날짜별 횡단면 · SPY 초과 · 중복제거 · ENTRY만 (§22.AO-50)</i>", ""]
    den = result.get("density") or {}
    if den:
        lines.append(f"<i>표본 밀도: 하루 {den['per_date']}건 · "
                     f"{den['dates']}일 중 {den['single']}일이 1건(횡단면 정보 0)</i>")
        lines.append("")
    lines.append("<b>검증 판정</b>")
    for name, d in v.items():
        lines.append(f"  {name}: <b>{d['status']}</b>")
        lines.append(f"     {d['detail']}")
    if any(d.get("actionable") for d in v.values()):
        lines.append("")
        lines.append("🔔 <b>기준 충족 — 적용 검토 필요</b>")
        for name, d in v.items():
            if d.get("actionable") and d.get("flag"):
                lines.append(f"   {name} 적용: {d['flag']}=true")
    for h, blk in result.get("horizons", {}).items():
        if "skipped" in blk:
            lines.append(f"\n<b>{h}일</b>: 표본부족 ({blk['skipped']})")
            continue
        lines.append(f"\n<b>{h}일 전방</b> (n={blk['n']}, 날짜 {blk['n_dates']}, "
                     f"초과 중앙 {blk['median_excess']:+.2%}, "
                     f"SPY상회 {blk['beat_bench']:.0%})")
        fs = {k: x for k, x in (blk.get("factors") or {}).items()
              if x.get("ic_xsec") is not None}
        for f, x in sorted(fs.items(), key=lambda kv: -kv[1]["ic_xsec"]):
            mark = " ①" if f == "llm_momentum_score" else (
                   " ①대조" if f == "sentiment_score" else "")
            zero = "" if (x.get("ic_lo") or 0) > 0 else " ·CI∋0"
            pz = ""
            if x.get("ic_pooled") is not None:
                pz = f" |풀링 {x['ic_pooled']:+.3f}"
                if (x.get("pooled_lo") or 0) > 0 or (x.get("pooled_hi") or 0) < 0:
                    pz += "*"
            lines.append(f"  {f.replace('_score','').replace('return_20d_rank','momentum')}"
                         f": {x['ic_xsec']:+.3f} "
                         f"(날짜 {x['valid_dates']}/{x['n_dates']}){zero}{pz}{mark}")
        dead = [f for f, x in (blk.get("factors") or {}).items()
                if x.get("ic_xsec") is None]
        if dead:
            lines.append(f"  ⚠️ 변동 없어 측정불가: {', '.join(d.replace('_score','') for d in dead)}")
        g = blk.get("intersection_gate")
        if g:
            lines.append(f"  ② 교집합: 통과 {g['n_pass']}건 중앙 {g['median_pass']:+.2%} "
                         f"승률 {g['win_pass']:.0%} / 미통과 {g['median_fail']:+.2%} "
                         f"→ 차이 {g['edge']:+.2%}")
    return "\n".join(lines)
