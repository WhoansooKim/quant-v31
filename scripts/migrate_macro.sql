-- Macro Overlay — snapshot table + config keys + signal column
-- Run: psql -U quant -d quantdb -f scripts/migrate_macro.sql

-- 1. Macro snapshots hypertable (시계열 저장)
CREATE TABLE IF NOT EXISTS swing_macro_snapshots (
    id SERIAL,
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    macro_score DOUBLE PRECISION,
    risk_off_score DOUBLE PRECISION,
    yield_curve_score DOUBLE PRECISION,
    copper_gold_score DOUBLE PRECISION,
    dollar_trend_score DOUBLE PRECISION,
    btc_momentum_score DOUBLE PRECISION,
    regime VARCHAR(20),
    vix DOUBLE PRECISION,
    tnx DOUBLE PRECISION,
    dxy DOUBLE PRECISION,
    gold_spy_ratio DOUBLE PRECISION,
    hy_spread DOUBLE PRECISION,
    copper_gold_ratio DOUBLE PRECISION,
    btc_momentum_20d DOUBLE PRECISION,
    dxy_momentum_20d DOUBLE PRECISION,
    detail JSONB
);

SELECT create_hypertable('swing_macro_snapshots', 'time', if_not_exists => true);

CREATE INDEX IF NOT EXISTS idx_macro_snapshots_time
    ON swing_macro_snapshots (time DESC);

-- 2. swing_signals에 macro_score 컬럼 추가
ALTER TABLE swing_signals
    ADD COLUMN IF NOT EXISTS macro_score DOUBLE PRECISION;

COMMENT ON COLUMN swing_signals.macro_score IS 'Macro overlay score 0-100 at signal scoring time';

-- 3. Config keys
INSERT INTO swing_config (key, value, category, description) VALUES
    ('macro_enabled', 'true', 'scoring', 'Enable macro overlay as 6th factor'),
    ('macro_weight', '0.10', 'scoring', 'Macro factor default weight (reduces others proportionally)'),
    ('macro_risk_off_threshold', '30', 'macro', 'Macro score below this = severe risk-off warning')
ON CONFLICT (key) DO NOTHING;
