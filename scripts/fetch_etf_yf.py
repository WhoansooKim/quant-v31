#!/usr/bin/env python
"""재설계 검증용 ETF 일봉 (§22.AO-68) — yfinance(무료), 배당·분할 조정(auto_adjust).
hist_prices_adj 에 레버리지·섹터 ETF 가 없어 별도 parquet 로 둔다(DB 미적재).
출력: data/parquet/etf/etf_daily.parquet (symbol, d, o, h, l, c)
"""
import pandas as pd, yfinance as yf
SYMS = ["SPY", "QQQ", "BIL", "SHV", "IEF", "EFA", "SSO", "QLD", "UPRO", "TQQQ",
        "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "SMH", "SPMO", "MTUM"]
OUT = "/home/quant/quant-v31/data/parquet/etf/etf_daily.parquet"
raw = yf.download(SYMS, start="2009-01-01", auto_adjust=True, progress=False, group_by="column")
rows = []
for s in SYMS:
    g = pd.DataFrame({"o": raw["Open"][s], "h": raw["High"][s], "l": raw["Low"][s], "c": raw["Close"][s]}).dropna()
    g["symbol"] = s; g["d"] = g.index.date; rows.append(g.reset_index(drop=True))
df = pd.concat(rows)[["symbol", "d", "o", "h", "l", "c"]]
df.to_parquet(OUT, index=False)
print(df.groupby("symbol").d.agg(["min", "max", "count"]).to_string())
