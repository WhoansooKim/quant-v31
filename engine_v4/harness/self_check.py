"""3K: 자가 진단 — 계측 버그 불변식 검사 (§22.AO-21).

**왜 만들었나**: 2026-08-18~19 세션에서 발견한 버그 4종은 전부 **불변식 위반**이었다.
사람이 의심해서 찾았지만, 한 번 알아낸 것은 두 번 다시 놓치지 않아야 한다.

| 검사 | 실제로 잡았어야 했던 버그 |
|---|---|
| 회계 항등식 | 유령손실 (실현 +$416 vs 자본증감 −$170) |
| 스냅샷 정합 | cash+invested ≠ total_value |
| 지표 범위 | MDD −505% |
| 가중치 일치 | REGIME_WEIGHTS 하드코딩 (DB 변경이 무시됨) |
| 팩터 분산 | Δ0.0 무력 키 (변이가 결과를 못 바꿈) |
| 자산곡선 연속성 | 평가액 급변 |
| **수집 결손** | **DXY 6개월 결손 (중립 기본값에 흡수돼 경보가 없었다, §22.AO-29)** |

⚠️ **한계**: 알려진 불변식만 검사한다. 새로운 종류의 버그는 여전히 사람이 발견해야 한다.

※ `data_freshness` 만 성격이 다르다 — 나머지가 "계측이 틀렸는가"를 본다면 이것은
"입력이 있는가"를 본다. 6/6 PASS 가 "데이터가 있다"는 뜻이 아니었기 때문에 추가했다(§22.AO-29).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

CRITICAL = "critical"
WARN = "warn"


def _record(pg, name: str, ok: bool, detail: dict, severity: str) -> dict:
    status = "PASS" if ok else "FAIL"
    try:
        import json
        with pg.get_conn() as conn:
            conn.execute(
                "INSERT INTO swing_self_check (check_name, status, detail, severity) "
                "VALUES (%s,%s,%s::jsonb,%s)",
                (name, status, json.dumps(detail, default=str), severity))
            conn.commit()
    except Exception as e:
        logger.warning(f"self_check record failed ({name}): {e}")
    return {"check": name, "status": status, "severity": severity, "detail": detail}


# ─── 개별 검사 ───────────────────────────────────────────

def check_snapshot_identity(pg) -> dict:
    """cash + invested = total_value. 어긋나면 스냅샷 계산이 깨진 것."""
    with pg.get_conn() as conn:
        rows = conn.execute("""
            SELECT time, total_value_usd, cash_usd, invested_usd
            FROM swing_snapshots
            WHERE total_value_usd IS NOT NULL AND cash_usd IS NOT NULL
              AND invested_usd IS NOT NULL
            ORDER BY time DESC LIMIT 30
        """).fetchall()
    bad = []
    for r in rows:
        tv, cash, inv = float(r["total_value_usd"]), float(r["cash_usd"]), float(r["invested_usd"])
        if abs((cash + inv) - tv) > max(1.0, tv * 0.005):
            bad.append({"time": r["time"], "total": tv, "cash": cash,
                        "invested": inv, "gap": round(cash + inv - tv, 2)})
    return _record(pg, "snapshot_identity", not bad,
                   {"checked": len(rows), "violations": bad[:5]}, CRITICAL)


def check_metric_range(pg) -> dict:
    """누적수익률·MDD 가 물리적으로 가능한 범위인가. MDD −505% 를 잡는 검사."""
    with pg.get_conn() as conn:
        row = conn.execute("""
            SELECT MIN(cumulative_return) AS min_cum, MAX(cumulative_return) AS max_cum,
                   MIN(max_drawdown) AS min_mdd, MAX(max_drawdown) AS max_mdd
            FROM swing_snapshots
        """).fetchone()
    issues = []
    if row["min_mdd"] is not None and float(row["min_mdd"]) < -1.0:
        issues.append(f"max_drawdown={float(row['min_mdd']):.2%} < −100% (불가능)")
    if row["max_mdd"] is not None and float(row["max_mdd"]) > 0.0001:
        issues.append(f"max_drawdown={float(row['max_mdd']):.2%} > 0 (낙폭은 음수여야 함)")
    if row["max_cum"] is not None and float(row["max_cum"]) > 3.0:
        issues.append(f"cumulative_return={float(row['max_cum']):.2%} > 300% (이상치 의심)")
    if row["min_cum"] is not None and float(row["min_cum"]) < -0.95:
        issues.append(f"cumulative_return={float(row['min_cum']):.2%} < −95% (이상치 의심)")
    return _record(pg, "metric_range", not issues,
                   {"issues": issues, "range": {k: (float(v) if v is not None else None)
                                                for k, v in row.items()}}, CRITICAL)


def check_equity_continuity(pg, max_jump: float = 0.5) -> dict:
    """자산곡선이 하루에 50% 이상 튀면 평가 로직 이상.

    단 **입출금일은 제외**한다 — 정상 자본 이동을 버그로 신고하면(2026-07-28 입금 $1,000)
    검사 자체가 무시되기 때문이다.
    """
    with pg.get_conn() as conn:
        rows = conn.execute("""
            SELECT time, total_value_usd FROM swing_snapshots
            WHERE total_value_usd IS NOT NULL ORDER BY time
        """).fetchall()
        cap_days = {r["d"] for r in conn.execute(
            "SELECT DISTINCT created_at::date AS d FROM swing_capital_events").fetchall()}
    bad, prev = [], None
    for r in rows:
        v = float(r["total_value_usd"])
        if (prev and prev > 0 and abs(v - prev) / prev > max_jump
                and r["time"].date() not in cap_days):
            bad.append({"time": r["time"], "from": prev, "to": v,
                        "change": round((v - prev) / prev, 3)})
        prev = v
    return _record(pg, "equity_continuity", not bad,
                   {"checked": len(rows), "violations": bad[:5],
                    "max_jump": max_jump, "capital_days_excluded": len(cap_days)}, WARN)


def check_weight_consistency(pg) -> dict:
    """DB 가중치가 실제 적용값과 같은가. REGIME_WEIGHTS 하드코딩 사고를 잡는 검사."""
    issues = []
    with pg.get_conn() as conn:
        rows = conn.execute(
            "SELECT regime, factor, weight FROM swing_factor_weights").fetchall()
    if not rows:
        return _record(pg, "weight_consistency", False,
                       {"issues": ["swing_factor_weights 비어 있음"]}, CRITICAL)

    db: dict[str, dict[str, float]] = {}
    for r in rows:
        db.setdefault(r["regime"], {})[r["factor"]] = float(r["weight"])
    for regime, w in db.items():
        tot = sum(w.values())
        if abs(tot - 1.0) > 0.01:
            issues.append(f"{regime} 가중치 합 {tot:.3f} ≠ 1.0")

    # 코드가 실제로 읽는 값과 대조
    try:
        from engine_v4.ai.multi_factor import MultiFactorScorer
        for regime in db:
            applied = MultiFactorScorer._load_weights(
                type("S", (), {"pg": pg, "REGIME_WEIGHTS": MultiFactorScorer.REGIME_WEIGHTS})(),
                regime)
            for f, v in db[regime].items():
                if abs(applied.get(f, -999) - v) > 1e-6:
                    issues.append(f"{regime}/{f}: DB {v} ≠ 적용 {applied.get(f)}")
    except Exception as e:
        issues.append(f"적용값 대조 실패: {e}")
    return _record(pg, "weight_consistency", not issues, {"issues": issues[:8]}, CRITICAL)


def check_factor_variance(pg, lookback: int = 80) -> dict:
    """팩터가 상수면 그 파라미터는 결과를 못 바꾼다(Δ0.0 무력 키)."""
    cols = ["technical_score", "sentiment_score", "quality_score", "value_score",
            "flow_score", "macro_score", "llm_momentum_score", "pead_score",
            "composite_score"]
    sel = ", ".join(f"STDDEV_SAMP({c}) AS sd_{c}, COUNT({c}) AS n_{c}" for c in cols)
    with pg.get_conn() as conn:
        row = conn.execute(
            f"SELECT {sel} FROM (SELECT * FROM swing_signals "
            f"ORDER BY time DESC LIMIT {lookback}) t").fetchone()
    inert, unmeasured = [], []
    for c in cols:
        n = int(row[f"n_{c}"] or 0)
        sd = row[f"sd_{c}"]
        if n < 10:
            unmeasured.append(f"{c}(n={n})")
        elif sd is None or float(sd) < 1e-9:
            inert.append(f"{c}(상수, n={n})")
    return _record(pg, "factor_variance", not inert,
                   {"inert": inert, "unmeasured": unmeasured, "lookback": lookback}, WARN)


def check_backtest_identity(pg) -> dict:
    """실현손익 + 미청산평가손익 = 자본증감. 유령손실을 잡은 바로 그 검사."""
    if pg.get_config_value("self_check_backtest", "true") != "true":
        return _record(pg, "backtest_identity", True, {"skipped": "disabled"}, CRITICAL)
    try:
        from engine_v4.backtest.runner import BacktestRunner
        from engine_v4.harness.auto_backtest import _baseline_config, _live_capital, _make_params
        base, cap = _baseline_config(pg), _live_capital(pg)
        end = date.today()
        r = BacktestRunner(pg).run(_make_params(base, {}, end - timedelta(days=180), end, cap))
        realized = sum(float(t["pnl"]) for t in r.trades_log if t["side"] == "SELL")
        equity_change = float(r.final_value) - cap
        unrealized = equity_change - realized
        # 미청산 평가손익이 미청산 원가를 초과하면 물리적으로 불가능
        buys = [t for t in r.trades_log if t["side"] == "BUY"]
        sells = [t for t in r.trades_log if t["side"] == "SELL"]
        open_cost = sum(float(t["qty"]) * float(t["price"]) for t in buys) \
            - sum(float(t["qty"]) * float(t["price"]) for t in sells)
        ok = abs(unrealized) <= max(abs(open_cost) * 1.5, cap * 0.05)
        return _record(pg, "backtest_identity", ok, {
            "realized": round(realized, 2), "equity_change": round(equity_change, 2),
            "unrealized": round(unrealized, 2), "open_cost_est": round(open_cost, 2),
            "note": "미청산 평가손익이 미청산 원가를 크게 초과하면 평가 로직 이상",
        }, CRITICAL)
    except Exception as e:
        return _record(pg, "backtest_identity", False, {"error": str(e)[:200]}, WARN)


def check_data_freshness(pg) -> dict:
    """수집 결손 감지 — 외부 입력이 조용히 사라졌는지 본다 (§22.AO-29).

    다른 검사들은 전부 "계측이 틀렸는가"를 본다. 이것만 "입력이 있는가"를 본다.
    DXY 가 142행(2026-03-20~09-13, 약 6개월) 동안 null 이었는데 어떤 검사도 잡지 못했다 —
    `_score_dollar_trend` 가 값이 없으면 중립 50 을 돌려줘 **실패가 예외가 아니라 기본값으로
    흡수**됐기 때문이다. 자가진단은 그동안 내내 6/6 PASS 였다.

    검사 컬럼을 하드코딩하지 않고 information_schema 에서 발견한다 —
    상수로 박으면 지표를 추가할 때마다 사각지대가 생긴다(§22.AO-28 과 같은 이유).

    검사 대상: ①매크로 신선도 ②매크로 컬럼 결손 ③가격 커버리지 ④가격 바 신선도
    ⑤소셜 수집 ⑥PEAD 수집 ⑦시그널 팩터 입력 회귀(뉴스감성·PEAD·LLM 등).

    ⚠️ 여전히 안 보는 것: `swing_events`(뉴스/EDGAR)는 **스케줄 잡이 없어** 수동 `/events/scan`
    전용이므로 결손 판정 대상이 아니다. `sentiment_scores` 는 V3.1 레거시로 V4 가 쓰지 않는다.
    """
    n = int(pg.get_config_value("self_check_freshness_rows", "10"))
    max_stale = int(pg.get_config_value("self_check_macro_stale_days", "3"))
    min_cover = float(pg.get_config_value("self_check_price_coverage_min", "0.90"))
    max_bar_stale = int(pg.get_config_value("self_check_price_stale_days", "4"))
    max_social_stale = int(pg.get_config_value("self_check_social_stale_days", "3"))
    max_pead_stale = int(pg.get_config_value("self_check_pead_stale_days", "10"))
    sig_win = int(pg.get_config_value("self_check_signal_window", "30"))

    issues: list[str] = []
    detail: dict[str, Any] = {}

    with pg.get_conn() as conn:
        cols = [r["column_name"] for r in conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'swing_macro_snapshots'
              AND data_type IN ('double precision', 'numeric', 'real')
            ORDER BY ordinal_position
        """).fetchall()]

        # ── 1. 매크로 신선도 ──
        row = conn.execute(
            "SELECT max(time) AS newest FROM swing_macro_snapshots").fetchone()
        newest = row["newest"] if row else None
        if newest is None:
            issues.append("매크로 스냅샷 없음")
            detail["macro_newest"] = None
        else:
            stale = (date.today() - newest.date()).days
            detail["macro_newest"] = str(newest.date())
            detail["macro_stale_days"] = stale
            if stale > max_stale:
                issues.append(f"매크로 수집 중단 {stale}일 (허용 {max_stale})")

        # ── 2. 매크로 컬럼별 결손 (최근 n행 기준) ──
        if cols:
            sel = ", ".join(f'count("{c}") AS "{c}"' for c in cols)
            r = conn.execute(
                f"SELECT count(*) AS rows, {sel} FROM "
                f"(SELECT * FROM swing_macro_snapshots ORDER BY time DESC LIMIT %s) t",
                (n,)).fetchone()
            rows = int(r["rows"] or 0)
            gone, partial = [], []
            for c in cols:
                present = int(r[c] or 0)
                if rows and present == 0:
                    gone.append(c)                       # n행 전부 null — 지속 결손
                elif rows and present <= rows / 2:
                    partial.append(f"{c}({present}/{rows})")
            detail["macro_rows_checked"] = rows
            if gone:
                detail["macro_missing"] = gone
                issues.append(f"매크로 지표 {len(gone)}종이 최근 {rows}행 내내 결손: {', '.join(gone)}")
            if partial:
                detail["macro_partial"] = partial

        # ── 3. 가격 커버리지 (유니버스 대비) ──
        # daily_prices 에는 유니버스 밖 심볼(벤치마크·헤지용 SH 등)도 들어 있다.
        # 전체 distinct 로 세면 비율이 1을 넘어 **결손이 있어도 절대 FAIL 하지 않는다** —
        # 반드시 유니버스에 속한 심볼만 센다.
        r = conn.execute("""
            SELECT (SELECT count(*) FROM swing_universe WHERE is_active) AS universe,
                   (SELECT count(*) FROM swing_universe u
                     WHERE u.is_active
                       AND EXISTS (SELECT 1 FROM daily_prices p
                                    WHERE p.symbol = u.symbol
                                      AND p.time > now() - interval '5 days')) AS covered,
                   (SELECT max(time)::date FROM daily_prices) AS newest_bar
        """).fetchone()
        uni, cov = int(r["universe"] or 0), int(r["covered"] or 0)
        detail["price_universe"] = uni
        detail["price_covered_5d"] = cov
        detail["price_newest_bar"] = str(r["newest_bar"]) if r["newest_bar"] else None
        if uni:
            ratio = cov / uni
            detail["price_coverage"] = round(ratio, 3)
            if ratio < min_cover:
                issues.append(f"가격 커버리지 {ratio:.1%} (하한 {min_cover:.0%}, {cov}/{uni})")
        # 최신 바 신선도 — 주말/공휴일을 감안해 넉넉히 잡는다(연휴 최대 4일)
        if r["newest_bar"]:
            bar_stale = (date.today() - r["newest_bar"]).days
            detail["price_stale_days"] = bar_stale
            if bar_stale > max_bar_stale:
                issues.append(f"가격 수집 중단 {bar_stale}일 (최신 바 {r['newest_bar']}, 허용 {max_bar_stale})")

        # ── 4. 소셜 수집 (일간 06:50 KST) ──
        r = conn.execute("""
            SELECT max(time) AS newest,
                   count(DISTINCT symbol) FILTER (WHERE time > now() - interval '2 days') AS syms
            FROM swing_social_sentiment
        """).fetchone()
        detail["social_newest"] = str(r["newest"].date()) if r["newest"] else None
        detail["social_symbols_2d"] = int(r["syms"] or 0)
        if r["newest"] is None:
            issues.append("소셜 수집 기록 없음")
        else:
            st = (date.today() - r["newest"].date()).days
            detail["social_stale_days"] = st
            if st > max_social_stale:
                issues.append(f"소셜 수집 중단 {st}일 (허용 {max_social_stale})")

        # ── 5. PEAD 수집 (주간 토 08:30 KST — 주기가 길어 허용치도 길다) ──
        r = conn.execute("""
            SELECT max(collected_at) AS newest,
                   count(DISTINCT symbol) FILTER (WHERE collected_at > now() - interval '30 days') AS syms
            FROM swing_earnings_surprises
        """).fetchone()
        detail["pead_newest"] = str(r["newest"].date()) if r["newest"] else None
        detail["pead_symbols_30d"] = int(r["syms"] or 0)
        if r["newest"] is None:
            issues.append("PEAD 수집 기록 없음")
        else:
            st = (date.today() - r["newest"].date()).days
            detail["pead_stale_days"] = st
            if st > max_pead_stale:
                issues.append(f"PEAD 수집 중단 {st}일 (허용 {max_pead_stale})")

        # ── 6. 시그널 팩터 입력 회귀 (뉴스감성·PEAD·LLM 등) ──
        # 결측 자체가 아니라 **'있다가 사라진' 것**만 잡는다.
        #   - 사장된 컬럼(tech_score: 213건 내내 0)은 조용해야 하고,
        #   - 새로 도입된 컬럼(pead_score: 14/60 → 30/30, 증가 중)도 경보 대상이 아니다.
        # 그래서 최근 구간과 직전 구간의 채움률을 비교한다 — 하드코딩 제외 목록은 낡는다.
        score_cols = [r["column_name"] for r in conn.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'swing_signals'
              AND data_type IN ('double precision', 'numeric', 'real', 'integer', 'bigint')
              AND (column_name LIKE '%%score%%' OR column_name LIKE '%%\\_rank')
            ORDER BY ordinal_position
        """).fetchall()]
        if score_cols:
            sel = ", ".join(f'count("{c}") AS "{c}"' for c in score_cols)
            cur = conn.execute(
                f"SELECT count(*) AS rows, {sel} FROM (SELECT * FROM swing_signals "
                f"WHERE signal_type='ENTRY' ORDER BY signal_id DESC LIMIT %s) t",
                (sig_win,)).fetchone()
            prev = conn.execute(
                f"SELECT count(*) AS rows, {sel} FROM (SELECT * FROM swing_signals "
                f"WHERE signal_type='ENTRY' ORDER BY signal_id DESC OFFSET %s LIMIT %s) t",
                (sig_win, sig_win * 2)).fetchone()
            cr, pr = int(cur["rows"] or 0), int(prev["rows"] or 0)
            detail["signal_rows"] = {"recent": cr, "prev": pr}
            lost = []
            if cr and pr:
                for c in score_cols:
                    c_rate = int(cur[c] or 0) / cr
                    p_rate = int(prev[c] or 0) / pr
                    if p_rate >= 0.5 and c_rate < 0.5:     # 채워지다가 끊긴 것만
                        lost.append(f"{c}({p_rate:.0%}→{c_rate:.0%})")
            if lost:
                detail["signal_inputs_lost"] = lost
                issues.append(f"시그널 팩터 입력 {len(lost)}종이 끊겼다: {', '.join(lost)}")

    detail["issues"] = issues
    detail["note"] = ("부분 결손(macro_partial)은 경보하지 않는다 — 복구 직후 구간이 여기 잡힌다. "
                      "시그널 입력은 '있다가 사라진' 것만 본다 — 사장된 컬럼과 신규 도입분을 구분하기 위해서다.")
    return _record(pg, "data_freshness", not issues, detail, CRITICAL)


CHECKS = [
    check_snapshot_identity,
    check_metric_range,
    check_equity_continuity,
    check_weight_consistency,
    check_factor_variance,
    check_backtest_identity,
    check_data_freshness,
]


def run_all(pg) -> dict[str, Any]:
    if pg.get_config_value("self_check_enabled", "true") != "true":
        return {"enabled": False}
    results = []
    for fn in CHECKS:
        try:
            results.append(fn(pg))
        except Exception as e:
            logger.exception(f"self_check {fn.__name__} failed: {e}")
            results.append({"check": fn.__name__, "status": "ERROR",
                            "severity": WARN, "detail": {"error": str(e)[:200]}})
    failed = [r for r in results if r["status"] != "PASS"]
    crit = [r for r in failed if r.get("severity") == CRITICAL]
    return {"results": results, "failed": len(failed), "critical": len(crit)}


def format_report(summary: dict[str, Any]) -> str:
    if not summary.get("enabled", True):
        return ""
    lines = ["<b>🩺 자가진단 (계측 버그)</b>"]
    for r in summary.get("results", []):
        icon = "✅" if r["status"] == "PASS" else ("🔴" if r.get("severity") == CRITICAL else "⚠️")
        lines.append(f"  {icon} {r['check']}: {r['status']}")
        if r["status"] != "PASS":
            d = r.get("detail", {})
            for k in ("issues", "violations", "inert", "error"):
                if d.get(k):
                    lines.append(f"     {k}: {str(d[k])[:160]}")
    if summary.get("critical"):
        lines.append(f"\n🔴 <b>치명 위반 {summary['critical']}건 — 즉시 확인 필요</b>")
    return "\n".join(lines)
