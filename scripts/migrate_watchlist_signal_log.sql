-- Watchlist Signal Log: 매일 분석 결과를 기록하여 리플레이 백테스트에 사용
-- 실행: psql -U quant -d quantdb -f scripts/migrate_watchlist_signal_log.sql

CREATE TABLE IF NOT EXISTS swing_watchlist_signal_log (
    log_id          BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    signal_date     DATE NOT NULL,
    direction       TEXT NOT NULL,             -- STRONG_BUY, BUY, NEUTRAL, SELL, STRONG_SELL
    weighted_score  DOUBLE PRECISION NOT NULL,
    confidence      INTEGER NOT NULL,
    current_price   DOUBLE PRECISION NOT NULL,
    regime          TEXT,                      -- TRENDING, SIDEWAYS, MIXED
    category_scores JSONB,                    -- {trend, momentum, macd, mean_reversion, volume}
    category_weights JSONB,                   -- {trend, momentum, macd, mean_reversion, volume}
    vol_ratio       DOUBLE PRECISION,
    vol_factor      DOUBLE PRECISION,
    target_price    DOUBLE PRECISION,
    stop_price      DOUBLE PRECISION,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, signal_date)
);

CREATE INDEX IF NOT EXISTS idx_wl_signal_log_date ON swing_watchlist_signal_log (signal_date);
CREATE INDEX IF NOT EXISTS idx_wl_signal_log_symbol ON swing_watchlist_signal_log (symbol);
