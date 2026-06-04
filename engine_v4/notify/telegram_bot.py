"""Telegram 양방향 봇 — 정형 명령 (옵션 A) + 자유 텍스트 큐 적재 (옵션 B).

정형 명령:
  /status              — 시스템 + 포지션 + IC 요약
  /positions           — 오픈 포지션 상세
  /signals             — 최근 시그널 10건
  /last                — 마지막 파이프라인 결과
  /perf [7d|30d]       — 성과 메트릭
  /regime              — 매크로 regime + macro score
  /analyze SYM         — 종목 분석 (가격/지표/팩터/Ollama 해설)
  /queue               — Claude 분석 큐 상태
  /help                — 명령 목록

자유 텍스트 (정형 명령 아닌 모든 메시지):
  → swing_analysis_queue 에 pending 으로 적재
  → 다음 Claude Code 세션에서 자동 확인 + 처리 후 Telegram 회신
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytz

from engine_v4.config.settings import SwingSettings
from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}"
KST = pytz.timezone("Asia/Seoul")


class TelegramBot:
    """Long-polling 기반 양방향 봇."""

    def __init__(self, pg: PostgresStore, settings: SwingSettings):
        self.pg = pg
        self.token = settings.telegram_bot_token
        self.allowed_chat_id = str(settings.telegram_chat_id)
        self._enabled = bool(
            self.token and self.allowed_chat_id
            and self.token != "your_bot_token"
        )
        self._offset = 0
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def start(self):
        """봇 polling 백그라운드 시작."""
        if not self._enabled:
            logger.info("Telegram bot disabled (no token/chat_id)")
            return
        if self.pg.get_config_value("telegram_bot_enabled", "false").lower() not in ("true", "1", "yes"):
            logger.info("Telegram bot polling skipped (telegram_bot_enabled=false)")
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram bot polling started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self):
        """getUpdates long-polling loop."""
        backoff = 1
        while self._running:
            try:
                async with httpx.AsyncClient(timeout=35) as client:
                    resp = await client.get(
                        f"{_API_BASE.format(token=self.token)}/getUpdates",
                        params={"offset": self._offset, "timeout": 30},
                    )
                    if resp.status_code != 200:
                        logger.warning(f"getUpdates {resp.status_code}: {resp.text[:100]}")
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 60)
                        continue
                    data = resp.json()
                    backoff = 1
                    for upd in data.get("result", []):
                        self._offset = upd["update_id"] + 1
                        await self._handle_update(upd)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Polling error: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _handle_update(self, upd: dict):
        msg = upd.get("message")
        if not msg:
            return
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if chat_id != self.allowed_chat_id:
            logger.warning(f"Unauthorized chat_id={chat_id}, ignoring")
            return
        text = (msg.get("text") or "").strip()
        if not text:
            return
        username = (msg.get("from") or {}).get("username", "")

        try:
            if text.startswith("/"):
                await self._handle_command(chat_id, username, text)
            else:
                await self._enqueue_for_claude(chat_id, username, text)
        except Exception as e:
            logger.error(f"Handle update failed: {e}", exc_info=True)
            await self._send(chat_id, f"⚠️ 처리 실패: {e}")

    # ─── 정형 명령 (옵션 A) ─────────────────────────────────

    async def _handle_command(self, chat_id: str, username: str, text: str):
        parts = text.split(maxsplit=2)
        cmd = parts[0].lower().split("@")[0]  # /status@botname → /status
        args = parts[1:] if len(parts) > 1 else []

        handlers = {
            "/start": self._cmd_help,
            "/help": self._cmd_help,
            "/status": self._cmd_status,
            "/positions": self._cmd_positions,
            "/signals": self._cmd_signals,
            "/last": self._cmd_last,
            "/perf": self._cmd_perf,
            "/regime": self._cmd_regime,
            "/analyze": self._cmd_analyze,
            "/queue": self._cmd_queue,
        }
        handler = handlers.get(cmd)
        if not handler:
            await self._send(chat_id, f"알 수 없는 명령: {cmd}\n/help 로 명령 목록 확인")
            return
        try:
            reply = await handler(args)
            await self._send(chat_id, reply)
        except Exception as e:
            logger.error(f"Command {cmd} failed: {e}", exc_info=True)
            await self._send(chat_id, f"⚠️ {cmd} 실패: {e}")

    async def _cmd_help(self, args) -> str:
        return (
            "<b>📡 Quant V4 Bot 명령</b>\n\n"
            "<b>정형 명령</b>\n"
            "/status — 시스템 + 포지션 + IC 요약\n"
            "/positions — 오픈 포지션 상세\n"
            "/signals — 최근 시그널 10건\n"
            "/last — 마지막 파이프라인 결과\n"
            "/perf [7d|30d] — 성과 메트릭\n"
            "/regime — 매크로 regime\n"
            "/analyze SYM — 종목 분석\n"
            "/queue — Claude 분석 큐 상태\n\n"
            "<b>자유 텍스트</b>\n"
            "정형 명령이 아닌 메시지는 Claude 분석 큐에 적재됩니다.\n"
            "다음 Claude Code 세션에서 자동 처리 후 회신됩니다.\n\n"
            "<i>예: \"오늘 21:30 파이프라인 결과 확인해줘\"</i>"
        )

    async def _cmd_status(self, args) -> str:
        with self.pg.get_conn() as conn:
            open_count = conn.execute(
                "SELECT COUNT(*) AS n FROM swing_positions WHERE status='open'"
            ).fetchone()["n"]
            pending_count = conn.execute(
                "SELECT COUNT(*) AS n FROM swing_signals WHERE status='pending' AND signal_type='ENTRY'"
            ).fetchone()["n"]
            snap = conn.execute(
                "SELECT total_value_usd, cumulative_return, daily_pnl_usd FROM swing_snapshots ORDER BY time DESC LIMIT 1"
            ).fetchone()
            last_ic = conn.execute(
                "SELECT rolling_30_information_coefficient AS ic, rolling_30_win_rate AS wr, "
                "rolling_30_sqn AS sqn FROM swing_daily_report ORDER BY report_date DESC LIMIT 1"
            ).fetchone()
            macro = conn.execute(
                "SELECT macro_score, regime FROM swing_macro_snapshots ORDER BY time DESC LIMIT 1"
            ).fetchone()

        regime = self.pg.get_config_value("current_regime", "NEUTRAL")
        mode = self.pg.get_config_value("trading_mode", "paper")
        snap_dict = dict(snap) if snap else {}
        ic_dict = dict(last_ic) if last_ic else {}
        macro_dict = dict(macro) if macro else {}

        return (
            f"<b>📊 시스템 상태</b> (mode={mode})\n"
            f"\n<b>포트폴리오</b>\n"
            f"Total: ${float(snap_dict.get('total_value_usd', 0)):.2f}\n"
            f"Cum: {float(snap_dict.get('cumulative_return', 0))*100:+.2f}%\n"
            f"Daily P&L: ${float(snap_dict.get('daily_pnl_usd', 0)):+.2f}\n"
            f"\n<b>거래</b>\n"
            f"Open: {open_count} · Pending ENTRY: {pending_count}\n"
            f"\n<b>Rolling 30 메트릭</b>\n"
            f"Win Rate: {float(ic_dict.get('wr', 0))*100:.1f}%\n"
            f"SQN: {float(ic_dict.get('sqn', 0) or 0):.2f}\n"
            f"IC: {float(ic_dict.get('ic', 0) or 0):+.3f}\n"
            f"\n<b>Regime</b>: {regime} (macro {float(macro_dict.get('macro_score', 0)):.1f})"
        )

    async def _cmd_positions(self, args) -> str:
        with self.pg.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT symbol, qty, entry_price, current_price, entry_time
                FROM swing_positions WHERE status='open'
                ORDER BY entry_time DESC
                """
            ).fetchall()
        if not rows:
            return "오픈 포지션 없음."
        lines = ["<b>📈 오픈 포지션</b>", ""]
        total_pl_pct = 0.0
        for r in rows:
            ep = float(r["entry_price"] or 0)
            cp = float(r["current_price"] or 0)
            pct = ((cp - ep) / ep * 100) if ep > 0 else 0
            total_pl_pct += pct
            arrow = "🟢" if pct >= 0 else "🔴"
            lines.append(
                f"{arrow} <b>{r['symbol']}</b> · {r['entry_time'].strftime('%m/%d')}\n"
                f"   Entry ${ep:.2f} → ${cp:.2f} ({pct:+.2f}%)"
            )
        lines.append(f"\n평균: {total_pl_pct/len(rows):+.2f}%")
        return "\n".join(lines)

    async def _cmd_signals(self, args) -> str:
        with self.pg.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT symbol, signal_type, status, composite_score, time
                FROM swing_signals
                ORDER BY time DESC LIMIT 10
                """
            ).fetchall()
        if not rows:
            return "최근 시그널 없음."
        lines = ["<b>🎯 최근 시그널 10건</b>", ""]
        for r in rows:
            t = r["time"].astimezone(KST).strftime("%m/%d %H:%M")
            comp = float(r["composite_score"] or 0)
            status_emoji = {"executed": "✅", "approved": "🟢", "rejected": "❌", "pending": "⏳"}.get(
                r["status"], "·")
            lines.append(
                f"{status_emoji} <b>{r['symbol']}</b> {r['signal_type']} · "
                f"comp={comp:.0f} · {r['status']} · {t}"
            )
        return "\n".join(lines)

    async def _cmd_last(self, args) -> str:
        with self.pg.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT step_name, status, elapsed_sec, details, created_at
                FROM swing_pipeline_log
                WHERE step_name IN ('scheduled_pipeline','full_pipeline')
                ORDER BY created_at DESC LIMIT 3
                """
            ).fetchall()
        if not rows:
            return "최근 파이프라인 기록 없음."
        lines = ["<b>📡 최근 파이프라인 3회</b>", ""]
        for r in rows:
            t = r["created_at"].astimezone(KST).strftime("%m/%d %H:%M")
            d = r["details"] or {}
            elapsed = float(r["elapsed_sec"] or 0)
            ent = d.get("entries", "-")
            ext = d.get("exits", "-")
            syms = d.get("symbols", "-")
            lines.append(
                f"<b>{r['step_name']}</b> {r['status']}\n"
                f"  {t} KST · {elapsed:.1f}s · 종목 {syms} · ENTRY {ent} · EXIT {ext}"
            )
        return "\n".join(lines)

    async def _cmd_perf(self, args) -> str:
        days = 7
        if args and args[0].endswith("d"):
            try:
                days = int(args[0][:-1])
            except ValueError:
                pass
        with self.pg.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT report_date, rolling_30_win_rate AS wr, rolling_30_expectancy_pct AS exp,
                       rolling_30_sqn AS sqn, rolling_30_information_coefficient AS ic
                FROM swing_daily_report
                WHERE report_date >= CURRENT_DATE - %s::interval
                ORDER BY report_date DESC LIMIT 10
                """,
                (f"{days} days",),
            ).fetchall()
        if not rows:
            return f"{days}일 성과 데이터 없음."
        lines = [f"<b>📈 최근 {days}일 Rolling 30 메트릭</b>", ""]
        for r in rows:
            lines.append(
                f"{r['report_date']} · WR {float(r['wr'] or 0)*100:.1f}% · "
                f"Exp {float(r['exp'] or 0):+.2f}% · "
                f"SQN {float(r['sqn'] or 0):+.2f} · "
                f"IC {float(r['ic'] or 0):+.3f}"
            )
        return "\n".join(lines)

    async def _cmd_regime(self, args) -> str:
        with self.pg.get_conn() as conn:
            macro = conn.execute(
                """
                SELECT macro_score, regime, vix, dxy, risk_off_score,
                       yield_curve_score, btc_momentum_20d, time
                FROM swing_macro_snapshots ORDER BY time DESC LIMIT 1
                """
            ).fetchone()
        if not macro:
            return "Macro 데이터 없음."
        m = dict(macro)
        current = self.pg.get_config_value("current_regime", "NEUTRAL")
        switch_on = self.pg.get_config_value("harness_regime_switch_enabled", "false")
        t = m["time"].astimezone(KST).strftime("%m/%d %H:%M")
        return (
            f"<b>🌐 Macro Regime</b>\n\n"
            f"Current: <b>{current}</b> (auto-switch: {switch_on})\n"
            f"Macro score: {float(m.get('macro_score', 0)):.1f} → {m.get('regime', 'N/A')}\n"
            f"\n<b>구성 지표</b>\n"
            f"VIX: {float(m.get('vix', 0)):.2f}\n"
            f"DXY: {float(m.get('dxy', 0)):.2f}\n"
            f"Risk-off score: {float(m.get('risk_off_score', 0)):.1f}\n"
            f"Yield curve: {float(m.get('yield_curve_score', 0)):.1f}\n"
            f"BTC 20d momentum: {float(m.get('btc_momentum_20d', 0)):.2%}\n"
            f"\n측정: {t} KST"
        )

    async def _cmd_analyze(self, args) -> str:
        if not args:
            return "사용법: /analyze SYMBOL\n예: /analyze AAPL"
        symbol = args[0].upper()
        with self.pg.get_conn() as conn:
            ind = conn.execute(
                """
                SELECT rsi_14, atr_14, adx_14, ema_20, ema_50, ema_200, time
                FROM swing_indicators WHERE symbol=%s ORDER BY time DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            price_row = conn.execute(
                "SELECT close FROM swing_prices WHERE symbol=%s ORDER BY time DESC LIMIT 1",
                (symbol,),
            ).fetchone()
            recent_sig = conn.execute(
                """
                SELECT composite_score, tech_score, sentiment_score, quality_score,
                       value_score, macro_score, status, time
                FROM swing_signals WHERE symbol=%s ORDER BY time DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        if not ind:
            return f"<b>{symbol}</b>: 지표 데이터 없음 (유니버스 외 종목일 수 있음)."
        i = dict(ind)
        price = float(price_row["close"]) if price_row else 0
        t = i["time"].astimezone(KST).strftime("%m/%d %H:%M")
        lines = [f"<b>📊 {symbol} 분석</b>", ""]
        lines.append(f"<b>가격/지표</b> ({t} KST)")
        lines.append(f"Close: ${price:.2f}")
        lines.append(f"RSI(14): {float(i.get('rsi_14') or 0):.1f}")
        lines.append(f"ATR(14): {float(i.get('atr_14') or 0):.2f}")
        lines.append(f"ADX(14): {float(i.get('adx_14') or 0):.1f}")
        lines.append(f"EMA 20/50/200: {float(i.get('ema_20') or 0):.2f} / "
                     f"{float(i.get('ema_50') or 0):.2f} / {float(i.get('ema_200') or 0):.2f}")
        if recent_sig:
            s = dict(recent_sig)
            lines.append("\n<b>최근 시그널 팩터</b>")
            lines.append(f"Composite: {float(s.get('composite_score') or 0):.1f}")
            lines.append(f"Tech {float(s.get('tech_score') or 0):.0f} · "
                         f"Sent {float(s.get('sentiment_score') or 0):.0f} · "
                         f"Qual {float(s.get('quality_score') or 0):.0f} · "
                         f"Val {float(s.get('value_score') or 0):.0f} · "
                         f"Macro {float(s.get('macro_score') or 0):.0f}")
            lines.append(f"Status: {s.get('status')}")
        return "\n".join(lines)

    async def _cmd_queue(self, args) -> str:
        with self.pg.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT request_id, request_text, status, created_at, processed_at
                FROM swing_analysis_queue
                ORDER BY created_at DESC LIMIT 10
                """
            ).fetchall()
        if not rows:
            return "분석 큐 비어있음."
        lines = ["<b>🧠 Claude 분석 큐 (최근 10건)</b>", ""]
        for r in rows:
            t = r["created_at"].astimezone(KST).strftime("%m/%d %H:%M")
            status_emoji = {"pending": "⏳", "processing": "🔄", "done": "✅", "error": "⚠️"}.get(
                r["status"], "·")
            text = r["request_text"][:60] + ("…" if len(r["request_text"]) > 60 else "")
            lines.append(f"{status_emoji} #{r['request_id']} · {t} · <code>{text}</code>")
        pending_n = sum(1 for r in rows if r["status"] == "pending")
        if pending_n:
            lines.append(f"\n<b>{pending_n}건 pending</b> — 다음 Claude Code 세션 시 처리됨.")
        return "\n".join(lines)

    # ─── 자유 텍스트 → Claude 큐 적재 (옵션 B) ───────────

    async def _enqueue_for_claude(self, chat_id: str, username: str, text: str):
        with self.pg.get_conn() as conn:
            row = conn.execute(
                """
                INSERT INTO swing_analysis_queue (from_chat_id, from_username, request_text, status)
                VALUES (%s, %s, %s, 'pending')
                RETURNING request_id
                """,
                (chat_id, username, text),
            ).fetchone()
            conn.commit()
        rid = row["request_id"]
        await self._send(
            chat_id,
            f"✅ Claude 분석 큐에 추가됨 (#{rid})\n"
            f"\n<i>요청:</i> <code>{text[:200]}</code>\n"
            f"\n다음 Claude Code 세션에서 자동 처리 후 회신됩니다.\n"
            f"<i>/queue 로 큐 상태 확인 가능</i>"
        )

    # ─── 송신 ───────────────────────────────────────

    async def _send(self, chat_id: str, text: str):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{_API_BASE.format(token=self.token)}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                )
                if resp.status_code != 200:
                    logger.warning(f"sendMessage {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"Send failed: {e}")
