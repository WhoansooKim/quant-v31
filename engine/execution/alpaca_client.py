"""
V3.1 Phase 3/5 — Alpaca API 래퍼 (alpaca-py SDK)
Paper/Live 자동 전환. 포지션 조회 + 주문 실행.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    qty: float
    side: str
    market_value: float
    unrealized_pl: float
    current_price: float


class AlpacaExecutor:
    """Alpaca 주문 실행기 (alpaca-py SDK)"""

    def __init__(self, config):
        self.config = config
        self._client = None

    def _get_client(self):
        """지연 로딩 (alpaca-py TradingClient)"""
        if self._client is None:
            if (not self.config.alpaca_key
                    or self.config.alpaca_key.startswith("your_")):
                logger.warning("Alpaca API 키 미설정 → 시뮬레이션 모드")
                self._client = _MockAlpacaClient()
                return self._client

            try:
                from alpaca.trading.client import TradingClient
                self._client = TradingClient(
                    api_key=self.config.alpaca_key,
                    secret_key=self.config.alpaca_secret,
                    paper=self.config.alpaca_paper,
                )
                logger.info("Alpaca API 연결 완료 "
                           f"(paper={self.config.alpaca_paper})")
            except ImportError:
                logger.warning("alpaca-py 미설치 → 시뮬레이션 모드")
                self._client = _MockAlpacaClient()
        return self._client

    def get_portfolio_value(self) -> float:
        """포트폴리오 총 가치"""
        try:
            client = self._get_client()
            if isinstance(client, _MockAlpacaClient):
                return client.get_portfolio_value()
            account = client.get_account()
            return float(account.portfolio_value)
        except Exception as e:
            logger.error(f"포트폴리오 조회 실패: {e}")
            return 100_000.0

    def get_positions(self) -> list[Position]:
        """현재 보유 포지션"""
        try:
            client = self._get_client()
            if isinstance(client, _MockAlpacaClient):
                return []
            positions = client.get_all_positions()
            return [
                Position(
                    symbol=p.symbol,
                    qty=float(p.qty),
                    side=p.side.value if hasattr(p.side, 'value') else str(p.side),
                    market_value=float(p.market_value),
                    unrealized_pl=float(p.unrealized_pl),
                    current_price=float(p.current_price),
                )
                for p in positions
            ]
        except Exception as e:
            logger.error(f"포지션 조회 실패: {e}")
            return []

    async def submit_order(self, symbol: str, qty: int,
                           side: str, order_type: str = "market",
                           time_in_force: str = "day") -> dict | None:
        """주문 제출"""
        try:
            client = self._get_client()
            if isinstance(client, _MockAlpacaClient):
                return client.submit_order(
                    symbol=symbol, qty=qty, side=side)

            from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
            tif = TimeInForce.DAY if time_in_force == "day" else TimeInForce.GTC

            request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=tif,
            )
            order = client.submit_order(request)
            logger.info(f"주문: {side} {qty} {symbol} → {order.id}")
            return {
                "order_id": str(order.id),
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "status": str(order.status),
            }
        except Exception as e:
            logger.error(f"주문 실패 {symbol}: {e}")
            return None

    async def close_position(self, symbol: str) -> bool:
        """포지션 청산"""
        try:
            client = self._get_client()
            if isinstance(client, _MockAlpacaClient):
                return True
            client.close_position(symbol)
            logger.info(f"청산: {symbol}")
            return True
        except Exception as e:
            logger.error(f"청산 실패 {symbol}: {e}")
            return False

    async def close_all_positions(self) -> int:
        """전량 청산"""
        try:
            client = self._get_client()
            if isinstance(client, _MockAlpacaClient):
                return 0
            client.close_all_positions(cancel_orders=True)
            logger.info("전량 청산 완료")
            return 0
        except Exception as e:
            logger.error(f"전량 청산 실패: {e}")
            return 0

    def get_account(self) -> dict:
        """계좌 정보"""
        try:
            client = self._get_client()
            if isinstance(client, _MockAlpacaClient):
                return client.get_account_dict()
            a = client.get_account()
            return {
                "equity": float(a.equity),
                "cash": float(a.cash),
                "buying_power": float(a.buying_power),
                "portfolio_value": float(a.portfolio_value),
                "status": str(a.status),
            }
        except Exception as e:
            logger.error(f"계좌 조회 실패: {e}")
            return {"equity": 100_000, "cash": 100_000,
                    "buying_power": 200_000, "portfolio_value": 100_000,
                    "status": "SIMULATED"}


class _MockAlpacaClient:
    """Alpaca API 키 미설정 시 시뮬레이션 객체"""

    def get_portfolio_value(self):
        return 100_000.0

    def get_account_dict(self):
        return {
            "equity": 100_000, "cash": 100_000,
            "buying_power": 200_000, "portfolio_value": 100_000,
            "status": "SIMULATED",
        }

    def submit_order(self, symbol="", qty=0, side=""):
        import uuid
        logger.info(f"[SIM] 주문: {side} {qty} {symbol}")
        return {
            "order_id": str(uuid.uuid4())[:8],
            "symbol": symbol, "side": side, "qty": qty,
            "status": "accepted",
        }
