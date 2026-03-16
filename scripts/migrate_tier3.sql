-- Tier 3: LSTM + Dual Sort + Social Sentiment
-- Run: docker exec -i quant-postgres psql -U quant -d quantdb < scripts/migrate_tier3.sql

BEGIN;

-- ═══════════════════════════════════════
-- 1. LSTM 예측 결과 테이블
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS swing_ml_predictions (
    prediction_id   BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL,
    time            TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_version   VARCHAR(20) NOT NULL DEFAULT 'v1',
    up_probability  FLOAT NOT NULL,           -- 5일 후 상승 확률 (0~1)
    predicted_return FLOAT,                   -- 예상 수익률
    confidence      FLOAT,                    -- 모델 신뢰도
    features_used   INT DEFAULT 10,
    lookback_days   INT DEFAULT 60,
    horizon_days    INT DEFAULT 5,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ml_pred_symbol ON swing_ml_predictions (symbol, time DESC);

-- LSTM 모델 메타 (학습 이력)
CREATE TABLE IF NOT EXISTS swing_ml_models (
    model_id        BIGSERIAL PRIMARY KEY,
    version         VARCHAR(20) NOT NULL,
    trained_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    train_start     DATE,
    train_end       DATE,
    test_start      DATE,
    test_end        DATE,
    accuracy        FLOAT,          -- 테스트 정확도
    auc_roc         FLOAT,          -- AUC-ROC
    sharpe_delta    FLOAT,          -- 기존 대비 Sharpe 개선
    total_samples   INT,
    model_path      TEXT,           -- 저장 경로
    status          VARCHAR(10) DEFAULT 'active'  -- active/archived
);

-- ═══════════════════════════════════════
-- 2. 소셜 감성 데이터 테이블
-- ═══════════════════════════════════════
CREATE TABLE IF NOT EXISTS swing_social_sentiment (
    sentiment_id    BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(10) NOT NULL,
    time            TIMESTAMPTZ NOT NULL DEFAULT now(),
    source          VARCHAR(20) NOT NULL,     -- reddit / stocktwits
    mention_count   INT DEFAULT 0,
    bullish_count   INT DEFAULT 0,
    bearish_count   INT DEFAULT 0,
    neutral_count   INT DEFAULT 0,
    bullish_ratio   FLOAT,                    -- bullish / (bullish+bearish)
    sentiment_score FLOAT,                    -- -100 ~ +100
    velocity        FLOAT,                    -- 감성 변화 속도
    top_posts       JSONB,                    -- 상위 게시글 요약
    analyzed_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_social_symbol ON swing_social_sentiment (symbol, time DESC);
CREATE INDEX IF NOT EXISTS idx_social_source ON swing_social_sentiment (source, time DESC);

-- ═══════════════════════════════════════
-- 3. swing_config 설정 키 추가
-- ═══════════════════════════════════════

-- Phase B: 이중 정렬
INSERT INTO swing_config (key, value, category, description) VALUES
    ('dual_sort_enabled', 'true', 'strategy', '이중 정렬 (모멘텀+가치) 필터 사용 여부'),
    ('dual_sort_momentum_weight', '0.5', 'strategy', '이중 정렬 모멘텀 비중 (0~1)'),
    ('dual_sort_value_weight', '0.5', 'strategy', '이중 정렬 가치 비중 (0~1)'),
    ('dual_sort_threshold', '0.5', 'strategy', '이중 정렬 합산 순위 최소 기준')
ON CONFLICT (key) DO NOTHING;

-- Phase A: LSTM
INSERT INTO swing_config (key, value, category, description) VALUES
    ('lstm_enabled', 'true', 'ml', 'LSTM 모멘텀 예측 사용 여부'),
    ('lstm_weight_in_technical', '0.5', 'ml', 'Technical Score 내 LSTM 비중'),
    ('lstm_min_accuracy', '0.53', 'ml', 'LSTM 최소 정확도 기준 (미달 시 미적용)'),
    ('lstm_retrain_day', 'saturday', 'ml', 'LSTM 재학습 요일')
ON CONFLICT (key) DO NOTHING;

-- Phase C: 소셜 감성
INSERT INTO swing_config (key, value, category, description) VALUES
    ('social_enabled', 'true', 'social', '소셜 감성 분석 사용 여부'),
    ('social_reddit_enabled', 'true', 'social', 'Reddit 수집 사용 여부'),
    ('social_stocktwits_enabled', 'true', 'social', 'StockTwits 수집 사용 여부'),
    ('social_weight_in_sentiment', '0.4', 'social', 'Sentiment Score 내 소셜 비중 (뉴스 1-x)')
ON CONFLICT (key) DO NOTHING;

COMMIT;

-- 확인
SELECT key, value, category, description FROM swing_config
WHERE category IN ('strategy', 'ml', 'social')
ORDER BY category, key;
