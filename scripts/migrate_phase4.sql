-- ═══════════════════════════════════════
--  Quant V3.1 Phase 4 — Backtest Tables
-- ═══════════════════════════════════════

-- Backtest run metadata
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    run_type VARCHAR(30) NOT NULL,        -- walk_forward, monte_carlo, regime_stress, granger, full
    started_at TIMESTAMPTZ DEFAULT now(),
    finished_at TIMESTAMPTZ,
    config JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'running', -- running, completed, failed
    summary JSONB DEFAULT '{}'
);

-- Walk-Forward fold results
CREATE TABLE IF NOT EXISTS walk_forward_results (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id BIGINT REFERENCES backtest_runs(run_id),
    fold_num INT NOT NULL,
    train_start DATE NOT NULL,
    train_end DATE NOT NULL,
    test_start DATE NOT NULL,
    test_end DATE NOT NULL,
    -- In-Sample metrics
    is_sharpe NUMERIC(8,4),
    is_cagr NUMERIC(8,4),
    is_mdd NUMERIC(8,4),
    -- Out-of-Sample metrics
    oos_sharpe NUMERIC(8,4),
    oos_cagr NUMERIC(8,4),
    oos_mdd NUMERIC(8,4),
    oos_calmar NUMERIC(8,4),
    -- Regime distribution
    regime_bull_pct NUMERIC(4,2),
    regime_sideways_pct NUMERIC(4,2),
    regime_bear_pct NUMERIC(4,2),
    -- Strategy allocations
    strategy_returns JSONB DEFAULT '{}'
);
SELECT create_hypertable('walk_forward_results', by_range('time'), if_not_exists => true);

-- Monte Carlo simulation results
CREATE TABLE IF NOT EXISTS monte_carlo_results (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id BIGINT REFERENCES backtest_runs(run_id),
    n_simulations INT,
    -- Distribution stats
    median_cagr NUMERIC(8,4),
    p5_cagr NUMERIC(8,4),
    p95_cagr NUMERIC(8,4),
    median_sharpe NUMERIC(8,4),
    p5_sharpe NUMERIC(8,4),
    p95_sharpe NUMERIC(8,4),
    median_mdd NUMERIC(8,4),
    p5_mdd NUMERIC(8,4),
    p95_mdd NUMERIC(8,4),
    -- Probability of ruin
    prob_negative NUMERIC(6,4),
    prob_mdd_over_20 NUMERIC(6,4),
    -- Full paths stored as JSONB array
    paths_summary JSONB DEFAULT '{}'
);
SELECT create_hypertable('monte_carlo_results', by_range('time'), if_not_exists => true);

-- Regime stress test results
CREATE TABLE IF NOT EXISTS regime_stress_results (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id BIGINT REFERENCES backtest_runs(run_id),
    scenario VARCHAR(50) NOT NULL,         -- covid_crash, rate_hike, recovery, vix_spike
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    -- Performance under stress
    total_return NUMERIC(8,4),
    max_drawdown NUMERIC(8,4),
    sharpe NUMERIC(8,4),
    -- Kill switch behavior
    kill_triggered BOOLEAN DEFAULT false,
    kill_level_reached VARCHAR(15),
    recovery_days INT,
    -- Regime detection accuracy
    regime_accuracy NUMERIC(6,4),
    false_positive_rate NUMERIC(6,4),
    detection_lag_days INT,
    details JSONB DEFAULT '{}'
);
SELECT create_hypertable('regime_stress_results', by_range('time'), if_not_exists => true);

-- DSR (Deflated Sharpe Ratio) results
CREATE TABLE IF NOT EXISTS dsr_results (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id BIGINT REFERENCES backtest_runs(run_id),
    raw_sharpe NUMERIC(8,4),
    dsr_score NUMERIC(8,4),
    dsr_pvalue NUMERIC(8,6),
    n_trials INT,                          -- number of strategy variants tested
    skewness NUMERIC(8,4),
    kurtosis NUMERIC(8,4),
    var_sharpe NUMERIC(8,6),
    t_stat NUMERIC(8,4),
    passed BOOLEAN DEFAULT false           -- DSR > 95%?
);
SELECT create_hypertable('dsr_results', by_range('time'), if_not_exists => true);

-- Granger causality test results
CREATE TABLE IF NOT EXISTS granger_results (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id BIGINT REFERENCES backtest_runs(run_id),
    symbol VARCHAR(10),
    lag_days INT,
    f_statistic NUMERIC(10,4),
    p_value NUMERIC(8,6),
    is_significant BOOLEAN DEFAULT false,  -- p < 0.05
    direction VARCHAR(20),                 -- sentiment_leads_price, price_leads_sentiment
    details JSONB DEFAULT '{}'
);
SELECT create_hypertable('granger_results', by_range('time'), if_not_exists => true);

-- GO/STOP decision log
CREATE TABLE IF NOT EXISTS go_stop_log (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision VARCHAR(10) NOT NULL,         -- GO, STOP, PENDING
    criteria JSONB NOT NULL,
    notes TEXT,
    decided_by VARCHAR(50) DEFAULT 'system'
);

-- Weekly prices continuous aggregate (for momentum calcs)
CREATE MATERIALIZED VIEW IF NOT EXISTS weekly_prices
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 week', time) AS week,
    symbol,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume
FROM daily_prices
GROUP BY week, symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('weekly_prices',
    start_offset => interval '30 days',
    end_offset => interval '1 day',
    schedule_interval => interval '1 day',
    if_not_exists => true);
