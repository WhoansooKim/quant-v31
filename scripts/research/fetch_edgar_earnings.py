#!/usr/bin/env python
"""§22.AO-70 데이터: SEC EDGAR 8-K Item 2.02(실적 발표) 제출일 + XBRL 분기 EPS(희석).
- 대상: hist_prices_adj 에 가격이 있는 종목(현재 티커 → CIK 는 company_tickers.json).
- 출력: data/pit/earn_dates.parquet (symbol, filing_date, accept_time), data/pit/eps_q.parquet
- SEC 제한 초당 10회 → 0.12s 간격. 헤더는 엔진 events/edgar.py 와 동일.
"""
import sys, time, json
import httpx, pandas as pd
sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

H = {"User-Agent": "QuantV4 SwingTrader admin@quant-v4.local", "Accept": "application/json"}
OUT = "/home/quant/quant-v31/data/pit/"
pg = PostgresStore(get_config().pg_dsn)
with pg.get_conn() as conn:
    syms = sorted(r["symbol"] for r in conn.execute("select distinct symbol from hist_prices_adj").fetchall())
c = httpx.Client(timeout=30, headers=H)
tick = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in c.get("https://www.sec.gov/files/company_tickers.json").json().values()}
dates, eps, miss = [], [], []


def get(url):
    for k in range(4):
        time.sleep(0.12)
        r = c.get(url)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 404:
            return None
        time.sleep(2 * (k + 1))
    return None


for n, s in enumerate(syms):
    cik = tick.get(s.replace(".", "-")) or tick.get(s)
    if not cik:
        miss.append(s); continue
    d = get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if not d:
        miss.append(s); continue
    blocks = [d["filings"]["recent"]]
    for f in d["filings"].get("files", []):
        b = get(f"https://data.sec.gov/submissions/{f['name']}")
        if b:
            blocks.append(b)
    for r in blocks:
        for i, form in enumerate(r["form"]):
            if form in ("8-K", "8-K/A") and "2.02" in (r["items"][i] or ""):
                dates.append({"symbol": s, "filing_date": r["filingDate"][i], "accept_time": r["acceptanceDateTime"][i], "form": form})
    f = get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/EarningsPerShareDiluted.json")
    if f:
        for unit in f.get("units", {}).values():
            for u in unit:
                if (u.get("fp") or "").startswith("Q") or u.get("form") in ("10-Q", "10-K"):
                    eps.append({"symbol": s, "end": u.get("end"), "start": u.get("start"), "val": u.get("val"),
                                "filed": u.get("filed"), "form": u.get("form"), "fp": u.get("fp"), "fy": u.get("fy")})
    if n % 50 == 0:
        print(f"{n}/{len(syms)} {s} dates={len(dates)} eps={len(eps)} miss={len(miss)}", flush=True)
        pd.DataFrame(dates).to_parquet(OUT + "earn_dates.parquet")
pd.DataFrame(dates).to_parquet(OUT + "earn_dates.parquet")
pd.DataFrame(eps).to_parquet(OUT + "eps_q.parquet")
pd.Series(miss).to_csv(OUT + "edgar_missing.csv", index=False, header=False)
print("DONE", len(dates), len(eps), "missing", len(miss))
