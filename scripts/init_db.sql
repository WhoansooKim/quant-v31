-- TimescaleDB 활성화
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 종목 마스터
CREATE TABLE symbols (
    symbol_id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL UNIQUE,
    company_name VARCHAR(200),
    sector VARCHAR(50),
    industry VARCHAR(100),
    market_cap NUMERIC(18,2),
    exchange VARCHAR(10),
    is_active BOOLEAN DEFAULT true,
    meta JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_symbols_sector ON symbols(sector);

-- 일봉 가격 (Hypertable)
CREATE TABLE daily_prices (
    time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    open NUMERIC(12,4),
    high NUMERIC(12,4),
    low NUMERIC(12,4),
    close NUMERIC(12,4),
    volume BIGINT,
    adj_close NUMERIC(12,4),
    UNIQUE(time, symbol)
);
SELECT create_hypertable('daily_prices', by_range('time'));

-- 자동 압축 (30일 후)
ALTER TABLE daily_prices SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('daily_prices', interval '30 days');

-- 레짐 히스토리 (Hypertable)
CREATE TABLE regime_history (
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    regime VARCHAR(10),
    bull_prob NUMERIC(5,4),
    sideways_prob NUMERIC(5,4),
    bear_prob NUMERIC(5,4),
    confidence NUMERIC(5,4),
    previous_regime VARCHAR(10),
    is_transition BOOLEAN DEFAULT false
);
SELECT create_hypertable('regime_history', by_range('detected_at'));

-- Kill Switch 로그
CREATE TABLE kill_switch_log (
    event_time TIMESTAMPTZ NOT NULL DEFAULT now(),
    from_level VARCHAR(15),
    to_level VARCHAR(15),
    current_mdd NUMERIC(6,4),
    portfolio_value NUMERIC(18,2),
    exposure_limit NUMERIC(4,2),
    cooldown_until TIMESTAMPTZ
);
SELECT create_hypertable('kill_switch_log', by_range('event_time'));

-- 포트폴리오 스냅샷 (Hypertable)
CREATE TABLE portfolio_snapshots (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_value NUMERIC(18,2),
    cash_value NUMERIC(18,2),
    daily_return NUMERIC(10,6),
    cumulative_return NUMERIC(10,6),
    sharpe_ratio NUMERIC(6,4),
    max_drawdown NUMERIC(6,4),
    vol_scale NUMERIC(4,2),
    regime VARCHAR(10),
    regime_confidence NUMERIC(4,3),
    kill_level VARCHAR(15),
    exposure_limit NUMERIC(4,2)
);
SELECT create_hypertable('portfolio_snapshots', by_range('time'));

-- 센티먼트 스코어 (Hypertable)
CREATE TABLE sentiment_scores (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol VARCHAR(10),
    finbert_score NUMERIC(5,3),
    claude_score NUMERIC(5,3),
    hybrid_score NUMERIC(5,3),
    source VARCHAR(20),
    headline_count INT
);
SELECT create_hypertable('sentiment_scores', by_range('time'));

-- 거래 기록
CREATE TABLE trades (
    trade_id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(50),
    symbol VARCHAR(10),
    strategy VARCHAR(50),
    side VARCHAR(5),
    qty NUMERIC(12,4),
    price NUMERIC(12,4),
    regime VARCHAR(10),
    kill_level VARCHAR(15),
    executed_at TIMESTAMPTZ DEFAULT now(),
    is_paper BOOLEAN DEFAULT true
);

-- 전략별 성과 (Hypertable)
CREATE TABLE strategy_performance (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    strategy VARCHAR(50),
    daily_return NUMERIC(10,6),
    allocation NUMERIC(4,2),
    regime VARCHAR(10),
    signal_count INT,
    win_rate NUMERIC(4,2)
);
SELECT create_hypertable('strategy_performance', by_range('time'));

-- 시그널 로그
CREATE TABLE signal_log (
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol VARCHAR(10),
    direction VARCHAR(10),
    strength NUMERIC(6,3),
    strategy VARCHAR(50),
    regime VARCHAR(10)
);
SELECT create_hypertable('signal_log', by_range('time'));

-- 재무 데이터
CREATE TABLE fundamentals (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10),
    report_date DATE DEFAULT CURRENT_DATE,
    market_cap NUMERIC(18,2),
    roe NUMERIC(8,4),
    revenue_growth NUMERIC(8,4),
    eps NUMERIC(10,4),
    debt_to_equity NUMERIC(8,4),
    free_cashflow NUMERIC(18,2),
    gross_margin NUMERIC(8,4),
    beta NUMERIC(6,4),
    extra JSONB DEFAULT '{}',
    UNIQUE(ticker, report_date)
);

-- 공적분 페어즈
CREATE TABLE cointegrated_pairs (
    pair_id SERIAL PRIMARY KEY,
    symbol1 VARCHAR(10),
    symbol2 VARCHAR(10),
    p_value NUMERIC(8,6),
    spread_zscore NUMERIC(6,2),
    is_active BOOLEAN DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(symbol1, symbol2)
);

-- 확인용 쿼리
SELECT 'TimescaleDB version: ' || extversion FROM pg_extension WHERE extname='timescaledb';
SELECT 'Tables: ' || count(*)::text FROM information_schema.tables WHERE table_schema='public';
