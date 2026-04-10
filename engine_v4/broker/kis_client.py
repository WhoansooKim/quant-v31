"""KIS 한국투자증권 REST API 래퍼 — 해외(미국) 주식 매매.

python-kis 2.1.x (PyKis) 기반.
paper=True  → 모의투자 (virtual_appkey/secretkey)
paper=False → 실계좌 (appkey/secretkey)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
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
    withdrawable_usd: float = 0.0
    message: str = ""


@dataclass
class QuoteInfo:
    """시세 정보."""
    symbol: str = ""
    price: float = 0.0
    change: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    prev_close: float = 0.0
    message: str = ""


@dataclass
class PendingOrderInfo:
    """미체결 주문."""
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    qty: int = 0
    price: float = 0.0
    filled_qty: int = 0
    time: str = ""


@dataclass
class OrderableInfo:
    """주문 가능 금액/수량."""
    orderable_cash: float = 0.0
    orderable_qty: int = 0
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

        if not self.settings.kis_user_id:
            logger.warning("KIS_USER_ID not set — running in simulation mode")
            self._initialized = True
            return False

        try:
            from pykis import PyKis

            user_id = self.settings.kis_user_id

            if self.settings.kis_is_paper:
                # 모의투자: virtual 앱키가 별도 필요 (없으면 시뮬레이션)
                if not self.settings.kis_virtual_app_key:
                    logger.info("KIS paper mode — no virtual keys, using simulation")
                    self._initialized = True
                    return False
                self._kis = PyKis(
                    id=user_id,
                    appkey=self.settings.kis_app_key,
                    secretkey=self.settings.kis_app_secret,
                    virtual_id=user_id,
                    virtual_appkey=self.settings.kis_virtual_app_key,
                    virtual_secretkey=self.settings.kis_virtual_app_secret,
                    account=self.settings.kis_account_no,
                    use_websocket=False,
                    keep_token=True,
                )
            else:
                # 실전투자
                self._kis = PyKis(
                    id=user_id,
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
        """종목 심볼로 시장 추정 (NASDAQ / NYSE / AMEX)."""
        nasdaq_symbols = {
            "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "TSLA",
            "NVDA", "AVGO", "COST", "NFLX", "AMD", "INTC", "QCOM",
            "ADBE", "CSCO", "TXN", "ISRG", "BKNG", "ADI", "ADP",
            "SBUX", "GILD", "AMGN", "PYPL", "INTU", "MDLZ", "REGN",
            "SNPS", "CDNS", "LRCX", "KLAC", "MRVL", "ASML", "PANW",
            "ABNB", "CRWD", "FTNT", "DDOG", "ZS", "TTD", "MDB",
            "MELI", "TEAM", "WDAY", "DASH", "COIN", "HOOD", "RBLX",
            "CPRT", "CSGP", "FICO", "MNST", "IDXX", "FAST", "EXC",
            "VRSK", "ANSS", "DXCM", "BIIB", "ILMN", "SIRI", "CEG",
            "XEL", "WBD", "DLTR", "EBAY", "EA", "ZM", "OKTA",
            "IONQ", "ANET", "SMCI", "ARM", "PLTR", "RIVN", "LCID",
        }
        return "NASDAQ" if symbol in nasdaq_symbols else "NYSE"

    # ─── 매수 ───

    def buy(self, symbol: str, qty: int,
            price: float | None = None,
            condition: str | None = None) -> OrderResult:
        """
        미국 주식 매수.
        price=None → 시장가, price=값 → 지정가.
        condition: 'extended'(시간외), 'LOO'(장시작시장가), 'LOC'(장마감시장가) 등.
        """
        if not self._init_client():
            return self._simulate_order(symbol, "BUY", qty, price)

        self._rate_limit()
        try:
            market = self._get_market(symbol)
            stock = self._kis.stock(symbol, market)

            kwargs = {"qty": qty}
            if price is not None:
                kwargs["price"] = price
            if condition:
                kwargs["condition"] = condition

            order = stock.buy(**kwargs)

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
             price: float | None = None,
             condition: str | None = None) -> OrderResult:
        """미국 주식 매도."""
        if not self._init_client():
            return self._simulate_order(symbol, "SELL", qty, price)

        self._rate_limit()
        try:
            market = self._get_market(symbol)
            stock = self._kis.stock(symbol, market)

            kwargs = {"qty": qty}
            if price is not None:
                kwargs["price"] = price
            if condition:
                kwargs["condition"] = condition

            order = stock.sell(**kwargs)

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
            return BalanceInfo(message="Simulation mode — KIS not connected")

        self._rate_limit()
        try:
            bal = self._account.balance(country="US")
            holdings = []
            for s in bal.stocks:
                holdings.append({
                    "symbol": s.symbol,
                    "name": getattr(s, "name", ""),
                    "qty": float(s.qty),
                    "purchase_price": float(s.purchase_price),
                    "current_price": float(s.current_price),
                    "purchase_amount": float(s.purchase_amount),
                    "current_amount": float(s.current_amount),
                    "profit": float(s.profit),
                    "profit_rate": float(s.profit_rate),
                })

            return BalanceInfo(
                total_value_usd=float(bal.total),
                cash_usd=float(bal.withdrawable),
                invested_usd=float(bal.purchase_amount),
                profit_usd=float(bal.profit),
                profit_rate=float(bal.profit_rate),
                withdrawable_usd=float(bal.withdrawable),
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
            q = stock.quote()

            return QuoteInfo(
                symbol=symbol,
                price=float(q.price),
                change=float(q.change),
                change_pct=float(q.rate) * 100,  # rate는 소수 → %로 변환
                volume=int(q.volume),
                high=float(q.high),
                low=float(q.low),
                open=float(q.open),
                prev_close=float(q.prev_price),
            )
        except Exception as e:
            logger.error(f"KIS quote error {symbol}: {e}")
            return QuoteInfo(symbol=symbol, message=str(e))

    # ─── 미체결 주문 조회 ───

    def get_pending_orders(self) -> list[PendingOrderInfo]:
        """미체결 주문 목록 조회."""
        if not self._init_client():
            return []

        self._rate_limit()
        try:
            orders = self._account.pending_orders(country="US")
            result = []
            for o in orders:
                result.append(PendingOrderInfo(
                    order_id=str(getattr(o, "number", "")),
                    symbol=getattr(o, "symbol", ""),
                    side=getattr(o, "side", ""),
                    qty=int(getattr(o, "qty", 0)),
                    price=float(getattr(o, "price", 0)),
                    filled_qty=int(getattr(o, "filled_qty", 0)),
                    time=str(getattr(o, "time", "")),
                ))
            return result
        except Exception as e:
            logger.error(f"KIS pending orders error: {e}")
            return []

    # ─── 주문 취소 ───

    def cancel_order(self, order_id: str) -> OrderResult:
        """미체결 주문 취소."""
        if not self._init_client():
            return OrderResult(success=False, message="KIS not connected")

        self._rate_limit()
        try:
            from pykis.api.account.order import KisOrderNumber
            order_num = KisOrderNumber.from_number(
                kis=self._kis,
                account=self._account.account_number,
                number=order_id,
            )
            result = self._account.cancel(order_num)
            logger.info(f"KIS CANCEL: order={order_id}")
            return OrderResult(
                success=True,
                order_id=order_id,
                message="Order cancelled",
            )
        except Exception as e:
            logger.error(f"KIS cancel error: {e}")
            return OrderResult(success=False, order_id=order_id, message=str(e))

    # ─── 주문 가능 금액/수량 조회 ───

    def get_orderable_amount(self, symbol: str,
                              price: float | None = None) -> OrderableInfo:
        """주문 가능 금액 및 최대 매수 수량 조회."""
        if not self._init_client():
            return OrderableInfo(message="Simulation mode")

        self._rate_limit()
        try:
            market = self._get_market(symbol)
            stock = self._kis.stock(symbol, market)
            amt = stock.orderable_amount(price=price)

            return OrderableInfo(
                orderable_cash=float(getattr(amt, "orderable_amount", 0)),
                orderable_qty=int(getattr(amt, "orderable_qty", 0)),
            )
        except Exception as e:
            logger.error(f"KIS orderable amount error {symbol}: {e}")
            return OrderableInfo(message=str(e))

    # ─── 일별 주문 내역 ───

    def get_daily_orders(self, start_date: date | None = None,
                          end_date: date | None = None) -> list[dict]:
        """일별 주문 내역 조회."""
        if not self._init_client():
            return []

        self._rate_limit()
        try:
            if start_date is None:
                start_date = date.today()
            if end_date is None:
                end_date = date.today()

            orders = self._account.daily_orders(
                start=start_date, end=end_date, country="US")
            result = []
            for o in orders:
                result.append({
                    "order_id": str(getattr(o, "number", "")),
                    "symbol": getattr(o, "symbol", ""),
                    "side": str(getattr(o, "side", "")),
                    "qty": int(getattr(o, "qty", 0)),
                    "price": float(getattr(o, "price", 0)),
                    "filled_qty": int(getattr(o, "filled_qty", 0)),
                    "status": str(getattr(o, "status", "")),
                    "time": str(getattr(o, "time", "")),
                })
            return result
        except Exception as e:
            logger.error(f"KIS daily orders error: {e}")
            return []

    # ─── 연결 테스트 ───

    def test_connection(self) -> dict:
        """KIS API 연결 테스트."""
        if not self._init_client():
            return {
                "connected": False,
                "paper": self.settings.kis_is_paper,
                "reason": "KIS credentials not configured or init failed",
            }

        try:
            self._rate_limit()
            bal = self._account.balance(country="US")
            return {
                "connected": True,
                "paper": self.settings.kis_is_paper,
                "account": self.settings.kis_account_no,
                "total_usd": float(bal.total),
                "deposit_usd": float(bal.deposit),
                "stock_count": len(bal.stocks),
            }
        except Exception as e:
            return {
                "connected": False,
                "paper": self.settings.kis_is_paper,
                "reason": str(e),
            }

    # ─── DB 포지션과 KIS 보유종목 동기화 ───

    def sync_positions(self, db_positions: list[dict]) -> dict:
        """
        DB 오픈 포지션과 KIS 실제 보유종목 비교.
        불일치 항목을 리포트하고 수동 조치를 유도.
        """
        if not self._init_client():
            return {"synced": False, "message": "KIS not connected"}

        self._rate_limit()
        try:
            bal = self._account.balance(country="US")
            kis_holdings = {s.symbol: {
                "qty": float(s.qty),
                "avg_price": float(s.purchase_price),
                "current_price": float(s.current_price),
            } for s in bal.stocks}

            db_symbols = {p["symbol"]: {
                "qty": float(p["qty"]),
                "entry_price": float(p["entry_price"]),
            } for p in db_positions}

            # 불일치 분석
            mismatches = []
            for sym, db_info in db_symbols.items():
                if sym not in kis_holdings:
                    mismatches.append({
                        "symbol": sym, "type": "DB_ONLY",
                        "detail": f"DB has {db_info['qty']} shares, KIS has 0",
                    })
                elif abs(kis_holdings[sym]["qty"] - db_info["qty"]) > 0.01:
                    mismatches.append({
                        "symbol": sym, "type": "QTY_MISMATCH",
                        "detail": f"DB={db_info['qty']}, KIS={kis_holdings[sym]['qty']}",
                    })

            for sym, kis_info in kis_holdings.items():
                if sym not in db_symbols:
                    mismatches.append({
                        "symbol": sym, "type": "KIS_ONLY",
                        "detail": f"KIS has {kis_info['qty']} shares, DB has 0",
                    })

            return {
                "synced": len(mismatches) == 0,
                "db_count": len(db_symbols),
                "kis_count": len(kis_holdings),
                "mismatches": mismatches,
                "kis_holdings": kis_holdings,
            }
        except Exception as e:
            logger.error(f"KIS sync error: {e}")
            return {"synced": False, "message": str(e)}

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
