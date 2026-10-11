#!/usr/bin/env python
"""분할 역조정 가격 테이블 생성 (§22.AO-43).

왜: daily_prices 는 분할 미조정이다. 수집기가 신규 봉만 upsert 하고 분할 시 과거를
    재조정하지 않기 때문이다. 196종목 423건의 불연속이 있고, 15.6년 백테스트에서
    2:1 분할은 **가짜 −50% 폭락일**로 나타나 스톱을 오발시키고 return_20d_rank 를 0 으로 만든다.

🔴 라이브 daily_prices 는 변경하지 않는다(엔진이 읽는다). 별도 테이블 hist_prices_adj 에 쓴다.
   라이브 테이블 재조정은 사용자 승인이 필요한 별건이다.

분할 이력은 yfinance 로 무료 취득한다(유료 API 미사용 — §22.AO-25 사용자 결정).
"""
from __future__ import annotations
import sys, time as _t
import pandas as pd, numpy as np, yfinance as yf

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

pg = PostgresStore(get_config().pg_dsn)

with pg.get_conn() as c:
    susp = [r["symbol"] for r in c.execute("""
        WITH j AS (SELECT symbol, time,
                 close/NULLIF(lag(close) OVER (PARTITION BY symbol ORDER BY time),0) r
                 FROM daily_prices)
        SELECT DISTINCT symbol FROM j WHERE r IS NOT NULL AND (r<0.65 OR r>1.55)
        ORDER BY symbol""").fetchall()]
print(f"불연속 종목 {len(susp)}개 — yfinance 에서 분할 이력 조회")

splits: dict[str, pd.Series] = {}
fail = []
for i, s in enumerate(susp, 1):
    try:
        sp = yf.Ticker(s).splits
        if sp is not None and len(sp):
            splits[s] = sp
    except Exception as e:
        fail.append((s, str(e)[:60]))
    if i % 40 == 0:
        print(f"  {i}/{len(susp)} …")
        _t.sleep(1)
print(f"분할 이력 확보 {len(splits)}종목 / 조회실패 {len(fail)}")
if fail:
    print("  실패:", fail[:5])

# 누적 역조정 계수: 분할일 **이전** 행을 1/ratio 배 한다(가격), 거래량은 ratio 배.
rows_out, stats = [], []
with pg.get_conn() as c:
    for s in splits:
        px = pd.DataFrame(c.execute("""
            SELECT time, open, high, low, close, volume FROM daily_prices
            WHERE symbol=%s ORDER BY time""", (s,)).fetchall())
        if px.empty:
            continue
        px["time"] = pd.to_datetime(px["time"], utc=True)
        for col in ("open", "high", "low", "close"):
            px[col] = px[col].astype(float)
        px["volume"] = px["volume"].astype(float)
        sp = splits[s]
        sp.index = pd.to_datetime(sp.index, utc=True)
        # 🔴 daily_prices 는 **부분적으로 이미 조정돼 있다**: 종목 최초 수집 시점에
        #    yfinance 가 그때까지의 분할을 반영한 이력을 주므로, 불연속은 **최초 수집 이후
        #    발생한 분할**만 만든다. yfinance 전체 분할 이력을 적용하면 과거분이 이중조정된다
        #    (NFLX 7:1×10:1 → 계수 0.0143 으로 불연속이 423→489 건 증가하는 것을 실측).
        #    따라서 **DB 에서 실제로 관측된 불연속일**에만, 그 날짜의 분할비로 조정한다.
        # 🔴 메커니즘(실측 규명): 수집기는 후행 ~435일 창만 재조회한다. 분할이 나면
        #    yfinance 는 전체 이력을 조정해 주므로 **창 안쪽은 재조정되지만 창보다 오래된
        #    행은 분할 전 가격으로 남는다** → 불연속이 (분할일 − 435일) 에 생긴다.
        #    실측: BKNG 분할 2026-04-06 / 불연속 2025-01-24 (437일), KLAC 435일, APH 434일.
        #    따라서 yfinance 의 **분할 날짜는 쓸 수 없다**(경계와 1년 이상 어긋난다).
        #    대신 **관측된 배율 자체가 조정 계수**다. 분할 여부 판정에만 yfinance 배율을 쓴다.
        known = sorted({float(x) for x in sp.values if x and float(x) > 0})
        px["_r"] = px["close"] / px["close"].shift(1)
        px["_vr"] = px["volume"] / px["volume"].shift(1)
        obs = px[(px["_r"] < 0.65) | (px["_r"] > 1.55)]
        factor = pd.Series(1.0, index=px.index)
        applied = 0
        for _, orow in obs.iterrows():
            r, vr = float(orow["_r"]), orow["_vr"]
            # 이 종목의 알려진 분할비 중 관측배율과 맞는 것이 있는가 (1/ratio 또는 ratio)
            hit = None
            for k in known:
                for cand in (1.0 / k, k):
                    if cand > 0 and 0.93 <= r / cand <= 1.07:
                        hit = cand
                        break
                if hit:
                    break
            if hit is None:
                continue
            # 분할은 가격과 주수가 역방향으로 움직인다 — 실제 급등락과 구분하는 확인
            if vr is None or pd.isna(vr) or vr <= 0:
                continue
            if not (0.25 <= (vr * r) <= 4.0):
                continue
            factor[px["time"] < orow["time"]] = \
                factor[px["time"] < orow["time"]] * r
            applied += 1
        px = px.drop(columns=["_r", "_vr"])
        if applied == 0:
            continue
        for col in ("open", "high", "low", "close"):
            px[col] = px[col] * factor
        px["volume"] = px["volume"] / factor      # 가격 축소 ↔ 주수 증가
        px["symbol"] = s
        rows_out.append(px)
        stats.append({"symbol": s, "splits_applied": applied,
                      "min_factor": round(float(factor.min()), 6)})

print(f"\n역조정 적용 {len(rows_out)}종목")
if stats:
    sdf = pd.DataFrame(stats).sort_values("min_factor")
    print(sdf.head(10).to_string(index=False))

# 조정 테이블: 조정분은 역조정값, 나머지 종목은 원본 그대로 복사
with pg.get_conn() as c:
    c.execute("DROP TABLE IF EXISTS hist_prices_adj")
    c.execute("""CREATE TABLE hist_prices_adj (
        time timestamptz NOT NULL, symbol varchar(10) NOT NULL,
        open numeric(14,6), high numeric(14,6), low numeric(14,6),
        close numeric(14,6), volume double precision,
        adjusted boolean NOT NULL DEFAULT false,
        PRIMARY KEY (time, symbol))""")
    c.execute("SELECT create_hypertable('hist_prices_adj','time',chunk_time_interval=>INTERVAL '1 year')")
    c.commit()
    adj_syms = [df["symbol"].iloc[0] for df in rows_out]
    c.execute("""INSERT INTO hist_prices_adj (time,symbol,open,high,low,close,volume,adjusted)
                 SELECT time,symbol,open,high,low,close,volume::float,false
                 FROM daily_prices WHERE NOT (symbol = ANY(%s))""", (adj_syms,))
    c.commit()
    print(f"미조정 종목 복사 완료")
    with c.cursor() as cur:
        for df in rows_out:
            recs = list(df[["time","symbol","open","high","low","close","volume"]]
                        .itertuples(index=False, name=None))
            cur.executemany("""INSERT INTO hist_prices_adj
                (time,symbol,open,high,low,close,volume,adjusted) VALUES (%s,%s,%s,%s,%s,%s,%s,true)
                ON CONFLICT (time,symbol) DO NOTHING""", recs)
    c.commit()
    n = c.execute("SELECT count(*) c, count(*) FILTER (WHERE adjusted) a FROM hist_prices_adj").fetchone()
    print(f"hist_prices_adj: 총 {n['c']:,}행 (역조정 {n['a']:,}행)")

    # 검증: 역조정 후 불연속이 줄었는가
    chk = c.execute("""
        WITH j AS (SELECT symbol, close/NULLIF(lag(close) OVER (PARTITION BY symbol ORDER BY time),0) r
                   FROM hist_prices_adj)
        SELECT count(*) n, count(DISTINCT symbol) s FROM j WHERE r IS NOT NULL AND (r<0.65 OR r>1.55)
    """).fetchone()
    print(f"역조정 후 남은 불연속: {chk['n']}건 / {chk['s']}종목  (조정 전 423건 / 196종목)")
