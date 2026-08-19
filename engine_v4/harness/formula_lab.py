"""3J 후속: 수식 신호 자동 검증 파이프라인 (§22.AO-22).

`swing_signal_formulas` 의 pending 수식을 **daily_prices 전량**으로 평가해
횡단면 IC 를 시계열 분할로 측정하고, **양쪽 구간 모두 기준을 넘을 때만** 승격한다.

2026-08-19 ④에서 손으로 한 절차(10종 중 9종 기각)를 그대로 자동화한 것이다.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from engine_v4.harness.knowledge import log_action
from engine_v4.harness.signal_dsl import FormulaError, evaluate, validate

logger = logging.getLogger(__name__)


def _load_prices(pg, symbols: list[str], start: str) -> pd.DataFrame:
    with pg.get_conn() as conn:
        rows = conn.execute("""
            SELECT time::date AS d, symbol, open, high, low, close, volume
            FROM daily_prices WHERE symbol = ANY(%s) AND time >= %s
            ORDER BY symbol, time
        """, (symbols, start)).fetchall()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["d"] = pd.to_datetime(df["d"])
    return df.dropna(subset=["close"]).sort_values(["symbol", "d"])


def _xs_ic(sub: pd.DataFrame, horizon: int, min_names: int = 30) -> tuple[float | None, int]:
    """일자별 횡단면 순위상관의 평균."""
    ics = []
    for _, g in sub.groupby("d"):
        gg = g[["sig", f"fwd{horizon}"]].dropna()
        if len(gg) < min_names:
            continue
        ics.append(gg["sig"].rank().corr(gg[f"fwd{horizon}"].rank()))
    return (float(np.nanmean(ics)) if ics else None), len(ics)


def validate_formula(pg, formula_id: int, prices: pd.DataFrame | None = None,
                     horizon: int | None = None) -> dict[str, Any]:
    cfg = pg.get_config_value
    horizon = horizon or int(float(cfg("formula_horizon", "10")))
    split = pd.Timestamp(cfg("formula_split_date", "2022-01-01"))
    ic_min = float(cfg("formula_ic_min", "0.02"))
    start = cfg("formula_start_date", "2016-01-01")

    with pg.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM swing_signal_formulas WHERE formula_id = %s", (formula_id,)).fetchone()
    if not row:
        return {"error": "not_found"}

    expr = row["expression"]
    try:
        validate(expr)
    except FormulaError as e:
        _reject(pg, formula_id, f"수식 거부: {e}")
        return {"formula_id": formula_id, "status": "rejected", "reason": str(e)}

    if prices is None:
        symbols = [u["symbol"] for u in pg.get_universe()]
        prices = _load_prices(pg, symbols, start)
    if prices.empty:
        return {"formula_id": formula_id, "status": "pending", "reason": "no_price_data"}

    def per_sym(g: pd.DataFrame) -> pd.DataFrame:
        out = pd.DataFrame(index=g.index)
        try:
            out["sig"] = evaluate(expr, g)
        except Exception:
            out["sig"] = np.nan
        c = g["close"].astype(float)
        out[f"fwd{horizon}"] = c.shift(-horizon) / c - 1
        out["d"] = g["d"].values
        return out

    feat = prices.groupby("symbol", group_keys=False).apply(per_sym, include_groups=False) \
        if pd.__version__ >= "2.2" else prices.groupby("symbol", group_keys=False).apply(per_sym)
    feat = feat.replace([np.inf, -np.inf], np.nan)
    feat = feat[feat["d"].dt.dayofweek == 2]          # 주간 횡단면 (중복 표본 축소)

    ic_tr, n_tr = _xs_ic(feat[feat["d"] < split], horizon)
    ic_te, n_te = _xs_ic(feat[feat["d"] >= split], horizon)

    if ic_tr is None or ic_te is None:
        _reject(pg, formula_id, f"표본 부족 (학습 {n_tr}일 / 검증 {n_te}일)")
        return {"formula_id": formula_id, "status": "rejected", "reason": "insufficient"}

    ic_lo = min(ic_tr, ic_te)
    ok = ic_lo >= ic_min          # 양쪽 구간 모두 기준 통과해야 승격
    reason = None if ok else (
        f"학습 {ic_tr:+.4f} / 검증 {ic_te:+.4f} — 최솟값 {ic_lo:+.4f} < 기준 {ic_min:+.3f}")

    with pg.get_conn() as conn:
        conn.execute("""
            UPDATE swing_signal_formulas
               SET status = %s, ic_train = %s, ic_test = %s, ic_min = %s,
                   n_days_train = %s, n_days_test = %s, horizon_days = %s,
                   rejection_reason = %s, validated_at = now()
             WHERE formula_id = %s
        """, ("validated" if ok else "rejected", round(ic_tr, 4), round(ic_te, 4),
              round(ic_lo, 4), n_tr, n_te, horizon, reason, formula_id))
        conn.commit()

    result = {"formula_id": formula_id, "name": row["name"],
              "status": "validated" if ok else "rejected",
              "ic_train": round(ic_tr, 4), "ic_test": round(ic_te, 4),
              "ic_min": round(ic_lo, 4), "n_days": [n_tr, n_te], "reason": reason}
    log_action(pg, "formula_validate", "completed", details=result)
    return result


def _reject(pg, formula_id: int, reason: str) -> None:
    with pg.get_conn() as conn:
        conn.execute("UPDATE swing_signal_formulas SET status='rejected', "
                     "rejection_reason=%s, validated_at=now() WHERE formula_id=%s",
                     (reason, formula_id))
        conn.commit()


def validate_all_pending(pg, max_per_run: int = 10) -> dict[str, Any]:
    """pending 수식 일괄 검증. 가격 데이터는 한 번만 읽어 재사용한다."""
    if pg.get_config_value("formula_lab_enabled", "true") != "true":
        return {"enabled": False}
    with pg.get_conn() as conn:
        ids = [r["formula_id"] for r in conn.execute(
            "SELECT formula_id FROM swing_signal_formulas WHERE status='pending' "
            "ORDER BY created_at LIMIT %s", (max_per_run,)).fetchall()]
    if not ids:
        return {"checked": 0}

    symbols = [u["symbol"] for u in pg.get_universe()]
    prices = _load_prices(pg, symbols, pg.get_config_value("formula_start_date", "2016-01-01"))
    results = [validate_formula(pg, fid, prices) for fid in ids]
    v = sum(1 for r in results if r.get("status") == "validated")
    return {"checked": len(results), "validated": v,
            "rejected": len(results) - v, "results": results}


def format_report(summary: dict[str, Any]) -> str:
    if not summary.get("enabled", True) or not summary.get("checked"):
        return ""
    lines = [f"<b>🧬 수식 신호 검증</b> ({summary['checked']}건 "
             f"→ 승격 {summary.get('validated', 0)} / 기각 {summary.get('rejected', 0)})"]
    for r in summary.get("results", [])[:8]:
        icon = "✅" if r.get("status") == "validated" else "❌"
        lines.append(f"  {icon} {r.get('name', r['formula_id'])}: "
                     f"학습 {r.get('ic_train')} / 검증 {r.get('ic_test')}")
    return "\n".join(lines)
