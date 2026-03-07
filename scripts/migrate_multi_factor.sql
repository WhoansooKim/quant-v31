-- Phase C: Multi-Factor Scoring columns on swing_signals
-- Run: psql -U quant -d quantdb -f scripts/migrate_multi_factor.sql

-- Factor scores (0-100 scale each)
ALTER TABLE swing_signals ADD COLUMN IF NOT EXISTS technical_score DOUBLE PRECISION;
ALTER TABLE swing_signals ADD COLUMN IF NOT EXISTS sentiment_score DOUBLE PRECISION;
ALTER TABLE swing_signals ADD COLUMN IF NOT EXISTS flow_score DOUBLE PRECISION;
ALTER TABLE swing_signals ADD COLUMN IF NOT EXISTS composite_score DOUBLE PRECISION;

-- Factor detail JSON (breakdown of sub-factors)
ALTER TABLE swing_signals ADD COLUMN IF NOT EXISTS factor_detail JSONB;
ALTER TABLE swing_signals ADD COLUMN IF NOT EXISTS factor_scored_at TIMESTAMPTZ;

-- Index for filtering by composite score
CREATE INDEX IF NOT EXISTS idx_swing_signals_composite
    ON swing_signals (composite_score DESC NULLS LAST)
    WHERE status = 'pending';

-- Finnhub config keys
INSERT INTO swing_config (key, value, category, description)
VALUES
    ('factor_weight_technical', '0.4', 'scoring', 'Technical factor weight (0-1)'),
    ('factor_weight_sentiment', '0.3', 'scoring', 'Sentiment factor weight (0-1)'),
    ('factor_weight_flow', '0.3', 'scoring', 'Flow factor weight (0-1)'),
    ('composite_score_min', '50', 'scoring', 'Minimum composite score for signal generation')
ON CONFLICT (key) DO NOTHING;
