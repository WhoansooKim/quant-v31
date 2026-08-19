"""④ 마이크로구조 신호 검증 (§22.AO-16).

Du·Walter·Ulrich, *Cross-Market Alpha* (arXiv 2601.06499): Alpha191 단기신호 191개를
S&P500(2002~2022)에서 double-selection LASSO 로 검증해 독립 유의 17개 식별.

여기서는 일간 OHLCV 로 구현 가능한 고순위 신호를 근사 구현하고, **우리 유니버스·우리 기간**에서
횡단면 IC 를 직접 측정한다. 논문 수치를 믿지 않고 재현되는지 본다(§22.AO-10 의 anomaly decay 경고).

⚠️ Alpha191 원식이 아니라 논문 설명 기반 **근사 구현**이다.
"""
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

pg = PostgresStore(get_config().pg_dsn)
START = "2016-01-01"
SPLIT = pd.Timestamp("2022-01-01")   # 학습 2016~2021 / 검증 2022~2026
HORIZONS = (5, 10, 20)

syms = [u["symbol"] for u in pg.get_universe()]
print(f"유니버스 {len(syms)}종목, {START} ~ 현재")

with pg.get_conn() as conn:
    rows = conn.execute("""
        SELECT time::date AS d, symbol, open, high, low, close, volume
        FROM daily_prices
        WHERE symbol = ANY(%s) AND time >= %s
        ORDER BY symbol, time
    """, (syms, START)).fetchall()

df = pd.DataFrame(rows)
for c in ("open", "high", "low", "close", "volume"):
    df[c] = pd.to_numeric(df[c], errors="coerce")
df["d"] = pd.to_datetime(df["d"])
df = df.dropna(subset=["close"]).sort_values(["symbol", "d"])
print(f"가격 데이터 {len(df):,}행 / {df['symbol'].nunique()}종목")


def per_symbol(g: pd.DataFrame) -> pd.DataFrame:
    c, h, l, o, v = g["close"], g["high"], g["low"], g["open"], g["volume"]
    ret = c.pct_change()
    out = pd.DataFrame(index=g.index)

    # 071 24일 평균 대비 괴리 (평균회귀) — 음의 부호로 진입신호화
    out["dev24"] = -(c / c.rolling(24).mean() - 1)

    # 046 다기간 평균회귀 비율 (5/10/20일 괴리 블렌드)
    dev = lambda n: (c / c.rolling(n).mean() - 1)
    out["mr_multi"] = -(dev(5) + dev(10) + dev(20)) / 3

    # 084 20일 누적 OBV
    obv = (np.sign(ret.fillna(0)) * v).cumsum()
    out["obv20"] = obv - obv.shift(20)

    # 063 6일 RSI
    up = ret.clip(lower=0).rolling(6).mean()
    dn = (-ret).clip(lower=0).rolling(6).mean()
    out["rsi6"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))

    # 015 야간 갭 수익
    out["gap"] = o / c.shift(1) - 1

    # 161 12일 ATR (가격 정규화)
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    out["atr12"] = tr.rolling(12).mean() / c

    # 190 로그 상승/하락 변동성 비율
    gain = ret.clip(lower=0).rolling(20).std()
    loss = (-ret).clip(lower=0).rolling(20).std()
    out["glr"] = np.log((gain + 1e-9) / (loss + 1e-9))

    # 155 거래량 MACD 히스토그램
    out["vmacd"] = (v.ewm(span=12).mean() - v.ewm(span=26).mean()) \
        - (v.ewm(span=12).mean() - v.ewm(span=26).mean()).ewm(span=9).mean()

    # 001 6일 거래량증가율·수익률 상관 (음의 상관)
    out["volret_corr"] = -v.pct_change().rolling(6).corr(ret)

    # 054 일중 변동성 순위 역
    out["intraday_vol"] = -((h - l) / c).rolling(10).mean()

    for n in HORIZONS:
        out[f"fwd{n}"] = c.shift(-n) / c - 1
    out["d"] = g["d"].values
    out["symbol"] = g["symbol"].values
    return out


feat = df.groupby("symbol", group_keys=False).apply(per_symbol)
feat = feat.replace([np.inf, -np.inf], np.nan)
FACTORS = ["dev24", "mr_multi", "obv20", "rsi6", "gap", "atr12",
           "glr", "vmacd", "volret_corr", "intraday_vol"]

# 주간 횡단면만 사용(중복 표본 축소)
feat = feat[feat["d"].dt.dayofweek == 2]
print(f"수요일 횡단면 {len(feat):,}행\n")


def xs_ic(sub: pd.DataFrame, f: str, n: int) -> float | None:
    """일자별 횡단면 순위상관의 평균 (표준 IC)."""
    ics = []
    for _, g in sub.groupby("d"):
        gg = g[[f, f"fwd{n}"]].dropna()
        if len(gg) < 30:
            continue
        ics.append(gg[f].rank().corr(gg[f"fwd{n}"].rank()))
    return float(np.nanmean(ics)) if ics else None


train = feat[feat["d"] < SPLIT]
test = feat[feat["d"] >= SPLIT]
print(f"학습 {train['d'].nunique()}일 / 검증 {test['d'].nunique()}일\n")

for n in HORIZONS:
    print(f"=== 전방 {n}일 IC ===")
    print(f"{'신호':16s} {'학습':>9s} {'검증':>9s} {'최솟값':>9s}")
    res = []
    for f in FACTORS:
        a, b = xs_ic(train, f, n), xs_ic(test, f, n)
        if a is None or b is None:
            continue
        res.append((f, a, b, min(a, b)))
    for f, a, b, m in sorted(res, key=lambda x: -x[3]):
        flag = " ★" if m > 0.01 else ""
        print(f"{f:16s} {a:+9.4f} {b:+9.4f} {m:+9.4f}{flag}")
    print()
