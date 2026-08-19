"""atr12 이 알파인가 위험 프리미엄인가 (§22.AO-16 후속).

위험 프리미엄이면 하락장에서 부호가 뒤집힌다(고변동 종목이 더 크게 빠짐).
알파라면 국면과 무관하게 양수여야 한다.
"""
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

pg = PostgresStore(get_config().pg_dsn)
syms = [u["symbol"] for u in pg.get_universe()]
with pg.get_conn() as conn:
    rows = conn.execute("""
        SELECT time::date AS d, symbol, high, low, close
        FROM daily_prices WHERE symbol = ANY(%s) AND time >= '2016-01-01'
        ORDER BY symbol, time
    """, (syms,)).fetchall()
df = pd.DataFrame(rows)
for c in ("high", "low", "close"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["d"] = pd.to_datetime(df["d"])
df = df.dropna(subset=["close"]).sort_values(["symbol", "d"])


def f(g):
    c, h, l = g["close"], g["high"], g["low"]
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    out = pd.DataFrame({"atr12": tr.rolling(12).mean() / c,
                        "fwd10": c.shift(-10) / c - 1})
    out["d"] = g["d"].values
    return out


feat = df.groupby("symbol", group_keys=False).apply(f).replace([np.inf, -np.inf], np.nan)
feat = feat[feat["d"].dt.dayofweek == 2]

# SPY 200일 SMA 로 국면 구분
with pg.get_conn() as conn:
    spy = pd.DataFrame(conn.execute(
        "SELECT time::date AS d, close FROM daily_prices WHERE symbol='SPY' AND time>='2015-01-01' ORDER BY time"
    ).fetchall())
spy["close"] = pd.to_numeric(spy["close"], errors="coerce")
spy["d"] = pd.to_datetime(spy["d"])
spy["sma200"] = spy["close"].rolling(200).mean()
spy["up"] = spy["close"] > spy["sma200"]
regime = spy.set_index("d")["up"]

feat["up"] = feat["d"].map(regime)


def ic(sub):
    ics = []
    for _, g in sub.groupby("d"):
        gg = g[["atr12", "fwd10"]].dropna()
        if len(gg) < 30:
            continue
        ics.append(gg["atr12"].rank().corr(gg["fwd10"].rank()))
    return (float(np.nanmean(ics)), len(ics)) if ics else (float("nan"), 0)


print("atr12 → 전방 10일 IC (국면별)")
for label, sub in (("상승국면 (SPY>SMA200)", feat[feat["up"] == True]),
                   ("하락국면 (SPY<SMA200)", feat[feat["up"] == False]),
                   ("2022 약세장", feat[(feat["d"] >= "2022-01-01") & (feat["d"] < "2023-01-01")]),
                   ("전체", feat)):
    v, n = ic(sub)
    print(f"  {label:26s} IC {v:+.4f}  ({n}일)")
