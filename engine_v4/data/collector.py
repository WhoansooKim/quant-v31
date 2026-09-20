"""UniverseManager + DataCollector — yfinance 기반 데이터 수집 + 지표 계산."""

from __future__ import annotations

import io
import logging
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests as _requests
import yfinance as yf

from engine_v4.config.settings import SwingSettings
from engine_v4.data.storage import PostgresStore, RedisCache

logger = logging.getLogger(__name__)

# ── S&P500 / NASDAQ100 대표 종목 (상위 200) ─────────────

_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_NDX100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) SwingV4-Collector/1.0"}

# 하드코드 시드 — Wikipedia 접근 실패 시 fallback
_SEED_SYMBOLS = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "ADI", "ADM", "ADP", "ADSK", "AEP",
    "AIG", "AMAT", "AMD", "AMGN", "AMP", "AMZN", "ANET", "ANSS", "AON", "APD",
    "APH", "AVGO", "AXP", "AZO", "BA", "BAC", "BDX", "BIIB", "BK", "BKNG",
    "BLK", "BMY", "BRK-B", "BSX", "C", "CAT", "CB", "CDNS", "CDW", "CEG",
    "CHTR", "CI", "CL", "CMCSA", "CME", "CMG", "COF", "COP", "COST", "CRM",
    "CRWD", "CSCO", "CTAS", "CTSH", "CVS", "CVX", "D", "DASH", "DD", "DE",
    "DHR", "DIS", "DUK", "DXCM", "EA", "ECL", "EL", "EMR", "ENPH", "EOG",
    "EQR", "ETN", "EW", "EXC", "F", "FANG", "FAST", "FCX", "FDX", "FI",
    "FICO", "FTNT", "GD", "GE", "GEHC", "GILD", "GIS", "GM", "GOOG", "GOOGL",
    "GPN", "GS", "HCA", "HD", "HON", "HSY", "HUM", "IBM", "ICE", "IDXX",
    "ILMN", "INTC", "INTU", "ISRG", "ITW", "JNJ", "JPM", "KDP", "KEYS", "KHC",
    "KLAC", "KMB", "KO", "LEN", "LHX", "LIN", "LLY", "LMT", "LOW", "LRCX",
    "LULU", "LVS", "MA", "MAR", "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT",
    "MET", "META", "MMC", "MMM", "MNST", "MO", "MPC", "MRVL", "MS", "MSCI",
    "MSFT", "MSI", "MU", "NFLX", "NKE", "NOC", "NOW", "NSC", "NTAP", "NXPI",
    "ODFL", "ON", "ORCL", "ORLY", "OXY", "PANW", "PAYX", "PCAR", "PDD", "PEP",
    "PFE", "PG", "PGR", "PH", "PLD", "PM", "PNC", "PSA", "PSX", "PYPL",
    "QCOM", "REGN", "ROP", "ROST", "RSG", "RTX", "SBUX", "SCHW", "SHW", "SLB",
    "SMCI", "SNPS", "SO", "SPG", "SPGI", "SRE", "SYK", "SYY", "T", "TDG",
    "TGT", "TJX", "TMO", "TMUS", "TSLA", "TT", "TTD", "TTWO", "TXN", "UNH",
    "UNP", "UPS", "URI", "USB", "V", "VICI", "VLO", "VMC", "VRSK", "VRTX",
    "VZ", "WBA", "WDAY", "WEC", "WELL", "WFC", "WM", "WMT", "XEL", "XOM",
    "ZS", "ZTS",
]


class UniverseManager:
    """S&P500 + NASDAQ100 상위 200개 종목 관리."""

    def __init__(self, pg: PostgresStore, cache: RedisCache):
        self.pg = pg
        self.cache = cache

    def _fetch_html(self, url: str) -> str | None:
        """User-Agent 헤더 포함 Wikipedia HTML 다운로드."""
        try:
            resp = _requests.get(url, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning(f"HTML fetch failed ({url}): {e}")
            return None

    def refresh_universe(self) -> list[dict]:
        """위키피디아에서 S&P500 + NDX100 가져와 시총 상위 200 선별."""
        logger.info("Refreshing universe from Wikipedia...")

        sp500 = set()
        ndx100 = set()

        # S&P 500
        try:
            html = self._fetch_html(_SP500_URL)
            if html:
                tables = pd.read_html(io.StringIO(html), header=0)
                df_sp = tables[0]
                col = "Symbol" if "Symbol" in df_sp.columns else df_sp.columns[0]
                sp500 = set(df_sp[col].str.replace(".", "-", regex=False).tolist())
                logger.info(f"S&P500: {len(sp500)} symbols")
        except Exception as e:
            logger.warning(f"S&P500 parse failed: {e}")

        # NASDAQ 100
        try:
            html = self._fetch_html(_NDX100_URL)
            if html:
                tables = pd.read_html(io.StringIO(html), header=0)
                for tbl in tables:
                    if "Ticker" in tbl.columns:
                        ndx100 = set(tbl["Ticker"].str.replace(".", "-", regex=False).tolist())
                        break
                    elif "Symbol" in tbl.columns:
                        ndx100 = set(tbl["Symbol"].str.replace(".", "-", regex=False).tolist())
                        break
                logger.info(f"NDX100: {len(ndx100)} symbols")
        except Exception as e:
            logger.warning(f"NDX100 parse failed: {e}")

        all_symbols = sp500 | ndx100
        if not all_symbols:
            # Fallback: 하드코드 시드 목록 사용
            logger.warning("Wikipedia scraping failed — using seed symbol list")
            all_symbols = set(_SEED_SYMBOLS)

        # 거래대금 기반 상위 200 선별 (yf.download — 빠름)
        logger.info(f"Ranking {len(all_symbols)} symbols by dollar volume...")
        symbol_list = sorted(all_symbols)
        universe = []

        # 최근 5일 종가×거래량으로 대략적 시총 프록시 (개별 .info보다 100x 빠름)
        batch_size = 100
        for i in range(0, len(symbol_list), batch_size):
            batch = symbol_list[i : i + batch_size]
            tickers_str = " ".join(batch)
            try:
                data = yf.download(tickers_str, period="5d", progress=False,
                                   group_by="ticker", threads=True)
                if data.empty:
                    continue
                for sym in batch:
                    try:
                        if len(batch) == 1:
                            df = data
                        else:
                            df = data[sym]
                        df = df.dropna(subset=["Close"])
                        if df.empty:
                            continue
                        avg_dv = float((df["Close"] * df["Volume"]).mean())
                        index_member = []
                        if sym in sp500:
                            index_member.append("SP500")
                        if sym in ndx100:
                            index_member.append("NDX100")
                        universe.append({
                            "symbol": sym,
                            "company_name": "",
                            "sector": "",
                            "market_cap": int(avg_dv),  # dollar volume proxy
                            "index_member": "+".join(index_member),
                        })
                    except Exception:
                        pass
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"Batch download error: {e}")
                time.sleep(1)

        # 거래대금 상위 200
        universe.sort(key=lambda x: x["market_cap"], reverse=True)
        top200 = universe[:200]
        logger.info(f"Universe filtered: {len(top200)} / {len(universe)} total")

        # DB에 저장
        active_symbols = [s["symbol"] for s in top200]
        self.pg.upsert_universe(top200)
        self.pg.deactivate_missing(active_symbols)
        self.cache.set_universe(top200, ttl=86400 * 7)

        return top200

    def get_universe(self) -> list[dict]:
        """캐시 우선, 없으면 DB."""
        cached = self.cache.get_universe()
        if cached:
            return cached
        return self.pg.get_universe()


class DataCollector:
    """yfinance → daily_prices → swing_indicators 계산."""

    def __init__(self, pg: PostgresStore, cache: RedisCache,
                 settings: SwingSettings):
        self.pg = pg
        self.cache = cache
        self.cfg = settings

    def collect_prices(self, symbols: list[str], days: int = 250) -> int:
        """yfinance에서 OHLCV 수집 → daily_prices 저장."""
        logger.info(f"Collecting prices for {len(symbols)} symbols, {days}d...")
        total = 0
        batch_size = 50

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            tickers_str = " ".join(batch)
            try:
                data = yf.download(
                    tickers_str,
                    period=f"{days}d",
                    group_by="ticker",
                    threads=True,
                    progress=False,
                )
                if data.empty:
                    continue

                rows = []
                missing: list[str] = []
                for sym in batch:
                    # 🔴 2026-09-20 (§22.AO-30): 여기 있던 `except Exception: pass` 때문에
                    #   배치 응답에서 빠진 종목이 **로그 한 줄 없이** 사라졌다. yfinance 는 50개
                    #   일괄 요청 시 일부 티커를 누락해 돌려주는 일이 잦은데, 그게 전부 삼켜졌다.
                    #   결과: 유니버스 200 중 22종목(11%)이 수개월간 미수집(SYY 6/23, CL 7/17 …).
                    #   개별 조회하면 멀쩡히 나오므로 데이터 소스 문제가 아니라 이 삼킴이 원인이었다.
                    #   → 실패/무행 종목을 모아 배치 뒤 개별 재시도하고, 그래도 없으면 경고로 남긴다.
                    n_before = len(rows)
                    rows.extend(self._extract_symbol_rows(data, sym))
                    if len(rows) == n_before:
                        missing.append(sym)

                # 배치에서 누락된 종목은 개별 재시도 (일괄 요청의 부분 누락 보정)
                if missing:
                    logger.info(f"  Batch {i // batch_size + 1}: {len(missing)} 종목 누락 → 개별 재시도")
                    still: list[str] = []
                    for sym in missing:
                        try:
                            one = yf.download(sym, period=f"{days}d", group_by="ticker",
                                              threads=False, progress=False)
                            got = self._extract_symbol_rows(one, sym)
                            if got:
                                rows.extend(got)
                            else:
                                still.append(sym)
                        except Exception as e:
                            still.append(sym)
                            logger.warning(f"  재시도 실패 {sym}: {type(e).__name__}: {str(e)[:80]}")
                        time.sleep(0.3)
                    if still:
                        logger.warning(f"  🔴 수집 실패 {len(still)}종목: {', '.join(still[:20])}")

                if rows:
                    self.pg.upsert_daily_prices(rows)
                    total += len(rows)
                    logger.info(f"  Batch {i // batch_size + 1}: {len(rows)} rows")

                time.sleep(1)  # rate limit
            except Exception as e:
                logger.warning(f"Batch download error: {e}")
                time.sleep(2)

        logger.info(f"Collected {total} price rows total")
        return total

    @staticmethod
    def _extract_symbol_rows(data, sym: str) -> list[dict]:
        """yfinance 응답에서 한 종목의 OHLCV 행을 뽑는다. 못 뽑으면 빈 리스트.

        group_by='ticker' 는 단일배치도 MultiIndex 를 반환하므로 항상 data[sym] 로 접근한다
        (단일 심볼 수집 시 df=data 로 하면 Close 접근이 실패하던 잠복버그).
        예외를 삼키지 않고 **빈 결과로 돌려** 호출부가 누락을 인지하게 한다.
        """
        out: list[dict] = []
        try:
            if data is None or getattr(data, "empty", True):
                return out
            if isinstance(data.columns, pd.MultiIndex):
                if sym not in data.columns.get_level_values(0):
                    return out
                df = data[sym]
            else:
                df = data
            df = df.dropna(subset=["Close"])
            for ts, row in df.iterrows():
                out.append({
                    "time": ts.to_pydatetime(),
                    "symbol": sym,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                })
        except Exception as e:
            logger.debug(f"  _extract_symbol_rows({sym}) 실패: {type(e).__name__}: {e}")
            return []
        return out

    def compute_indicators(self, symbols: list[str]) -> int:
        """daily_prices → swing_indicators 계산."""
        logger.info(f"Computing indicators for {len(symbols)} symbols...")
        all_prices = self.pg.get_all_daily_prices(symbols, days=300)

        if not all_prices:
            logger.warning("No price data found")
            return 0

        df = pd.DataFrame(all_prices)
        df["time"] = pd.to_datetime(df["time"])
        df = df.sort_values(["symbol", "time"])

        indicator_rows = []
        latest_date = df["time"].max()
        # volume_ratio_min: DB config 우선(scan_entries 와 일관), 없으면 settings 폴백 — 루프 밖 1회
        _vol_min = float(self.pg.get_config_value(
            "volume_ratio_min", str(self.cfg.volume_ratio_min)))
        # breakout_margin: 5일 고점 근접 허용(백테스트 검증 0.03=−3% → 진입↑·수익·Sharpe↑)
        _bo_margin = float(self.pg.get_config_value("breakout_margin", "0.0"))

        for sym, grp in df.groupby("symbol"):
            grp = grp.sort_values("time").copy()
            if len(grp) < self.cfg.sma_long:
                continue

            close = grp["close"].astype(float)
            volume = grp["volume"].astype(float)

            grp["sma_50"] = close.rolling(self.cfg.sma_short).mean()
            grp["sma_200"] = close.rolling(self.cfg.sma_long).mean()
            grp["return_20d"] = close.pct_change(self.cfg.return_period)
            grp["high_5d"] = close.shift(1).rolling(self.cfg.breakout_days).max()
            grp["volume_avg_20d"] = volume.rolling(20).mean()
            grp["volume_ratio"] = volume / grp["volume_avg_20d"]
            grp["trend_aligned"] = (close > grp["sma_50"]) & (grp["sma_50"] > grp["sma_200"])
            grp["breakout_5d"] = close > grp["high_5d"] * (1 - _bo_margin)
            # volume_ratio_min: DB config 우선(scan_entries 와 일관), 없으면 settings 폴백
            grp["volume_surge"] = grp["volume_ratio"] > _vol_min

            # 최신 날짜만 저장 (매일 실행 시)
            latest = grp[grp["time"] == latest_date]
            if latest.empty:
                # 해당 종목의 최신 날짜
                latest = grp.tail(1)

            for _, row in latest.iterrows():
                if pd.isna(row.get("sma_200")):
                    continue
                indicator_rows.append({
                    "time": row["time"],
                    "symbol": sym,
                    "close": float(row["close"]),
                    "sma_50": float(row["sma_50"]),
                    "sma_200": float(row["sma_200"]),
                    "return_20d": float(row["return_20d"]) if pd.notna(row["return_20d"]) else 0,
                    "return_20d_rank": 0,  # 아래서 계산
                    "high_5d": float(row["high_5d"]) if pd.notna(row["high_5d"]) else 0,
                    "volume": int(row["volume"]),
                    "volume_avg_20d": float(row["volume_avg_20d"]) if pd.notna(row["volume_avg_20d"]) else 0,
                    "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 0,
                    "trend_aligned": bool(row["trend_aligned"]),
                    "breakout_5d": bool(row["breakout_5d"]),
                    "volume_surge": bool(row["volume_surge"]),
                })

        # return_20d_rank 계산 (유니버스 내 백분위)
        if indicator_rows:
            returns = [r["return_20d"] for r in indicator_rows]
            sorted_returns = sorted(returns)
            n = len(sorted_returns)
            for row in indicator_rows:
                rank = sorted_returns.index(row["return_20d"]) / max(n - 1, 1)
                row["return_20d_rank"] = round(rank, 4)

            self.pg.upsert_indicators(indicator_rows)
            self.cache.set_indicators(indicator_rows, ttl=3600)
            logger.info(f"Computed {len(indicator_rows)} indicator rows")

        return len(indicator_rows)
