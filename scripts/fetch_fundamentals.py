#!/usr/bin/env python
"""Finnhub 분기 재무 시계열 소급 수집 (§22.AO-46).

왜 필요했나: `strategy/swing.py` 의 `_apply_dual_sort` 가 라이브 진입 공급의 **63%** 를
거르는데(월 21.2 → 7.9건) 그 효과를 측정할 수 없었다 — `_quick_value_score` 가 Finnhub
재무지표를 쓰고 `hist_indicators` 에 그 컬럼이 없었다. 라이브 n=130 으로는 거래당 효과를
검정할 수 없다([[measurement-bandwidth-first]]).

무료 티어 확인: /stock/metric 은 `metric`(현재) 외에 `series.quarterly` 를 같이 준다.
  peTTM n≈104 (2000~) · pb n≈107 (1999~) · fcfPerShareTTM n≈143 (1990~)
  evEbitdaTTM 는 대개 비어 있다 — 그런데 **라이브의 현재 지표에서도 None** 이라 충실하다.

재개 가능: hist_fundamentals_fetch 에 종목별 상태를 남기고 이미 받은 종목은 건너뛴다.
속도: 🔴 병목은 레이트리밋이 아니라 **응답 지연**이다 — 한 호출이 12~14초(응답 120~260KB)라
  순차로는 1504종목에 5.4시간이 걸린다. 8스레드로 받으면 ≈37회/분(무료 한도 60 아래)에
  40~50분이다. HTTP 는 스레드에서, DB 쓰기는 **메인 스레드 한 곳**에서만 한다.
"""
from __future__ import annotations
import json, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKERS = 8

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

SLEEP = 1.15
BASE = "https://finnhub.io/api/v1/stock/metric"


def api_key() -> str:
    for line in open("/home/quant/quant-v31/.env", encoding="utf-8"):
        if line.startswith("FINNHUB_API_KEY"):
            return line.split("=", 1)[1].strip()
    raise SystemExit("FINNHUB_API_KEY 없음")


def targets(pg) -> list[str]:
    """백테스트 신호에 실제로 등장하는 종목만 — 상위200 유동성 × mom>=0.92."""
    with pg.get_conn() as c:
        rows = c.execute("""
            WITH u AS (SELECT i.symbol,
                              row_number() OVER (PARTITION BY i.time
                                                 ORDER BY i.dollar_vol_20d DESC) lr
                       FROM hist_indicators i
                       WHERE i.clean AND i.trend_aligned AND i.breakout_5d
                             AND i.volume_ratio >= 1.0 AND i.atr14 > 0
                             AND i.return_20d_rank >= 0.92)
            SELECT DISTINCT u.symbol FROM u
            WHERE u.lr <= 200
              AND NOT EXISTS (SELECT 1 FROM hist_fundamentals_fetch f
                              WHERE f.symbol = u.symbol AND f.status IN ('ok','empty'))
            ORDER BY 1""").fetchall()
    return [r["symbol"] for r in rows]


def series_map(ser: dict, key: str) -> dict:
    """[{period, v}] → {period: v}. None/비유한/절대값 1e9 초과는 버린다.

    🔴 P/E 가 10^12 인 종목이 있다(이익이 0 에 가까운 분기). numeric(14,4) 에서
       overflow 로 수집이 160종목에서 죽었다. 점수는 임계값 비교(pe<15/20/30)만 쓰므로
       거대값은 '비싸다'와 구분이 없다 — 버려도 판정이 바뀌지 않는다."""
    out = {}
    for x in ser.get(key, []) or []:
        v = x.get("v")
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v != v or v in (float("inf"), float("-inf")) or abs(v) > 1e9:
            continue
        out[x["period"]] = v
    return out


def fetch(sym: str, key: str) -> dict | None:
    url = f"{BASE}?symbol={sym}&metric=all&token={key}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:            # 레이트리밋 — 기다렸다 재시도
                time.sleep(20 * (attempt + 1)); continue
            if e.code in (403, 404):     # 권한없음/없는 종목 — 재시도 무의미
                return None
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def parse(sym: str, d: dict) -> tuple[list, tuple]:
    """응답 → (hist_fundamentals 행들, hist_fundamentals_fetch 행)."""
    m = d.get("metric") or {}
    q = (d.get("series") or {}).get("quarterly") or {}
    pe, pb = series_map(q, "peTTM"), series_map(q, "pb")
    fcf, ev = series_map(q, "fcfPerShareTTM"), series_map(q, "evEbitdaTTM")
    periods = sorted(set(pe) | set(pb) | set(fcf) | set(ev))
    rows = [(sym, p, pe.get(p), pb.get(p), fcf.get(p), ev.get(p)) for p in periods]
    def _n(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return None if (v != v or abs(v) > 1e9) else v
    audit = (sym, "ok" if rows else "empty", len(rows),
             _n(m.get("peTTM")), _n(m.get("pbAnnual")),
             _n(m.get("freeCashFlowYieldTTM")), _n(m.get("enterpriseValue/ebitdaTTM")))
    return rows, audit


def main() -> None:
    key = api_key()
    pg = PostgresStore(get_config().pg_dsn)
    syms = targets(pg)
    est = len(syms) * 13 / max(WORKERS, 1) / 60
    print(f"대상 {len(syms)}종목 (이미 받은 것 제외)  스레드 {WORKERS}  예상 {est:.0f}분", flush=True)
    ok = empty = err = 0
    done = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch, s_, key): s_ for s_ in syms}
        for fu in as_completed(futs):
            sym = futs[fu]
            done += 1
            try:
                d = fu.result()
            except Exception:
                d = None
            if not d or not isinstance(d, dict):
                with pg.get_conn() as c:
                    c.execute("""INSERT INTO hist_fundamentals_fetch(symbol,status)
                                 VALUES(%s,'error') ON CONFLICT (symbol) DO UPDATE
                                 SET status='error', fetched_at=now()""", (sym,))
                    c.commit()   # 🔴 get_conn 은 커밋 없이 닫는다(storage.py:29)
                err += 1
            else:
                rows, audit = parse(sym, d)
                with pg.get_conn() as c:
                    if rows:
                        c.cursor().executemany("""
                            INSERT INTO hist_fundamentals
                              (symbol,period,pe_ttm,pb,fcf_per_share,ev_ebitda)
                            VALUES (%s,%s,%s,%s,%s,%s)
                            ON CONFLICT (symbol,period) DO UPDATE SET
                              pe_ttm=EXCLUDED.pe_ttm, pb=EXCLUDED.pb,
                              fcf_per_share=EXCLUDED.fcf_per_share,
                              ev_ebitda=EXCLUDED.ev_ebitda""", rows)
                    c.execute("""INSERT INTO hist_fundamentals_fetch
                                   (symbol,status,n_periods,cur_pe,cur_pb,
                                    cur_fcfy,cur_evebitda)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s)
                                 ON CONFLICT (symbol) DO UPDATE SET
                                   status=EXCLUDED.status, n_periods=EXCLUDED.n_periods,
                                   cur_pe=EXCLUDED.cur_pe, cur_pb=EXCLUDED.cur_pb,
                                   cur_fcfy=EXCLUDED.cur_fcfy,
                                   cur_evebitda=EXCLUDED.cur_evebitda,
                                   fetched_at=now()""", audit)
                    c.commit()   # 🔴 같은 이유 — 빼먹으면 전부 롤백된다
                ok += 1 if rows else 0
                empty += 0 if rows else 1
            if done % 50 == 0 or done == len(syms):
                rate = done / max(time.time() - t0, 1) * 60
                print(f"  {done}/{len(syms)}  ok={ok} empty={empty} err={err}"
                      f"  {rate:.0f}회/분", flush=True)
    print(f"완료: ok={ok} empty={empty} error={err}", flush=True)


if __name__ == "__main__":
    main()
