-- Phase E: Real-time Event System
-- Run: docker exec quant-postgres psql -U quant -d quantdb -f - < scripts/migrate_events.sql

CREATE TABLE IF NOT EXISTS swing_events (
    event_id   BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    symbol     VARCHAR(20),
    severity   VARCHAR(20) DEFAULT 'info',
    title      TEXT NOT NULL,
    detail     JSONB DEFAULT '{}',
    llm_score  INTEGER,
    action_taken VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Make it a hypertable if not already
SELECT create_hypertable('swing_events', 'created_at', if_not_exists => true);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_swing_events_symbol ON swing_events (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_swing_events_type ON swing_events (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_swing_events_severity ON swing_events (severity) WHERE severity IN ('warning', 'critical');
