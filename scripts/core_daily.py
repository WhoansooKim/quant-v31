#!/usr/bin/env python
"""코어 운용 일일 보고 + 배분 경보 (2026-11-22, 은퇴한 스윙 감시기 exit_watch·payoff·ao26 대체).

왜 바꿨나: exit_watch.py 는 스윙 시절 '투자율 45% 대역'을 재고 있어서, 설계상 100% 투자인 코어+J 에
"🔴 상한 초과 — max_total_exposure_pct 가 안 먹고 있다" 오탐을 보냈다.
메시지 내용은 engine_v4/notify/core_report.py (텔레그램 /status 와 공용).

  alloc   (화~토 00:50 KST, core_allocate 00:30 직후): 미실행·실패면 🔴, 주문이 있었으면 요약, 그 외 무발송
  summary (화~토 07:15 KST, 미국 마감 스냅샷 07:00 뒤): 매일 1회 요약 + 경보
  --dry   : 보내지 않고 출력만
"""
from __future__ import annotations

import sys
import urllib.parse
import urllib.request

sys.path.insert(0, "/home/quant/quant-v31")
import psycopg
from psycopg.rows import dict_row

from engine_v4.config.settings import get_config
from engine_v4.data.prices import install_download_lock
from engine_v4.notify.core_report import alloc_message, summary_message


def tg(text: str) -> bool:
    cfg = get_config()
    tok, chat = cfg.telegram_bot_token.strip(), cfg.telegram_chat_id.strip()
    if not tok or not chat:
        print("telegram 설정 없음")
        return False
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=20).read()
        return True
    except Exception as e:  # 토큰이 섞인 URL 은 출력하지 않는다
        print(f"telegram 실패: {type(e).__name__}")
        return False


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    mode = args[0] if args else "summary"
    install_download_lock()
    with psycopg.connect(get_config().pg_dsn, row_factory=dict_row) as c:
        msg = {"alloc": alloc_message, "summary": summary_message}[mode](c)
    if msg:
        print(msg)
        if not dry:
            print("sent" if tg(msg) else "not sent")
    else:
        print("(발송 없음)")


if __name__ == "__main__":
    main()
