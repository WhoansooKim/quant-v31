"""Telegram 알림 — 시그널, 체결, 일일 요약."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from engine_v4.config.settings import SwingSettings

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}"


class TelegramNotifier:
    """텔레그램 봇 알림 전송."""

    def __init__(self, settings: SwingSettings):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self._enabled = bool(self.token and self.chat_id
                             and self.token != "your_bot_token")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def send(self, text: str, parse_mode: str = "HTML") -> bool:
        """텔레그램 메시지 전송."""
        if not self._enabled:
            logger.debug(f"Telegram disabled, skipping: {text[:50]}...")
            return False

        url = f"{_API_BASE.format(token=self.token)}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    return True
                logger.warning(f"Telegram API error: {resp.status_code} {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            return False

    def send_sync(self, text: str, parse_mode: str = "HTML") -> bool:
        """동기 전송 (스케줄러용)."""
        if not self._enabled:
            return False

        url = f"{_API_BASE.format(token=self.token)}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(url, json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram sync send error: {e}")
            return False

    # ─── 시그널 알림 ─────────────────────────────────

    async def notify_signals(self, entries: list[dict],
                             exits: list[dict]) -> bool:
        """시그널 발생 알림."""
        if not entries and not exits:
            return False

        lines = ["<b>📊 Swing Signal Alert</b>", ""]

        if entries:
            lines.append(f"<b>🟢 Entry Signals: {len(entries)}</b>")
            for s in entries[:5]:  # 최대 5개
                lines.append(
                    f"  • <b>{s['symbol']}</b> @ ${s.get('entry_price', 0):.2f}"
                    f"  SL ${s.get('stop_loss', 0):.2f} / TP ${s.get('take_profit', 0):.2f}"
                    f"  (rank {s.get('return_20d_rank', 0):.0%})"
                )
            if len(entries) > 5:
                lines.append(f"  ... +{len(entries) - 5} more")
            lines.append("")

        if exits:
            lines.append(f"<b>🔴 Exit Signals: {len(exits)}</b>")
            for s in exits[:5]:
                lines.append(
                    f"  • <b>{s['symbol']}</b> @ ${s.get('entry_price', 0):.2f}"
                    f"  reason: {s.get('exit_reason', '?')}"
                )
            lines.append("")

        lines.append("👉 Dashboard에서 승인/거절하세요")
        lines.append(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M KST')}")

        return await self.send("\n".join(lines))

    # ─── 체결 알림 ─────────────────────────────────

    async def notify_trade(self, result: dict) -> bool:
        """거래 체결 알림."""
        side = "🟢 BUY" if result.get("side", "BUY") == "BUY" else "🔴 SELL"
        pnl_text = ""
        if "pnl" in result and result["pnl"]:
            pnl = result["pnl"]
            emoji = "💰" if pnl > 0 else "💸"
            pnl_text = f"\n{emoji} P&L: ${pnl:+.2f}"

        text = (
            f"<b>✅ Trade Executed</b>\n\n"
            f"{side} <b>{result.get('symbol', '?')}</b>\n"
            f"Qty: {result.get('qty', 0)} shares\n"
            f"Price: ${result.get('entry_price', result.get('exit_price', 0)):.2f}\n"
            f"Amount: ${result.get('amount', 0):.2f}"
            f"{pnl_text}\n"
            f"Order: {result.get('order_id', 'N/A')}\n"
            f"⏰ {datetime.now().strftime('%H:%M KST')}"
        )
        return await self.send(text)

    # ─── 일일 요약 ─────────────────────────────────

    async def notify_daily_summary(self, summary: dict) -> bool:
        """일일 포트폴리오 요약."""
        total = summary.get("total_value_usd", 0)
        daily_pnl = summary.get("daily_pnl_usd", 0)
        cum_return = summary.get("cumulative_return", 0)
        positions = summary.get("open_positions", 0)
        max_dd = summary.get("max_drawdown", 0)

        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"

        text = (
            f"<b>📋 Daily Summary</b>\n\n"
            f"💰 Total: <b>${total:,.2f}</b>\n"
            f"{pnl_emoji} Daily P&L: <b>${daily_pnl:+.2f}</b>\n"
            f"📊 Cum. Return: <b>{cum_return:+.2%}</b>\n"
            f"📉 Max DD: <b>{max_dd:.2%}</b>\n"
            f"📦 Positions: {positions}/4\n\n"
            f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M KST')}"
        )
        return await self.send(text)

    # ─── 에러 알림 ─────────────────────────────────

    async def notify_error(self, step: str, error: str) -> bool:
        """에러 알림."""
        text = (
            f"<b>⚠️ Engine Error</b>\n\n"
            f"Step: <code>{step}</code>\n"
            f"Error: {error[:500]}\n"
            f"⏰ {datetime.now().strftime('%H:%M KST')}"
        )
        return await self.send(text)
