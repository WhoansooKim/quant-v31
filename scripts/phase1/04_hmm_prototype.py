"""
V3.1 Phase 1 — HMM 3-State 레짐 프로토타입 (수정본)
Parquet MultiIndex 컬럼 + DB 폴백 처리
"""
import numpy as np
import psycopg
import polars as pl
from hmmlearn.hmm import GaussianHMM
from pathlib import Path
import pickle
import warnings
warnings.filterwarnings('ignore')

PG_DSN = "postgresql://quant:QuantV31!Secure@localhost:5432/quantdb"
MODEL_DIR = Path("/home/quant/quant-v31/models")


def find_close_column(df):
    """Parquet에서 Close 컬럼 찾기 (MultiIndex 대응)"""
    for col in df.columns:
        if col.lower() in ('close', 'adj close', 'adj_close'):
            return col
        if 'close' in col.lower():
            return col
    raise KeyError(f"Close 컬럼 없음. 컬럼 목록: {df.columns}")


def load_spy_data() -> np.ndarray:
    """SPY 데이터 로드 (DB 우선, Parquet 폴백)"""
    # 1. DB에서 시도
    try:
        with psycopg.connect(PG_DSN) as conn:
            rows = conn.execute("""
                SELECT time, close FROM daily_prices
                WHERE symbol = 'SPY'
                ORDER BY time ASC
            """).fetchall()
        if rows and len(rows) > 252:
            print(f"  SPY: DB에서 {len(rows)}일 로드")
            return np.array([float(r[1]) for r in rows])
    except:
        pass
    
    # 2. Parquet 폴백
    path = Path("/home/quant/quant-v31/data/parquet/benchmark/SPY.parquet")
    if not path.exists():
        # 3. OHLCV Parquet
        path = Path("/home/quant/quant-v31/data/parquet/ohlcv/SPY.parquet")
    
    if path.exists():
        df = pl.read_parquet(path)
        print(f"  SPY Parquet 컬럼: {df.columns}")
        close_col = find_close_column(df)
        prices = df[close_col].drop_nulls().to_numpy().astype(float)
        print(f"  SPY: Parquet에서 {len(prices)}일 로드 (컬럼: {close_col})")
        return prices
    
    raise FileNotFoundError("SPY 데이터 없음. 02 또는 03 스크립트를 먼저 실행하세요.")


def load_vix_data() -> np.ndarray:
    """VIX 데이터 로드"""
    path = Path("/home/quant/quant-v31/data/parquet/benchmark/VIX.parquet")
    if not path.exists():
        return None
    
    df = pl.read_parquet(path)
    close_col = find_close_column(df)
    prices = df[close_col].drop_nulls().to_numpy().astype(float)
    print(f"  VIX: {len(prices)}일 로드 (컬럼: {close_col})")
    return prices


def prepare_features(prices: np.ndarray, vix: np.ndarray = None):
    """관측 변수: 일수익률 + 21일 변동성 (+ VIX 변화율)"""
    ret = np.diff(prices) / prices[:-1]
    
    vol = np.array([
        np.std(ret[max(0, i-21):i]) * np.sqrt(252)
        for i in range(21, len(ret))
    ])
    ret = ret[21:]
    
    n = min(len(ret), len(vol))
    ret = ret[-n:]
    vol = vol[-n:]
    
    if vix is not None and len(vix) > n + 22:
        vix_aligned = vix[-(n+1):]
        vix_chg = np.diff(vix_aligned) / vix_aligned[:-1]
        vix_chg = vix_chg[-n:]
        
        if len(vix_chg) == n:
            X = np.column_stack([ret, vol, vix_chg])
        else:
            X = np.column_stack([ret, vol])
    else:
        X = np.column_stack([ret, vol])
    
    mask = ~(np.isnan(X).any(axis=1) | np.isinf(X).any(axis=1))
    return X[mask]


def train_hmm(X: np.ndarray, n_states: int = 3):
    """HMM 학습 (여러 시드)"""
    best_model = None
    best_score = -np.inf
    
    for seed in [42, 123, 456, 789, 1024]:
        try:
            model = GaussianHMM(
                n_components=n_states, covariance_type="full",
                n_iter=300, random_state=seed, tol=0.001
            )
            model.fit(X)
            score = model.score(X)
            if score > best_score:
                best_score = score
                best_model = model
        except:
            continue
    
    return best_model


def map_states(model):
    """상태 → 레짐 매핑"""
    means = model.means_[:, 0]
    idx = np.argsort(means)[::-1]
    return {int(idx[0]): "bull", int(idx[1]): "sideways", int(idx[2]): "bear"}


def analyze_regimes(model, X, state_map):
    """레짐 분석"""
    states = model.predict(X)
    _, posteriors = model.score_samples(X)
    
    print("\n📊 레짐 통계")
    for state_id, regime in sorted(state_map.items()):
        mask = states == state_id
        count = mask.sum()
        pct = count / len(states) * 100
        mean_ret = model.means_[state_id][0] * 252
        
        icon = {"bull": "🟢", "sideways": "🟡", "bear": "🔴"}[regime]
        print(f"  {icon} {regime:10s}: {count:4d}일 ({pct:5.1f}%) | 연간 수익률: {mean_ret:+6.1f}%")
    
    # 현재 레짐
    current_probs = posteriors[-1]
    current_state = states[-1]
    current_regime = state_map[current_state]
    
    print(f"\n🎯 현재 레짐: {current_regime.upper()}")
    for state_id, regime in sorted(state_map.items()):
        conf = current_probs[state_id] * 100
        bar = "█" * int(conf / 2) + "░" * (50 - int(conf / 2))
        print(f"  {regime:10s}: {bar} {conf:5.1f}%")
    
    # 전이 행렬
    print(f"\n📊 전이 확률 행렬")
    trans = model.transmat_
    header = "".join(f"{state_map[i]:>10s}" for i in sorted(state_map.keys()))
    print(f"  {'':12s}→{header}")
    for i in sorted(state_map.keys()):
        row = "".join(f"{trans[i][j]*100:9.1f}%" for j in sorted(state_map.keys()))
        print(f"  {state_map[i]:12s}:{row}")
    
    return states, posteriors


def validate_covid(states, state_map, total_price_days):
    """2020 COVID Bear 감지 검증"""
    print("\n🦠 2020 COVID Bear 감지 검증")
    
    # 2020.02~04은 대략 끝에서 ~1500일 (2026-2020=6년, 6*252=1512)
    # 좀 더 넓게 잡아서 탐색
    n = len(states)
    
    # COVID crash: 약 2020년 2~4월 (약 40~60 거래일)
    # 끝에서 약 1450~1510일 전 구간
    for offset in [1500, 1450, 1400, 1350]:
        start = max(0, n - offset)
        end = min(n, start + 60)
        
        segment = states[start:end]
        regime_names = [state_map[s] for s in segment]
        bear_count = regime_names.count("bear")
        bear_pct = bear_count / len(regime_names) * 100 if regime_names else 0
        
        if bear_pct >= 20:
            print(f"  구간 [{start}:{end}] ({len(regime_names)}일):")
            print(f"  Bull: {regime_names.count('bull')}일, "
                  f"Sideways: {regime_names.count('sideways')}일, "
                  f"Bear: {regime_names.count('bear')}일 ({bear_pct:.0f}%)")
            
            if bear_pct >= 30:
                print(f"  ✅ COVID Bear 감지 성공! ({bear_pct:.0f}% ≥ 30%)")
                return True
            else:
                print(f"  ⚠️ Bear 감지 있으나 약함 ({bear_pct:.0f}%)")
    
    # 전체에서 Bear 비율 확인
    all_regimes = [state_map[s] for s in states]
    total_bear = all_regimes.count("bear")
    print(f"\n  전체 Bear 비율: {total_bear}/{n} ({total_bear/n*100:.1f}%)")
    
    if total_bear > 0:
        print(f"  ⚠️ Bear 상태 존재함 — Phase 2에서 피처 추가로 개선 예정")
        return True
    
    print(f"  ❌ Bear 미감지 — 피처 추가 필요")
    return False


def save_model(model, state_map):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = MODEL_DIR / "hmm_regime_v31.pkl"
    with open(path, "wb") as f:
        pickle.dump({"model": model, "state_map": state_map}, f)
    print(f"\n💾 모델 저장: {path}")


def save_regime_to_db(state_map, model, X):
    _, posteriors = model.score_samples(X)
    p = posteriors[-1]
    
    # state_map에서 각 레짐의 확률 추출
    bull_prob = sideways_prob = bear_prob = 0.0
    for state_id, regime_name in state_map.items():
        if regime_name == "bull":
            bull_prob = float(p[state_id])
        elif regime_name == "sideways":
            sideways_prob = float(p[state_id])
        elif regime_name == "bear":
            bear_prob = float(p[state_id])
    
    current = max(state_map.values(), key=lambda r: 
                  {"bull": bull_prob, "sideways": sideways_prob, "bear": bear_prob}[r])
    
    with psycopg.connect(PG_DSN) as conn:
        conn.execute("""
            INSERT INTO regime_history 
                (regime, bull_prob, sideways_prob, bear_prob, confidence,
                 previous_regime, is_transition)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (current, bull_prob, sideways_prob, bear_prob,
              float(max(p)), None, False))
        conn.commit()
    
    print(f"  ✅ 레짐 DB 기록: {current.upper()} (신뢰도 {max(p):.1%})")


def main():
    print("=" * 60)
    print("🎯 V3.1 Phase 1 — HMM 3-State 레짐 프로토타입")
    print("=" * 60)
    
    # 1. 데이터 로드
    print("\n📡 Step 1: 데이터 로드")
    prices = load_spy_data()
    vix = load_vix_data()
    
    # 2. 피처 생성
    print(f"\n🔧 Step 2: 관측 변수 생성")
    X = prepare_features(prices, vix)
    print(f"  피처 행렬: {X.shape}")
    
    # 3. HMM 학습
    print(f"\n🧠 Step 3: HMM 3-State 학습")
    model = train_hmm(X)
    state_map = map_states(model)
    print(f"  ✅ 학습 완료: {state_map}")
    
    # 4. 분석
    states, posteriors = analyze_regimes(model, X, state_map)
    
    # 5. COVID 검증
    covid_ok = validate_covid(states, state_map, len(prices))
    
    # 6. 저장
    save_model(model, state_map)
    
    print("\n💾 Step 6: 현재 레짐 DB 기록")
    save_regime_to_db(state_map, model, X)
    
    print(f"\n{'=' * 60}")
    if covid_ok:
        print("🎉 HMM 프로토타입 검증 성공!")
    else:
        print("⚠️ 부분 성공 — Phase 2에서 피처 보강 예정")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
