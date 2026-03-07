"""FinnhubClient — Finnhub API 데이터 수집 (뉴스/실적/내부자/기관).

무료 tier: 60 calls/min. 각 메서드는 rate limit을 고려하여 설계.
API 키 없으면 빈 결과 반환 (graceful degradation).
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# Finnhub free tier: 60 calls/min
_RATE_LIMIT_DELAY = 1.1  # seconds between calls


class FinnhubClient:
    """Finnhub REST API wrapper."""

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key
        self._last_call = 0.0

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def _get(self, endpoint: str, params: dict | None = None) -> dict | list | None:
        """Rate-limited GET request."""
        if not self.api_key:
            return None

        # Rate limiting
        elapsed = time.time() - self._last_call
        if elapsed < _RATE_LIMIT_DELAY:
            time.sleep(_RATE_LIMIT_DELAY - elapsed)

        params = params or {}
        params["token"] = self.api_key

        try:
            resp = requests.get(
                f"{self.BASE_URL}/{endpoint}",
                params=params,
                timeout=10,
            )
            self._last_call = time.time()

            if resp.status_code == 429:
                logger.warning("Finnhub rate limit hit, waiting 60s")
                time.sleep(60)
                return self._get(endpoint, params)

            if resp.status_code != 200:
                logger.warning(f"Finnhub {endpoint}: HTTP {resp.status_code}")
                return None

            return resp.json()
        except Exception as e:
            logger.error(f"Finnhub {endpoint} failed: {e}")
            return None

    # ─── Company News ────────────────────────────────────

    def get_company_news(self, symbol: str, days: int = 7) -> list[dict]:
        """최근 뉴스 조회. Returns list of {headline, summary, source, datetime, url}."""
        to_date = date.today()
        from_date = to_date - timedelta(days=days)

        data = self._get("company-news", {
            "symbol": symbol,
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        })

        if not data or not isinstance(data, list):
            return []

        results = []
        for item in data[:10]:  # max 10 articles
            results.append({
                "headline": item.get("headline", ""),
                "summary": item.get("summary", "")[:300],
                "source": item.get("source", ""),
                "datetime": datetime.fromtimestamp(item.get("datetime", 0)).isoformat()
                    if item.get("datetime") else "",
                "url": item.get("url", ""),
                "category": item.get("category", ""),
            })
        return results

    # ─── Insider Transactions ────────────────────────────

    def get_insider_transactions(self, symbol: str) -> dict:
        """내부자 거래 요약. Returns {total_buys, total_sells, net_shares, transactions}."""
        data = self._get("stock/insider-transactions", {"symbol": symbol})

        if not data or not isinstance(data, dict):
            return {"total_buys": 0, "total_sells": 0, "net_shares": 0, "transactions": []}

        txns = data.get("data", [])
        recent = txns[:20]  # last 20 transactions

        total_buys = 0
        total_sells = 0
        for t in recent:
            change = t.get("change", 0) or 0
            if change > 0:
                total_buys += change
            else:
                total_sells += abs(change)

        return {
            "total_buys": total_buys,
            "total_sells": total_sells,
            "net_shares": total_buys - total_sells,
            "transaction_count": len(recent),
            "transactions": [
                {
                    "name": t.get("name", ""),
                    "share": t.get("share", 0),
                    "change": t.get("change", 0),
                    "filing_date": t.get("filingDate", ""),
                    "transaction_code": t.get("transactionCode", ""),
                }
                for t in recent[:5]
            ],
        }

    # ─── Earnings Calendar ───────────────────────────────

    def get_upcoming_earnings(self, symbol: str) -> dict | None:
        """다음 실적 발표일 조회. Returns {date, estimate, quarter} or None."""
        from_date = date.today()
        to_date = from_date + timedelta(days=30)

        data = self._get("calendar/earnings", {
            "symbol": symbol,
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        })

        if not data or not isinstance(data, dict):
            return None

        earnings = data.get("earningsCalendar", [])
        for e in earnings:
            if e.get("symbol") == symbol:
                return {
                    "date": e.get("date", ""),
                    "estimate": e.get("epsEstimate"),
                    "quarter": e.get("quarter"),
                    "year": e.get("year"),
                    "days_until": (
                        datetime.strptime(e["date"], "%Y-%m-%d").date() - date.today()
                    ).days if e.get("date") else None,
                }
        return None

    # ─── Basic Financials (for institutional data proxy) ─

    def get_basic_financials(self, symbol: str) -> dict:
        """기본 재무 지표 (institutional proxy). Returns key metrics."""
        data = self._get("stock/metric", {
            "symbol": symbol,
            "metric": "all",
        })

        if not data or not isinstance(data, dict):
            return {}

        metric = data.get("metric", {})
        return {
            "pe_ratio": metric.get("peNormalizedAnnual"),
            "pb_ratio": metric.get("pbAnnual"),
            "dividend_yield": metric.get("dividendYieldIndicatedAnnual"),
            "beta": metric.get("beta"),
            "52w_high": metric.get("52WeekHigh"),
            "52w_low": metric.get("52WeekLow"),
            "52w_high_date": metric.get("52WeekHighDate"),
            "revenue_growth_3y": metric.get("revenueGrowth3Y"),
            "eps_growth_3y": metric.get("epsGrowth3Y"),
            "net_margin": metric.get("netMarginTTM"),
            "roe": metric.get("roeTTM"),
        }

    # ─── Recommendation Trends ───────────────────────────

    def get_recommendation_trends(self, symbol: str) -> dict:
        """애널리스트 추천 트렌드. Returns {buy, hold, sell, strongBuy, strongSell, period}."""
        data = self._get("stock/recommendation", {"symbol": symbol})

        if not data or not isinstance(data, list) or len(data) == 0:
            return {"buy": 0, "hold": 0, "sell": 0, "strong_buy": 0, "strong_sell": 0}

        latest = data[0]
        return {
            "buy": latest.get("buy", 0),
            "hold": latest.get("hold", 0),
            "sell": latest.get("sell", 0),
            "strong_buy": latest.get("strongBuy", 0),
            "strong_sell": latest.get("strongSell", 0),
            "period": latest.get("period", ""),
        }

    # ─── Batch: All data for a symbol ────────────────────

    def get_all_data(self, symbol: str) -> dict:
        """한 종목에 대한 전체 데이터 수집 (4 API calls).

        Returns: {news, insider, earnings, financials, recommendations}
        """
        news = self.get_company_news(symbol)
        insider = self.get_insider_transactions(symbol)
        earnings = self.get_upcoming_earnings(symbol)
        recommendations = self.get_recommendation_trends(symbol)

        return {
            "symbol": symbol,
            "news": news,
            "insider": insider,
            "earnings": earnings,
            "recommendations": recommendations,
            "fetched_at": datetime.now().isoformat(),
        }
