"""18% 연수익 달성/판정 가능성 — 실측 기반 산술. 쓰기 없음."""
import sys, math
sys.path.insert(0, "/home/quant/quant-v31")
import numpy as np
from engine_v4.data.storage import PostgresStore
from engine_v4.config.settings import get_config

pg = PostgresStore(get_config().pg_dsn)
CAP = 1000.0
COMM = 0.0025          # 편도. 왕복 0.50%
with pg.get_conn() as c:
    pos = c.execute("""SELECT realized_pct, realized_pnl, hold_days, exit_time, qty, entry_price
                         FROM swing_positions WHERE status='closed' AND exit_price IS NOT NULL
                        ORDER BY exit_time""").fetchall()
    comm = float(c.execute("SELECT COALESCE(sum(commission),0) s FROM swing_trades").fetchone()["s"])
    runs = c.execute("""SELECT run_id, start_date, end_date, cagr, total_trades, avg_hold_days,
                               max_drawdown, sharpe_ratio,
                               COALESCE((params->>'position_pct')::float, 0.05) pp
                          FROM swing_backtest_runs
                         WHERE (end_date-start_date) > 700 AND cagr IS NOT NULL
                         ORDER BY cagr DESC LIMIT 8""").fetchall()

pct = np.array([float(p["realized_pct"]) for p in pos])
gross = sum(float(p["realized_pnl"]) for p in pos)
d0, d1 = pos[0]["exit_time"].date(), pos[-1]["exit_time"].date()
months = (d1 - d0).days / 30.44
n = len(pos)

print("═══ 1) 라이브 페이퍼 실측 ═══")
print(f"  기간 {d0} ~ {d1} = {months:.1f}개월 · 종료거래 {n}건 ({n/months:.1f}건/월)")
print(f"  가격손익(수수료前)  {gross:+8.2f} = {gross/CAP*100:+6.2f}% of ${CAP:,.0f}")
print(f"  수수료              {-comm:+8.2f} = {-comm/CAP*100:+6.2f}%   (편도 0.25% × 277체결)")
print(f"  ── 순손익           {gross-comm:+8.2f} = {(gross-comm)/CAP*100:+6.2f}%"
      f"  → 연율 {((gross-comm)/CAP)*12/months*100:+.1f}%")
print(f"  거래당 가격수익 평균 {pct.mean()*100:+.3f}% · 중앙값 {np.median(pct)*100:+.3f}%"
      f" · σ {pct.std(ddof=1)*100:.2f}%")
print(f"  왕복 수수료 0.50% → 거래당 순수익 평균 {(pct.mean()-0.005)*100:+.3f}%"
      f" · 승률 {(pct>0).mean()*100:.1f}% (수수료後 {(pct>0.005).mean()*100:.1f}%)")

print("\n═══ 2) 18% 를 내려면 거래당 얼마가 필요한가 ═══")
tpy = n / months * 12
PP = 0.10          # live position_pct
drag = tpy * PP * 2 * COMM
print(f"  라이브 회전율 {tpy:.0f}건/년 · 종목당 {PP:.0%} → 수수료 드래그 {drag*100:.1f}%/년")
print(f"  순 18% 필요 → 총 {18+drag*100:.1f}% gross")
need = (0.18 + drag) / (tpy * PP)
print(f"  거래당 필요 가격수익 {need*100:+.2f}%  vs  실측 평균 {pct.mean()*100:+.3f}%"
      f"  → 격차 {(need-pct.mean())*100:.2f}%p/거래")

print("\n═══ 3) 백테스트 CAGR 에 수수료를 넣으면 (>2년 구간, 상위 8) ═══")
print("  run  기간        년   슬롯비중 회전/년  CAGR(gross)  드래그   CAGR(net)")
for r in runs:
    yrs = (r["end_date"] - r["start_date"]).days / 365.25
    t = r["total_trades"] / yrs
    dg = t * r["pp"] * 2 * COMM
    g = float(r["cagr"]) * 100
    print(f"  {r['run_id']:>4} {r['start_date']}~{str(r['end_date'])[2:]} {yrs:4.1f}"
          f"  {r['pp']:.2f}  {t:7.0f}   {g:7.2f}%   {dg*100:6.1f}%   {g-dg*100:+7.2f}%")

print("\n═══ 4) 2027-03 까지 18% 를 '판정' 할 수 있는가 ═══")
for horizon_m, label in ((4.5, "2027-03-01"), (5.5, "2027-03-31")):
    k = tpy / 12 * horizon_m                    # 예상 거래수
    sd_trade = pct.std(ddof=1)
    sd_ret = sd_trade * PP * math.sqrt(k)       # 독립 가정(낙관)
    tgt = 0.18 * horizon_m / 12
    print(f"  {label} ({horizon_m:.1f}개월): 예상 {k:.0f}건 · 누적수익 σ ≈ {sd_ret*100:.1f}%"
          f" → 95%폭 ±{1.96*sd_ret*100:.1f}%")
    print(f"      18%연율 = 이 기간 {tgt*100:+.1f}% 인데 노이즈 폭이 그보다 "
          f"{'크다 🔴' if 1.96*sd_ret > tgt else '작다'} "
          f"({1.96*sd_ret/tgt:.1f}배)")
    print(f"      18% 와 0% 를 2σ 로 구분하려면 {int((2*1.96*sd_trade*PP/tgt)**2)}건 필요"
          f" ≈ {(2*1.96*sd_trade*PP/tgt)**2/tpy*12:.1f}개월")
print("  ※ 독립 가정은 낙관적이다 — 같은 날 같은 섹터 신호가 몰려 실제 σ 는 더 크다.")
