"""§22.AO-61 후보 공급 격차 측정 — 결론: 격차는 없었다(창 불일치였다).

실측(2026-10-19):
  라이브 수정후 창(2026-07-24~10-09) ⑤통과 4.87건/일
  백테스트 같은 창·캡200           4.64건/일   ← 일치
  백테스트 15.6년 평균·캡200       7.94건/일   ← "모델 8.8" 의 출처
  즉 §22.AO-59 의 "1.9배 공급 격차" 는 라이브 창(저공급 국면)을 장기평균과 비교한 것이다.

같은 (날짜,종목) 10,920행 교차검증: 라이브 4.87 vs 백테스트 4.59건/일, 편측 불일치 34 vs 19.
→ 필터는 동등하다. 공급은 유니버스 크기에 선형(100종목당 +4.0건/일, 전 구간 통과율 4.0%).

🔴 그러나 진짜 결손 하나를 찾았다: volume_surge 임계가 2026-03-04~07-23 동안 1.0 이 아니라
   settings.py 기본값 1.5 였다(collector 만 cfg 폴백, 스캔부는 DB 1.0). 커밋 dcd2a95(07-24)로
   이미 수정. 그 97일간 ⑤통과가 0.9건/일 — 보정값 4.5건/일의 1/5 이었다.
"""

import sys; sys.path.insert(0, "/home/quant/quant-v31")
import psycopg, datetime as dt
from psycopg.rows import dict_row
from engine_v4.config.settings import get_config

conn = psycopg.connect(get_config().pg_dsn, row_factory=dict_row)
CUT = dt.date(2026, 7, 24)

# ⑤ 통과 종목을 날짜별로 실제 열거
pool = conn.execute("""
    SELECT time::date d, symbol FROM swing_indicators
    WHERE time::date >= %s AND close BETWEEN 10 AND 250
      AND trend_aligned AND breakout_5d AND volume_surge
      AND coalesce(return_20d_rank,0) >= 0.6
""", (CUT,)).fetchall()
from collections import defaultdict
P = defaultdict(set)
for r in pool: P[r["d"]].add(r["symbol"])

S = defaultdict(set)
for r in conn.execute("""SELECT time::date d, symbol FROM swing_signals
                         WHERE signal_type='ENTRY' AND time::date >= %s""", (CUT,)).fetchall():
    S[r["d"]].add(r["symbol"])

days = sorted(P)
n = len(days)
tot_pool = sum(len(P[d]) for d in days)
tot_sig  = sum(len(S.get(d, set())) for d in days)
print(f"수정 후 {n}일: ⑤풀 {tot_pool}건({tot_pool/n:.2f}/일) → 시그널 {tot_sig}건({tot_sig/n:.2f}/일)")

# ⓐ 풀>0 인데 시그널 0 인 날 = 날 단위 차단 의심
blank = [d for d in days if len(P[d]) > 0 and not S.get(d)]
blanked = sum(len(P[d]) for d in blank)
print(f"\nⓐ 날 전체 차단 의심: {len(blank)}/{n}일, 그 날들의 ⑤풀 {blanked}건 "
      f"({blanked/tot_pool*100:.0f}% of 풀)")

# ⓒ 그 날 보유중이던 종목 (positions 기간 겹침)
held = conn.execute("""
    SELECT p.symbol, p.entry_time::date lo,
           coalesce(p.exit_time::date, '2026-10-16'::date) hi
    FROM swing_positions p WHERE coalesce(p.exit_time, now()) >= %s
""", (CUT,)).fetchall()
HELD = defaultdict(set)
for h in held:
    d = h["lo"]
    while d <= h["hi"]:
        HELD[d].add(h["symbol"]); d += dt.timedelta(days=1)

# ⓑ abs_mom: daily_prices 로 날짜별 126거래일 수익 재계산
am = conn.execute("""
    WITH r AS (SELECT symbol, time::date d, close,
                      row_number() OVER (PARTITION BY symbol ORDER BY time) rn
               FROM daily_prices)
    SELECT c.symbol, c.d, (c.close/NULLIF(p.close,0)-1) mom
    FROM r c JOIN r p ON c.symbol=p.symbol AND p.rn = c.rn-126
    WHERE c.d >= %s
""", (CUT,)).fetchall()
AM = {(a["symbol"], a["d"]): (float(a["mom"]) if a["mom"] is not None else None) for a in am}

# 날 전체 차단일을 제외한 날들에서 종목단위 기각 집계
act = [d for d in days if S.get(d)]
c_held = c_am = c_amiss = c_rest = c_sig = 0
for d in act:
    for s in P[d]:
        if s in S[d]: c_sig += 1; continue
        if s in HELD.get(d, set()): c_held += 1; continue
        m = AM.get((s, d))
        if m is None: c_amiss += 1
        elif m < 0.0: c_am += 1
        else: c_rest += 1
pool_act = sum(len(P[d]) for d in act)
print(f"\n시그널이 있었던 {len(act)}일 (⑤풀 {pool_act}건) 내부 분해:")
print(f"  시그널로 나간 것        {c_sig:4d}건 ({c_sig/pool_act*100:4.1f}%)")
print(f"  ⓒ 이미 보유중 제외      {c_held:4d}건 ({c_held/pool_act*100:4.1f}%)")
print(f"  ⓑ abs_mom 6M<0 제외     {c_am:4d}건 ({c_am/pool_act*100:4.1f}%)")
print(f"  ⓑ' abs_mom 데이터없음   {c_amiss:4d}건 (통과여야 함)")
print(f"  설명 안 되는 잔차        {c_rest:4d}건 ({c_rest/pool_act*100:4.1f}%)")
