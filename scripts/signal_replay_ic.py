"""시그널 리플레이 — 기록된 팩터 점수의 예측력 검증 (§22.AO-8).

미래참조 없음: swing_signals 에 '당시' 계산돼 저장된 점수만 쓰고,
수익은 시그널 시점 이후 daily_prices 실제 종가로 계산한다.
"""
import sys
from statistics import mean, stdev

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

pg = PostgresStore(get_config().pg_dsn)
HORIZONS = (5, 10, 20)

SQL = """
WITH sig AS (
    SELECT signal_id, symbol, time::date AS d, entry_price,
           composite_score, technical_score, sentiment_score,
           flow_score, quality_score, value_score, macro_score
    FROM swing_signals
    WHERE composite_score IS NOT NULL AND entry_price > 0
),
fwd AS (
    SELECT s.*, %s AS h,
           (SELECT p.close FROM daily_prices p
             WHERE p.symbol = s.symbol AND p.time::date > s.d
             ORDER BY p.time LIMIT 1 OFFSET %s) AS px_fwd
    FROM sig s
)
SELECT * FROM fwd WHERE px_fwd IS NOT NULL
"""


def spearman(xs, ys):
    """순위상관 — 동점은 평균순위."""
    def rank(v):
        idx = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and v[idx[j + 1]] == v[idx[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[idx[k]] = avg
            i = j + 1
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    if n < 3:
        return None
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


FACTORS = ["composite_score", "technical_score", "sentiment_score",
           "flow_score", "quality_score", "value_score", "macro_score"]

for h in HORIZONS:
    with pg.get_conn() as conn:
        rows = conn.execute(SQL, (h, h - 1)).fetchall()
    if not rows:
        print(f"[{h}일] 표본 없음")
        continue
    rets = [(float(r["px_fwd"]) - float(r["entry_price"])) / float(r["entry_price"]) for r in rows]
    print(f"\n=== {h}일 전방수익 (표본 {len(rows)}건, 평균 {mean(rets):+.2%}) ===")
    print(f"{'팩터':20s} {'IC(순위상관)':>14s} {'표본':>6s}")
    for f in FACTORS:
        pairs = [(float(r[f]), ret) for r, ret in zip(rows, rets) if r[f] is not None]
        if len(pairs) < 10:
            print(f"{f:20s} {'표본부족':>14s} {len(pairs):6d}")
            continue
        ic = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        print(f"{f:20s} {ic:+14.3f} {len(pairs):6d}")

    # composite 임계값 분석
    print(f"\n  [composite_score 구간별 {h}일 수익]")
    buckets = [(0, 50), (50, 55), (55, 61), (61, 65), (65, 70), (70, 101)]
    for lo, hi in buckets:
        sub = [ret for r, ret in zip(rows, rets)
               if r["composite_score"] is not None and lo <= float(r["composite_score"]) < hi]
        if not sub:
            print(f"    {lo:3d}-{hi:3d}: (없음)")
            continue
        wr = sum(1 for x in sub if x > 0) / len(sub)
        print(f"    {lo:3d}-{hi:3d}: n={len(sub):3d}  평균 {mean(sub):+7.2%}  승률 {wr:5.1%}")
