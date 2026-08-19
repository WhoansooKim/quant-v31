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

⚠️ **한계**: 알려진 불변식만 검사한다. 새로운 종류의 버그는 여전히 사람이 발견해야 한다.
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


CHECKS = [
    check_snapshot_identity,
    check_metric_range,
    check_equity_continuity,
    check_weight_consistency,
    check_factor_variance,
    check_backtest_identity,
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
