import sys, math
sys.path.insert(0,"/home/quant/quant-v31")
import numpy as np
from engine_v4.data.storage import PostgresStore
from engine_v4.config.settings import get_config
pg = PostgresStore(get_config().pg_dsn)
with pg.get_conn() as c:
    pct = np.array([float(r["realized_pct"]) for r in c.execute(
        "SELECT realized_pct FROM swing_positions WHERE status='closed' AND exit_price IS NOT NULL").fetchall()])
sd, PP, tpy = pct.std(ddof=1), 0.10, 229.0
need = 0.0129    # 18% net 에 필요한 거래당 가격수익

print("A) '거래당 우위가 +1.29% 인가' — 거래 단위 검정")
n2 = (2*sd/need)**2
print(f"   σ={sd*100:.2f}%/거래 · 2σ 로 0 과 구분하려면 {n2:.0f}건 ≈ {n2/tpy*12:.1f}개월")
print(f"   (현재 누적 132건 → 이미 가능한 수준. 실측 평균 {pct.mean()*100:+.3f}% 는 0 과 구분 안 됨:"
      f" t={pct.mean()/(sd/math.sqrt(len(pct))):+.2f})")

print("\nB) '연수익률이 18% 인가' — 연율 추정의 정확도")
print("   개월  거래수   연율추정 95%반폭")
for m in (4.5, 5.5, 12, 24, 36, 60):
    n = tpy*m/12
    se_ann = PP*sd*math.sqrt(n)*(12/m)
    print(f"   {m:5.1f} {n:7.0f}   ±{1.96*se_ann*100:6.1f}%p"
          + ("   ← 2027-03" if m in (4.5,5.5) else "")
          + ("   ← ±9%p 도달" if 1.96*se_ann*100 <= 9 else ""))
print("   ※ 18% 를 '0% 가 아니다' 수준으로 말하려면 반폭 ≤9%p 필요")
