"""KIS 한국투자증권 REST API 래퍼 — 해외(미국) 주식 매매."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

from engine_v4.config.settings import SwingSettings

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    """주문 결과."""
    success: bool
    order_id: str | None = None
    symbol: str = ""
    side: str = ""
    qty: int = 0
    price: float = 0.0
    message: str = ""


@dataclass
class BalanceInfo:
    """계좌 잔고."""
    total_value_usd: float = 0.0
    cash_usd: float = 0.0
    invested_usd: float = 0.0
    profit_usd: float = 0.0
    profit_rate: float = 0.0
    holdings: list[dict] | None = None
    message: str = ""


@dataclass
class QuoteInfo:
    """시세 정보."""
    symbol: str = ""
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    message: str = ""


class KisClient:
    """
    KIS (한국투자증권) 해외주식 클라이언트.
    paper=True → 모의투자, paper=False → 실계좌.
    """

    def __init__(self, settings: SwingSettings):
        self.settings = settings
        self._kis = None
        self._account = None
        self._initialized = False
        self._last_request = 0.0
        self._min_interval = 0.5  # 초당 2회 제한

    def _init_client(self) -> bool:
        """PyKis 클라이언트 초기화 (지연 로딩)."""
        if self._initialized:
            return self._kis is not None

        if not self.settings.kis_app_key or self.settings.kis_app_key == "your_kis_app_key":
            logger.warning("KIS credentials not configured — running in simulation mode")
            self._initialized = True
            return False

        try:
            from pykis import PyKis

            if self.settings.kis_is_paper:
                # 모의투자
                self._kis = PyKis(
                    virtual_id=self.settings.kis_app_key[:8],
                    virtual_appkey=self.settings.kis_app_key,
                    virtual_secretkey=self.settings.kis_app_secret,
                    account=self.settings.kis_account_no,
                    use_websocket=False,
                    keep_token=True,
                )
            else:
                # 실계좌
                self._kis = PyKis(
                    id=self.settings.kis_app_key[:8],
                    appkey=self.settings.kis_app_key,
                    secretkey=self.settings.kis_app_secret,
                    account=self.settings.kis_account_no,
                    use_websocket=False,
                    keep_token=True,
                )

            self._account = self._kis.account()
            self._initialized = True
            logger.info(f"KIS client initialized (paper={self.settings.kis_is_paper})")
            return True

        except Exception as e:
            logger.error(f"KIS initialization failed: {e}")
            self._initialized = True
            return False

    def _rate_limit(self):
        """API 호출 간격 제한."""
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    def _get_market(self, symbol: str) -> str:
        """종목 심볼로 시장 추정."""
        # 대부분 NYSE/NASDAQ. 간단히 분류.
        nasdaq_symbols = {
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "TSLA",
            "NVDA", "AVGO", "COST", "NFLX", "AMD", "INTC", "QCOM",
            "ADBE", "CSCO", "TXN", "ISRG", "BKNG", "ADI", "ADP",
            "SBUX", "GILD", "AMGN", "PYPL", "INTU", "MDLZ", "REGN",
            "SNPS", "CDNS", "LRCX", "KLAC", "MRVL", "ASML", "PANW",
            "ABNB", "CRWD", "FTNT", "DDOG", "ZS", "TTD", "MDB",
        }
        return "NASDAQ" if symbol in nasdaq_symbols else "NYSE"

    # ─── 매수 ───

    def buy(self, symbol: str, qty: int,
            price: float | None = None) -> OrderResult:
        """
        미국 주식 매수.
        price=None → 시장가, price=값 → 지정가.
        """
        if not self._init_client():
            return self._simulate_order(symbol, "BUY", qty, price)

        self._rate_limit()
        try:
            market = self._get_market(symbol)
            stock = self._kis.stock(symbol, market)

            if price is not None:
                order = stock.buy(price=price, qty=qty)
            else:
                order = stock.buy(qty=qty)  # 시장가

            order_id = str(order.number) if order.number else None
            logger.info(f"KIS BUY: {symbol} x{qty} @ {price or 'MKT'} → order={order_id}")
            return OrderResult(
                success=True,
                order_id=order_id,
                symbol=symbol,
                side="BUY",
                qty=qty,
                price=price or 0,
                message="Order placed",
            )
        except Exception as e:
            logger.error(f"KIS BUY failed: {symbol} x{qty} — {e}")
            return OrderResult(
                success=False, symbol=symbol, side="BUY",
                qty=qty, price=price or 0, message=str(e),
            )

    # ─── 매도 ───

    def sell(self, symbol: str, qty: int,
             price: float | None = None) -> OrderResult:
        """미국 주식 매도."""
        if not self._init_client():
            return self._simulate_order(symbol, "SELL", qty, price)

        self._rate_limit()
        try:
            market = self._get_market(symbol)
            stock = self._kis.stock(symbol, market)

            if price is not None:
                order = stock.sell(price=price, qty=qty)
            else:
                order = stock.sell(qty=qty)

            order_id = str(order.number) if order.number else None
            logger.info(f"KIS SELL: {symbol} x{qty} @ {price or 'MKT'} → order={order_id}")
            return OrderResult(
                success=True,
                order_id=order_id,
                symbol=symbol,
                side="SELL",
                qty=qty,
                price=price or 0,
                message="Order placed",
            )
        except Exception as e:
            logger.error(f"KIS SELL failed: {symbol} x{qty} — {e}")
            return OrderResult(
                success=False, symbol=symbol, side="SELL",
                qty=qty, price=price or 0, message=str(e),
            )

    # ─── 잔고 ───

    def get_balance(self) -> BalanceInfo:
        """계좌 잔고 조회."""
        if not self._init_client():
            return BalanceInfo(
                total_value_usd=2200.0,
                cash_usd=2200.0,
                message="Simulation mode",
            )

        self._rate_limit()
        try:
            bal = self._account.balance(country="US")
            holdings = []
            for stock in bal.stocks:
                holdings.append({
                    "symbol": stock.symbol,
                    "qty": float(stock.qty) if hasattr(stock, "qty") else 0,
                    "avg_price": float(stock.purchase_amount) if hasattr(stock, "purchase_amount") else 0,
                    "current_price": float(stock.current_amount) if hasattr(stock, "current_amount") else 0,
                })

            return BalanceInfo(
                total_value_usd=float(bal.total) if hasattr(bal, "total") else 0,
                cash_usd=float(bal.deposit) if hasattr(bal, "deposit") else 0,
                invested_usd=float(bal.purchase_amount) if hasattr(bal, "purchase_amount") else 0,
                profit_usd=float(bal.profit) if hasattr(bal, "profit") else 0,
                profit_rate=float(bal.profit_rate) if hasattr(bal, "profit_rate") else 0,
                holdings=holdings,
            )
        except Exception as e:
            logger.error(f"KIS balance error: {e}")
            return BalanceInfo(message=str(e))

    # ─── 시세 ───

    def get_quote(self, symbol: str) -> QuoteInfo:
        """종목 현재가 조회."""
        if not self._init_client():
            return QuoteInfo(symbol=symbol, message="Simulation mode")

        self._rate_limit()
        try:
            market = self._get_market(symbol)
            stock = self._kis.stock(symbol, market)
            quote = stock.quote()

            return QuoteInfo(
                symbol=symbol,
                price=float(quote.price) if hasattr(quote, "price") else 0,
                change=float(quote.change) if hasattr(quote, "change") else 0,
                change_pct=float(quote.change_rate) if hasattr(quote, "change_rate") else 0,
                volume=int(quote.volume) if hasattr(quote, "volume") else 0,
            )
        except Exception as e:
            logger.error(f"KIS quote error {symbol}: {e}")
            return QuoteInfo(symbol=symbol)

    # ─── 시뮬레이션 (KIS 미설정 시) ───

    def _simulate_order(self, symbol: str, side: str,
                        qty: int, price: float | None) -> OrderResult:
        """KIS 미연동 시 시뮬레이션 주문."""
        sim_id = f"SIM-{int(time.time())}"
        logger.info(f"SIMULATED {side}: {symbol} x{qty} @ {price or 'MKT'} → {sim_id}")
        return OrderResult(
            success=True,
            order_id=sim_id,
            symbol=symbol,
            side=side,
            qty=qty,
            price=price or 0,
            message="Simulated order (KIS not configured)",
        )

    @property
    def is_connected(self) -> bool:
        """KIS 연결 여부."""
        return self._kis is not None
