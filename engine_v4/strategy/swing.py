"""SwingStrategy — 진입 4조건 + 청산 3조건 기반 스윙 전략."""

from __future__ import annotations

import logging
from datetime import datetime

from engine_v4.config.settings import SwingSettings
from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)


class SwingStrategy:
    """
    진입 조건 (ALL 충족):
      1. 20일 수익률 상위 40% (return_20d_rank ≥ 0.6)
      2. 추세 정렬 (Close > SMA50 > SMA200)
      3. 5일 고점 돌파 (breakout_5d)
      4. 거래량 급증 (volume_ratio > 1.5)

    청산 조건 (ANY 충족):
      1. 손절 -5% (stop_loss)
      2. 익절 +10% (take_profit)
      3. 추세 이탈 (Close < SMA50)
    """

    def __init__(self, pg: PostgresStore, settings: SwingSettings):
        self.pg = pg
        self.cfg = settings

    def scan_entries(self) -> list[dict]:
        """진입 시그널 스캔 → swing_signals 생성."""
        indicators = self.pg.get_latest_indicators()
        if not indicators:
            logger.warning("No indicators available for entry scan")
            return []

        # 런타임 설정 오버라이드
        rank_min = float(self.pg.get_config_value("return_rank_min", str(self.cfg.return_rank_min)))
        price_min = float(self.pg.get_config_value("price_range_min", str(self.cfg.price_range_min)))
        price_max = float(self.pg.get_config_value("price_range_max", str(self.cfg.price_range_max)))

        signals = []
        for ind in indicators:
            symbol = ind["symbol"]

            # 이미 오픈 포지션 있으면 스킵
            if self.pg.has_open_position(symbol):
                continue

            # 가격 범위 필터 (소액 계좌 대응)
            close = float(ind["close"])
            if close < price_min or close > price_max:
                continue

            # 4조건 체크
            rank_ok = (ind["return_20d_rank"] or 0) >= rank_min
            trend_ok = bool(ind["trend_aligned"])
            breakout_ok = bool(ind["breakout_5d"])
            volume_ok = bool(ind["volume_surge"])

            if rank_ok and trend_ok and breakout_ok and volume_ok:
                stop_loss = round(close * (1 + self.cfg.stop_loss_pct), 4)
                take_profit = round(close * (1 + self.cfg.take_profit_pct), 4)

                sig = {
                    "symbol": symbol,
                    "signal_type": "ENTRY",
                    "entry_price": close,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "return_20d_rank": ind["return_20d_rank"],
                    "trend_aligned": True,
                    "breakout_5d": True,
                    "volume_surge": True,
                    "status": "pending",
                }
                signal_id = self.pg.insert_signal(sig)
                sig["signal_id"] = signal_id
                signals.append(sig)
                logger.info(f"ENTRY signal: {symbol} @ ${close:.2f} "
                            f"(SL=${stop_loss:.2f}, TP=${take_profit:.2f})")

        logger.info(f"Entry scan: {len(signals)} signals from {len(indicators)} stocks")
        return signals

    def scan_exits(self) -> list[dict]:
        """청산 시그널 스캔 → swing_signals 생성."""
        positions = self.pg.get_open_positions()
        if not positions:
            logger.info("No open positions for exit scan")
            return []

        signals = []
        for pos in positions:
            symbol = pos["symbol"]
            entry_price = float(pos["entry_price"])
            position_id = pos["position_id"]

            # 최신 지표 조회
            history = self.pg.get_indicator_history(symbol, days=5)
            if not history:
                continue
            latest = history[-1]
            current_price = float(latest["close"])

            # 포지션 현재가 업데이트
            self.pg.update_position_price(position_id, current_price)

            # 수익률
            pnl_pct = (current_price - entry_price) / entry_price
            exit_reason = None

            # 청산 3조건 (OR)
            stop_loss_pct = float(self.pg.get_config_value(
                "stop_loss_pct", str(self.cfg.stop_loss_pct)))
            take_profit_pct = float(self.pg.get_config_value(
                "take_profit_pct", str(self.cfg.take_profit_pct)))

            if pnl_pct <= stop_loss_pct:
                exit_reason = "stop_loss"
            elif pnl_pct >= take_profit_pct:
                exit_reason = "take_profit"
            elif not latest.get("trend_aligned", True):
                # Close < SMA50 → 추세 이탈
                exit_reason = "trend_break"

            if exit_reason:
                sig = {
                    "symbol": symbol,
                    "signal_type": "EXIT",
                    "entry_price": current_price,
                    "exit_reason": exit_reason,
                    "position_id": position_id,
                    "return_20d_rank": latest.get("return_20d_rank"),
                    "trend_aligned": latest.get("trend_aligned"),
                    "breakout_5d": latest.get("breakout_5d"),
                    "volume_surge": latest.get("volume_surge"),
                    "status": "pending",
                }
                signal_id = self.pg.insert_signal(sig)
                sig["signal_id"] = signal_id
                signals.append(sig)
                logger.info(f"EXIT signal: {symbol} @ ${current_price:.2f} "
                            f"reason={exit_reason} pnl={pnl_pct:+.2%}")

        logger.info(f"Exit scan: {len(signals)} signals from {len(positions)} positions")
        return signals
