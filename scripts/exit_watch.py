#!/usr/bin/env python
"""6시간 정밀 감시 — §22.AO-43 출구 교정 전진검증 + 벤치마크 대조.

왜 '변화가 있을 때만' 보고하는가: 0.92 게이트에서 체결은 월 ~5건이다. 6시간마다
빈 보고를 보내면 §22.AO-28 의 양치기 소년이 되어 진짜 경보를 무시하게 된다.
→ 6시간마다 **검사**하고, 상태가 바뀌었거나 하루 1회 요약 시각일 때만 **발송**한다.

감시 항목
  1. config 드리프트 — 6키 중 하나라도 되돌아가면 실험 무효 (즉시 경보)
  2. 신규 청산 진척 — n / 25, 실현 중앙값 vs +0.50% 기준선
  3. 청산 사유별 중앙값 — 특히 trail_or_be 가 0% 부근을 벗어났는가 (교정의 직접 서명)
  4. 보유 포지션의 확보 수익 — 스톱이 진입 위로 올라갔는가
  5. 투자율 — 18% 경로는 ~45% 를 요구한다 (현재 29%)
  6. 벤치마크 대조 — 적용일 이후 시스템 vs SPY / QQQ
"""
from __future__ import annotations
import sys, os, json, hashlib, datetime as dt, urllib.request, urllib.parse

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

CUTOFF = "2026-10-11"          # §22.AO-43 적용일
MIN_N, BAR_MEDIAN = 25, 0.50   # 사전등록 기준
KILL_N, KILL_MEDIAN = 15, -1.0 # 중단 조건
EXPECT = {"atr_trailing_multiplier": "1.0", "breakeven_enabled": "false",
          "rsi2_exit_min_hold_days": "999", "time_stop_days": "60",
          "swing_legacy_exit_enabled": "false", "intersection_momentum_min": "0.92"}
STATE = "/home/quant/quant-v31/scripts/.exit_watch_state"
ENVF = "/home/quant/quant-v31/.env"


def tg(text: str) -> bool:
    try:
        env = dict(l.strip().split("=", 1) for l in open(ENVF)
                   if "=" in l and not l.startswith("#"))
        tok = env.get("TELEGRAM_BOT_TOKEN", "").strip('"\' ')
        chat = env.get("TELEGRAM_CHAT_ID", "").strip('"\' ')
        if not tok or not chat:
            return False
        data = urllib.parse.urlencode(
            {"chat_id": chat, "text": text, "parse_mode": "HTML"}).encode()
        urllib.request.urlopen(
            f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=20).read()
        return True
    except Exception as e:
        print(f"telegram 실패: {e}")
        return False


def build(pg) -> tuple[str, dict]:
    L, state = [], {}
    cur = {k: pg.get_config_value(k, None) for k in EXPECT}
    drift = {k: (v, cur[k]) for k, v in EXPECT.items() if cur[k] != v}
    state["drift"] = sorted(drift)

    L.append(f"<b>§22.AO-43 출구 교정 감시</b>  {dt.datetime.now():%m-%d %H:%M}")
    if drift:
        L.append("\n🔴 <b>CONFIG 드리프트 — 실험 무효 위험</b>")
        for k, (want, got) in drift.items():
            L.append(f"  {k}: 기대 {want} / 실제 {got}")
        L.append("  되돌린 주체를 찾을 것 (regime_switcher · 변이 적용 · 수동)")
    else:
        L.append("\n✅ config 6키 유지")

    with pg.get_conn() as c:
        r = c.execute("""
            SELECT count(*) n,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY realized_pct*100) med,
                   avg(realized_pct*100) avg_, avg(hold_days) hd,
                   count(*) FILTER (WHERE realized_pct > 0) w
            FROM swing_positions
            WHERE status='closed' AND exit_time::date > %s""", (CUTOFF,)).fetchone()
        n = r["n"] or 0
        state["n_new"] = n
        L.append(f"\n<b>신규 청산 {n}/{MIN_N}건</b>  (적용 {CUTOFF} 이후)")
        if n:
            med = float(r["med"]); wr = r["w"] / n * 100
            state["med"] = round(med, 2)
            mark = "✅" if med > BAR_MEDIAN else ("⚠️" if med > 0 else "🔴")
            L.append(f"  실현 중앙 {med:+.2f}% {mark} (기준 &gt;+{BAR_MEDIAN:.2f}%)"
                     f" · 평균 {float(r['avg_']):+.2f}%")
            L.append(f"  승률 {wr:.0f}% (백테스트 59.3%) · 보유 {float(r['hd']):.1f}d")
            if n >= KILL_N and med < KILL_MEDIAN:
                L.append(f"  🔴 <b>중단 조건 도달</b> (n≥{KILL_N} 에서 중앙 &lt;{KILL_MEDIAN}%)"
                         f" — 되돌림 검토")
            # 교정의 직접 서명: 사유별 중앙값
            rs = c.execute("""
                SELECT exit_reason,count(*) n,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY realized_pct*100) med
                FROM swing_positions WHERE status='closed' AND exit_time::date > %s
                GROUP BY 1 ORDER BY 2 DESC""", (CUTOFF,)).fetchall()
            L.append("  사유별: " + " · ".join(
                f"{x['exit_reason']} {x['n']}건 {float(x['med']):+.1f}%" for x in rs))
        else:
            L.append("  아직 없음 — 0.92 게이트에서 월 ~5건 예상, 판정은 2027-01-31 또는 n≥25")

        op = c.execute("""
            SELECT symbol, entry_price::float ep, stop_loss::float sl,
                   current_price::float cp
            FROM swing_positions WHERE status='open' ORDER BY symbol""").fetchall()
        if op:
            locked = [(x["symbol"], (x["sl"] / x["ep"] - 1) * 100) for x in op if x["sl"] and x["ep"]]
            state["locked"] = {s: round(v, 1) for s, v in locked}
            pos_n = sum(1 for _, v in locked if v > 0)
            L.append(f"\n<b>보유 {len(op)}건 · 스톱이 진입 위 {pos_n}건</b>"
                     f"  ← 교정의 직접 효과")
            for s, v in locked:
                L.append(f"  {s}: 확보 {v:+.1f}%" + ("  ✅" if v > 0 else ""))

        sn = c.execute("""SELECT total_value_usd::float tv, invested_usd::float iv,
                                 cumulative_return::float cr, max_drawdown::float dd, time
                          FROM swing_snapshots ORDER BY time DESC LIMIT 1""").fetchone()
        if sn and sn["tv"]:
            dep = (sn["iv"] or 0) / sn["tv"] * 100
            state["dep"] = round(dep)
            L.append(f"\n<b>자산 ${sn['tv']:,.0f}</b> · 누적 {float(sn['cr'] or 0)*100:+.2f}%"
                     f" · 최대낙폭 {float(sn['dd'] or 0)*100:.1f}%")
            L.append(f"  투자율 {dep:.0f}%  (18% 경로는 ~45% 요구 — 백테스트 @29% 는 11.2%)")

        # 벤치마크 — 적용일 이후
        bm = []
        for s in ("SPY", "QQQ"):
            # 기준가는 **적용일 직전 봉**이다(적용일이 주말이면 그 이후 봉이 없다).
            b = c.execute("""
                WITH b0 AS (SELECT close::float v FROM daily_prices
                            WHERE symbol=%s AND time::date <= %s
                            ORDER BY time DESC LIMIT 1),
                     b1 AS (SELECT close::float v FROM daily_prices
                            WHERE symbol=%s ORDER BY time DESC LIMIT 1)
                SELECT ((SELECT v FROM b1)/NULLIF((SELECT v FROM b0),0)-1)*100 AS ret""",
                (s, CUTOFF, s)).fetchone()
            if b and b["ret"] is not None:
                bm.append(f"{s} {float(b['ret']):+.2f}%")
        s0 = c.execute("""SELECT total_value_usd::float v FROM swing_snapshots
                          WHERE time::date <= %s ORDER BY time DESC LIMIT 1""", (CUTOFF,)).fetchone()
        if bm:
            sys_ret = ((sn["tv"] / s0["v"] - 1) * 100) if (s0 and s0["v"] and sn) else None
            line = f"\n<b>적용 이후 대조</b>: " + " · ".join(bm)
            if sys_ret is not None:
                line += f" · <b>시스템 {sys_ret:+.2f}%</b>"
                state["sysret"] = round(sys_ret, 2)
            L.append(line)
    L.append("\n<i>14.8년 56,340거래 기준: @29% CAGR 11.2% / @45% 17.5% (낙폭 −32%)</i>")
    return "\n".join(L), state


if __name__ == "__main__":
    force = "--force" in sys.argv
    pg = PostgresStore(get_config().pg_dsn)
    msg, state = build(pg)
    h = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    prev = ""
    try:
        prev = json.load(open(STATE)).get("hash", "")
    except Exception:
        pass
    changed = h != prev
    digest = dt.datetime.now().hour in (9,)      # 하루 1회 요약 시각
    urgent = bool(state.get("drift")) or (
        state.get("n_new", 0) >= KILL_N and state.get("med", 0) < KILL_MEDIAN)
    print(msg.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""))
    print(f"\n[state {h} / prev {prev} / changed={changed} digest={digest} urgent={urgent}]")
    if force or urgent or (changed and state.get("n_new", 0) > 0) or digest:
        if tg(msg):
            print("텔레그램 발송")
    else:
        print("변화 없음 — 발송 생략(빈 보고 반복 방지)")
    json.dump({"hash": h, "at": dt.datetime.now().isoformat(), "state": state},
              open(STATE, "w"), ensure_ascii=False)
