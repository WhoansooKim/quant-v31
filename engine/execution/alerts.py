"""
V3.1 Phase 3 — Telegram Bot 알림
레짐 전환, Kill Switch, 매매 완료 등 실시간 알림
"""
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


class TelegramAlert:
    """Telegram Bot 알림 전송기"""

    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, config):
        self.token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        self.enabled = bool(self.token and self.chat_id)

        if not self.enabled:
            logger.info("Telegram 알림 비활성화 (토큰/채팅ID 미설정)")

    async def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """메시지 전송 (비동기)"""
        if not self.enabled:
            logger.info(f"[TG OFF] {message[:100]}")
            return False

        url = self.API_URL.format(token=self.token)
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.debug(f"TG 전송 완료: {message[:50]}...")
                    return True
                else:
                    logger.warning(f"TG 전송 실패: {resp.status_code}")
                    return False
        except Exception as e:
            logger.error(f"TG 전송 오류: {e}")
            return False

    async def send_regime_change(self, prev: str, current: str,
                                  bull_prob: float, sideways_prob: float,
                                  bear_prob: float) -> bool:
        """레짐 전환 알림"""
        msg = (
            f"<b>🎯 레짐 전환</b>\n"
            f"{prev} → <b>{current.upper()}</b>\n\n"
            f"🟢 Bull: {bull_prob:.1%}\n"
            f"🟡 Sideways: {sideways_prob:.1%}\n"
            f"🔴 Bear: {bear_prob:.1%}"
        )
        return await self.send(msg)

    async def send_kill_switch(self, prev_level: str, new_level: str,
                                mdd: float, pv: float) -> bool:
        """Kill Switch 알림"""
        emoji = {"NORMAL": "✅", "WARNING": "⚠️",
                 "DEFENSIVE": "🔴", "EMERGENCY": "🚨"}
        msg = (
            f"<b>{emoji.get(new_level, '🛡️')} Kill Switch</b>\n"
            f"{prev_level} → <b>{new_level}</b>\n"
            f"MDD: {mdd:.2%}\n"
            f"PV: ${pv:,.2f}"
        )
        return await self.send(msg)

    async def send_pipeline_complete(self, regime: str, kill_level: str,
                                      signal_count: int, trade_count: int,
                                      pv: float, mdd: float,
                                      elapsed: float) -> bool:
        """파이프라인 완료 알림"""
        msg = (
            f"<b>✅ 일일 파이프라인 완료</b> ({elapsed:.1f}s)\n\n"
            f"레짐: {regime} | Kill: {kill_level}\n"
            f"시그널: {signal_count} | 체결: {trade_count}\n"
            f"PV: ${pv:,.2f} (MDD: {mdd:.2%})\n"
            f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        return await self.send(msg)

    async def send_error(self, error: str) -> bool:
        """오류 알림"""
        msg = (
            f"<b>🚨 파이프라인 오류</b>\n"
            f"<code>{error[:500]}</code>\n"
            f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        return await self.send(msg)

    async def send_emergency(self, position_count: int,
                              cooldown_days: int) -> bool:
        """EMERGENCY 전량 청산 알림"""
        msg = (
            f"<b>🚨 EMERGENCY 전량 청산</b>\n\n"
            f"포지션 {position_count}개 → 현금 전환\n"
            f"냉각기: {cooldown_days}일 (재진입 불가)\n"
            f"시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        return await self.send(msg)
