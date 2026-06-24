"""PositionManager — 포지션 사이징 + 리스크 제한 체크 + 매크로 리스크 조절."""

from __future__ import annotations

import logging
from datetime import datetime

from engine_v4.config.settings import SwingSettings
from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

# 매크로 레짐별 포지션 사이즈 배율
MACRO_POSITION_MULTIPLIER = {
    "RISK_ON":  1.0,    # 100% — 유리한 환경
    "NEUTRAL":  0.85,   # 85%  — 약간 보수적
    "RISK_OFF": 0.50,   # 50%  — 절반으로 축소
    "CRISIS":   0.0,    # 0%   — 신규 진입 차단
}


class PositionManager:
    """
    포지션 사이징 규칙:
    - 계좌의 5% per position
    - 동시 최대 4종목
    - 하루 최대 1건 진입
    - 가격 범위 $20~$80 (소액 계좌 대응)
    - 매크로 레짐에 따라 포지션 사이즈 동적 조절
    """

    def __init__(self, pg: PostgresStore, settings: SwingSettings,
                 macro_scorer=None):
        self.pg = pg
        self.cfg = settings
        self.macro_scorer = macro_scorer

    def can_open_position(self) -> tuple[bool, str]:
        """새 포지션 개시 가능 여부. (가능여부, 사유)"""
        # 0) 매크로 CRISIS 체크 — 신규 진입 차단
        macro_enabled = self.pg.get_config_value("macro_enabled", "true") == "true"
        if macro_enabled:
            regime = self._get_macro_regime()
            if regime == "CRISIS":
                return False, f"Macro regime CRISIS — new entries blocked"

        # 1) 최대 포지션 수 체크
        max_pos = int(self.pg.get_config_value("max_positions", str(self.cfg.max_positions)))
        open_count = self.pg.get_open_position_count()
        if open_count >= max_pos:
            return False, f"Max positions reached ({open_count}/{max_pos})"

        # 2) 일일 진입 제한
        max_daily = int(self.pg.get_config_value("max_daily_entries", str(self.cfg.max_daily_entries)))
        today_entries = self.pg.get_today_entry_count()
        if today_entries >= max_daily:
            return False, f"Daily entry limit reached ({today_entries}/{max_daily})"

        return True, "OK"

    def calculate_position_size(self, account_value_usd: float,
                                entry_price: float,
                                stop_loss: float | None = None) -> dict:
        """
        포지션 사이즈 계산 (매크로 레짐 + 집중 캡 반영).

        집중 캡(concentration_cap_enabled=true)은 base 수량에 3중 상한을 적용:
          1) 리스크 캡   : 스톱거리×수량 ≤ 계좌×max_risk_per_trade_pct (변동성 큰 종목 자동 축소)
          2) 명목 캡     : 수량×진입가 ≤ 계좌×max_position_pct_cap (단일종목 과집중 차단)
          3) 총노출 캡   : 기존 오픈 명목 + 신규 명목 ≤ 계좌×max_total_exposure_pct (현금버퍼 유지)
        1주조차 캡을 넘으면 qty=0 으로 반환 → 호출부가 진입 거부 (강제 1주 진입 금지).

        반환: {qty, amount, pct_of_account, macro_regime, macro_multiplier, cap_reason}
        """
        pct = float(self.pg.get_config_value("position_pct", str(self.cfg.position_pct)))

        # position_pct 안전 검증: 1 초과이면 % 단위로 입력한 것 → 소수로 변환
        if pct > 1.0:
            logger.warning(f"position_pct={pct} > 1.0 — treating as percentage, converting to {pct/100}")
            pct = pct / 100.0

        # 매크로 레짐 기반 사이즈 조절
        macro_enabled = self.pg.get_config_value("macro_enabled", "true") == "true"
        regime = "NEUTRAL"
        multiplier = 1.0
        if macro_enabled:
            regime = self._get_macro_regime()
            multiplier = MACRO_POSITION_MULTIPLIER.get(regime, 1.0)
            if multiplier < 1.0:
                logger.info(f"Macro regime {regime}: position size ×{multiplier:.0%}")

        adjusted_pct = pct * multiplier
        target_amount = account_value_usd * adjusted_pct
        base_qty = int(target_amount / entry_price) if entry_price > 0 else 0  # 목표 수량(내림)

        # ── 집중 캡: 각 캡을 '허용 상한(ceiling)'으로 계산 ──
        # 목표가 0주로 내림돼도 1주가 모든 캡 이내면 허용, 1주조차 초과면 거부.
        cap_reason = ""
        cap_enabled = self.pg.get_config_value("concentration_cap_enabled", "true") == "true"
        if cap_enabled and account_value_usd > 0 and entry_price > 0:
            ceilings = []  # (max_qty, reason)

            # 1) 리스크 캡 (스톱거리 기반) — 변동성 큰(스톱 먼) 종목 자동 축소
            if stop_loss and stop_loss > 0 and stop_loss < entry_price:
                max_risk_pct = float(self.pg.get_config_value("max_risk_per_trade_pct", "0.015"))
                risk_per_share = entry_price - stop_loss
                ceilings.append((int((account_value_usd * max_risk_pct) / risk_per_share), "risk_cap"))

            # 2) 명목 캡 (단일 종목 상한)
            max_pos_cap = float(self.pg.get_config_value("max_position_pct_cap", "0.20"))
            ceilings.append((int((account_value_usd * max_pos_cap) / entry_price), "notional_cap"))

            # 3) 총노출 캡 (기존 오픈 명목 합 + 신규)
            max_total = float(self.pg.get_config_value("max_total_exposure_pct", "0.90"))
            room = account_value_usd * max_total - self._get_open_exposure_usd()
            ceilings.append((int(room / entry_price) if room > 0 else 0, "total_exposure_cap"))

            max_allowed, bind_reason = min(ceilings, key=lambda c: c[0])
            # 목표가 0이면 1주 시도 (소액계좌 고가주 대응), 단 캡 상한 내에서만
            desired = base_qty if base_qty >= 1 else 1
            qty = min(desired, max_allowed)
            if qty < desired:
                cap_reason = bind_reason
        else:
            qty = base_qty if base_qty >= 1 else 1

        if qty < 1:
            # 1주조차 캡 초과 → 진입 거부 (강제 1주 진입 금지)
            return {
                "qty": 0,
                "amount": 0.0,
                "pct_of_account": 0.0,
                "macro_regime": regime,
                "macro_multiplier": multiplier,
                "cap_reason": cap_reason or "below_min",
            }

        actual_amount = qty * entry_price
        actual_pct = actual_amount / account_value_usd if account_value_usd > 0 else 0

        return {
            "qty": qty,
            "amount": round(actual_amount, 2),
            "pct_of_account": round(actual_pct, 4),
            "macro_regime": regime,
            "macro_multiplier": multiplier,
            "cap_reason": cap_reason,
        }

    def _get_open_exposure_usd(self) -> float:
        """현재 오픈 포지션 명목가치 합 (entry_price × qty)."""
        try:
            positions = self.pg.get_open_positions()
            return sum(float(p.get("entry_price") or 0) * float(p.get("qty") or 0)
                       for p in positions)
        except Exception as e:
            logger.warning(f"open exposure calc failed: {e}")
            return 0.0

    def validate_entry(self, symbol: str, entry_price: float) -> tuple[bool, str]:
        """진입 시그널 종합 검증."""
        # 1) 포지션 제한
        can_open, reason = self.can_open_position()
        if not can_open:
            return False, reason

        # 2) 중복 포지션
        if self.pg.has_open_position(symbol):
            return False, f"Already have open position for {symbol}"

        # 3) 가격 범위
        price_min = float(self.pg.get_config_value("price_range_min", str(self.cfg.price_range_min)))
        price_max = float(self.pg.get_config_value("price_range_max", str(self.cfg.price_range_max)))
        if entry_price < price_min or entry_price > price_max:
            return False, f"Price ${entry_price:.2f} outside range ${price_min}-${price_max}"

        return True, "OK"

    def execute_entry(self, signal: dict, account_value_usd: float) -> dict | None:
        """
        진입 시그널 실행: 포지션 오픈 + 거래 기록.
        KIS 주문은 별도 broker/kis_client에서 처리.
        여기서는 DB 기록만.
        """
        symbol = signal["symbol"]
        entry_price = float(signal["entry_price"])

        valid, reason = self.validate_entry(symbol, entry_price)
        if not valid:
            logger.warning(f"Entry rejected for {symbol}: {reason}")
            return None

        stop_loss = float(signal["stop_loss"]) if signal.get("stop_loss") else None
        sizing = self.calculate_position_size(account_value_usd, entry_price, stop_loss)

        # 집중 캡으로 1주조차 불가 → 진입 거부 (강제 1주 진입 금지)
        if sizing["qty"] < 1:
            logger.warning(
                f"Entry rejected for {symbol}: concentration cap "
                f"({sizing.get('cap_reason')}) — ${entry_price:.2f} too large "
                f"for account ${account_value_usd:.2f}")
            return None

        is_paper = self.pg.get_config_value("trading_mode", "paper") == "paper"

        # 포지션 오픈
        position_id = self.pg.open_position({
            "symbol": symbol,
            "side": "BUY",
            "qty": sizing["qty"],
            "entry_price": entry_price,
            "stop_loss": signal.get("stop_loss"),
            "take_profit": signal.get("take_profit"),
            "signal_id": signal.get("signal_id"),
            "is_paper": is_paper,
        })

        # 거래 기록
        trade_id = self.pg.insert_trade({
            "position_id": position_id,
            "signal_id": signal.get("signal_id"),
            "symbol": symbol,
            "side": "BUY",
            "qty": sizing["qty"],
            "price": entry_price,
            "is_paper": is_paper,
        })

        # 시그널 상태 업데이트 (position_id 역참조 포함)
        if signal.get("signal_id"):
            self.pg.mark_signal_executed(signal["signal_id"], position_id)

        # ATR 기반 청산 파라미터 설정
        try:
            from engine_v4.risk.exit_manager import ExitManager
            exit_mgr = ExitManager(self.pg, macro_scorer=self.macro_scorer)
            atr_result = exit_mgr.setup_position_atr(
                position_id, symbol, entry_price)
            if atr_result:
                # Hard stop을 ATR 기반으로 업데이트
                self.pg.update_position_stop_loss(
                    position_id, atr_result["hard_stop"])
                logger.info(f"ATR-based hard stop set: ${atr_result['hard_stop']:.2f} "
                            f"(ATR={atr_result['atr']:.2f})")
        except Exception as e:
            logger.warning(f"ATR setup failed for {symbol}: {e}")

        logger.info(f"Opened position #{position_id}: {symbol} "
                    f"{sizing['qty']} shares @ ${entry_price:.2f} "
                    f"(${sizing['amount']:.2f}, {sizing['pct_of_account']:.1%})")

        return {
            "position_id": position_id,
            "trade_id": trade_id,
            "symbol": symbol,
            "qty": sizing["qty"],
            "entry_price": entry_price,
            "amount": sizing["amount"],
        }

    def execute_exit(self, signal: dict) -> dict | None:
        """
        청산 시그널 실행: 포지션 클로즈 + 거래 기록.
        """
        position_id = signal.get("position_id")
        if not position_id:
            logger.error("Exit signal has no position_id")
            return None

        # 기존 포지션 조회
        positions = self.pg.get_open_positions()
        pos = next((p for p in positions if p["position_id"] == position_id), None)
        if not pos:
            logger.warning(f"Position #{position_id} not found or already closed")
            return None

        exit_price = float(signal["entry_price"])  # exit signal의 entry_price = 현재가
        exit_reason = signal.get("exit_reason", "manual")
        qty = float(pos["qty"])
        is_paper = bool(pos.get("is_paper", True))

        # 포지션 종료
        self.pg.close_position(position_id, exit_price, exit_reason)

        # 거래 기록
        trade_id = self.pg.insert_trade({
            "position_id": position_id,
            "signal_id": signal.get("signal_id"),
            "symbol": pos["symbol"],
            "side": "SELL",
            "qty": qty,
            "price": exit_price,
            "is_paper": is_paper,
        })

        # 시그널 상태 업데이트
        if signal.get("signal_id"):
            self.pg.mark_signal_executed(signal["signal_id"], position_id)

        pnl = (exit_price - float(pos["entry_price"])) * qty
        logger.info(f"Closed position #{position_id}: {pos['symbol']} "
                    f"@ ${exit_price:.2f} reason={exit_reason} "
                    f"P&L=${pnl:+.2f}")

        return {
            "position_id": position_id,
            "trade_id": trade_id,
            "symbol": pos["symbol"],
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl": round(pnl, 2),
        }

    def _get_macro_regime(self) -> str:
        """현재 매크로 레짐 조회 (캐시된 매크로 스코어 기반)."""
        if self.macro_scorer:
            try:
                result = self.macro_scorer.calc_macro_score()
                return result.get("regime", "NEUTRAL")
            except Exception as e:
                logger.warning(f"Macro regime check failed: {e}")
        return "NEUTRAL"

    def get_risk_adjustment(self) -> dict:
        """현재 매크로 리스크 조절 상태 반환."""
        macro_enabled = self.pg.get_config_value("macro_enabled", "true") == "true"
        if not macro_enabled:
            return {"enabled": False, "regime": "NEUTRAL", "multiplier": 1.0,
                    "entry_blocked": False}

        regime = self._get_macro_regime()
        multiplier = MACRO_POSITION_MULTIPLIER.get(regime, 1.0)
        base_pct = float(self.pg.get_config_value("position_pct", str(self.cfg.position_pct)))
        adjusted_pct = base_pct * multiplier

        cap_enabled = self.pg.get_config_value("concentration_cap_enabled", "true") == "true"
        account_value = 0.0
        snap = self.pg.get_latest_snapshot()
        if snap and snap.get("total_value_usd"):
            account_value = float(snap["total_value_usd"])

        return {
            "enabled": True,
            "regime": regime,
            "multiplier": multiplier,
            "base_position_pct": base_pct,
            "adjusted_position_pct": round(adjusted_pct, 4),
            "entry_blocked": regime == "CRISIS",
            "concentration_cap": {
                "enabled": cap_enabled,
                "max_position_pct_cap": float(self.pg.get_config_value("max_position_pct_cap", "0.20")),
                "max_risk_per_trade_pct": float(self.pg.get_config_value("max_risk_per_trade_pct", "0.015")),
                "max_total_exposure_pct": float(self.pg.get_config_value("max_total_exposure_pct", "0.90")),
                "current_exposure_usd": round(self._get_open_exposure_usd(), 2),
                "current_exposure_pct": round(self._get_open_exposure_usd() / account_value, 4) if account_value > 0 else None,
            },
        }
