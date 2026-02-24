"""V3.1 개발환경 전체 검증 스크립트"""
import sys

def test(name, func):
    try:
        result = func()
        print(f"  ✅ {name}: {result}")
        return True
    except Exception as e:
        print(f"  ❌ {name}: {e}")
        return False

print("=" * 60)
print("🔍 Quant V3.1 개발환경 검증")
print("=" * 60)
passed = 0
total = 0

# ── Python 버전 ──
print("\n📦 Python")
total += 1
passed += test("Python 버전", lambda: f"{sys.version_info.major}.{sys.version_info.minor}")

# ── 핵심 패키지 ──
print("\n📦 핵심 패키지")
for pkg in ["polars","numpy","scipy","pandas","fastapi","grpc"]:
    total += 1
    passed += test(pkg, lambda p=pkg: __import__(p).__version__ 
                   if hasattr(__import__(p),'__version__') else "OK")

# ── PostgreSQL 연결 ──
print("\n🐘 PostgreSQL + TimescaleDB")
total += 1
def test_pg():
    import psycopg
    conn = psycopg.connect("postgresql://quant:QuantV31!Secure@localhost:5432/quantdb")
    ver = conn.execute("SELECT version()").fetchone()[0][:40]
    conn.close()
    return ver
passed += test("PostgreSQL 연결", test_pg)

total += 1
def test_ts():
    import psycopg
    conn = psycopg.connect("postgresql://quant:QuantV31!Secure@localhost:5432/quantdb")
    ver = conn.execute("SELECT extversion FROM pg_extension WHERE extname='timescaledb'").fetchone()[0]
    conn.close()
    return f"TimescaleDB {ver}"
passed += test("TimescaleDB", test_ts)

total += 1
def test_ht():
    import psycopg
    conn = psycopg.connect("postgresql://quant:QuantV31!Secure@localhost:5432/quantdb")
    cnt = conn.execute("SELECT count(*) FROM timescaledb_information.hypertables").fetchone()[0]
    conn.close()
    return f"{cnt}개 hypertable"
passed += test("Hypertables", test_ht)

# ── Redis ──
print("\n🔴 Redis")
total += 1
def test_redis():
    import redis
    r = redis.from_url("redis://localhost:6379")
    return r.ping()
passed += test("Redis 연결", test_redis)

# ── V3.1 레짐/센티먼트 ──
print("\n🎯 V3.1 레짐/센티먼트 패키지")
total += 1
passed += test("hmmlearn", lambda: __import__("hmmlearn").__version__)

total += 1
def test_hmm():
    from hmmlearn.hmm import GaussianHMM
    import numpy as np
    model = GaussianHMM(n_components=3, n_iter=10)
    X = np.random.randn(100, 2)
    model.fit(X)
    return f"3-State HMM OK"
passed += test("HMM 동작", test_hmm)

total += 1
passed += test("torch", lambda: __import__("torch").__version__)

total += 1
passed += test("transformers", lambda: __import__("transformers").__version__)

total += 1
def test_finbert():
    from transformers import pipeline
    nlp = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=-1)
    result = nlp("Apple reports record revenue")[0]
    return f"label={result['label']}, score={result['score']:.3f}"
passed += test("FinBERT 추론", test_finbert)

total += 1
passed += test("shap", lambda: __import__("shap").__version__)

# ── 데이터 수집 ──
print("\n📊 데이터 수집")
total += 1
def test_yf():
    import yfinance as yf
    data = yf.download("SPY", period="5d", progress=False)
    return f"SPY {len(data)}일 데이터"
passed += test("yfinance", test_yf)

total += 1
passed += test("alpaca-py", lambda: __import__("alpaca").__name__)
total += 1
passed += test("statsmodels", lambda: __import__("statsmodels").__version__)

# ── 결과 ──
print("\n" + "=" * 60)
pct = passed / total * 100
color = "✅" if pct == 100 else "⚠️" if pct >= 80 else "❌"
print(f"{color} 결과: {passed}/{total} 통과 ({pct:.0f}%)")
if pct == 100:
    print("🎉 개발환경 완벽! Phase 1 데이터 수집 시작 가능")
elif pct >= 80:
    print("⚠️ 일부 실패 — 실패 항목 확인 후 수정 필요")
else:
    print("❌ 다수 실패 — 패키지 재설치 필요")
print("=" * 60)
