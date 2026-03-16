"""SwingStrategy — 진입 4조건 + 이중 정렬 + 청산 3조건 기반 스윙 전략."""

from __future__ import annotations

import logging
from datetime import datetime

from engine_v4.config.settings import SwingSettings
from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)


class SwingStrategy:
    """
    진입 조건 (ALL 충족):
      1. 추세 정렬 (Close > SMA50 > SMA200)
      2. 5일 고점 돌파 (breakout_5d)
      3. 거래량 급증 (volume_ratio > 1.5)
      4a. [기본] 20일 수익률 상위 40% (return_20d_rank ≥ 0.6)
      4b. [이중 정렬] 모멘텀+가치 합산 순위 상위 50%

    청산 조건 (ANY 충족):
      1. 손절 -5% (stop_loss)
      2. 익절 +10% (take_profit)
      3. 추세 이탈 (Close < SMA50)
    """

    def __init__(self, pg: PostgresStore, settings: SwingSettings,
                 finnhub=None):
        self.pg = pg
        self.cfg = settings
        self.finnhub = finnhub  # FinnhubClient (optional, for value scoring)

    # ─── Value Score (lightweight) ────────────────────
    def _quick_value_score(self, symbol: str) -> float:
        """Finnhub 재무 지표로 간이 Value Score (0~1) 산출.

        Finnhub 없으면 0.5 (neutral) 반환.
        """
        if not self.finnhub or not self.finnhub.is_available:
            return 0.5

        try:
            fin = self.finnhub.get_basic_financials(symbol)
            if not fin:
                return 0.5

            score = 0.0
            total = 0.0

            # P/E (낮을수록 좋음)
            pe = fin.get("pe_ttm")
            if pe and pe > 0:
                if pe < 15:
                    score += 30
                elif pe < 20:
                    score += 20
                elif pe < 30:
                    score += 10
                total += 30

            # P/B (낮을수록 좋음)
            pb = fin.get("pb_ratio")
            if pb and pb > 0:
                if pb < 2:
                    score += 25
                elif pb < 3:
                    score += 15
                elif pb < 5:
                    score += 10
                total += 25

            # FCF Yield (높을수록 좋음)
            fcf = fin.get("fcf_yield")
            if fcf is not None:
                if fcf > 5:
                    score += 25
                elif fcf > 3:
                    score += 15
                elif fcf > 1:
                    score += 10
                total += 25

            # EV/EBITDA (낮을수록 좋음)
            ev = fin.get("ev_ebitda")
            if ev and ev > 0:
                if ev < 10:
                    score += 20
                elif ev < 15:
                    score += 12
                elif ev < 20:
                    score += 5
                total += 20

            return (score / total) if total > 0 else 0.5
        except Exception:
            return 0.5

    # ─── Dual Sort Filter ─────────────────────────────
    def _apply_dual_sort(self, candidates: list[dict]) -> list[dict]:
        """모멘텀+가치 이중 정렬로 후보 필터링.

        candidates: [{"symbol", "return_20d_rank", ...ind dict}]
        Returns: 이중 정렬 상위 종목만 포함된 리스트.
        """
        m_w = float(self.pg.get_config_value("dual_sort_momentum_weight", "0.5"))
        v_w = float(self.pg.get_config_value("dual_sort_value_weight", "0.5"))
        threshold = float(self.pg.get_config_value("dual_sort_threshold", "0.5"))

        # 종목별 가치 점수 수집
        for c in candidates:
            c["_value_rank"] = self._quick_value_score(c["symbol"])
            c["_momentum_rank"] = float(c.get("return_20d_rank") or 0)

        # 합산 점수 계산
        for c in candidates:
            c["_combined_rank"] = (
                c["_momentum_rank"] * m_w + c["_value_rank"] * v_w
            )

        # 필터링
        passed = [c for c in candidates if c["_combined_rank"] >= threshold]

        # 높은 순 정렬
        passed.sort(key=lambda x: x["_combined_rank"], reverse=True)

        logger.info(
            f"Dual sort: {len(candidates)} candidates → "
            f"{len(passed)} passed (threshold={threshold:.2f})"
        )
        return passed

    def scan_entries(self) -> list[dict]:
        """진입 시그널 스캔 → swing_signals 생성."""
        indicators = self.pg.get_latest_indicators()
        if not indicators:
            logger.warning("No indicators available for entry scan")
            return []

        # 런타임 설정 오버라이드
        dual_sort = self.pg.get_config_value("dual_sort_enabled", "true") == "true"
        rank_min = float(self.pg.get_config_value("return_rank_min", str(self.cfg.return_rank_min)))
        price_min = float(self.pg.get_config_value("price_range_min", str(self.cfg.price_range_min)))
        price_max = float(self.pg.get_config_value("price_range_max", str(self.cfg.price_range_max)))

        # Step 1: 기본 필터 (추세/브레이크아웃/거래량/가격) 통과 후보
        candidates = []
        for ind in indicators:
            symbol = ind["symbol"]

            if self.pg.has_open_position(symbol):
                continue

            close = float(ind["close"])
            if close < price_min or close > price_max:
                continue

            trend_ok = bool(ind["trend_aligned"])
            breakout_ok = bool(ind["breakout_5d"])
            volume_ok = bool(ind["volume_surge"])

            if not (trend_ok and breakout_ok and volume_ok):
                continue

            if dual_sort:
                # 이중 정렬: 모멘텀 순위 기준은 나중에 합산으로 처리
                candidates.append(ind)
            else:
                # 기존 방식: 모멘텀 상위만 통과
                rank_ok = (ind["return_20d_rank"] or 0) >= rank_min
                if rank_ok:
                    candidates.append(ind)

        # Step 2: 이중 정렬 필터 적용
        if dual_sort and candidates:
            candidates = self._apply_dual_sort(candidates)

        # Step 3: 시그널 생성
        signals = []
        for ind in candidates:
            symbol = ind["symbol"]
            close = float(ind["close"])
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

            extra = ""
            if dual_sort:
                cr = ind.get("_combined_rank", 0)
                extra = f" combined_rank={cr:.2f}"
            logger.info(f"ENTRY signal: {symbol} @ ${close:.2f} "
                        f"(SL=${stop_loss:.2f}, TP=${take_profit:.2f}){extra}")

        mode = "dual_sort" if dual_sort else "momentum"
        logger.info(f"Entry scan [{mode}]: {len(signals)} signals from {len(indicators)} stocks")
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
