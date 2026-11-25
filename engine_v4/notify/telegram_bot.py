"""Telegram 양방향 봇 — 정형 명령 (옵션 A) + 자유 텍스트 큐 적재 (옵션 B).

정형 명령:
  /status              — 코어 일일 보고(총자산·추세·비중·섀도·경보) — cron 일일 보고와 같은 함수
  /positions           — 보유 종목별 합산(슬리브·비중·손익)
  /last                — 최근 코어 배분 3회
  /perf [7d|30d]       — 재시작 후 일별 총자산
  (2026-11-22 스윙 은퇴 정리: /signals 폐지, /status·/last·/perf 를 코어 기준으로 교체)
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

    async def stop(self, timeout: float = 5.0):
        """폴링 중지. **종료를 막지 않는 것이 최우선**이다 (§22.AO-34).

        uvicorn 은 `lifespan.shutdown()` 에 타임아웃을 걸지 않는다
        (`--timeout-graceful-shutdown` 은 연결 대기 단계만 덮는다 — uvicorn/server.py:289 vs 301).
        그래서 여기서 매달리면 systemd 가 SIGKILL 할 때까지 프로세스가 안 죽는다.
        실측(2026-10-06): 재시작이 매번 30초 TimeoutStopSec 까지 가서
        `Failed with result 'timeout'` 으로 끝났다.
        """
        self._running = False
        task = self._task
        if not task or task.done():
            return
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.CancelledError:
            pass                      # 정상 — 취소가 전파된 것
        except asyncio.TimeoutError:
            # 취소에 응답하지 않는다. 기다려주면 종료 자체가 막히므로 버리고 간다.
            logger.warning(f"Telegram polling did not stop within {timeout}s — 포기하고 진행")
        except Exception as e:
            logger.warning(f"Telegram polling stop 중 예외: {type(e).__name__}: {e}")

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
                # 🔴 2026-10-07 (§22.AO-34): 원래 여기서 `break` 했다. 취소를 삼키고 정상 종료로
                #   바꾸는 셈이어서 stop() 의 `await self._task` 가 취소 완료를 인지하지 못했다.
                #   CancelledError 는 **반드시 재전파**해야 한다(asyncio 규약).
                self._running = False
                raise
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
            "/signals": self._cmd_retired,
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
            "/status — 코어 일일 보고 (총자산·추세·비중·섀도)\n"
            "/positions — 보유 종목별 합산\n"
            "/last — 최근 코어 배분 3회\n"
            "/perf [7d|30d] — 재시작 후 일별 총자산\n"
            "/regime — 매크로 regime\n"
            "/analyze SYM — 종목 분석\n"
            "/queue — Claude 분석 큐 상태\n\n"
            "<b>자유 텍스트</b>\n"
            "정형 명령이 아닌 메시지는 Claude 분석 큐에 적재됩니다.\n"
            "다음 Claude Code 세션에서 자동 처리 후 회신됩니다.\n\n"
            "<i>예: \"오늘 00:30 코어 배분 결과 확인해줘\"</i>"
        )

    async def _cmd_status(self, args) -> str:
        """코어 일일 보고와 같은 메시지(engine_v4/notify/core_report.py). 시세 조회가 있어 스레드에서."""
        def _build() -> str:
            from engine_v4.notify.core_report import summary_message
            with self.pg.get_conn() as conn:
                return summary_message(conn)
        mode = self.pg.get_config_value("trading_mode", "paper")
        return f"<i>mode={mode}</i>\n" + await asyncio.to_thread(_build)

    async def _cmd_retired(self, args) -> str:
        return ("스윙 매매는 은퇴했다(§22.AO-67) — 시그널은 매매로 이어지지 않는다.\n"
                "/status 코어 보고 · /positions 보유 · /last 코어 배분")

    async def _cmd_positions(self, args) -> str:
        with self.pg.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT symbol, side, SUM(qty) qty, SUM(qty*entry_price) cost,
                       MAX(current_price) cp, MIN(entry_time) first_t, COUNT(*) lots
                FROM swing_positions WHERE status='open'
                GROUP BY symbol, side
                """
            ).fetchall()
        if not rows:
            return "오픈 포지션 없음."
        core = {"UPRO", "BIL"}
        items = []
        for r in rows:
            qty, cost = float(r["qty"]), float(r["cost"])
            val = qty * float(r["cp"]) if r["cp"] is not None else cost
            sleeve = ("코어" if r["symbol"] in core else "J") if r["side"] == "CORE" else r["side"]
            items.append((sleeve, r["symbol"], val, cost, int(r["lots"])))
        tot = sum(i[2] for i in items) or 1.0
        items.sort(key=lambda i: (i[0] != "코어", -i[2]))
        lines = ["<b>📈 보유 (종목별 합산)</b>", ""]
        for sleeve, sym, val, cost, lots in items:
            pnl = val - cost
            lines.append(f"{'🟢' if pnl >= 0 else '🔴'} <b>{sym}</b> {sleeve} · ${val:,.2f} ({val / tot:.1%})"
                         f" · {'+' if pnl >= 0 else '−'}${abs(pnl):,.2f} ({pnl / cost * 100:+.1f}%)"
                         + (f" · ×{lots}" if lots > 1 else ""))
        for label, keyf in (("코어", lambda i: i[0] == "코어"), ("J", lambda i: i[0] == "J")):
            v = sum(i[2] for i in items if keyf(i)); c = sum(i[3] for i in items if keyf(i))
            if c:
                lines.append(f"\n{label} 합계 ${v:,.2f} ({v / tot:.1%}) · {'+' if v >= c else '−'}${abs(v - c):,.2f}")
        return "\n".join(lines)

    async def _cmd_last(self, args) -> str:
        with self.pg.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT status, details, error_msg, created_at FROM swing_pipeline_log
                WHERE step_name='core_allocate' ORDER BY created_at DESC LIMIT 3
                """
            ).fetchall()
        if not rows:
            return "코어 배분 기록 없음."
        lines = ["<b>🏛️ 최근 코어 배분 3회</b>", ""]
        for r in rows:
            t = r["created_at"].astimezone(KST).strftime("%m/%d %H:%M")
            d = r["details"] or {}
            tr = d.get("trend") or {}
            orders = d.get("orders") or []
            head = f"<b>{t}</b> {'✅' if r['status'] == 'completed' else '🔴'} {r['status']}"
            if tr:
                head += f" · 추세 {tr.get('label')}" + (" ⚡전환" if tr.get("changed") else "")
            lines.append(head)
            if r["status"] != "completed":
                lines.append(f"  {(r['error_msg'] or '')[:150]}")
            elif orders:
                lines += [f"  {o}" for o in orders[:6]] + ([f"  … 외 {len(orders) - 6}건"] if len(orders) > 6 else [])
            else:
                lines.append("  주문 없음")
        return "\n".join(lines)

    async def _cmd_perf(self, args) -> str:
        days = 7
        if args and args[0].endswith("d"):
            try:
                days = int(args[0][:-1])
            except ValueError:
                pass
        since = self.pg.get_config_value("account_epoch_time", "") or None
        cap = float(self.pg.get_config_value("account_epoch_capital", "0") or 0)
        with self.pg.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT ON ((time AT TIME ZONE 'Asia/Seoul')::date)
                       (time AT TIME ZONE 'Asia/Seoul')::date d, total_value_usd tv,
                       cumulative_return cr, max_drawdown dd
                FROM swing_snapshots
                WHERE time >= GREATEST(now() - %s::interval, COALESCE(%s::timestamptz, '-infinity'))
                ORDER BY (time AT TIME ZONE 'Asia/Seoul')::date, time DESC
                """,
                (f"{days} days", since),
            ).fetchall()
        if not rows:
            return f"{days}일 스냅샷 없음."
        lines = [f"<b>📈 최근 {days}일 총자산</b>" + (f" (재시작 ${cap:,.0f} 기준)" if cap else ""), ""]
        prev = None
        for r in rows:
            tv = float(r["tv"])
            chg = f" · 하루 {tv - prev:+,.2f}" if prev is not None else ""
            lines.append(f"{r['d']:%m/%d} ${tv:,.2f} · 누적 {float(r['cr'] or 0) * 100:+.2f}%{chg}")
            prev = tv
        lines.append(f"\n재시작 후 최대낙폭 {float(rows[-1]['dd'] or 0) * 100:.1f}%")
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
        def fmt(key, fmt_str="{:.2f}", default="—"):
            v = m.get(key)
            if v is None:
                return default
            try:
                return fmt_str.format(float(v))
            except (ValueError, TypeError):
                return default

        return (
            f"<b>🌐 Macro Regime</b>\n\n"
            f"Current: <b>{current}</b> (auto-switch: {switch_on})\n"
            f"Macro score: {fmt('macro_score', '{:.1f}')} → {m.get('regime') or 'N/A'}\n"
            f"\n<b>구성 지표</b>\n"
            f"VIX: {fmt('vix')}\n"
            f"DXY: {fmt('dxy')}\n"
            f"Risk-off score: {fmt('risk_off_score', '{:.1f}')}\n"
            f"Yield curve: {fmt('yield_curve_score', '{:.1f}')}\n"
            f"BTC 20d momentum: {fmt('btc_momentum_20d', '{:.2f}%')}\n"
            f"\n측정: {t} KST"
        )

    async def _cmd_analyze(self, args) -> str:
        if not args:
            return "사용법: /analyze SYMBOL\n예: /analyze AAPL"
        symbol = args[0].upper()
        with self.pg.get_conn() as conn:
            ind = conn.execute(
                """
                SELECT close, sma_50, sma_200, return_20d, return_20d_rank,
                       high_5d, volume, volume_avg_20d, volume_ratio,
                       trend_aligned, breakout_5d, volume_surge, time
                FROM swing_indicators WHERE symbol=%s ORDER BY time DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            recent_sig = conn.execute(
                """
                SELECT composite_score, technical_score, sentiment_score, quality_score,
                       value_score, macro_score, status, time
                FROM swing_signals WHERE symbol=%s ORDER BY time DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            position = conn.execute(
                """
                SELECT qty, entry_price, current_price, entry_time
                FROM swing_positions WHERE symbol=%s AND status='open' LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        if not ind:
            return f"<b>{symbol}</b>: 지표 데이터 없음 (유니버스 외 종목일 수 있음)."
        i = dict(ind)
        close = float(i.get("close") or 0)
        sma50 = float(i.get("sma_50") or 0)
        sma200 = float(i.get("sma_200") or 0)
        ret20 = float(i.get("return_20d") or 0)
        rank20 = float(i.get("return_20d_rank") or 0)
        high5 = float(i.get("high_5d") or 0)
        vol_ratio = float(i.get("volume_ratio") or 0)
        t = i["time"].astimezone(KST).strftime("%m/%d %H:%M")

        # 트렌드 판정
        if close > sma50 > sma200:
            trend = "🟢 상승추세 (Close > SMA50 > SMA200)"
        elif close < sma50 < sma200:
            trend = "🔴 하락추세 (Close < SMA50 < SMA200)"
        else:
            trend = "🟡 횡보/혼조"

        lines = [f"<b>📊 {symbol} 분석</b>", ""]
        lines.append(f"<b>가격/추세</b> ({t} KST)")
        lines.append(f"Close: ${close:.2f}")
        lines.append(f"SMA 50/200: ${sma50:.2f} / ${sma200:.2f}")
        lines.append(f"5d 고가: ${high5:.2f} ({(close/high5-1)*100:+.1f}% from high)" if high5 > 0 else "")
        lines.append(trend)
        lines.append("")
        lines.append(f"<b>모멘텀/거래량</b>")
        lines.append(f"20일 수익률: {ret20*100:+.2f}% (rank {rank20*100:.0f} percentile)")
        lines.append(f"Volume ratio: {vol_ratio:.2f}× (vs 20d avg)")
        flags = []
        if i.get("trend_aligned"): flags.append("trend_aligned")
        if i.get("breakout_5d"): flags.append("breakout_5d")
        if i.get("volume_surge"): flags.append("volume_surge")
        if flags:
            lines.append(f"Flags: {', '.join(flags)}")

        if recent_sig:
            s = dict(recent_sig)
            sig_t = s["time"].astimezone(KST).strftime("%m/%d %H:%M")
            lines.append(f"\n<b>최근 시그널 팩터</b> ({sig_t})")
            lines.append(f"Composite: {float(s.get('composite_score') or 0):.1f}")
            lines.append(f"Tech {float(s.get('technical_score') or 0):.0f} · "
                         f"Sent {float(s.get('sentiment_score') or 0):.0f} · "
                         f"Qual {float(s.get('quality_score') or 0):.0f} · "
                         f"Val {float(s.get('value_score') or 0):.0f} · "
                         f"Macro {float(s.get('macro_score') or 0):.0f}")
            lines.append(f"Status: {s.get('status')}")

        if position:
            p = dict(position)
            ep = float(p["entry_price"] or 0)
            cp = float(p["current_price"] or 0)
            pct = ((cp - ep) / ep * 100) if ep > 0 else 0
            lines.append(f"\n<b>📌 오픈 포지션</b>")
            lines.append(f"Qty {float(p['qty']):.0f} · Entry ${ep:.2f} → ${cp:.2f} ({pct:+.2f}%)")

        return "\n".join(l for l in lines if l)

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
