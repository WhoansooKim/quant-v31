"""팩터 가중치 조정 검증 — 시계열 분할 (§22.AO-9).

같은 표본으로 가중치를 고르고 같은 표본으로 평가하면 과적합이다.
학습(2026-03~05)에서 후보를 정하고 검증(2026-06~08)에서만 평가한다.
저장된 팩터 점수만 재조합하므로 미래참조 없음.
"""
import sys
from datetime import date
from statistics import mean

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

pg = PostgresStore(get_config().pg_dsn)
SPLIT = date(2026, 6, 1)
H = 10  # 전방 10일 (IC 신호가 가장 뚜렷했던 구간)

FACTORS = ["technical_score", "sentiment_score", "flow_score",
           "quality_score", "value_score", "macro_score"]

CANDIDATES = {
    "현행         t.25/s.18/f.10/q.19/v.18/m.10": dict(technical_score=.25, sentiment_score=.18, flow_score=.10,
                                                        quality_score=.19, value_score=.18, macro_score=.10),
    "flow 제거    t.28/s.20/f.00/q.21/v.20/m.11": dict(technical_score=.28, sentiment_score=.20, flow_score=.0,
                                                        quality_score=.21, value_score=.20, macro_score=.11),
    "flow+val제거 t.36/s.26/f.00/q.25/v.00/m.13": dict(technical_score=.36, sentiment_score=.26, flow_score=.0,
                                                        quality_score=.25, value_score=.0, macro_score=.13),
    "tech 중심    t.50/s.10/f.00/q.20/v.00/m.20": dict(technical_score=.50, sentiment_score=.10, flow_score=.0,
                                                        quality_score=.20, value_score=.0, macro_score=.20),
    "tech 단독    t1.0                          ": dict(technical_score=1.0, sentiment_score=.0, flow_score=.0,
                                                        quality_score=.0, value_score=.0, macro_score=.0),
    "flow 반전    t.25/s.18/f-.10/q.19/v-.18/m.10": dict(technical_score=.25, sentiment_score=.18, flow_score=-.10,
                                                         quality_score=.19, value_score=-.18, macro_score=.10),
}

SQL = """
SELECT s.signal_id, s.time::date AS d, s.entry_price,
       s.technical_score, s.sentiment_score, s.flow_score,
       s.quality_score, s.value_score, s.macro_score,
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


with pg.get_conn() as conn:
    rows = [r for r in conn.execute(SQL, (H - 1,)).fetchall() if r["px_fwd"]]

# 전 팩터가 채워진 행만 (조합 비교의 공정성)
rows = [r for r in rows if all(r[f] is not None for f in FACTORS)]
train = [r for r in rows if r["d"] < SPLIT]
test = [r for r in rows if r["d"] >= SPLIT]
print(f"표본 {len(rows)}건 → 학습(~{SPLIT}) {len(train)} / 검증({SPLIT}~) {len(test)}\n")


def evaluate(subset, w):
    xs, ys = [], []
    for r in subset:
        score = sum(w[f] * float(r[f]) for f in FACTORS)
        ret = (float(r["px_fwd"]) - float(r["entry_price"])) / float(r["entry_price"])
        xs.append(score)
        ys.append(ret)
    return spearman(xs, ys)


print(f"{'가중치 구성':46s} {'학습 IC':>9s} {'검증 IC':>9s}")
for name, w in CANDIDATES.items():
    tr = evaluate(train, w)
    te = evaluate(test, w)
    tr_s = f"{tr:+.3f}" if tr is not None else "  n/a"
    te_s = f"{te:+.3f}" if te is not None else "  n/a"
    print(f"{name:46s} {tr_s:>9s} {te_s:>9s}")
