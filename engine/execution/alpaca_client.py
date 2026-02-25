"""
V3.1 Phase 3 — Alpaca API 래퍼
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
    """Alpaca 주문 실행기"""

    def __init__(self, config):
        self.config = config
        self._api = None

    def _get_api(self):
        """지연 로딩 (alpaca-trade-api)"""
        if self._api is None:
            try:
                from alpaca_trade_api import REST
                self._api = REST(
                    key_id=self.config.alpaca_key,
                    secret_key=self.config.alpaca_secret,
                    base_url=self.config.alpaca_base_url,
                )
                logger.info("Alpaca API 연결 완료 "
                           f"(paper={self.config.alpaca_paper})")
            except ImportError:
                logger.warning("alpaca-trade-api 미설치 → 시뮬레이션 모드")
                self._api = _MockAlpacaAPI()
        return self._api

    def get_portfolio_value(self) -> float:
        """포트폴리오 총 가치"""
        try:
            api = self._get_api()
            account = api.get_account()
            return float(account.portfolio_value)
        except Exception as e:
            logger.error(f"포트폴리오 조회 실패: {e}")
            return 100_000.0  # 기본값

    def get_positions(self) -> list[Position]:
        """현재 보유 포지션"""
        try:
            api = self._get_api()
            positions = api.list_positions()
            return [
                Position(
                    symbol=p.symbol,
                    qty=float(p.qty),
                    side=p.side,
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
            api = self._get_api()
            order = api.submit_order(
                symbol=symbol,
                qty=qty,
                side=side,
                type=order_type,
                time_in_force=time_in_force,
            )
            logger.info(f"주문: {side} {qty} {symbol} → {order.id}")
            return {
                "order_id": str(order.id),
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "status": order.status,
            }
        except Exception as e:
            logger.error(f"주문 실패 {symbol}: {e}")
            return None

    async def close_position(self, symbol: str) -> bool:
        """포지션 청산"""
        try:
            api = self._get_api()
            api.close_position(symbol)
            logger.info(f"청산: {symbol}")
            return True
        except Exception as e:
            logger.error(f"청산 실패 {symbol}: {e}")
            return False

    async def close_all_positions(self) -> int:
        """전량 청산"""
        try:
            api = self._get_api()
            api.close_all_positions()
            logger.info("전량 청산 완료")
            return len(self.get_positions())
        except Exception as e:
            logger.error(f"전량 청산 실패: {e}")
            return 0

    def get_account(self) -> dict:
        """계좌 정보"""
        try:
            api = self._get_api()
            a = api.get_account()
            return {
                "equity": float(a.equity),
                "cash": float(a.cash),
                "buying_power": float(a.buying_power),
                "portfolio_value": float(a.portfolio_value),
                "status": a.status,
            }
        except Exception as e:
            logger.error(f"계좌 조회 실패: {e}")
            return {"equity": 100_000, "cash": 100_000,
                    "buying_power": 200_000, "portfolio_value": 100_000,
                    "status": "SIMULATED"}


class _MockAlpacaAPI:
    """alpaca-trade-api 미설치 시 목 객체"""

    class _Account:
        portfolio_value = "100000.00"
        equity = "100000.00"
        cash = "100000.00"
        buying_power = "200000.00"
        status = "SIMULATED"

    class _Order:
        def __init__(self):
            import uuid
            self.id = str(uuid.uuid4())[:8]
            self.status = "accepted"

    def get_account(self):
        return self._Account()

    def list_positions(self):
        return []

    def submit_order(self, **kwargs):
        logger.info(f"[SIM] 주문: {kwargs}")
        return self._Order()

    def close_position(self, symbol):
        logger.info(f"[SIM] 청산: {symbol}")

    def close_all_positions(self):
        logger.info("[SIM] 전량 청산")
