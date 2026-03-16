"""Exit Strategy Manager — Trailing Stop + Partial Exit + 매크로 리스크 조절.

현재 고정 SL(-5%)/TP(+10%)을 보완:
  1. Trailing Stop: 수익 +5% 이상 → SL을 현재가 -3%로 동적 상향
  2. Partial Exit: 수익 +7% → 50% 분할 청산, 나머지는 trailing stop
  3. 매크로 RISK_OFF/CRISIS 시 trailing stop 파라미터 긴축

동작 방식 (_job_exit_check에서 호출):
  1. update_trailing_stops() — 모든 open 포지션의 high water mark 갱신, trailing SL 상향
  2. check_partial_exits() — partial exit 조건 충족 시 반환 (호출자가 실제 청산 처리)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

# 매크로 레짐별 trailing stop 조절
# activation: 낮을수록 빨리 활성화, distance: 좁을수록 빨리 청산
MACRO_TRAILING_ADJUSTMENT = {
    "RISK_ON":  {"activation_mult": 1.0, "distance_mult": 1.0},   # 기본값 유지
    "NEUTRAL":  {"activation_mult": 1.0, "distance_mult": 1.0},   # 기본값 유지
    "RISK_OFF": {"activation_mult": 0.6, "distance_mult": 0.7},   # 3% 활성화, 2.1% 거리
    "CRISIS":   {"activation_mult": 0.4, "distance_mult": 0.5},   # 2% 활성화, 1.5% 거리
}


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
    """Trailing Stop + Partial Exit 관리 + 매크로 리스크 조절."""

    def __init__(self, pg: PostgresStore, macro_scorer=None):
        self.pg = pg
        self.macro_scorer = macro_scorer

    def _get_config_float(self, key: str, default: float) -> float:
        return float(self.pg.get_config_value(key, str(default)))

    def update_trailing_stops(self, positions: list[dict], current_prices: dict[str, float]) -> int:
        """모든 open 포지션에 대해 trailing stop 업데이트 (매크로 레짐 반영).

        Returns: 업데이트된 포지션 수.
        """
        activation_pct = self._get_config_float("trailing_stop_activation", 0.05)
        trail_distance = self._get_config_float("trailing_stop_distance", 0.03)

        # 매크로 레짐별 trailing stop 긴축
        macro_enabled = self.pg.get_config_value("macro_enabled", "true") == "true"
        regime = self._get_macro_regime() if macro_enabled else "NEUTRAL"
        adj = MACRO_TRAILING_ADJUSTMENT.get(regime, MACRO_TRAILING_ADJUSTMENT["NEUTRAL"])
        activation_pct *= adj["activation_mult"]
        trail_distance *= adj["distance_mult"]

        if regime in ("RISK_OFF", "CRISIS"):
            logger.info(f"Macro {regime}: trailing tightened — "
                        f"activation={activation_pct:.1%}, distance={trail_distance:.1%}")

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
        """분할 청산 조건 체크 (매크로 레짐 반영).

        Returns: PartialExitAction 목록 (호출자가 실제 청산 처리).
        """
        threshold = self._get_config_float("partial_exit_threshold", 0.07)
        exit_pct = self._get_config_float("partial_exit_pct", 0.5)

        # 매크로 RISK_OFF/CRISIS: 더 일찍 부분 청산 (7%→5%→3.5%)
        macro_enabled = self.pg.get_config_value("macro_enabled", "true") == "true"
        if macro_enabled:
            regime = self._get_macro_regime()
            if regime == "RISK_OFF":
                threshold *= 0.7   # 7%→4.9% (더 일찍 이익 실현)
                exit_pct = min(exit_pct + 0.1, 0.7)  # 50%→60% 더 많이 청산
            elif regime == "CRISIS":
                threshold *= 0.5   # 7%→3.5%
                exit_pct = min(exit_pct + 0.2, 0.8)  # 50%→70%

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

    def _get_macro_regime(self) -> str:
        """현재 매크로 레짐 조회."""
        if self.macro_scorer:
            try:
                result = self.macro_scorer.calc_macro_score()
                return result.get("regime", "NEUTRAL")
            except Exception as e:
                logger.warning(f"Macro regime check failed: {e}")
        return "NEUTRAL"

    def get_trailing_params(self) -> dict:
        """현재 적용 중인 trailing stop 파라미터 (매크로 반영)."""
        activation = self._get_config_float("trailing_stop_activation", 0.05)
        distance = self._get_config_float("trailing_stop_distance", 0.03)
        partial_threshold = self._get_config_float("partial_exit_threshold", 0.07)
        partial_pct = self._get_config_float("partial_exit_pct", 0.5)

        macro_enabled = self.pg.get_config_value("macro_enabled", "true") == "true"
        regime = self._get_macro_regime() if macro_enabled else "NEUTRAL"
        adj = MACRO_TRAILING_ADJUSTMENT.get(regime, MACRO_TRAILING_ADJUSTMENT["NEUTRAL"])

        return {
            "regime": regime,
            "base_activation": 0.05,
            "base_distance": 0.03,
            "adjusted_activation": round(activation * adj["activation_mult"], 4),
            "adjusted_distance": round(distance * adj["distance_mult"], 4),
            "base_partial_threshold": 0.07,
            "adjusted_partial_threshold": round(
                partial_threshold * (0.7 if regime == "RISK_OFF" else 0.5 if regime == "CRISIS" else 1.0), 4),
            "adjusted_partial_pct": round(
                min(partial_pct + (0.1 if regime == "RISK_OFF" else 0.2 if regime == "CRISIS" else 0), 0.8), 2),
        }
