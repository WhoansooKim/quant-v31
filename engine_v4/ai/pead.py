"""③ PEAD — 실적 서프라이즈 드리프트 (§22.AO-14).

근거: Kaczmarek & Zaremba, *Beyond the last surprise* (Finance Research Letters 2025-10).
  - SUE 를 1분기가 아닌 **다분기 이력**으로 쓰면 Sharpe 가 거의 2배
  - **대형주에서 최강** — 최근 서프라이즈는 즉시 반영되나 과거 패턴은 간과된다
  - 드리프트는 애널리스트 상향이 **2~4주** 순차 반영되며 발생 → 스윙 5~15일과 정합

데이터 제약: Finnhub 무료 티어는 `stock/earnings` 4분기 + `calendar/earnings` 최근 1건뿐이라
논문의 12분기를 바로 쓸 수 없다. 그래서 **수집분을 DB 에 누적**해 시간이 지나며 이력을 쌓는다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class PeadScorer:
    """실적 서프라이즈 수집 + 드리프트 점수 산출."""

    def __init__(self, pg, finnhub):
        self.pg = pg
        self.finnhub = finnhub

    # ─── 수집 ────────────────────────────────────────────

    def collect_symbol(self, symbol: str) -> int:
        """한 종목의 서프라이즈 이력을 upsert. 반환: 저장 건수.

        stock/earnings 로 분기별 서프라이즈(발표일 없음)를,
        calendar/earnings 로 최근 발표일을 받아 합친다.
        """
        rows = self.finnhub._get("stock/earnings", {"symbol": symbol}) or []
        if not isinstance(rows, list):
            return 0

        # 최근 발표일 (드리프트 기산점)
        announce: dict[tuple[int, int], date] = {}
        try:
            today = date.today()
            cal = self.finnhub._get("calendar/earnings", {
                "symbol": symbol,
                "from": (today - timedelta(days=120)).isoformat(),
                "to": today.isoformat(),
            }) or {}
            for e in (cal.get("earningsCalendar") or []):
                if e.get("date") and e.get("year") and e.get("quarter"):
                    announce[(int(e["year"]), int(e["quarter"]))] = \
                        datetime.strptime(e["date"], "%Y-%m-%d").date()
        except Exception as e:
            logger.debug(f"{symbol} calendar fetch failed: {e}")

        saved = 0
        with self.pg.get_conn() as conn:
            for r in rows:
                try:
                    y, q = int(r["year"]), int(r["quarter"])
                except (KeyError, TypeError, ValueError):
                    continue
                period = r.get("period")
                period_end = None
                if period:
                    try:
                        period_end = datetime.strptime(period, "%Y-%m-%d").date()
                    except ValueError:
                        pass
                conn.execute("""
                    INSERT INTO swing_earnings_surprises
                        (symbol, fiscal_year, fiscal_quarter, period_end, announce_date,
                         eps_actual, eps_estimate, surprise_pct, collected_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
                    ON CONFLICT (symbol, fiscal_year, fiscal_quarter) DO UPDATE SET
                        period_end   = COALESCE(EXCLUDED.period_end, swing_earnings_surprises.period_end),
                        announce_date= COALESCE(EXCLUDED.announce_date, swing_earnings_surprises.announce_date),
                        eps_actual   = COALESCE(EXCLUDED.eps_actual, swing_earnings_surprises.eps_actual),
                        eps_estimate = COALESCE(EXCLUDED.eps_estimate, swing_earnings_surprises.eps_estimate),
                        surprise_pct = COALESCE(EXCLUDED.surprise_pct, swing_earnings_surprises.surprise_pct)
                """, (symbol, y, q, period_end, announce.get((y, q)),
                      r.get("actual"), r.get("estimate"), r.get("surprisePercent")))
                saved += 1
            conn.commit()
        return saved

    def collect_universe(self, symbols: list[str]) -> dict[str, Any]:
        ok = failed = total = 0
        for sym in symbols:
            try:
                total += self.collect_symbol(sym)
                ok += 1
            except Exception as e:
                failed += 1
                logger.warning(f"PEAD collect failed for {sym}: {e}")
        return {"symbols_ok": ok, "symbols_failed": failed, "rows": total}

    # ─── 점수 ────────────────────────────────────────────

    def score(self, symbol: str, as_of: date | None = None) -> dict[str, Any]:
        """PEAD 점수 0-100. 50 = 중립(드리프트 창 밖 또는 데이터 없음)."""
        as_of = as_of or date.today()
        cfg = self.pg.get_config_value
        if cfg("pead_enabled", "true") != "true":
            return {"score": 50.0, "signal": "DISABLED"}

        drift_days = int(float(cfg("pead_drift_days", "30")))
        min_sup = float(cfg("pead_min_surprise_pct", "2.0"))
        hist_w = float(cfg("pead_history_weight", "0.4"))

        with self.pg.get_conn() as conn:
            rows = conn.execute("""
                SELECT fiscal_year, fiscal_quarter, announce_date, period_end, surprise_pct
                FROM swing_earnings_surprises
                WHERE symbol = %s AND surprise_pct IS NOT NULL
                ORDER BY fiscal_year DESC, fiscal_quarter DESC
                LIMIT 12
            """, (symbol,)).fetchall()

        if not rows:
            return {"score": 50.0, "signal": "NO_DATA", "quarters": 0}

        latest = rows[0]
        sup = float(latest["surprise_pct"])

        # 드리프트 창: 발표일이 있으면 그 기준, 없으면 분기말+35일로 근사
        ref = latest["announce_date"] or (
            latest["period_end"] + timedelta(days=35) if latest["period_end"] else None)
        days_since = (as_of - ref).days if ref else None
        in_window = days_since is not None and 0 <= days_since <= drift_days

        # 다분기 패턴 — 논문 핵심: 과거 서프라이즈 이력이 예측력을 크게 높인다
        hist = [float(r["surprise_pct"]) for r in rows[1:]]
        hist_mean = sum(hist) / len(hist) if hist else 0.0

        if not in_window or abs(sup) < min_sup:
            signal = "NONE" if not in_window else "WEAK"
            return {"score": 50.0, "signal": signal, "surprise_pct": round(sup, 2),
                    "days_since": days_since, "quarters": len(rows),
                    "hist_mean_pct": round(hist_mean, 2)}

        # 서프라이즈 크기를 ±20% 에서 포화시켜 0-100 으로 사상
        def to_score(pct: float) -> float:
            return 50.0 + 50.0 * max(-1.0, min(1.0, pct / 20.0))

        blended = (1 - hist_w) * to_score(sup) + hist_w * to_score(hist_mean)
        # 드리프트는 시간이 갈수록 소진 → 창 후반부일수록 중립으로 감쇠
        decay = 1.0 - (days_since / drift_days) * 0.5
        score = 50.0 + (blended - 50.0) * decay

        return {
            "score": round(max(0.0, min(100.0, score)), 1),
            "signal": "POSITIVE_DRIFT" if sup > 0 else "NEGATIVE_DRIFT",
            "surprise_pct": round(sup, 2),
            "hist_mean_pct": round(hist_mean, 2),
            "days_since": days_since,
            "quarters": len(rows),
            "decay": round(decay, 2),
        }
