"""Exit Strategy Manager — Trailing Stop + Partial Exit.

현재 고정 SL(-5%)/TP(+10%)을 보완:
  1. Trailing Stop: 수익 +5% 이상 → SL을 현재가 -3%로 동적 상향
  2. Partial Exit: 수익 +7% → 50% 분할 청산, 나머지는 trailing stop

동작 방식 (_job_exit_check에서 호출):
  1. update_trailing_stops() — 모든 open 포지션의 high water mark 갱신, trailing SL 상향
  2. check_partial_exits() — partial exit 조건 충족 시 반환 (호출자가 실제 청산 처리)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)


@dataclass
class PartialExitAction:
    """분할 청산 지시."""
    position_id: int
    symbol: str
    current_price: float
    exit_qty: float
    remaining_qty: float
    gain_pct: float


class ExitManager:
    """Trailing Stop + Partial Exit 관리."""

    def __init__(self, pg: PostgresStore):
        self.pg = pg

    def _get_config_float(self, key: str, default: float) -> float:
        return float(self.pg.get_config_value(key, str(default)))

    def update_trailing_stops(self, positions: list[dict], current_prices: dict[str, float]) -> int:
        """모든 open 포지션에 대해 trailing stop 업데이트.

        Returns: 업데이트된 포지션 수.
        """
        activation_pct = self._get_config_float("trailing_stop_activation", 0.05)
        trail_distance = self._get_config_float("trailing_stop_distance", 0.03)
        updated = 0

        for pos in positions:
            symbol = pos["symbol"]
            pid = pos["position_id"]
            entry_price = float(pos["entry_price"])
            current_price = current_prices.get(symbol)
            if not current_price:
                continue

            old_sl = float(pos.get("stop_loss") or (entry_price * 0.95))
            hwm = float(pos.get("high_water_mark") or entry_price)
            trailing_active = bool(pos.get("trailing_stop_active"))

            # High water mark 갱신
            if current_price > hwm:
                hwm = current_price
                self.pg.update_high_water_mark(pid, hwm)

            # Trailing 활성화 체크
            gain_pct = (current_price - entry_price) / entry_price
            if not trailing_active and gain_pct >= activation_pct:
                trailing_active = True
                self.pg.activate_trailing_stop(pid)
                logger.info(f"Trailing stop ACTIVATED for {symbol} (position #{pid}): "
                            f"gain={gain_pct:+.1%}")

            # Trailing SL 계산 (활성화된 경우만)
            if trailing_active:
                new_sl = round(hwm * (1 - trail_distance), 4)
                if new_sl > old_sl:
                    self.pg.update_position_stop_loss(pid, new_sl)
                    updated += 1
                    logger.info(f"Trailing SL raised for {symbol}: "
                                f"${old_sl:.2f} → ${new_sl:.2f} (HWM=${hwm:.2f})")

        if updated:
            logger.info(f"Trailing stops updated: {updated}/{len(positions)} positions")
        return updated

    def check_partial_exits(self, positions: list[dict],
                            current_prices: dict[str, float]) -> list[PartialExitAction]:
        """분할 청산 조건 체크.

        Returns: PartialExitAction 목록 (호출자가 실제 청산 처리).
        """
        threshold = self._get_config_float("partial_exit_threshold", 0.07)
        exit_pct = self._get_config_float("partial_exit_pct", 0.5)
        actions = []

        for pos in positions:
            # 이미 분할 청산한 포지션 스킵
            if pos.get("partial_exited"):
                continue

            symbol = pos["symbol"]
            entry_price = float(pos["entry_price"])
            qty = float(pos.get("qty") or 1)
            current_price = current_prices.get(symbol)
            if not current_price:
                continue

            gain_pct = (current_price - entry_price) / entry_price
            if gain_pct >= threshold:
                exit_qty = round(qty * exit_pct)
                if exit_qty < 1:
                    exit_qty = 1
                remaining_qty = qty - exit_qty
                if remaining_qty < 0:
                    remaining_qty = 0

                actions.append(PartialExitAction(
                    position_id=pos["position_id"],
                    symbol=symbol,
                    current_price=current_price,
                    exit_qty=exit_qty,
                    remaining_qty=remaining_qty,
                    gain_pct=gain_pct,
                ))
                logger.info(f"PARTIAL EXIT signal for {symbol}: gain={gain_pct:+.1%}, "
                            f"sell {exit_qty}/{qty} shares @ ${current_price:.2f}")

        return actions
