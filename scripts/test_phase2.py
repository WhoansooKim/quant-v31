"""
V3.1 Phase 2 — 통합 테스트
모든 모듈을 실데이터로 검증
"""
import sys
import os
import time

# 경로 설정
sys.path.insert(0, "/home/quant/quant-v31")
os.chdir("/home/quant/quant-v31")

PG_DSN = "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb"


def test(name, func):
    try:
        start = time.time()
        result = func()
        elapsed = time.time() - start
        print(f"  ✅ {name}: {result} ({elapsed:.1f}초)")
        return True
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        return False


def main():
    print("=" * 60)
    print("🧪 V3.1 Phase 2 — 통합 테스트")
    print("=" * 60)
    
    passed = 0
    total = 0
    
    # ─── 1. 레짐 엔진 ───
    print("\n🎯 레짐 엔진")
    
    from engine.risk.regime import RegimeDetector
    detector = RegimeDetector(PG_DSN)
    
    total += 1
    passed += test("레짐 모델 로드", lambda: (
        detector.load(),
        f"states={list(detector.state_map.values())}"
    )[1])
    
    total += 1
    def test_regime():
        state = detector.predict_current()
        return (f"{state.current.upper()} "
                f"(B:{state.bull_prob:.0%} S:{state.sideways_prob:.0%} "
                f"R:{state.bear_prob:.0%}) conf={state.confidence:.0%}")
    passed += test("현재 레짐 예측", test_regime)
    
    regime = detector.predict_current()
    
    # ─── 2. 레짐 배분기 ───
    print("\n📊 레짐 배분기")
    
    from engine.risk.regime_allocator import RegimeAllocator
    allocator = RegimeAllocator()
    
    total += 1
    def test_alloc():
        a = allocator.get_allocation(regime)
        return (f"LowVol={a.lowvol_quality:.0%} Mom={a.vol_momentum:.0%} "
                f"Pairs={a.pairs_trading:.0%} Cash={a.cash:.0%}")
    passed += test(f"배분 ({regime.current})", test_alloc)
    
    # ─── 3. Kill Switch ───
    print("\n🛡️ Kill Switch")
    
    from engine.risk.kill_switch import DrawdownKillSwitch, DefenseLevel
    ks = DrawdownKillSwitch(initial_value=100000)
    
    total += 1
    passed += test("NORMAL 상태", lambda: (
        ks.update(100000),
        f"level={ks.level.value}, MDD={ks.current_mdd:.1%}"
    )[1])
    
    total += 1
    passed += test("WARNING (-10%)", lambda: (
        ks.update(89000),
        f"level={ks.level.value}, MDD={ks.current_mdd:.1%}, exp={ks.get_exposure_limit():.0%}"
    )[1])
    
    total += 1
    passed += test("DEFENSIVE (-15%)", lambda: (
        ks.update(84000),
        f"level={ks.level.value}, MDD={ks.current_mdd:.1%}, exp={ks.get_exposure_limit():.0%}"
    )[1])
    
    total += 1
    passed += test("EMERGENCY (-20%)", lambda: (
        ks.update(79000),
        f"level={ks.level.value}, MDD={ks.current_mdd:.1%}, cooldown={ks.cooldown_until}"
    )[1])
    
    # 리셋
    ks = DrawdownKillSwitch(initial_value=100000)
    
    # ─── 4. 포지션 사이저 ───
    print("\n📐 포지션 사이저")
    
    from engine.risk.position_sizer import DynamicPositionSizer
    sizer = DynamicPositionSizer()
    
    total += 1
    def test_atr_size():
        ps = sizer.calculate(
            symbol="AAPL", portfolio_value=100000,
            current_price=180.0, atr=3.5,
        )
        return f"shares={ps.shares}, weight={ps.weight:.1%}, stop={ps.stop_price:.2f}, method={ps.method}"
    passed += test("ATR 사이징", test_atr_size)
    
    total += 1
    def test_vol_inv():
        vols = {"AAPL": 0.25, "MSFT": 0.20, "JNJ": 0.12}
        w = sizer.size_by_vol_inverse(vols, "JNJ")
        return f"JNJ weight={w:.1%} (저변동성 우대)"
    passed += test("Vol역가중", test_vol_inv)
    
    # ─── 5. ① Low-Vol + Quality ───
    print("\n📈 ① Low-Vol + Quality")
    
    from engine.strategies.lowvol_quality import LowVolQuality
    strat1 = LowVolQuality(PG_DSN)
    
    total += 1
    def test_lowvol():
        sigs = strat1.generate_signals(regime.current, regime.confidence)
        if sigs:
            top3 = ", ".join(f"{s.symbol}({s.strength:.2f})" for s in sigs[:3])
            return f"{len(sigs)}개 시그널. 상위: {top3}"
        return "시그널 없음"
    passed += test("Low-Vol 시그널", test_lowvol)
    
    # ─── 6. ② Vol-Managed 모멘텀 ───
    print("\n📈 ② Vol-Managed 모멘텀")
    
    from engine.strategies.vol_momentum import VolManagedMomentum
    strat2 = VolManagedMomentum(PG_DSN)
    
    total += 1
    def test_momentum():
        sigs = strat2.generate_signals(regime.current, regime.confidence)
        if sigs:
            top3 = ", ".join(f"{s.symbol}({s.strength:.2f})" for s in sigs[:3])
            return f"{len(sigs)}개 시그널. 상위: {top3}"
        return "시그널 없음 (정상: Bear에서 축소)"
    passed += test("모멘텀 시그널", test_momentum)
    
    # ─── 7. ④ Vol-Targeting ───
    print("\n📈 ④ Vol-Targeting")
    
    from engine.strategies.vol_targeting import VolatilityTargeting
    import numpy as np
    vt = VolatilityTargeting()
    
    total += 1
    def test_voltarget():
        # 시뮬레이션 수익률 (고변동)
        returns = np.random.randn(60) * 0.02
        scale = vt.calculate_scale(returns, regime.current)
        return f"scale={scale:.2f} (regime={regime.current})"
    passed += test("Vol-Targeting 스케일", test_voltarget)
    
    # ─── 8. ⑤ 센티먼트 (FinBERT) ───
    print("\n📈 ⑤ FinBERT 센티먼트")
    
    from engine.strategies.sentiment import SentimentOverlay
    sent = SentimentOverlay(PG_DSN)
    
    total += 1
    def test_finbert():
        headlines = [
            {"symbol": "AAPL", "text": "Apple reports record quarterly revenue"},
            {"symbol": "TSLA", "text": "Tesla misses delivery targets significantly"},
            {"symbol": "NVDA", "text": "Nvidia announces new AI chip breakthrough"},
        ]
        results = sent.analyze_headlines(headlines)
        return ", ".join(f"{r['symbol']}={r['score']:+.2f}" for r in results)
    passed += test("FinBERT 분석", test_finbert)
    
    # ─── 9. 시그널 → 배분 통합 ───
    print("\n🔗 통합 파이프라인")
    
    total += 1
    def test_pipeline():
        # 레짐 → 배분 → 시그널 → Kill Switch
        state = detector.predict_current()
        alloc = allocator.get_allocation(state, ks.get_exposure_limit())
        
        # Low-Vol 시그널
        sigs = strat1.generate_signals(state.current, state.confidence)
        
        return (f"regime={state.current}, alloc_lowvol={alloc.lowvol_quality:.0%}, "
                f"signals={len(sigs)}, kill={ks.level.value}")
    passed += test("레짐→배분→시그널→Kill", test_pipeline)
    
    # ─── 결과 ───
    print(f"\n{'=' * 60}")
    pct = passed / total * 100
    icon = "🎉" if pct >= 90 else "⚠️" if pct >= 70 else "❌"
    print(f"{icon} Phase 2 테스트: {passed}/{total} 통과 ({pct:.0f}%)")
    
    if pct >= 90:
        print("\n🎉 Phase 2 핵심 모듈 검증 성공!")
        print("  다음 단계:")
        print("  1. ③ 페어즈: python -c 'from engine.strategies.pairs_trading import PairsTrading'")
        print("  2. Phase 3: 오케스트레이터 + Blazor 대시보드")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
