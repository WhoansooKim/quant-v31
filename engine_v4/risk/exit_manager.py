"""5-Layer Auto-Exit Strategy Manager.

연구 기반 복합 청산 전략:
  Layer 1: ATR Trailing Stop — 2.5×ATR(14) trailing from HWM (+1R 이상 수익 시 활성화)
  Layer 2: Hard Stop-Loss — 1.5×ATR(14) below entry (절대 손실 제한)
  Layer 3: Time Stop — 15 거래일 이후 무조건 청산 (자본 효율성)
  Layer 4: RSI(2) Override — RSI(2) > 90 시 즉시 매도 (과매수 탈출)
  Layer 5: Regime Adaptation — 고변동: 3.0×ATR, 저변동: 2.0×ATR

동작 방식:
  1. 진입 시: ATR(14) 계산 → entry_atr + hard_stop 설정
  2. 장중 체크 (3회/일): 5개 레이어 순차 평가 → 매도 조건 발생 시 auto-execute
  3. 부분 청산은 기존대로 유지 (partial_exit)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)


@dataclass
class ExitAction:
    """청산 지시 (자동 실행용)."""
    position_id: int
    symbol: str
    current_price: float
    exit_qty: float
    exit_reason: str
    gain_pct: float
    layer: str  # which layer triggered


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
    """5-Layer Auto-Exit Strategy + Partial Exit + Macro Regime."""

    def __init__(self, pg: PostgresStore, macro_scorer=None):
        self.pg = pg
        self.macro_scorer = macro_scorer

    def _get_config_float(self, key: str, default: float) -> float:
        return float(self.pg.get_config_value(key, str(default)))

    def _get_config_bool(self, key: str, default: bool = True) -> bool:
        return self.pg.get_config_value(key, str(default).lower()) == "true"

    # ─── ATR Calculation ─────────────────────────────────

    def calc_atr(self, symbol: str, period: int = 14) -> float | None:
        """ATR(14) 계산 — daily_prices 기반."""
        # 거래일 기준 period+1 필요 → 캘린더일 기준 약 1.5배 요청
        prices = self.pg.get_daily_prices(symbol, days=int(period * 2.5))
        if len(prices) < period + 1:
            return None

        trs = []
        for i in range(1, len(prices)):
            h = float(prices[i]["high"])
            l = float(prices[i]["low"])
            prev_c = float(prices[i - 1]["close"])
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)

        if len(trs) < period:
            return None

        # Wilder smoothed ATR
        atr = np.mean(trs[:period])
        for tr in trs[period:]:
            atr = (atr * (period - 1) + tr) / period

        return round(float(atr), 4)

    def calc_rsi(self, symbol: str, period: int = 2) -> float | None:
        """RSI(2) 계산 — 극단적 과매수 탈출용."""
        prices = self.pg.get_daily_prices(symbol, days=int(period * 2.5) + 10)
        if len(prices) < period + 1:
            return None

        closes = [float(p["close"]) for p in prices]
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

        if len(deltas) < period:
            return None

        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    # ─── Position Entry Setup ────────────────────────────

    def setup_position_atr(self, position_id: int, symbol: str,
                           entry_price: float) -> dict | None:
        """진입 시 ATR(14) 계산 → entry_atr, hard_stop 설정.

        Returns: {"atr": float, "hard_stop": float} or None
        """
        atr = self.calc_atr(symbol)
        if not atr:
            logger.warning(f"Cannot calc ATR for {symbol} — using fallback %")
            return None

        hard_stop_mult = self._get_config_float("atr_hard_stop_multiplier", 1.5)
        hard_stop = round(entry_price - (hard_stop_mult * atr), 4)

        with self.pg.get_conn() as conn:
            conn.execute("""
                UPDATE swing_positions
                SET atr_14 = %s, entry_atr = %s, hard_stop = %s
                WHERE position_id = %s AND status = 'open'
            """, (atr, atr, hard_stop, position_id))
            conn.commit()

        logger.info(f"ATR setup for {symbol} #{position_id}: "
                    f"ATR={atr:.2f}, hard_stop=${hard_stop:.2f} "
                    f"(entry=${entry_price:.2f} - {hard_stop_mult}×{atr:.2f})")
        return {"atr": atr, "hard_stop": hard_stop}

    # ─── 5-Layer Exit Check ──────────────────────────────

    def check_exits(self, positions: list[dict],
                    current_prices: dict[str, float]) -> list[ExitAction]:
        """5-Layer 복합 청산 조건 체크.

        Returns: ExitAction 목록 (호출자가 auto-execute).
        """
        actions = []

        # Config
        trail_mult = self._get_config_float("atr_trailing_multiplier", 2.5)
        hard_stop_mult = self._get_config_float("atr_hard_stop_multiplier", 1.5)
        time_stop_days = int(self._get_config_float("time_stop_days", 15))
        rsi2_threshold = self._get_config_float("rsi2_exit_threshold", 90)
        activation_r = self._get_config_float("atr_trailing_activation_r", 1.0)

        # Regime adaptation
        regime = self._get_macro_regime()
        regime_mult = self._get_regime_atr_multiplier(regime, trail_mult)

        if regime_mult != trail_mult:
            logger.info(f"Regime {regime}: ATR trailing {trail_mult}× → {regime_mult}×")

        for pos in positions:
            symbol = pos["symbol"]
            pid = pos["position_id"]
            entry_price = float(pos["entry_price"])
            current_price = current_prices.get(symbol)
            if not current_price:
                continue

            qty = float(pos.get("qty") or 1)
            gain_pct = (current_price - entry_price) / entry_price
            entry_atr = float(pos.get("entry_atr") or 0)

            # === Layer 2: Hard Stop-Loss (1.5×ATR below entry) ===
            hard_stop = float(pos.get("hard_stop") or 0)
            if not hard_stop and entry_atr > 0:
                hard_stop = entry_price - (hard_stop_mult * entry_atr)
            elif not hard_stop:
                # Fallback: 기존 고정 SL
                hard_stop = entry_price * 0.95

            if current_price <= hard_stop:
                actions.append(ExitAction(
                    position_id=pid, symbol=symbol,
                    current_price=current_price, exit_qty=qty,
                    exit_reason="hard_stop",
                    gain_pct=gain_pct, layer="L2_HardStop"))
                logger.info(f"L2 HARD STOP: {symbol} ${current_price:.2f} <= "
                            f"${hard_stop:.2f} (entry ${entry_price:.2f} - "
                            f"{hard_stop_mult}×ATR)")
                continue  # 하위 레이어 skip

            # === Layer 4: RSI(2) Override (RSI > 90 즉시 매도) ===
            if gain_pct > 0:  # 수익 중일 때만
                rsi2 = self.calc_rsi(symbol, period=2)
                if rsi2 is not None and rsi2 > rsi2_threshold:
                    actions.append(ExitAction(
                        position_id=pid, symbol=symbol,
                        current_price=current_price, exit_qty=qty,
                        exit_reason="rsi2_overbought",
                        gain_pct=gain_pct, layer="L4_RSI2"))
                    logger.info(f"L4 RSI(2) OVERRIDE: {symbol} RSI(2)={rsi2:.1f} > "
                                f"{rsi2_threshold}, gain={gain_pct:+.1%}")
                    continue

            # === Layer 3: Time Stop (15 거래일) ===
            entry_time = pos.get("entry_time")
            if entry_time:
                if isinstance(entry_time, str):
                    entry_time = datetime.fromisoformat(entry_time)
                hold_days = (datetime.now(entry_time.tzinfo) - entry_time).days
                if hold_days >= time_stop_days:
                    actions.append(ExitAction(
                        position_id=pid, symbol=symbol,
                        current_price=current_price, exit_qty=qty,
                        exit_reason="time_stop",
                        gain_pct=gain_pct, layer="L3_TimeStop"))
                    logger.info(f"L3 TIME STOP: {symbol} held {hold_days} days "
                                f">= {time_stop_days} (gain={gain_pct:+.1%})")
                    continue

            # === Layer 1: ATR Trailing Stop (regime-adaptive) ===
            if entry_atr > 0:
                # Activation: 수익이 1R (=1×ATR) 이상일 때 trailing 시작
                r_multiple = (current_price - entry_price) / entry_atr if entry_atr else 0
                hwm = float(pos.get("high_water_mark") or entry_price)
                trailing_active = bool(pos.get("trailing_stop_active"))

                # HWM 갱신
                if current_price > hwm:
                    hwm = current_price
                    self.pg.update_high_water_mark(pid, hwm)

                # Trailing 활성화
                if not trailing_active and r_multiple >= activation_r:
                    trailing_active = True
                    self.pg.activate_trailing_stop(pid)
                    logger.info(f"L1 ATR Trailing ACTIVATED: {symbol} R={r_multiple:.1f} "
                                f">= {activation_r}R")

                # Trailing SL 계산
                if trailing_active:
                    trail_sl = hwm - (regime_mult * entry_atr)
                    old_sl = float(pos.get("stop_loss") or hard_stop)

                    # SL은 올리기만 (내리지 않음)
                    if trail_sl > old_sl:
                        self.pg.update_position_stop_loss(pid, round(trail_sl, 4))
                        logger.info(f"L1 ATR Trail SL raised: {symbol} "
                                    f"${old_sl:.2f} → ${trail_sl:.2f} "
                                    f"(HWM=${hwm:.2f} - {regime_mult}×{entry_atr:.2f})")

                    if current_price <= trail_sl and trail_sl > old_sl:
                        # Trailing stop hit (only if trail_sl was raised above old_sl)
                        pass  # Let existing stop_loss check handle it below

                    # Check if current price breaks trailing stop
                    effective_sl = max(trail_sl, old_sl)
                    if current_price <= effective_sl and trailing_active:
                        actions.append(ExitAction(
                            position_id=pid, symbol=symbol,
                            current_price=current_price, exit_qty=qty,
                            exit_reason="atr_trailing_stop",
                            gain_pct=gain_pct, layer="L1_ATRTrail"))
                        logger.info(f"L1 ATR TRAILING STOP: {symbol} "
                                    f"${current_price:.2f} <= ${effective_sl:.2f}")
                        continue

            # === Fallback: 기존 고정 SL/TP ===
            stop_loss_pct = self._get_config_float("stop_loss_pct", -0.05)
            take_profit_pct = self._get_config_float("take_profit_pct", 0.10)
            current_sl = float(pos.get("stop_loss") or (entry_price * (1 + stop_loss_pct)))

            if current_price <= current_sl:
                actions.append(ExitAction(
                    position_id=pid, symbol=symbol,
                    current_price=current_price, exit_qty=qty,
                    exit_reason="stop_loss",
                    gain_pct=gain_pct, layer="Fallback_SL"))
                logger.info(f"FALLBACK SL: {symbol} ${current_price:.2f} <= "
                            f"SL ${current_sl:.2f}")
            elif gain_pct >= take_profit_pct:
                actions.append(ExitAction(
                    position_id=pid, symbol=symbol,
                    current_price=current_price, exit_qty=qty,
                    exit_reason="take_profit",
                    gain_pct=gain_pct, layer="Fallback_TP"))
                logger.info(f"FALLBACK TP: {symbol} gain={gain_pct:+.1%} >= "
                            f"{take_profit_pct:+.1%}")

        return actions

    # ─── Partial Exit (기존 유지) ────────────────────────

    def check_partial_exits(self, positions: list[dict],
                            current_prices: dict[str, float]) -> list[PartialExitAction]:
        """분할 청산 조건 체크 (매크로 레짐 반영)."""
        threshold = self._get_config_float("partial_exit_threshold", 0.07)
        exit_pct = self._get_config_float("partial_exit_pct", 0.5)

        macro_enabled = self._get_config_bool("macro_enabled", True)
        if macro_enabled:
            regime = self._get_macro_regime()
            if regime == "RISK_OFF":
                threshold *= 0.7
                exit_pct = min(exit_pct + 0.1, 0.7)
            elif regime == "CRISIS":
                threshold *= 0.5
                exit_pct = min(exit_pct + 0.2, 0.8)

        actions = []
        for pos in positions:
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
                logger.info(f"PARTIAL EXIT signal: {symbol} gain={gain_pct:+.1%}, "
                            f"sell {exit_qty}/{qty} shares @ ${current_price:.2f}")

        return actions

    # ─── Legacy compatibility ────────────────────────────

    def update_trailing_stops(self, positions: list[dict],
                              current_prices: dict[str, float]) -> int:
        """기존 호환: HWM 갱신 + trailing SL 상향 (check_exits에서도 수행).

        Returns: 업데이트된 포지션 수.
        """
        # check_exits가 trailing도 처리하므로 HWM만 갱신
        updated = 0
        for pos in positions:
            symbol = pos["symbol"]
            pid = pos["position_id"]
            current_price = current_prices.get(symbol)
            if not current_price:
                continue
            hwm = float(pos.get("high_water_mark") or float(pos["entry_price"]))
            if current_price > hwm:
                self.pg.update_high_water_mark(pid, current_price)
                updated += 1
        return updated

    # ─── Regime Helpers ──────────────────────────────────

    def _get_macro_regime(self) -> str:
        if self.macro_scorer:
            try:
                result = self.macro_scorer.calc_macro_score()
                return result.get("regime", "NEUTRAL")
            except Exception as e:
                logger.warning(f"Macro regime check failed: {e}")
        return "NEUTRAL"

    def _get_regime_atr_multiplier(self, regime: str,
                                    base_mult: float) -> float:
        """Layer 5: Regime-adaptive ATR multiplier."""
        if regime == "CRISIS":
            # Crisis: tighter stop (low multiplier = closer to HWM)
            return self._get_config_float("atr_regime_low_vol", 2.0)
        elif regime == "RISK_OFF":
            return self._get_config_float("atr_regime_low_vol", 2.0)
        elif regime == "RISK_ON":
            # Risk-on/trending: wider stop (high multiplier = more room)
            return self._get_config_float("atr_regime_high_vol", 3.0)
        return base_mult  # NEUTRAL = base

    def get_exit_params(self) -> dict:
        """현재 적용 중인 5-layer exit 파라미터."""
        regime = self._get_macro_regime()
        trail_mult = self._get_config_float("atr_trailing_multiplier", 2.5)

        return {
            "auto_sell_enabled": self._get_config_bool("auto_sell_enabled", True),
            "regime": regime,
            "atr_trailing_multiplier": trail_mult,
            "atr_regime_adjusted": self._get_regime_atr_multiplier(regime, trail_mult),
            "atr_hard_stop_multiplier": self._get_config_float("atr_hard_stop_multiplier", 1.5),
            "atr_trailing_activation_r": self._get_config_float("atr_trailing_activation_r", 1.0),
            "time_stop_days": int(self._get_config_float("time_stop_days", 15)),
            "rsi2_exit_threshold": self._get_config_float("rsi2_exit_threshold", 90),
            "partial_exit_threshold": self._get_config_float("partial_exit_threshold", 0.07),
            "partial_exit_pct": self._get_config_float("partial_exit_pct", 0.5),
            "stop_loss_pct": self._get_config_float("stop_loss_pct", -0.05),
            "take_profit_pct": self._get_config_float("take_profit_pct", 0.10),
        }

    # Legacy alias
    def get_trailing_params(self) -> dict:
        return self.get_exit_params()
