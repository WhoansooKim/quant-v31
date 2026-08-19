"""② 신호 교집합 — 가중평균 대비 우위 검증 (§22.AO-12).

Sobotka(2025): 여러 anomaly 에 동시 등장하는 종목의 알파가 3배.
우리 실측: composite(가중평균) IC +0.20 < technical 단독 +0.35 → 평균이 신호를 희석.
가설: '동시 충족 개수'가 가중평균보다 예측력이 높다.

시계열 분할(학습 2026-03~05 / 검증 06~08)로 과적합 배제.
"""
import sys
from datetime import date
from statistics import mean

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

pg = PostgresStore(get_config().pg_dsn)
H = 10
SPLIT = date(2026, 6, 1)

SQL = """
SELECT s.signal_id, s.time::date AS d, s.entry_price, s.composite_score,
       s.technical_score, s.quality_score, s.macro_score, s.value_score,
       s.sentiment_score, s.flow_score,
       s.return_20d_rank, s.trend_aligned, s.breakout_5d, s.volume_surge,
       (SELECT p.close FROM daily_prices p
         WHERE p.symbol = s.symbol AND p.time::date > s.time::date
         ORDER BY p.time LIMIT 1 OFFSET %s) AS px_fwd
FROM swing_signals s
WHERE s.composite_score IS NOT NULL AND s.entry_price > 0
"""


def spearman(xs, ys):
    def rank(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            for k in range(i, j + 1):
                r[idx[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    if len(xs) < 5:
        return None
    rx, ry = rank(xs), rank(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** .5
    return num / den if den else None


# 화면(screen) 정의 — IC 가 양수로 측정된 신호족만 사용(flow/value 는 음수라 제외).
# 각각 다른 정보원이라 교집합의 의미가 있다.
def screens(r):
    out = {}
    ts = r["technical_score"]
    out["technical"] = ts is not None and float(ts) >= 60
    q = r["quality_score"]
    out["quality"] = q is not None and float(q) >= 55
    m = r["macro_score"]
    out["macro"] = m is not None and float(m) >= 55
    rk = r["return_20d_rank"]
    out["momentum"] = rk is not None and float(rk) >= 0.70
    out["breakout"] = bool(r["breakout_5d"]) and bool(r["volume_surge"])
    out["trend"] = bool(r["trend_aligned"])
    return out


with pg.get_conn() as conn:
    rows = [r for r in conn.execute(SQL, (H - 1,)).fetchall() if r["px_fwd"]]

train = [r for r in rows if r["d"] < SPLIT]
test = [r for r in rows if r["d"] >= SPLIT]
print(f"표본 {len(rows)}건 → 학습 {len(train)} / 검증 {len(test)}  (전방 {H}일)\n")


def ret(r):
    return (float(r["px_fwd"]) - float(r["entry_price"])) / float(r["entry_price"])


def ic_of(subset, keyfn):
    pairs = [(keyfn(r), ret(r)) for r in subset if keyfn(r) is not None]
    return spearman([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 5 else None


def count_of(r, names):
    sc = screens(r)
    return sum(sc[n] for n in names)


CANDIDATES = {
    "composite (현행 가중평균)": lambda r: float(r["composite_score"]) if r["composite_score"] is not None else None,
    "technical 단독":            lambda r: float(r["technical_score"]) if r["technical_score"] is not None else None,
    "교집합 6화면 전체":         lambda r: count_of(r, ["technical","quality","macro","momentum","breakout","trend"]),
    "교집합 3화면(mom/tech/trend)": lambda r: count_of(r, ["momentum","technical","trend"]),
    "교집합 4화면(+quality)":     lambda r: count_of(r, ["momentum","technical","trend","quality"]),
    "교집합 2화면(mom/tech)":     lambda r: count_of(r, ["momentum","technical"]),
    "momentum rank 단독":         lambda r: float(r["return_20d_rank"]) if r["return_20d_rank"] is not None else None,
}

print(f"{'지표':30s} {'학습 IC':>9s} {'검증 IC':>9s}")
for name, fn in CANDIDATES.items():
    tr, te = ic_of(train, fn), ic_of(test, fn)
    print(f"{name:30s} {(f'{tr:+.3f}' if tr else '  n/a'):>9s} {(f'{te:+.3f}' if te else '  n/a'):>9s}")

# 교집합 개수별 실제 수익
print(f"\n[교집합 개수별 {H}일 수익 — 전체 표본]")
for k in range(7):
    sub = [ret(r) for r in rows if sum(screens(r).values()) == k]
    if not sub:
        continue
    wr = sum(1 for x in sub if x > 0) / len(sub)
    print(f"  {k}개 충족: n={len(sub):3d}  평균 {mean(sub):+7.2%}  승률 {wr:5.1%}")

# 화면별 단독 성적
print(f"\n[화면별 단독 — 충족 시 {H}일 평균수익]")
for name in ("technical", "quality", "macro", "momentum", "breakout", "trend"):
    yes = [ret(r) for r in rows if screens(r)[name]]
    no = [ret(r) for r in rows if not screens(r)[name]]
    if yes and no:
        print(f"  {name:10s} 충족 n={len(yes):3d} {mean(yes):+7.2%}  |  미충족 n={len(no):3d} {mean(no):+7.2%}"
              f"  → 차이 {mean(yes)-mean(no):+.2%}")

# ── 게이트로서의 성능 (순위지표가 아니라 진입 허용 기준으로 썼을 때) ──
print(f"\n[게이트 비교 — 통과분의 {H}일 성적]")
GATES = {
    "게이트 없음 (전체)":           lambda r: True,
    "현행 composite >= 61":         lambda r: r["composite_score"] is not None and float(r["composite_score"]) >= 61,
    "교집합 >= 4 (6화면)":          lambda r: count_of(r, ["technical","quality","macro","momentum","breakout","trend"]) >= 4,
    "교집합 >= 5 (6화면)":          lambda r: count_of(r, ["technical","quality","macro","momentum","breakout","trend"]) >= 5,
    "momentum+technical 동시":      lambda r: count_of(r, ["momentum","technical"]) == 2,
    "momentum+tech+trend 동시":     lambda r: count_of(r, ["momentum","technical","trend"]) == 3,
    "composite>=61 AND 교집합>=4":  lambda r: (r["composite_score"] is not None and float(r["composite_score"]) >= 61)
                                              and count_of(r, ["technical","quality","macro","momentum","breakout","trend"]) >= 4,
}
print(f"{'게이트':32s} {'통과':>5s} {'평균수익':>9s} {'승률':>7s} {'중앙값':>8s}")
for name, fn in GATES.items():
    sub = [ret(r) for r in rows if fn(r)]
    if not sub:
        print(f"{name:32s} {'0':>5s}")
        continue
    wr = sum(1 for x in sub if x > 0) / len(sub)
    med = sorted(sub)[len(sub) // 2]
    print(f"{name:32s} {len(sub):5d} {mean(sub):+9.2%} {wr:6.1%} {med:+8.2%}")

# 학습/검증 각각에서도 확인 (안정성)
print(f"\n[게이트 안정성 — 학습 / 검증 각각 평균수익]")
for name, fn in GATES.items():
    a = [ret(r) for r in train if fn(r)]
    b = [ret(r) for r in test if fn(r)]
    sa = f"{mean(a):+.2%}(n={len(a)})" if a else "n/a"
    sb = f"{mean(b):+.2%}(n={len(b)})" if b else "n/a"
    print(f"  {name:32s} 학습 {sa:>16s}  검증 {sb:>16s}")
