"""
V3.1 Phase 1 — 마스터 실행기
모든 Phase 1 스크립트를 순서대로 실행
"""
import subprocess
import sys
import time

SCRIPTS = [
    ("01_build_universe.py",     "유니버스 구축 (S&P 종목 수집 → PostgreSQL)"),
    ("02_collect_ohlcv.py",      "15년 OHLCV 수집 (→ PostgreSQL + Parquet)"),
    ("03_collect_benchmarks.py", "벤치마크 + 매크로 (SPY, VIX, FRED)"),
    ("04_hmm_prototype.py",      "HMM 3-State 레짐 프로토타입 검증"),
]


def run_script(filename: str, description: str) -> bool:
    print(f"\n{'═' * 60}")
    print(f"▶ {description}")
    print(f"  스크립트: {filename}")
    print(f"{'═' * 60}")
    
    start = time.time()
    result = subprocess.run(
        [sys.executable, f"scripts/phase1/{filename}"],
        cwd="/home/quant/quant-v31"
    )
    elapsed = time.time() - start
    
    if result.returncode == 0:
        print(f"\n✅ {filename} 완료 ({elapsed/60:.1f}분)")
        return True
    else:
        print(f"\n❌ {filename} 실패 (코드: {result.returncode})")
        return False


def main():
    print("=" * 60)
    print("🚀 V3.1 Phase 1 — 전체 실행")
    print("=" * 60)
    print(f"\n실행 순서:")
    for i, (f, d) in enumerate(SCRIPTS, 1):
        print(f"  {i}. {d}")
    
    print(f"\n⏱️ 총 예상 소요: 30분 ~ 2시간 (종목 수에 따라)")
    print(f"   (대부분 02_collect_ohlcv.py에서 소요)")
    
    results = {}
    total_start = time.time()
    
    for filename, description in SCRIPTS:
        ok = run_script(filename, description)
        results[filename] = ok
        
        if not ok:
            print(f"\n⚠️ {filename} 실패. 계속 진행하시겠습니까?")
            print(f"   다음 스크립트부터 개별 실행 가능:")
            print(f"   python scripts/phase1/{SCRIPTS[SCRIPTS.index((filename, description)) + 1][0] if SCRIPTS.index((filename, description)) + 1 < len(SCRIPTS) else '(완료)'}")
    
    total_elapsed = time.time() - total_start
    
    print(f"\n{'═' * 60}")
    print(f"📊 Phase 1 실행 결과")
    print(f"{'═' * 60}")
    for filename, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {filename}")
    
    passed = sum(1 for v in results.values() if v)
    print(f"\n  결과: {passed}/{len(results)} 성공 ({total_elapsed/60:.1f}분)")
    
    if passed == len(results):
        print(f"\n🎉 Phase 1 완료! Phase 2 (레짐 엔진 + 전략 개발)로 진행 가능합니다.")
    else:
        print(f"\n⚠️ 실패 스크립트를 개별 재실행하세요.")


if __name__ == "__main__":
    main()
