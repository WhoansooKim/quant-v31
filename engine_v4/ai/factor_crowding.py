"""FactorCrowdingMonitor — 팩터 크라우딩 모니터.

ETF 보유 종목과 포트폴리오/시그널 중복도를 추적하여
팩터 크라우딩 리스크를 감지한다.

지원 팩터 ETF:
  - MTUM (Momentum), QUAL (Quality), VLUE (Value)
  - USMV (Low Volatility), VUG (Growth)

ETF 보유 종목은 Redis 캐시에 저장 (7일 TTL).
yfinance로 가져오되, 실패 시 정적 시드 리스트 사용.
"""

from __future__ import annotations

import logging
from datetime import datetime

import yfinance as yf

from engine_v4.data.storage import PostgresStore, RedisCache

logger = logging.getLogger(__name__)

# ── 팩터 ETF 정의 ──
FACTOR_ETFS = {
    "momentum": "MTUM",   # iShares MSCI USA Momentum
    "quality": "QUAL",     # iShares MSCI USA Quality
    "value": "VLUE",       # iShares MSCI USA Value
    "low_vol": "USMV",     # iShares MSCI USA Min Vol
    "growth": "VUG",       # Vanguard Growth
}

# ── 정적 시드 리스트 (yfinance 실패 시 폴백) ──
# 각 ETF의 상위 보유 종목 (2025-Q4 기준, 공개 자료)
SEED_HOLDINGS: dict[str, list[str]] = {
    "MTUM": [
        "NVDA", "META", "MSFT", "AAPL", "AVGO", "LLY", "AMZN", "GOOGL",
        "COST", "NFLX", "GE", "JPM", "UBER", "ISRG", "CRM", "TMUS",
        "NOW", "TJX", "BK", "VST", "GEV", "ANET", "APP", "PLTR",
        "BSX", "WMT", "HWM", "AXON", "DECK", "GDDY", "SN", "SPOT",
        "IBKR", "HOOD", "EME", "WDAY", "FICO", "COIN", "CRWD", "RCL",
        "MRVL", "VRT", "LEN", "PANW", "TTWO", "TPL", "ABNB", "DASH",
        "DUOL", "EQT",
    ],
    "QUAL": [
        "MSFT", "AAPL", "NVDA", "META", "GOOGL", "AMZN", "LLY", "AVGO",
        "JPM", "V", "MA", "UNH", "HD", "JNJ", "PG", "COST", "ABBV",
        "MRK", "KO", "PEP", "ACN", "TMO", "ADBE", "CRM", "MCD",
        "TXN", "PM", "IBM", "ISRG", "GE", "INTU", "CAT", "AMAT",
        "NOW", "AXP", "LRCX", "TJX", "BKNG", "BLK", "KLAC", "SYK",
        "MMC", "CB", "CME", "AON", "ITW", "CTAS", "MSI", "ORLY",
        "MCHP",
    ],
    "VLUE": [
        "AAPL", "JPM", "BAC", "WFC", "INTC", "C", "CVX", "PFE",
        "CSCO", "CMCSA", "VZ", "BMY", "MO", "T", "GM", "F", "USB",
        "GS", "MS", "COF", "KEY", "RF", "HBAN", "CFG", "FITB",
        "AIG", "MET", "PRU", "ALL", "TFC", "ZION", "CMA", "MTB",
        "WBA", "KHC", "NEM", "FCX", "DVN", "OXY", "HAL", "SLB",
        "BKR", "EOG", "MPC", "VLO", "PSX", "PXD", "FANG", "COP",
        "XOM", "PARA",
    ],
    "USMV": [
        "MSFT", "AAPL", "BRK-B", "JPM", "V", "MA", "JNJ", "PG",
        "KO", "PEP", "MCD", "WMT", "COST", "ACN", "TXN", "IBM",
        "LIN", "WM", "RSG", "DUK", "SO", "NEE", "AEP", "D", "SRE",
        "ED", "XEL", "WEC", "CMS", "EVRG", "ATO", "NI", "PNW",
        "AES", "PPL", "AWK", "OTIS", "ITW", "PAYX", "CTAS",
        "ADP", "CME", "ICE", "MMC", "AON", "TRV", "CB", "ALL",
        "GIS", "SJM",
    ],
    "VUG": [
        "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG",
        "LLY", "AVGO", "TSLA", "V", "MA", "UNH", "COST", "HD",
        "NFLX", "CRM", "ADBE", "ACN", "TMO", "NOW", "ISRG", "INTU",
        "BKNG", "TXN", "AMD", "LRCX", "AMAT", "KLAC", "SNPS", "CDNS",
        "PANW", "CRWD", "MRVL", "SYK", "BSX", "EW", "DXCM", "ZTS",
        "IDXX", "VEEV", "MELI", "ORLY", "AZO", "ROST", "TJX", "DECK",
        "LULU", "MNST",
    ],
}

# ── 크라우딩 리스크 임계값 ──
CROWDING_THRESHOLDS = {
    "high": 0.60,     # 60% 이상 ETF 중복 → 높은 크라우딩
    "moderate": 0.35,  # 35% 이상 → 중간 크라우딩
    "low": 0.0,        # 그 이하 → 낮은 크라우딩
}

# Redis 캐시 TTL: 7일
ETF_CACHE_TTL = 7 * 24 * 3600


class FactorCrowdingMonitor:
    """팩터 크라우딩 모니터 — ETF 보유 종목 중복도 추적."""

    def __init__(self, pg: PostgresStore, cache: RedisCache):
        self.pg = pg
        self.cache = cache

    # ─── ETF 보유 종목 로드/갱신 ───────────────────────────

    def _get_holdings(self, factor: str, etf_symbol: str) -> list[str]:
        """Redis 캐시에서 ETF 보유 종목 조회. 없으면 시드 리스트 반환."""
        cache_key = f"etf_holdings:{etf_symbol}"
        cached = self.cache.get_json(cache_key)
        if cached:
            return cached
        # 캐시 없으면 시드 리스트 저장 후 반환
        seed = SEED_HOLDINGS.get(etf_symbol, [])
        if seed:
            self.cache.set_json(cache_key, seed, ttl=ETF_CACHE_TTL)
        return seed

    def refresh_etf_holdings(self) -> dict[str, dict]:
        """모든 팩터 ETF 보유 종목 갱신.

        yfinance에서 가져오기 시도 → 실패 시 정적 시드 리스트 사용.
        Returns: {factor: {etf, count, source, updated}} 딕셔너리.
        """
        results = {}
        for factor, etf_symbol in FACTOR_ETFS.items():
            holdings = []
            source = "seed"

            # 1) yfinance 시도 — Ticker의 여러 메서드로 보유 종목 추출
            try:
                ticker = yf.Ticker(etf_symbol)

                # 방법 1: top_holdings / holdings 속성 (yfinance 0.2.31+)
                if hasattr(ticker, "major_holders"):
                    try:
                        inst = ticker.institutional_holders
                        if inst is not None and not inst.empty:
                            # institutional_holders는 기관 보유자 목록이라 용도가 다름
                            pass
                    except Exception:
                        pass

                # 방법 2: funds_data에서 보유 종목 추출
                try:
                    if hasattr(ticker, "funds_data"):
                        fd = ticker.funds_data
                        if hasattr(fd, "top_holdings") and fd.top_holdings is not None:
                            df_hold = fd.top_holdings
                            if hasattr(df_hold, "index"):
                                holdings = [
                                    str(s).split(".")[0]
                                    for s in df_hold.index.tolist()
                                    if s and str(s) != "nan"
                                ]
                                if holdings:
                                    source = "yfinance"
                except Exception:
                    pass

                if not holdings:
                    logger.debug(f"yfinance 보유 종목 없음: {etf_symbol}, 시드 사용")

            except Exception as e:
                logger.warning(f"yfinance ETF 조회 실패: {etf_symbol} — {e}")

            # 2) 폴백: 정적 시드 리스트
            if not holdings:
                holdings = SEED_HOLDINGS.get(etf_symbol, [])
                source = "seed"

            # 3) Redis 캐시 저장 (7일 TTL)
            cache_key = f"etf_holdings:{etf_symbol}"
            self.cache.set_json(cache_key, holdings, ttl=ETF_CACHE_TTL)

            results[factor] = {
                "etf": etf_symbol,
                "count": len(holdings),
                "source": source,
                "updated": datetime.now().isoformat(),
            }
            logger.info(
                f"ETF 보유 종목 갱신: {etf_symbol} ({factor}) — "
                f"{len(holdings)}종목 ({source})"
            )

        return results

    # ─── 크라우딩 분석 ─────────────────────────────────────

    def check_crowding(self, symbols: list[str]) -> dict:
        """주어진 종목 리스트의 팩터 ETF 중복도 분석.

        Returns:
            {
                "total_symbols": int,
                "factors": {
                    "momentum": {
                        "etf": "MTUM",
                        "overlap_count": int,
                        "overlap_pct": float,
                        "overlap_symbols": list[str],
                        "risk_level": "high" | "moderate" | "low"
                    }, ...
                },
                "most_crowded_factor": str | None,
                "overall_risk": "high" | "moderate" | "low",
                "multi_factor_overlap": list[str]  # 3개 이상 ETF에 동시 포함된 종목
            }
        """
        if not symbols:
            return {
                "total_symbols": 0,
                "factors": {},
                "most_crowded_factor": None,
                "overall_risk": "low",
                "multi_factor_overlap": [],
            }

        symbols_upper = [s.upper() for s in symbols]
        symbol_set = set(symbols_upper)
        factors_result = {}
        symbol_factor_count: dict[str, int] = {s: 0 for s in symbols_upper}
        max_pct = 0.0
        max_factor = None

        for factor, etf_symbol in FACTOR_ETFS.items():
            holdings = self._get_holdings(factor, etf_symbol)
            holdings_set = set(h.upper() for h in holdings)

            overlap = symbol_set & holdings_set
            overlap_pct = len(overlap) / len(symbols_upper) if symbols_upper else 0

            # 리스크 수준 판정
            risk_level = "low"
            if overlap_pct >= CROWDING_THRESHOLDS["high"]:
                risk_level = "high"
            elif overlap_pct >= CROWDING_THRESHOLDS["moderate"]:
                risk_level = "moderate"

            factors_result[factor] = {
                "etf": etf_symbol,
                "overlap_count": len(overlap),
                "overlap_pct": round(overlap_pct, 4),
                "overlap_symbols": sorted(overlap),
                "risk_level": risk_level,
            }

            # 종목별 팩터 카운트 누적
            for s in overlap:
                symbol_factor_count[s] += 1

            if overlap_pct > max_pct:
                max_pct = overlap_pct
                max_factor = factor

        # 3개 이상 팩터 ETF에 동시 포함된 종목 → 과도한 팩터 노출
        multi_overlap = sorted(
            s for s, cnt in symbol_factor_count.items() if cnt >= 3
        )

        # 전체 리스크 판정
        overall_risk = "low"
        if max_pct >= CROWDING_THRESHOLDS["high"]:
            overall_risk = "high"
        elif max_pct >= CROWDING_THRESHOLDS["moderate"]:
            overall_risk = "moderate"

        return {
            "total_symbols": len(symbols_upper),
            "factors": factors_result,
            "most_crowded_factor": max_factor,
            "overall_risk": overall_risk,
            "multi_factor_overlap": multi_overlap,
        }

    def get_crowding_score(self, symbol: str) -> dict:
        """단일 종목의 팩터 크라우딩 점수.

        Returns:
            {
                "symbol": str,
                "factor_memberships": list[str],  # 해당 종목이 속한 팩터 목록
                "factor_count": int,               # 속한 팩터 수
                "risk_level": "high" | "moderate" | "low",
                "details": {factor: bool, ...}
            }
        """
        symbol_upper = symbol.upper()
        memberships = []
        details = {}

        for factor, etf_symbol in FACTOR_ETFS.items():
            holdings = self._get_holdings(factor, etf_symbol)
            holdings_set = set(h.upper() for h in holdings)
            is_member = symbol_upper in holdings_set
            details[factor] = is_member
            if is_member:
                memberships.append(factor)

        factor_count = len(memberships)
        # 3개 이상 팩터 = high, 2개 = moderate, 0-1 = low
        if factor_count >= 3:
            risk_level = "high"
        elif factor_count >= 2:
            risk_level = "moderate"
        else:
            risk_level = "low"

        return {
            "symbol": symbol_upper,
            "factor_memberships": memberships,
            "factor_count": factor_count,
            "risk_level": risk_level,
            "details": details,
        }

    def get_portfolio_crowding(self) -> dict:
        """현재 오픈 포지션 + pending 시그널의 크라우딩 분석.

        Returns: check_crowding 결과 + positions/signals 상세 정보.
        """
        # 오픈 포지션 종목
        positions = self.pg.get_open_positions()
        pos_symbols = [p["symbol"] for p in positions]

        # pending 시그널 종목
        signals = self.pg.get_signals(status="pending", limit=100)
        sig_symbols = [s["symbol"] for s in signals]

        # 전체 종목 (중복 제거)
        all_symbols = list(set(pos_symbols + sig_symbols))

        # 크라우딩 분석
        crowding = self.check_crowding(all_symbols)

        # 종목별 상세 크라우딩 점수 (list for JSON array)
        per_symbol = []
        for sym in all_symbols:
            per_symbol.append(self.get_crowding_score(sym))

        return {
            "portfolio": {
                "open_positions": pos_symbols,
                "pending_signals": sig_symbols,
                "total_unique": len(all_symbols),
            },
            "crowding": crowding,
            "per_symbol": per_symbol,
            "analyzed_at": datetime.now().isoformat(),
        }
