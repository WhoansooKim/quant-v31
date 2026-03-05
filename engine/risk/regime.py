"""
V3.1 Phase 2 — HMM 3-State 레짐 엔진 (프로덕션)
Phase 1 프로토타입 → 프로덕션 레벨: 월간 재학습, 전이 감지, DB 연동
"""
import numpy as np
import psycopg
from hmmlearn.hmm import GaussianHMM
from pathlib import Path
import pickle
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MODEL_DIR = Path("/home/quant/quant-v31/models")


@dataclass
class RegimeState:
    """레짐 상태"""
    current: str           # "bull", "sideways", "bear"
    bull_prob: float
    sideways_prob: float
    bear_prob: float
    confidence: float
    previous: str | None
    is_transition: bool
    detected_at: datetime


class RegimeDetector:
    """HMM 3-State 레짐 감지 엔진 (프로덕션)
    
    Features:
    - SPY 일수익률 + 21일 변동성 + VIX 변화율
    - 월간 자동 재학습
    - 레짐 전이 감지 (이전 vs 현재)
    - Smoothing: 전이 속도 조절 (급변 방지)
    """
    
    MODEL_PATH = MODEL_DIR / "hmm_regime_v31.pkl"
    
    def __init__(self, pg_dsn: str, n_states: int = 3, lookback: int = 504,
                 transition_speed: float = 0.3):
        self.pg_dsn = pg_dsn
        self.n_states = n_states
        self.lookback = lookback
        self.transition_speed = transition_speed  # 0.0=느림, 1.0=즉시 전환
        self.model: GaussianHMM | None = None
        self.state_map: dict = {}
        self._prev_regime: str | None = None
        self._smoothed_probs: np.ndarray | None = None
    
    def _get_conn(self):
        return psycopg.connect(self.pg_dsn)
    
    # ─── 데이터 로드 ───
    
    def _load_spy(self) -> np.ndarray:
        """DB에서 SPY 종가 로드"""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT close FROM daily_prices
                WHERE symbol = 'SPY'
                ORDER BY time ASC
            """).fetchall()
        if not rows or len(rows) < self.lookback:
            raise ValueError(f"SPY 데이터 부족: {len(rows) if rows else 0}일")
        return np.array([float(r[0]) for r in rows])
    
    def _load_vix(self) -> np.ndarray | None:
        """Parquet에서 VIX 로드"""
        path = Path("/home/quant/quant-v31/data/parquet/benchmark/VIX.parquet")
        if not path.exists():
            return None
        try:
            import polars as pl
            df = pl.read_parquet(path)
            close_col = [c for c in df.columns if 'close' in c.lower() or 'Close' in c]
            if close_col:
                return df[close_col[0]].drop_nulls().to_numpy().astype(float)
        except:
            pass
        return None
    
    # ─── 피처 생성 ───
    
    def _prepare_features(self, prices: np.ndarray, 
                          vix: np.ndarray | None = None) -> np.ndarray:
        """관측 변수: 일수익률 + 21일Vol + VIX변화율"""
        ret = np.diff(prices) / prices[:-1]
        
        # 21일 롤링 변동성 (연간화)
        vol = np.array([
            np.std(ret[max(0, i-21):i]) * np.sqrt(252)
            for i in range(21, len(ret))
        ])
        ret = ret[21:]
        n = min(len(ret), len(vol))
        ret, vol = ret[-n:], vol[-n:]
        
        # VIX 변화율 추가
        if vix is not None and len(vix) > n + 22:
            vix_chg = np.diff(vix[-(n+1):]) / vix[-(n+1):-1]
            if len(vix_chg) == n:
                X = np.column_stack([ret, vol, vix_chg])
            else:
                X = np.column_stack([ret, vol])
        else:
            X = np.column_stack([ret, vol])
        
        mask = ~(np.isnan(X).any(axis=1) | np.isinf(X).any(axis=1))
        return X[mask]
    
    # ─── 학습 ───
    
    def fit(self) -> "RegimeDetector":
        """HMM 학습 (여러 시드, 최적 선택)"""
        logger.info("HMM 레짐 학습 시작")
        prices = self._load_spy()
        vix = self._load_vix()
        X = self._prepare_features(prices, vix)
        
        best_model, best_score = None, -np.inf
        for seed in [42, 123, 456, 789, 1024]:
            try:
                m = GaussianHMM(n_components=self.n_states, covariance_type="full",
                                n_iter=300, random_state=seed, tol=0.001)
                m.fit(X)
                score = m.score(X)
                if score > best_score:
                    best_score, best_model = score, m
            except:
                continue
        
        self.model = best_model
        
        # 상태 매핑 (수익률 기준)
        means = self.model.means_[:, 0]
        idx = np.argsort(means)[::-1]
        self.state_map = {int(idx[0]): "bull", int(idx[1]): "sideways", int(idx[2]): "bear"}
        
        self.save()
        logger.info(f"HMM 학습 완료: {self.state_map}, score={best_score:.2f}")
        return self
    
    # ─── 예측 ───
    
    def predict_current(self) -> RegimeState:
        """현재 레짐 예측 + 스무딩 + 전이 감지"""
        if self.model is None:
            self.load()
        
        prices = self._load_spy()
        vix = self._load_vix()
        X = self._prepare_features(prices, vix)
        
        _, posteriors = self.model.score_samples(X)
        raw_probs = posteriors[-1]
        
        # ─── 확률 스무딩 (급변 방지) ───
        if self._smoothed_probs is not None:
            alpha = self.transition_speed
            smoothed = alpha * raw_probs + (1 - alpha) * self._smoothed_probs
            smoothed /= smoothed.sum()  # 정규화
        else:
            smoothed = raw_probs
        self._smoothed_probs = smoothed
        
        # 레짐 결정
        current_state = int(np.argmax(smoothed))
        current_regime = self.state_map[current_state]
        
        # 전이 감지
        is_transition = (self._prev_regime is not None and 
                         self._prev_regime != current_regime)
        previous = self._prev_regime
        self._prev_regime = current_regime
        
        # 확률 추출
        probs = {}
        for sid, rname in self.state_map.items():
            probs[rname] = float(smoothed[sid])
        
        state = RegimeState(
            current=current_regime,
            bull_prob=probs.get("bull", 0),
            sideways_prob=probs.get("sideways", 0),
            bear_prob=probs.get("bear", 0),
            confidence=float(np.max(smoothed)),
            previous=previous,
            is_transition=is_transition,
            detected_at=datetime.now(),
        )
        
        if is_transition:
            logger.warning(f"🔄 레짐 전이: {previous} → {current_regime} "
                          f"(신뢰도 {state.confidence:.1%})")
        
        return state
    
    def forecast_k_step(self, horizons: list[int] = [5, 21, 63]) -> list[dict]:
        """Hamilton (1989) k-step regime forecast via transition matrix power.
        P(regime_t+k | current) = current_probs @ T^k
        """
        if self.model is None:
            self.load()

        T = self.model.transmat_

        # Use smoothed probs if available, otherwise run predict_current
        if self._smoothed_probs is None:
            self.predict_current()

        current = self._smoothed_probs
        results = []
        for k in horizons:
            Tk = np.linalg.matrix_power(T, k)
            future = current @ Tk
            future = future / future.sum()  # normalize
            probs = {self.state_map[i]: float(future[i]) for i in range(self.n_states)}
            dominant = max(probs, key=probs.get)
            results.append({
                "horizon_days": k,
                "bull": probs.get("bull", 0),
                "sideways": probs.get("sideways", 0),
                "bear": probs.get("bear", 0),
                "dominant": dominant,
            })
        return results

    def record_to_db(self, state: RegimeState):
        """레짐 상태를 DB에 기록"""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO regime_history 
                    (regime, bull_prob, sideways_prob, bear_prob, confidence,
                     previous_regime, is_transition)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (state.current, state.bull_prob, state.sideways_prob,
                  state.bear_prob, state.confidence,
                  state.previous, state.is_transition))
            conn.commit()
    
    def should_retrain(self, interval_days: int = 30) -> bool:
        """재학습 필요 여부 (모델 파일 수정일 기준)"""
        if not self.MODEL_PATH.exists():
            return True
        age = datetime.now().timestamp() - self.MODEL_PATH.stat().st_mtime
        return age > interval_days * 86400
    
    # ─── 저장/로드 ───
    
    def save(self):
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.MODEL_PATH, "wb") as f:
            pickle.dump({
                "model": self.model,
                "state_map": self.state_map,
                "trained_at": datetime.now().isoformat(),
            }, f)
    
    def load(self) -> "RegimeDetector":
        if not self.MODEL_PATH.exists():
            raise FileNotFoundError(f"모델 없음: {self.MODEL_PATH}. fit()을 먼저 실행하세요.")
        with open(self.MODEL_PATH, "rb") as f:
            d = pickle.load(f)
            self.model = d["model"]
            self.state_map = d["state_map"]
        return self
