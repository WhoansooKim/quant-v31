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
import psycopg
from psycopg.rows import dict_row
from engine_v4.config.settings import get_config

conn = psycopg.connect(get_config().pg_dsn, row_factory=dict_row)
PMIN, PMAX, RK = 10.0, 250.0, 0.6

Q = """
SELECT time::date AS d, count(*) total,
  count(*) FILTER (WHERE close BETWEEN %(a)s AND %(b)s) f_price,
  count(*) FILTER (WHERE close BETWEEN %(a)s AND %(b)s AND trend_aligned) f_tr,
  count(*) FILTER (WHERE close BETWEEN %(a)s AND %(b)s AND trend_aligned AND breakout_5d) f_bo,
  count(*) FILTER (WHERE close BETWEEN %(a)s AND %(b)s AND trend_aligned AND breakout_5d
                   AND volume_surge) f_three,
  -- 플래그 대신 자기 자신의 비율로 재계산한 것(결손 보정)
  count(*) FILTER (WHERE close BETWEEN %(a)s AND %(b)s AND trend_aligned AND breakout_5d
                   AND volume_ratio > 1.0) f_three_fix,
  count(*) FILTER (WHERE close BETWEEN %(a)s AND %(b)s AND trend_aligned AND breakout_5d
                   AND volume_surge AND coalesce(return_20d_rank,0) >= %(r)s) f_rank,
  count(*) FILTER (WHERE close BETWEEN %(a)s AND %(b)s AND trend_aligned AND breakout_5d
                   AND volume_ratio > 1.0 AND coalesce(return_20d_rank,0) >= %(r)s) f_rank_fix
FROM swing_indicators WHERE volume_ratio IS NOT NULL GROUP BY 1 ORDER BY 1
"""
rows = conn.execute(Q, dict(a=PMIN, b=PMAX, r=RK)).fetchall()

sig = {r["d"]: r["n"] for r in conn.execute("""
    SELECT time::date d, count(DISTINCT symbol) n FROM swing_signals
    WHERE signal_type='ENTRY' GROUP BY 1""").fetchall()}

import datetime as dt
CUT = dt.date(2026, 7, 24)
for label, sel in (("결손 구간 2026-03-04~07-23", lambda d: d < CUT),
                   ("수정 후 2026-07-24~10-16", lambda d: d >= CUT)):
    g = [r for r in rows if sel(r["d"])]
    n = len(g)
    f = lambda k: sum(r[k] for r in g) / n
    print(f"\n── {label}  ({n}일)")
    print(f"  총 지표행         {f('total'):7.1f}/일")
    print(f"  ① 가격 10-250     {f('f_price'):7.1f}/일")
    print(f"  ② +추세정렬       {f('f_tr'):7.1f}/일")
    print(f"  ③ +5일 브레이크아웃 {f('f_bo'):7.1f}/일")
    print(f"  ④ +거래량(플래그) {f('f_three'):7.1f}/일   ← 저장된 volume_surge")
    print(f"  ④'+거래량(비율>1) {f('f_three_fix'):7.1f}/일   ← 결손 보정")
    print(f"  ⑤ +rank>=0.6      {f('f_rank'):7.1f}/일   (보정 {f('f_rank_fix'):.1f}/일)")
    s = [sig.get(r["d"], 0) for r in g]
    print(f"  실제 ENTRY 시그널 {sum(s)/n:7.2f}/일 (합 {sum(s)}건)")
    z = sum(1 for r in g if r["f_rank"] == 0)
    print(f"  ⑤가 0 인 날 {z}/{n}일")
