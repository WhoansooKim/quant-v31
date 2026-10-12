#!/usr/bin/env python
"""6시간 정밀 감시 — §22.AO-43 출구 교정 전진검증 + 벤치마크 대조.

왜 '변화가 있을 때만' 보고하는가: 0.92 게이트에서 체결은 월 ~5건이다. 6시간마다
빈 보고를 보내면 §22.AO-28 의 양치기 소년이 되어 진짜 경보를 무시하게 된다.
→ 6시간마다 **검사**하고, 상태가 바뀌었거나 하루 1회 요약 시각일 때만 **발송**한다.

감시 항목
  1. config 드리프트 — 등록키 중 하나라도 되돌아가면 실험 무효 (즉시 경보)
  2. 신규 청산 진척 — n / 25, 실현 중앙값 vs +0.50% 기준선
  3. 청산 사유별 중앙값 — 특히 trail_or_be 가 0% 부근을 벗어났는가 (교정의 직접 서명)
  4. 보유 포지션의 확보 수익 — 스톱이 진입 위로 올라갔는가
  5. 투자율 — 45% 목표 대역(33~48%) 집행 여부 + 낙폭 중단선 −30%
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
          "swing_legacy_exit_enabled": "false", "intersection_momentum_min": "0.92",
          # §22.AO-44 투자율 29%→45% (사용자 결정 2026-10-12). 이 둘은 **쌍으로만** 의미가 있다:
          #   position_pct 만 올리면 신호 폭주 때 100% 까지 가고, 그 폭주는 낙폭 직전에 일어난다.
          #   max_total_exposure_pct 가 백테스트의 target_deploy 와 같은 하드캡 역할을 한다.
          "position_pct": "0.10", "max_total_exposure_pct": "0.45",
          # §22.AO-46: dual_sort 는 거래당 구별력이 0인데 포트폴리오를 −5.0%p 깎았다.
          #   기전 — 모멘텀이 높을수록 기각률이 올라간다(0.92~0.95 15.7% → 0.995+ 23.8%).
          #   거래당 중앙값은 같아도(통과 +0.497% vs 기각 +0.541%) 포트폴리오는 상위
          #   모멘텀부터 담으므로, 최상위를 빼면 수익이 빠진다.
          "dual_sort_enabled": "false"}
# 사전등록(§22.AO-44) — 투자율은 수익 다이얼이 아니라 위험 다이얼이다. 기대와 중단선을 먼저 못박는다.
DEP_TARGET = 45.0          # 목표 투자율 %
DEP_BAND = (33.0, 48.0)    # 이 밖이면 다이얼이 의도대로 안 먹은 것 (NEUTRAL×0.85 감쇠 포함)
# §22.AO-45 정정: 아래 두 값은 **가격 하한 $10 을 넣은** 백테스트 기준이다.
#   라이브 유니버스 최저가가 $13.4 라 하한이 사실상 걸려 있는데, 이전 기대값(−44.2)은
#   하한 없는 조건(= $10 미만 종목 포함, 그 구간 중앙 +1.23% 로 최고 성과)의 값이었다.
#   하한을 넣으면 5슬롯@45% 는 CAGR 22.5%/−44.2% 가 아니라 **18.9%/−42.9%** 다.
DD_EXPECT = -42.9          # 백테스트 5슬롯@45% 최대낙폭(하한 $10 포함)
DD_YEAR_MEAN = -8.9        # 연도별 최대낙폭의 평균 — MDD 보다 표본성질이 훨씬 낫다.
#   🔴 MDD 는 14.8년 중 한 구간이 정해서 인접 설정끼리 7~9%p 씩 튄다
#      (해제 10슬롯 −41.5% vs 12슬롯 −32.2%). 판정에는 연낙폭 평균을 쓸 것.
DD_KILL = -30.0            # 실측 낙폭이 여기 닿으면 투자율을 되돌릴지 사용자에게 묻는다
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

    L.append(f"<b>§22.AO-43 출구교정 + AO-44 투자율45% 감시</b>  {dt.datetime.now():%m-%d %H:%M}")
    if drift:
        L.append("\n🔴 <b>CONFIG 드리프트 — 실험 무효 위험</b>")
        for k, (want, got) in drift.items():
            L.append(f"  {k}: 기대 {want} / 실제 {got}")
        L.append("  되돌린 주체를 찾을 것 (regime_switcher · 변이 적용 · 수동)")
    else:
        L.append(f"\n✅ config {len(EXPECT)}키 유지")

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
            ddm = float(sn["dd"] or 0) * 100
            state["dd"] = round(ddm, 1)
            if dep < DEP_BAND[0]:
                # 동시보유가 적으면 다이얼을 올려도 투자율이 안 오른다 — 공급 제약 신호다.
                L.append(f"  투자율 {dep:.0f}%  ⚠️ 목표 {DEP_TARGET:.0f}% 미달"
                         f" — 신호 공급 제약(게이트)일 수 있다. 동시보유 수를 확인하라")
            elif dep > DEP_BAND[1]:
                L.append(f"  투자율 {dep:.0f}%  🔴 상한 초과 — max_total_exposure_pct 가 안 먹고 있다")
            else:
                L.append(f"  투자율 {dep:.0f}%  ✅ 목표 {DEP_TARGET:.0f}% 대역")
            if ddm <= DD_KILL:
                L.append(f"  🔴 <b>낙폭 {ddm:.1f}% — 중단 검토선 {DD_KILL:.0f}% 도달</b>"
                         f" (백테스트 기대 최악 {DD_EXPECT:.1f}%). 투자율 되돌릴지 판단 필요")
                state["urgent"] = True

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
    L.append("\n<i>14.8년 백테스트 (가격 하한 $10 포함 — 라이브 유니버스 최저가 $13.4):\n"
             "  <b>5슬롯 @45% CAGR +18.9% · 최대낙폭 −42.9% · 연낙폭평균 −8.9% · 샤프 1.20</b>\n"
             "  12슬롯 경로는 수익 매칭하면 낙폭이 같았다(−8.9%) — 적용하지 않음(§22.AO-45)</i>")
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
