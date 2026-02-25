"""
V3.1 Phase 3 — VWAP 분할 실행
대량 주문을 여러 슬라이스로 나눠 슬리피지 최소화
"""
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class VWAPExecutor:
    """VWAP 분할 주문 실행기

    대량 주문을 slices개로 분할하여
    시간 간격을 두고 실행 → 시장 충격 최소화
    """

    def __init__(self, alpaca_executor, slices: int = 5,
                 interval_sec: int = 60):
        self.executor = alpaca_executor
        self.default_slices = slices
        self.interval_sec = interval_sec

    async def execute(self, symbol: str, side: str,
                      total_qty: int,
                      slices: int | None = None) -> dict | None:
        """VWAP 분할 실행

        Args:
            symbol: 종목 코드
            side: "buy" 또는 "sell"
            total_qty: 총 수량
            slices: 분할 수 (기본 5)

        Returns:
            {"order_id", "symbol", "side", "filled_qty", "avg_price", "slippage"}
        """
        slices = slices or self.default_slices

        if total_qty <= 0:
            return None

        # 소량이면 분할하지 않음
        if total_qty <= 10:
            slices = 1

        slice_qty = total_qty // slices
        remainder = total_qty % slices

        filled_qty = 0
        total_cost = 0.0
        first_order_id = None

        logger.info(f"VWAP 실행: {side} {total_qty} {symbol} "
                   f"({slices}슬라이스 × {slice_qty})")

        for i in range(slices):
            qty = slice_qty + (1 if i < remainder else 0)
            if qty <= 0:
                continue

            result = await self.executor.submit_order(
                symbol=symbol, qty=qty, side=side,
                order_type="market", time_in_force="day"
            )

            if result:
                if first_order_id is None:
                    first_order_id = result["order_id"]
                filled_qty += qty
                # 실제 체결가는 order status에서 조회해야 하지만,
                # Paper Trading에서는 시장가 즉시 체결
                price = self._get_fill_price(symbol)
                total_cost += qty * price
                logger.debug(f"  슬라이스 {i+1}/{slices}: "
                           f"{qty}주 @ ${price:.2f}")
            else:
                logger.warning(f"  슬라이스 {i+1}/{slices} 실패")

            # 마지막 슬라이스가 아니면 대기
            if i < slices - 1:
                await asyncio.sleep(self.interval_sec)

        if filled_qty == 0:
            return None

        avg_price = total_cost / filled_qty if filled_qty > 0 else 0
        # 슬리피지 = (평균 체결가 - 시작 가격) / 시작 가격
        initial_price = self._get_fill_price(symbol)
        slippage = ((avg_price - initial_price) / initial_price
                    if initial_price > 0 else 0)

        logger.info(f"VWAP 완료: {filled_qty}/{total_qty} 체결, "
                   f"avg=${avg_price:.2f}, slippage={slippage:.4%}")

        return {
            "order_id": first_order_id or "N/A",
            "symbol": symbol,
            "side": side,
            "filled_qty": filled_qty,
            "avg_price": avg_price,
            "slippage": slippage,
            "slices_executed": slices,
        }

    def _get_fill_price(self, symbol: str) -> float:
        """체결가 조회 (현재가 대용)"""
        try:
            positions = self.executor.get_positions()
            for p in positions:
                if p.symbol == symbol:
                    return p.current_price
        except Exception:
            pass
        # 포지션에 없으면 Alpaca에서 최신가 조회
        try:
            api = self.executor._get_api()
            bar = api.get_latest_bar(symbol)
            return float(bar.c)
        except Exception:
            return 0.0
