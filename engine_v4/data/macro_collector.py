"""MacroDataCollector — yfinance 기반 매크로 지표 수집 + Redis 캐시.

수집 지표: VIX, 10Y 금리, 달러인덱스, 금, 구리, BTC, HY 스프레드, SPY
파생 비율: Gold/SPY, Copper/Gold, HY Spread (LQD/HYG), 20d 모멘텀
"""

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# yfinance 티커 매핑
MACRO_TICKERS = {
    "vix": "^VIX",
    "tnx": "^TNX",         # 10Y Treasury yield (×10 스케일)
    "dxy": "DX=F",          # US Dollar Index Futures
    "gold": "GC=F",        # Gold futures
    "copper": "HG=F",      # Copper futures
    "btc": "BTC-USD",      # Bitcoin
    "hyg": "HYG",          # High Yield Bond ETF
    "lqd": "LQD",          # Investment Grade Bond ETF
    "spy": "SPY",           # S&P 500 ETF
}


class MacroDataCollector:
    """매크로 지표 수집기 — yfinance 배치 다운로드 + Redis 1일 캐시."""

    CACHE_KEY = "macro_data"
    CACHE_TTL = 86400  # 24시간

    def __init__(self, cache):
        self.cache = cache

    def collect_macro_data(self, force: bool = False) -> dict:
        """매크로 지표 수집. Redis 캐시 활용 (force=True면 강제 갱신).

        Returns:
            {vix, tnx, dxy, gold, copper, btc, spy, hyg, lqd,
             hy_spread, gold_spy_ratio, copper_gold_ratio,
             btc_momentum_20d, dxy_momentum_20d, vix_sma_20,
             collected_at}
        """
        if not force and self.cache:
            cached = self.cache.get_json(self.CACHE_KEY)
            if cached:
                logger.info("Macro data from cache")
                return cached

        import yfinance as yf

        ticker_list = list(MACRO_TICKERS.values())
        logger.info(f"Downloading macro data: {len(ticker_list)} tickers")

        try:
            df = yf.download(
                ticker_list,
                period="60d",
                interval="1d",
                progress=False,
                threads=True,
            )
        except Exception as e:
            logger.error(f"yfinance macro download failed: {e}")
            return self._default_result("download_failed")

        if df.empty:
            logger.warning("Macro download returned empty dataframe")
            return self._default_result("empty_data")

        result = {}

        # 각 티커별 최신 종가 + 20일 전 종가 추출
        for name, ticker in MACRO_TICKERS.items():
            try:
                if len(MACRO_TICKERS) > 1 and ("Close", ticker) in df.columns:
                    series = df[("Close", ticker)].dropna()
                elif "Close" in df.columns:
                    series = df["Close"].dropna()
                else:
                    series = None

                if series is not None and len(series) >= 2:
                    result[name] = round(float(series.iloc[-1]), 4)
                    if len(series) >= 20:
                        result[f"{name}_20d_ago"] = round(float(series.iloc[-20]), 4)
                    else:
                        result[f"{name}_20d_ago"] = round(float(series.iloc[0]), 4)

                    # VIX SMA-20
                    if name == "vix" and len(series) >= 20:
                        result["vix_sma_20"] = round(float(series.tail(20).mean()), 2)
                    elif name == "vix":
                        result["vix_sma_20"] = result.get("vix", 20)
                else:
                    result[name] = None
                    result[f"{name}_20d_ago"] = None
            except Exception as e:
                logger.warning(f"Macro ticker {name} ({ticker}) failed: {e}")
                result[name] = None
                result[f"{name}_20d_ago"] = None

        # 파생 비율 계산
        result["gold_spy_ratio"] = self._safe_ratio(result.get("gold"), result.get("spy"))
        result["copper_gold_ratio"] = self._safe_ratio(result.get("copper"), result.get("gold"))

        # HY Spread proxy: LQD/HYG 비율 (높을수록 스프레드 확대 = risk-off)
        result["hy_spread"] = self._safe_ratio(result.get("lqd"), result.get("hyg"))

        # Gold/SPY 비율 20일 전 (방향 감지용)
        result["gold_spy_ratio_20d"] = self._safe_ratio(
            result.get("gold_20d_ago"), result.get("spy_20d_ago"))

        # 모멘텀 (20일 수익률 %)
        result["btc_momentum_20d"] = self._safe_return(
            result.get("btc"), result.get("btc_20d_ago"))
        result["dxy_momentum_20d"] = self._safe_return(
            result.get("dxy"), result.get("dxy_20d_ago"))
        result["vix_momentum_20d"] = self._safe_return(
            result.get("vix"), result.get("vix_20d_ago"))

        # TNX: yfinance ^TNX는 이미 % 단위 (e.g., 4.28 = 4.28%)
        if result.get("tnx") is not None:
            result["yield_10y"] = round(result["tnx"], 3)
        else:
            result["yield_10y"] = None

        result["collected_at"] = datetime.now().isoformat()
        result["status"] = "ok"

        # Redis 캐시 저장
        if self.cache:
            self.cache.set_json(self.CACHE_KEY, result, ttl=self.CACHE_TTL)
            logger.info("Macro data cached (TTL=24h)")

        logger.info(f"Macro collect done: VIX={result.get('vix')}, "
                     f"10Y={result.get('yield_10y')}%, DXY={result.get('dxy')}, "
                     f"Gold/SPY={result.get('gold_spy_ratio')}, "
                     f"Cu/Au={result.get('copper_gold_ratio')}")

        return result

    @staticmethod
    def _safe_ratio(a, b) -> float | None:
        if a is not None and b is not None and b != 0:
            return round(float(a) / float(b), 6)
        return None

    @staticmethod
    def _safe_return(current, past) -> float | None:
        if current is not None and past is not None and past != 0:
            return round((float(current) / float(past) - 1) * 100, 2)
        return None

    @staticmethod
    def _default_result(reason: str) -> dict:
        return {
            "status": reason,
            "vix": None, "tnx": None, "dxy": None,
            "gold": None, "copper": None, "btc": None,
            "spy": None, "hyg": None, "lqd": None,
            "gold_spy_ratio": None, "copper_gold_ratio": None,
            "hy_spread": None, "yield_10y": None,
            "btc_momentum_20d": None, "dxy_momentum_20d": None,
            "vix_sma_20": None,
            "collected_at": datetime.now().isoformat(),
        }
