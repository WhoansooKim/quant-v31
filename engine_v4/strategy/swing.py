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
        # 마지막 scan_entries 진입 깔때기 (진입 0일 때 "왜 없는지" 설명용)
        self._last_entry_funnel: dict | None = None

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
            self._last_entry_funnel = {
                "total": 0, "price_ok": 0, "trend": 0, "breakout": 0,
                "volume": 0, "three_cond": 0, "passed_basic": 0, "final": 0,
                "message": "진입 시그널 0 — 지표 데이터가 없습니다(수집/지표계산 확인 필요).",
            }
            return []

        # 런타임 설정 오버라이드
        dual_sort = self.pg.get_config_value("dual_sort_enabled", "true") == "true"
        rank_min = float(self.pg.get_config_value("return_rank_min", str(self.cfg.return_rank_min)))
        price_min = float(self.pg.get_config_value("price_range_min", str(self.cfg.price_range_min)))
        price_max = float(self.pg.get_config_value("price_range_max", str(self.cfg.price_range_max)))

        # Tier 1 시장 트렌드 필터 (GEM/Faber): SPY<SMA200 하락국면이면 신규 진입 전면 중단(현금).
        # 백테스트: Sharpe 1.48→1.63, MDD −12.4%→−9.1%(약세장 −8.5%→−4.4%). config off 시 기존 동작.
        market_filter = self.pg.get_config_value("market_filter_enabled", "false") == "true"
        if market_filter:
            mkt_days = int(self.pg.get_config_value("market_filter_sma_days", "200"))
            mkt = self.pg.get_market_trend("SPY", mkt_days)
            if not mkt["ok"]:
                msg = (f"진입 시그널 0 — 시장 하락국면(SPY ${mkt.get('close')} < "
                       f"SMA{mkt_days} ${mkt.get('sma')}). Tier 1 시장필터가 신규 진입 중단(현금 보유). "
                       f"하락장 손실 회피 — 설계 의도.")
                logger.info(f"Market filter: SPY below SMA{mkt_days} → entries suspended")
                self._last_entry_funnel = {
                    "total": len(indicators), "price_ok": 0, "trend": 0, "breakout": 0,
                    "volume": 0, "three_cond": 0, "passed_basic": 0, "final": 0, "message": msg}
                return []

        # Tier 2 레짐 킬스위치 (VIX 급등 조기경보): RISK_OFF 또는 VIX>임계면 진입 중단.
        # Tier 1(SPY 추세, 느림) 보완 — 변동성 급등을 더 빠르게 감지(risk-off 시 상관 1로 수렴).
        macro_kill = self.pg.get_config_value("macro_kill_switch_enabled", "false") == "true"
        if macro_kill:
            vix_kill = float(self.pg.get_config_value("vix_kill_threshold", "30"))
            ms = self.pg.get_macro_risk_state()
            vix = ms.get("vix")
            if ms.get("regime") == "RISK_OFF" or (vix is not None and vix > vix_kill):
                msg = (f"진입 시그널 0 — 리스크오프 국면(regime={ms.get('regime')}, "
                       f"VIX={vix}). Tier 2 킬스위치가 신규 진입 중단. 변동성 급등 방어 — 설계 의도.")
                logger.info(f"Macro kill switch: regime={ms.get('regime')} VIX={vix} → entries suspended")
                self._last_entry_funnel = {
                    "total": len(indicators), "price_ok": 0, "trend": 0, "breakout": 0,
                    "volume": 0, "three_cond": 0, "passed_basic": 0, "final": 0, "message": msg}
                return []

        # ③번 절대 모멘텀 필터 (TSMOM, 백테스트 E2: 6개월>0 → Sharpe 1.20→1.24, MDD 개선)
        # 하락추세 종목의 브레이크아웃 함정 회피. config off 시 기존 동작.
        abs_mom_enabled = self.pg.get_config_value("abs_momentum_enabled", "false") == "true"
        abs_mom_min = float(self.pg.get_config_value("abs_momentum_min", "0.0"))
        abs_mom_days = int(self.pg.get_config_value("abs_momentum_lookback_days", "126"))
        abs_mom = self.pg.get_abs_momentum(abs_mom_days) if abs_mom_enabled else {}

        # Step 1: 기본 필터 (추세/브레이크아웃/거래량/가격) 통과 후보
        # 진입 0일 때 "왜 없는지" 설명하기 위해 각 조건별 통과 수(깔때기)도 집계한다.
        n_total = len(indicators)
        f_price = f_trend = f_breakout = f_volume = f_three = 0
        f_absmom = 0
        candidates = []
        for ind in indicators:
            symbol = ind["symbol"]

            if self.pg.has_open_position(symbol):
                continue

            close = float(ind["close"])
            price_ok = price_min <= close <= price_max
            trend_ok = bool(ind["trend_aligned"])
            breakout_ok = bool(ind["breakout_5d"])
            volume_ok = bool(ind["volume_surge"])

            if price_ok:
                f_price += 1
            if trend_ok:
                f_trend += 1
            if breakout_ok:
                f_breakout += 1
            if volume_ok:
                f_volume += 1
            if trend_ok and breakout_ok and volume_ok:
                f_three += 1

            if not price_ok:
                continue
            if not (trend_ok and breakout_ok and volume_ok):
                continue

            # ③번 절대 모멘텀 게이트: 6개월 수익 < 임계면 제외 (데이터 없으면 통과=보수적)
            if abs_mom_enabled:
                m = abs_mom.get(symbol)
                if m is not None and m < abs_mom_min:
                    continue
                f_absmom += 1

            if dual_sort:
                # 이중 정렬: 모멘텀 순위 기준은 나중에 합산으로 처리
                candidates.append(ind)
            else:
                # 기존 방식: 모멘텀 상위만 통과
                rank_ok = (ind["return_20d_rank"] or 0) >= rank_min
                if rank_ok:
                    candidates.append(ind)

        n_passed_basic = len(candidates)

        # Step 2: 이중 정렬 필터 적용
        if dual_sort and candidates:
            candidates = self._apply_dual_sort(candidates)

        # 진입 깔때기 저장 (대시보드/텔레그램 "왜 시그널이 없나" 설명용)
        self._last_entry_funnel = self._build_entry_funnel(
            n_total, f_price, f_trend, f_breakout, f_volume, f_three,
            n_passed_basic, len(candidates), dual_sort)

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

    def scan_hedge(self) -> dict | None:
        """Tier 3 하락장 헤지 (inverse ETF): 시장 국면 전환 시 SH 진입/청산 판정.

        백테스트: 하락국면(SPY<SMA200) SH 보유 시 +22.5%(2022 +14.5%). Tier1=현금회피,
        Tier3=하락장 능동수익. hedge_enabled=false 기본(리스크). 반환: 헤지 액션 dict 또는 None.

        - 하락 전환 + 헤지 미보유 → SH 진입 시그널(ENTER)
        - 상승 전환 + 헤지 보유 → SH 청산 시그널(EXIT)
        ⚠️ inverse ETF 는 장기부적합(일일 리밸 감쇠) — 시장국면 기반 전술적 보유만.
        """
        if self.pg.get_config_value("hedge_enabled", "false") != "true":
            return None
        hedge_sym = self.pg.get_config_value("hedge_symbol", "SH")
        # 헤지 전용 신호 SMA (Tier1 진입필터와 분리). 백테스트: SMA150 이 SMA200 대비
        # 하락국면 수익↑(+14→+20%)·낙폭↓ — 하락을 더 일찍 포착(A안, 2026-08-18).
        mkt_days = int(self.pg.get_config_value("hedge_sma_days", "150"))
        mkt = self.pg.get_market_trend("SPY", mkt_days)
        has_hedge = self.pg.has_open_position(hedge_sym)

        if not mkt["ok"] and not has_hedge:
            logger.info(f"Hedge: bear regime (SPY<SMA{mkt_days}) → SH hedge ENTER signal")
            return {"action": "ENTER", "symbol": hedge_sym,
                    "reason": f"시장 하락국면(SPY ${mkt.get('close')}<SMA{mkt_days} ${mkt.get('sma')}) — inverse ETF 헤지 진입"}
        if mkt["ok"] and has_hedge:
            logger.info(f"Hedge: bull regime recovered → SH hedge EXIT signal")
            return {"action": "EXIT", "symbol": hedge_sym,
                    "reason": "시장 상승국면 복귀 — 헤지 청산"}
        return None

    def _build_entry_funnel(self, total, price, trend, breakout, volume,
                            three, passed_basic, final, dual_sort) -> dict:
        """진입 깔때기 요약 + '왜 시그널이 없나' 한글 사유 메시지 생성."""
        counts = {
            "total": total, "price_ok": price, "trend": trend,
            "breakout": breakout, "volume": volume, "three_cond": three,
            "passed_basic": passed_basic, "final": final,
        }
        if final > 0:
            counts["message"] = (
                f"진입 후보 {final}개 도출 ({total}종목 중). "
                f"조건 통과: 추세 {trend}·브레이크아웃 {breakout}·거래량급증 {volume}, 3조건 동시 {three}."
            )
            return counts

        head = (f"진입 시그널 0 — {total}종목 스캔. 통과 수: 가격대 {price}, "
                f"추세 {trend}, 브레이크아웃 {breakout}, 거래량급증 {volume}, 3조건 동시 {three}.")
        if passed_basic > 0:
            tail = (f" 기본필터 {passed_basic}개가 통과했으나 "
                    f"이중정렬(모멘텀+가치) 순위 컷에서 전부 제외됨.")
        elif three == 0:
            binding = min(
                ("추세", trend), ("브레이크아웃", breakout), ("거래량급증", volume),
                key=lambda x: x[1])
            tail = (f" 추세·브레이크아웃·거래량급증을 동시에 만족하는 종목이 없습니다"
                    f" (병목: {binding[0]} {binding[1]}개). "
                    f"조용한 장에서 흔한 정상 상태이며, 셋업이 없을 때 진입하지 않는 것이 설계 의도입니다.")
        else:
            tail = (f" 3조건 충족 {three}개가 가격대 또는 순위 필터에서 제외됨.")
        counts["message"] = head + tail
        return counts

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
