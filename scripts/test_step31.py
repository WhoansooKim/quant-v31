"""Step 3.1 통합 테스트"""
import sys
sys.path.insert(0, "/home/quant/quant-v31")

from engine.config.settings import Settings
from engine.data.storage import PostgresStore, RedisCache
from engine.risk.regime import RegimeDetector
from engine.risk.regime_allocator import RegimeAllocator
from engine.risk.kill_switch import DrawdownKillSwitch, DefenseLevel
from engine.risk.position_sizer import DynamicPositionSizer

config = Settings()

# 1. PostgreSQL 연결
pg = PostgresStore(config.pg_dsn)
with pg.get_conn() as conn:
    row = conn.execute("SELECT count(*) as cnt FROM daily_prices").fetchone()
    print(f"[OK] PG daily_prices: {row['cnt']} rows")

# 2. Redis 연결
cache = RedisCache(config.redis_url)
print(f"[OK] Redis ping: {cache.ping()}")

# 3. HMM 레짐 감지
rd = RegimeDetector(pg_dsn=config.pg_dsn)
rd.load()
state = rd.predict_current()
print(f"[OK] Regime: {state.current} (conf={state.confidence:.1%})")
print(f"     Bull={state.bull_prob:.1%}, Side={state.sideways_prob:.1%}, Bear={state.bear_prob:.1%}")

# 4. 레짐 배분
alloc_mgr = RegimeAllocator()
alloc = alloc_mgr.get_allocation(state, exposure_limit=1.0)
print(f"[OK] Allocation: LV={alloc.lowvol_quality:.1%} Mom={alloc.vol_momentum:.1%} "
      f"Pairs={alloc.pairs_trading:.1%} Cash={alloc.cash:.1%}")

# 5. Kill Switch
ks = DrawdownKillSwitch(initial_value=100000)
level = ks.update(100000)
print(f"[OK] Kill Switch: {level.value}, MDD={ks.current_mdd:.2%}, "
      f"exposure={ks.get_exposure_limit():.0%}")

# 6. 포지션 사이저
ps = DynamicPositionSizer()
size = ps.calculate("AAPL", 100000, 185.0, 3.5)
print(f"[OK] Position: {size.symbol} {size.shares}주 "
      f"(weight={size.weight:.1%}, stop=${size.stop_price:.2f})")

# 7. ATR (DB)
atr = pg.get_atr("SPY", period=14)
print(f"[OK] SPY ATR(14): {atr:.4f}")

# 8. Latest Price
price = pg.get_latest_price("SPY")
print(f"[OK] SPY latest price: ${price:.2f}")

# 9. Regime → DB 기록
pg.insert_regime(state)
print(f"[OK] Regime recorded to DB")

# 10. Cache 기록
cache.set_regime(state)
cached = cache.get_regime()
print(f"[OK] Regime cached: {cached['current']}")

# 11. import 오케스트레이터 (구문 확인만)
from engine.api.main import PortfolioOrchestrator, app
print(f"[OK] Orchestrator + FastAPI import 성공")

print()
print("=" * 50)
print("Step 3.1 통합 테스트 전체 통과!")
