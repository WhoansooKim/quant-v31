#!/usr/bin/env python
"""과거 실적 발표일 — SEC EDGAR 8-K Item 2.02(Results of Operations) 로 복원.

왜 EDGAR 인가: swing_earnings_surprises.announce_date 는 2026-07 이후뿐이다(Finnhub 무료 한도).
실적 블랙아웃을 14.8년 백테스트로 재려면 전 기간 발표일이 필요하다. 8-K 2.02 는 미국 상장사가
실적 발표 시 의무 제출하므로 2001년 이후 무료·완전하다(유료 API 없음 원칙).

갭 반영일(gap_day): 시장이 뉴스를 처음 가격에 반영하는 거래일.
  acceptance < 09:30 ET → 그날 시가 / 그 외(장중·장후) → 다음 거래일 시가
  🔴 submissions JSON 의 acceptanceDateTime 은 **진짜 UTC** 다(2026-11-01 실측: 'Z' 그대로 읽으면
     10~12시·20~21시 군집 = 장전 06~08 ET·장후 16~17 ET 의 UTC 표기). 처음엔 동부시간이라 가정했다가
     분포 출력으로 틀린 것을 잡았다 → America/New_York 로 변환한다. main() 이 분포를 계속 출력한다.

출력: data/parquet/earnings/edgar_8k202.parquet  (symbol, filing_date, accept_et, gap_day)
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path
import httpx, numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

UA = {"User-Agent": "QuantV4 research admin@quant-v4.local"}
OUT = Path("/home/quant/quant-v31/data/parquet/earnings/edgar_8k202.parquet")
SLEEP = 0.12          # SEC 한도 10 req/s


def get(cl, url):
    for k in range(4):
        r = cl.get(url)
        if r.status_code == 200:
            time.sleep(SLEEP); return r.json()
        if r.status_code == 404:
            return None
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(f"{url} → {r.status_code}")


def rows_of(block):
    out = []
    for f, fd, acc, it in zip(block["form"], block["filingDate"],
                              block["acceptanceDateTime"], block["items"]):
        if f == "8-K" and "2.02" in (it or "").split(","):
            out.append((fd, acc))
    return out


def main():
    pg = PostgresStore(get_config().pg_dsn)
    with pg.get_conn() as c:
        syms = [r["symbol"] for r in c.execute("SELECT symbol FROM swing_universe").fetchall()]
        cal = np.array(sorted(r["d"] for r in c.execute(
            "SELECT DISTINCT time::date d FROM daily_prices WHERE symbol='SPY'").fetchall()))

    with httpx.Client(headers=UA, timeout=30) as cl:
        tick = get(cl, "https://www.sec.gov/files/company_tickers.json")
        cik_of = {v["ticker"].upper(): int(v["cik_str"]) for v in tick.values()}
        rows, miss = [], []
        for n, s in enumerate(syms, 1):
            cik = cik_of.get(s) or cik_of.get(s.replace("-", "."))
            if cik is None:
                miss.append(s); continue
            sub = get(cl, f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
            if sub is None:
                miss.append(s); continue
            got = rows_of(sub["filings"]["recent"])
            for fobj in sub["filings"].get("files", []):
                old = get(cl, f"https://data.sec.gov/submissions/{fobj['name']}")
                if old: got += rows_of(old)
            rows += [(s, fd, acc) for fd, acc in got]
            if n % 50 == 0:
                print(f"  {n}/{len(syms)} · 누적 {len(rows):,}", flush=True)

    df = pd.DataFrame(rows, columns=["symbol", "filing_date", "accept"]).drop_duplicates()
    df["filing_date"] = pd.to_datetime(df.filing_date).dt.date
    df["accept_et"] = (pd.to_datetime(df.accept, utc=True)
                       .dt.tz_convert("America/New_York").dt.tz_localize(None))
    hr = df.accept_et.dt.hour + df.accept_et.dt.minute / 60
    # 같은 날 접수가 아닌 경우(정정 등 접수일≠제출일) 접수시각 날짜를 기준으로 쓴다
    base = df.accept_et.dt.date
    pre = hr < 9.5
    pos = np.searchsorted(cal, np.array(base, dtype=object), side="left")
    # 장전이면 base 당일(휴장이면 다음 거래일), 아니면 base 다음 거래일
    nxt = np.searchsorted(cal, np.array(base, dtype=object), side="right")
    gi = np.where(pre, pos, nxt)
    df["gap_day"] = [cal[i] if i < len(cal) else pd.NaT for i in gi]
    df = df.drop(columns="accept").dropna(subset=["gap_day"])
    df = df.drop_duplicates(["symbol", "gap_day"]).sort_values(["symbol", "gap_day"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)

    h = df.accept_et.dt.hour.value_counts().sort_index()
    print(f"\n8-K 2.02 {len(df):,}건 · {df.symbol.nunique()}종목 · "
          f"{df.filing_date.min()} ~ {df.filing_date.max()} · CIK 미매핑 {len(miss)}: {' '.join(miss)}")
    print("접수 시각(ET) 분포:", " ".join(f"{k}시:{v}" for k, v in h.items()))
    per = df[df.gap_day >= pd.Timestamp("2012-01-01").date()].groupby("symbol").size()
    print(f"2012~ 종목당 건수: 중앙 {per.median():.0f} · p10 {per.quantile(.1):.0f} "
          f"(분기 발표면 ~59 기대)")


if __name__ == "__main__":
    main()
