"""
V3.1 Phase 2 — ⑤ FinBERT + Claude 하이브리드 센티먼트
1차: FinBERT 로컬 대량 (무료)
2차: Claude API 강신호만 (비용 절감)
"""
import numpy as np
import logging
from datetime import datetime
from .base import BaseStrategy, Signal

logger = logging.getLogger(__name__)


class SentimentOverlay(BaseStrategy):
    """FinBERT + Claude 하이브리드 센티먼트 오버레이
    
    논리:
    1. FinBERT 로컬: 전 종목 헤드라인 대량 분석 (무료)
    2. 강신호 필터: |FinBERT score| > threshold만 추출
    3. Claude API: 강신호만 2차 검증 (비용 90% 절감)
    4. 최종: 기존 시그널 strength에 센티먼트 가중
    
    사용 방법:
    - 다른 전략의 시그널을 받아서 센티먼트로 조정 (오버레이)
    - 독자적으로도 시그널 생성 가능
    """
    
    def __init__(self, pg_dsn: str, config: dict | None = None):
        super().__init__(pg_dsn, config)
        self.finbert_threshold = config.get("finbert_threshold", 0.7) if config else 0.7
        self.claude_enabled = config.get("claude_enabled", False) if config else False
        self._finbert_pipeline = None
    
    def _get_finbert(self):
        """FinBERT 파이프라인 (지연 로딩)"""
        if self._finbert_pipeline is None:
            from transformers import pipeline
            self._finbert_pipeline = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                device=-1,  # CPU
                batch_size=32,
            )
            logger.info("FinBERT 모델 로드 완료")
        return self._finbert_pipeline
    
    def analyze_headlines(self, headlines: list[dict]) -> list[dict]:
        """FinBERT로 헤드라인 배치 분석
        
        Args:
            headlines: [{"symbol": "AAPL", "text": "Apple reports...", "source": "reuters"}]
            
        Returns:
            [{"symbol": "AAPL", "score": 0.85, "label": "positive", ...}]
        """
        if not headlines:
            return []
        
        pipe = self._get_finbert()
        texts = [h["text"][:512] for h in headlines]  # 512 토큰 제한
        
        results = pipe(texts)
        
        scored = []
        for h, r in zip(headlines, results):
            label = r["label"]
            conf = r["score"]
            
            # -1 ~ +1 스코어 변환
            if label == "positive":
                score = conf
            elif label == "negative":
                score = -conf
            else:
                score = 0.0
            
            scored.append({
                "symbol": h["symbol"],
                "text": h["text"],
                "source": h.get("source", ""),
                "finbert_label": label,
                "finbert_conf": conf,
                "score": score,
            })
        
        return scored
    
    def get_sentiment_scores(self, symbols: list[str]) -> dict[str, float]:
        """종목별 센티먼트 스코어 (DB에서 최근 조회)"""
        if not symbols:
            return {}
        
        try:
            with self._get_conn() as conn:
                rows = conn.execute("""
                    SELECT symbol, avg(hybrid_score) AS avg_score
                    FROM sentiment_scores
                    WHERE symbol = ANY(%s)
                      AND time > now() - interval '7 days'
                    GROUP BY symbol
                """, (symbols,)).fetchall()
            return {r[0]: float(r[1]) for r in rows}
        except:
            return {}
    
    def apply_overlay(self, signals: list[Signal],
                      sentiment_scores: dict[str, float],
                      weight: float = 0.2) -> list[Signal]:
        """기존 시그널에 센티먼트 오버레이 적용
        
        adjusted_strength = (1 - weight) * original + weight * sentiment
        
        Args:
            signals: 기존 전략 시그널
            sentiment_scores: {symbol: score} (-1 ~ +1)
            weight: 센티먼트 가중치 (기본 20%)
        """
        adjusted = []
        for s in signals:
            sent = sentiment_scores.get(s.symbol, 0.0)
            new_strength = (1 - weight) * s.strength + weight * sent
            
            adjusted.append(Signal(
                symbol=s.symbol,
                direction=s.direction,
                strength=float(np.clip(new_strength, -1, 1)),
                strategy=s.strategy,
                regime=s.regime,
                factors={**s.factors, "sentiment": sent},
            ))
        
        return adjusted
    
    def record_scores_to_db(self, scores: list[dict]):
        """센티먼트 스코어 DB 기록"""
        with self._get_conn() as conn:
            for s in scores:
                conn.execute("""
                    INSERT INTO sentiment_scores
                        (symbol, finbert_score, hybrid_score, source, headline_count)
                    VALUES (%s, %s, %s, %s, %s)
                """, (s["symbol"], s["score"], s["score"],
                      s.get("source", "finbert"), 1))
            conn.commit()
    
    def generate_signals(self, regime: str,
                         regime_conf: float) -> list[Signal]:
        """독자적 센티먼트 시그널 (DB에 센티먼트 데이터 있을 때)"""
        universe = self.get_universe()
        scores = self.get_sentiment_scores(universe)
        
        if not scores:
            logger.info(f"[{self.name}] 센티먼트 데이터 없음 → 시그널 없음")
            return []
        
        # 강한 센티먼트만 시그널
        strong = [(sym, sc) for sym, sc in scores.items()
                  if abs(sc) >= self.finbert_threshold]
        strong.sort(key=lambda x: abs(x[1]), reverse=True)
        
        n = {"bull": 10, "sideways": 5, "bear": 3}.get(regime, 5)
        
        signals = []
        for sym, score in strong[:n]:
            direction = "long" if score > 0 else "short"
            signals.append(Signal(
                symbol=sym, direction=direction,
                strength=float(score),
                strategy=self.name, regime=regime,
                factors={"sentiment_score": score},
            ))
        
        return signals
