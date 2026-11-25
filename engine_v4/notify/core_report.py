"""코어 운용 보고 메시지 (2026-11-22) — 은퇴한 스윙 감시기(exit_watch·payoff·ao26) 대체.

scripts/core_daily.py(cron)와 텔레그램 봇 /status 가 같은 함수를 쓴다. 메시지를 만들기만 하고 보내지 않는다.

경보 기준(정상 흐름에서는 울리지 않아야 한다)
  - 마지막 core_allocate 실패 / 최근 30시간 스냅샷 없음
  - 현금 > 예비금 + $30 (배분이 돈을 놀리고 있다)
  - 코어 슬리브 안 UPRO 비율이 추세 on 비율에서 15%p 이상 벗어남
  - J 슬리브 비중이 목표(core_j_weight)에서 12%p 이상 벗어남 (월중 동결 드리프트보다 큰 어긋남만)
손실 표기: 재시작($2,000) 대비와 총 실투입(초기자본 + 입출금) 대비를 항상 함께 쓴다.
입력 c 는 psycopg 연결(row_factory=dict_row).
"""
from __future__ import annotations

import datetime as dt
import json
from zoneinfo import ZoneInfo

from engine_v4.data.prices import last_closes

KST = ZoneInfo("Asia/Seoul")
ET = ZoneInfo("America/New_York")
CORE_SYMS = {"UPRO", "BIL"}


def cfg(c, key: str, default: str = "") -> str:
    r = c.execute("SELECT value FROM swing_config WHERE key=%s", (key,)).fetchone()
    return r["value"] if r and r["value"] is not None else default


def money(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"


def pct(x: float) -> str:
    return f"{'+' if x >= 0 else '−'}{abs(x) * 100:.2f}%"


def last_alloc(c):
    return c.execute("""SELECT created_at, status, error_msg, details FROM swing_pipeline_log
                        WHERE step_name='core_allocate' ORDER BY created_at DESC LIMIT 1""").fetchone()


def alloc_message(c) -> str | None:
    """core_allocate 직후 점검 — 실패/미실행이면 🔴, 주문이 있었으면 요약, 그 외 None(무발송)."""
    r = last_alloc(c)
    now = dt.datetime.now(KST)
    if r is None or (now - r["created_at"].astimezone(KST)).total_seconds() > 3 * 3600:
        return (f"🔴 <b>코어 배분 실행 기록 없음</b>\n오늘 00:30 core_allocate 가 돌지 않았다 "
                f"(마지막 {r['created_at'].astimezone(KST):%m-%d %H:%M} KST)." if r else "🔴 <b>코어 배분 기록이 전혀 없다</b>")
    if r["status"] != "completed":
        return (f"🔴 <b>코어 배분 실패</b> ({r['created_at'].astimezone(KST):%m-%d %H:%M} KST)\n"
                f"{(r['error_msg'] or '')[:300]}\n다음 실행이 재시도한다 — 원인 확인 필요.")
    d = r["details"] or {}
    orders = d.get("orders") or []
    if not orders:
        return None  # 주문 없는 정상 실행은 조용히
    t = d.get("trend") or {}
    lines = [f"🏛️ <b>코어 배분 주문 {len(orders)}건</b> ({r['created_at'].astimezone(KST):%m-%d %H:%M} KST)"]
    if t:
        lines.append(f"추세 {t.get('label')} (SPY ${t.get('close')} vs SMA200 ${t.get('sma')}, {t.get('asof')})"
                     + (" ⚡전환" if t.get("changed") else ""))
    lines += [f"  {o}" for o in orders[:14]]
    lines.append(f"현금 ${d.get('cash_before')} → ${d.get('cash_after')}")
    return "\n".join(lines)


def trend_preview(c) -> dict | None:
    """다음 core_allocate 가 쓸 판정(직전 확정 종가 기준)을 엔진과 같은 히스테리시스로 미리 계산."""
    import yfinance as yf
    try:
        n = int(cfg(c, "core_trend_sma", "200"))
        bufs = [float(b) for b in json.loads(cfg(c, "core_trend_bufs", "[0,0.01,0.02,0.03,0.04,0.05]"))]
        prev = json.loads(cfg(c, "core_trend_state", "{}") or "{}")
        close = yf.Ticker(cfg(c, "core_symbol", "SPY")).history(period="14mo", auto_adjust=True)["Close"].dropna()
        et_now = dt.datetime.now(ET)
        if (et_now.hour, et_now.minute) < (16, 15):
            close = close[close.index.date < et_now.date()]
        cl, sma = float(close.iloc[-1]), float(close.iloc[-n:].mean())
        st = {}
        for b in bufs:
            k, p = f"{b:g}", prev.get(f"{b:g}")
            st[k] = ("off" if cl < sma * (1 - b) else "on") if p == "on" else \
                    ("on" if cl > sma * (1 + b) else "off") if p == "off" else ("on" if cl > sma else "off")
        return {"asof": str(close.index[-1].date()), "close": cl, "sma": sma,
                "on": sum(v == "on" for v in st.values()), "n": len(st),
                "prev_on": sum(v == "on" for v in prev.values()) if prev else None}
    except Exception as e:
        print(f"trend preview 실패: {e}")
        return None


def summary_message(c) -> str:
    """일일 요약 + 경보. 텔레그램 /status 와 cron 일일 보고가 같은 함수를 쓴다."""
    alerts: list[str] = []
    sn = c.execute("SELECT * FROM swing_snapshots ORDER BY time DESC LIMIT 1").fetchone()
    if sn is None:
        return "🔴 <b>코어 일일 보고</b>: 스냅샷이 없다"
    age_h = (dt.datetime.now(dt.timezone.utc) - sn["time"]).total_seconds() / 3600
    if age_h > 30:
        alerts.append(f"🔴 마지막 스냅샷이 {age_h:.0f}시간 전 — 스냅샷 생성 확인")

    total = float(sn["total_value_usd"]); cash = float(sn["cash_usd"])
    epoch_cap = float(cfg(c, "account_epoch_capital", "0") or 0)
    epoch_t = cfg(c, "account_epoch_time", "")
    invested_all = float(cfg(c, "initial_capital", "0")) + float(c.execute(
        """SELECT COALESCE(SUM(CASE WHEN event_type='deposit' THEN amount
                                    WHEN event_type='withdraw' THEN -amount ELSE 0 END),0) s
           FROM swing_capital_events""").fetchone()["s"])
    prev = c.execute("""SELECT total_value_usd, trading_pnl FROM swing_snapshots
                        WHERE time < %s ORDER BY time DESC LIMIT 1""",
                     (sn["time"] - dt.timedelta(hours=20),)).fetchone()
    day_pnl = (float(sn["trading_pnl"]) - float(prev["trading_pnl"])) if prev and prev["trading_pnl"] is not None else None

    # 보유 — 스냅샷이 갱신한 current_price 로
    lots = c.execute("""SELECT symbol, qty, entry_price, current_price FROM swing_positions
                        WHERE status='open' AND side='CORE'""").fetchall()
    val: dict[str, float] = {}
    cost: dict[str, float] = {}
    for l in lots:
        p = float(l["current_price"] or l["entry_price"])
        val[l["symbol"]] = val.get(l["symbol"], 0) + float(l["qty"]) * p
        cost[l["symbol"]] = cost.get(l["symbol"], 0) + float(l["qty"]) * float(l["entry_price"])
    hv = sum(val.values()) or 1.0
    upro, bil = val.get("UPRO", 0.0), val.get("BIL", 0.0)
    jv = sum(v for s, v in val.items() if s not in CORE_SYMS)
    jc = sum(v for s, v in cost.items() if s not in CORE_SYMS)

    L = [f"🏛️ <b>코어 일일 보고</b> · {sn['time'].astimezone(KST):%m-%d %H:%M} KST 스냅샷"]
    if epoch_cap > 0:
        L.append(f"<b>총자산 ${total:,.2f}</b>  재시작 ${epoch_cap:,.0f} 대비 {money(total - epoch_cap)} ({pct(total / epoch_cap - 1)})")
    L.append(f"총 실투입 ${invested_all:,.2f} 대비 {money(total - invested_all)} ({pct(total / invested_all - 1)})")
    L.append(f"하루 손익 {money(day_pnl) if day_pnl is not None else '--'} · 재시작 후 최대낙폭 {float(sn['max_drawdown'] or 0) * 100:.1f}%")

    a = last_alloc(c)
    t = (a["details"] or {}).get("trend") if a and a["details"] else None
    if a is not None and a["status"] != "completed":
        alerts.append(f"🔴 마지막 배분({a['created_at'].astimezone(KST):%m-%d %H:%M}) 실패: {(a['error_msg'] or '')[:150]}")
    frac = None
    st = cfg(c, "core_trend_state", "")
    if st.startswith("{"):
        s_ = json.loads(st); frac = sum(v == "on" for v in s_.values()) / len(s_)
        L.append(f"\n<b>추세</b> 현재 {sum(v == 'on' for v in s_.values())}/{len(s_)} on"
                 + (f" (판정 {t['asof']} SPY ${t['close']} vs SMA200 ${t['sma']})" if t else ""))
    pv = trend_preview(c)
    if pv:
        chg = "" if pv["prev_on"] is None or pv["on"] == pv["prev_on"] else f"  ⚡ {pv['prev_on']}/{pv['n']} → {pv['on']}/{pv['n']}"
        L.append(f"  다음 배분 예상 {pv['on']}/{pv['n']} on ({pv['asof']} SPY ${pv['close']:.2f}, "
                 f"SMA200 대비 {pct(pv['close'] / pv['sma'] - 1)}){chg}")

    L.append(f"\n<b>비중</b> UPRO {upro / hv:.1%} · BIL {bil / hv:.1%} · J {jv / hv:.1%} · 현금 ${cash:,.2f}")
    if jc > 0:
        L.append(f"  J 10종목 평가 ${jv:,.2f} ({pct(jv / jc - 1)}) · UPRO "
                 + (f"{pct(upro / cost['UPRO'] - 1)}" if cost.get("UPRO") else "--"))

    # 섀도 — 같은 최신 시세로 평가해 실계좌와 같은 시점에서 비교
    sh = c.execute("""SELECT DISTINCT ON (variant) variant, holdings FROM core_shadow
                      ORDER BY variant, time DESC""").fetchall()
    first = c.execute("""SELECT details FROM core_shadow ORDER BY time LIMIT 1""").fetchone()
    if sh and first:
        base = float((first["details"] or {}).get("live_equity") or 0)
        syms = sorted({k for r in sh for k in (r["holdings"] or {}) if k != "_cash"})
        px, bad = last_closes(syms, period="5d")
        if base > 0 and not bad:
            parts = [f"실계좌 {pct(total / base - 1)}"]
            for r in sorted(sh, key=lambda r: r["variant"] != "core_only"):
                h = r["holdings"] or {}
                eq = float(h.get("_cash", 0)) + sum(float(q) * px[s] for s, q in h.items() if s != "_cash")
                parts.append(f"{r['variant']} {pct(eq / base - 1)}")
            L.append("\n<b>섀도</b> (시작 이후) " + " · ".join(parts))

    # 경보
    reserve = float(cfg(c, "core_cash_reserve_usd", "5"))
    if cash > reserve + 30:
        alerts.append(f"⚠️ 현금 ${cash:,.2f} — 예비금 ${reserve:.0f} 를 넘게 놀고 있다(배분 확인)")
    core_v = upro + bil
    if frac is not None and core_v > 0 and abs(upro / core_v - frac) > 0.15:
        alerts.append(f"⚠️ 코어 안 UPRO {upro / core_v:.0%} vs 추세 on 비율 {frac:.0%} — 15%p 넘게 어긋남")
    jw = float(cfg(c, "core_j_weight", "0") or 0)
    if jw > 0 and abs(jv / hv - jw) > 0.12:
        alerts.append(f"⚠️ J 비중 {jv / hv:.0%} vs 목표 {jw:.0%} — 12%p 넘게 어긋남(다음 월초 교체에서 재조정)")
    if alerts:
        L.append("\n" + "\n".join(alerts))
    return "\n".join(L)
