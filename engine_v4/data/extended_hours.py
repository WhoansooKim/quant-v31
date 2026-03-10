"""Extended Hours Data — Pre-market / After-hours price & volume fetcher.

Uses yfinance Ticker.info for pre/post market data.
US Market Hours (ET → KST):
  Pre-market:  04:00–09:30 ET = 18:00–23:30 KST
  Regular:     09:30–16:00 ET = 23:30–06:00 KST
  After-hours: 16:00–20:00 ET = 06:00–10:00 KST
"""

import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import yfinance as yf

logger = logging.getLogger(__name__)


def fetch_extended_hours(symbols: list[str]) -> list[dict]:
    """Fetch pre-market and after-hours data for given symbols.

    Returns list of dicts with keys:
      symbol, regular_close, pre_price, pre_change_pct, post_price, post_change_pct,
      gap_pct, regular_volume, session ('pre'|'post'|'regular')
    """
    results = []

    def _fetch_one(sym: str) -> dict | None:
        try:
            t = yf.Ticker(sym)
            info = t.info
            regular_close = info.get("regularMarketPreviousClose") or info.get("previousClose") or 0
            regular_price = info.get("regularMarketPrice") or 0
            regular_vol = info.get("regularMarketVolume") or 0
            market_state = info.get("marketState", "")  # PRE, REGULAR, POST, CLOSED

            pre_price = info.get("preMarketPrice")
            pre_change = info.get("preMarketChangePercent")
            post_price = info.get("postMarketPrice")
            post_change = info.get("postMarketChangePercent")

            # Determine session and gap
            if market_state in ("PRE", "PREPRE") and pre_price:
                session = "pre"
                gap_pct = ((pre_price - regular_close) / regular_close * 100) if regular_close else 0
            elif market_state in ("POST", "POSTPOST") and post_price:
                session = "post"
                gap_pct = ((post_price - regular_price) / regular_price * 100) if regular_price else 0
            elif market_state == "CLOSED":
                # After all extended hours — use post if available
                session = "post" if post_price else "closed"
                if post_price and regular_price:
                    gap_pct = ((post_price - regular_price) / regular_price * 100)
                else:
                    gap_pct = 0
            else:
                session = "regular"
                gap_pct = ((regular_price - regular_close) / regular_close * 100) if regular_close else 0

            return {
                "symbol": sym,
                "regular_close": round(regular_close, 2),
                "regular_price": round(regular_price, 2),
                "regular_volume": regular_vol,
                "pre_price": round(pre_price, 2) if pre_price else None,
                "pre_change_pct": round(pre_change * 100, 2) if pre_change else None,
                "post_price": round(post_price, 2) if post_price else None,
                "post_change_pct": round(post_change * 100, 2) if post_change else None,
                "gap_pct": round(gap_pct, 2),
                "session": session,
                "market_state": market_state,
            }
        except Exception as e:
            logger.warning(f"Extended hours fetch failed for {sym}: {e}")
            return None

    # Parallel fetch (max 8 threads to avoid rate limits)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_one, s): s for s in symbols}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)

    return sorted(results, key=lambda x: x["symbol"])
