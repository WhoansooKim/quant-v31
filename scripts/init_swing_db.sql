-- ============================================================
-- Swing Trading System — DB Schema
-- 기존 quantdb에 swing_ 접두어 테이블 추가
-- daily_prices 재사용, 나머지 신규
-- ============================================================

-- TimescaleDB (이미 활성화되어 있지만 안전하게)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ─── 1. swing_universe: 종목 유니버스 (200개) ───
CREATE TABLE IF NOT EXISTS swing_universe (
    symbol        VARCHAR(10) PRIMARY KEY,
    company_name  VARCHAR(200),
    sector        VARCHAR(50),
    market_cap    NUMERIC(18,2),
    index_member  VARCHAR(20),       -- 'SP500', 'NDX100', 'BOTH'
    is_active     BOOLEAN DEFAULT true,
    added_at      TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_swing_universe_active
    ON swing_universe (is_active) WHERE is_active = true;

-- ─── 2. swing_indicators: 기술지표 (hypertable) ───
CREATE TABLE IF NOT EXISTS swing_indicators (
    time            TIMESTAMPTZ NOT NULL,
    symbol          VARCHAR(10) NOT NULL,
    close           NUMERIC(12,4),
    sma_50          NUMERIC(12,4),
    sma_200         NUMERIC(12,4),
    return_20d      NUMERIC(10,6),       -- 20일 수익률
    return_20d_rank NUMERIC(5,4),        -- 유니버스 내 백분위 (0~1)
    high_5d         NUMERIC(12,4),       -- 최근 5일 최고가
    volume          BIGINT,
    volume_avg_20d  NUMERIC(18,2),       -- 20일 평균 거래량
    volume_ratio    NUMERIC(8,4),        -- 당일/20일평균
    trend_aligned   BOOLEAN,             -- Close > SMA50 > SMA200
    breakout_5d     BOOLEAN,             -- Close > high_5d(전일까지)
    volume_surge    BOOLEAN,             -- volume_ratio > 1.5
    UNIQUE(time, symbol)
);

SELECT create_hypertable('swing_indicators', by_range('time'),
       if_not_exists => true);

ALTER TABLE swing_indicators SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('swing_indicators', interval '30 days',
       if_not_exists => true);

CREATE INDEX IF NOT EXISTS idx_swing_indicators_symbol_time
    ON swing_indicators (symbol, time DESC);

-- ─── 3. swing_signals: 시그널 + 승인 워크플로우 (hypertable) ───
CREATE TABLE IF NOT EXISTS swing_signals (
    signal_id       BIGSERIAL,
    time            TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol          VARCHAR(10) NOT NULL,
    signal_type     VARCHAR(10) NOT NULL,      -- 'ENTRY' / 'EXIT'
    entry_price     NUMERIC(12,4),
    stop_loss       NUMERIC(12,4),             -- -5%
    take_profit     NUMERIC(12,4),             -- +10%
    return_20d_rank NUMERIC(5,4),              -- 조건1 점수
    trend_aligned   BOOLEAN,                   -- 조건2
    breakout_5d     BOOLEAN,                   -- 조건3
    volume_surge    BOOLEAN,                   -- 조건4
    exit_reason     VARCHAR(20),               -- EXIT: stop_loss/take_profit/trend_break
    position_id     BIGINT,
    status          VARCHAR(15) DEFAULT 'pending',
                    -- pending → approved → executed
                    -- pending → rejected / expired
    approved_at     TIMESTAMPTZ,
    executed_at     TIMESTAMPTZ,
    PRIMARY KEY (signal_id, time)
);

SELECT create_hypertable('swing_signals', by_range('time'),
       if_not_exists => true);

CREATE INDEX IF NOT EXISTS idx_swing_signals_status
    ON swing_signals (status, time DESC);
CREATE INDEX IF NOT EXISTS idx_swing_signals_symbol
    ON swing_signals (symbol, time DESC);

-- ─── 4. swing_positions: 오픈/청산 포지션 ───
CREATE TABLE IF NOT EXISTS swing_positions (
    position_id   BIGSERIAL PRIMARY KEY,
    symbol        VARCHAR(10) NOT NULL,
    side          VARCHAR(5) DEFAULT 'BUY',
    qty           NUMERIC(12,4) NOT NULL,
    entry_price   NUMERIC(12,4) NOT NULL,
    entry_time    TIMESTAMPTZ NOT NULL DEFAULT now(),
    stop_loss     NUMERIC(12,4),
    take_profit   NUMERIC(12,4),
    current_price NUMERIC(12,4),
    unrealized_pnl NUMERIC(12,4),
    unrealized_pct NUMERIC(8,4),
    status        VARCHAR(10) DEFAULT 'open',   -- open / closed
    exit_price    NUMERIC(12,4),
    exit_time     TIMESTAMPTZ,
    exit_reason   VARCHAR(20),
    realized_pnl  NUMERIC(12,4),
    realized_pct  NUMERIC(8,4),
    hold_days     INT,
    signal_id     BIGINT,
    is_paper      BOOLEAN DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_swing_positions_status
    ON swing_positions (status) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_swing_positions_symbol
    ON swing_positions (symbol, status);

-- ─── 5. swing_trades: 체결 로그 ───
CREATE TABLE IF NOT EXISTS swing_trades (
    trade_id      BIGSERIAL PRIMARY KEY,
    position_id   BIGINT REFERENCES swing_positions(position_id),
    signal_id     BIGINT,
    symbol        VARCHAR(10) NOT NULL,
    side          VARCHAR(5) NOT NULL,          -- BUY / SELL
    qty           NUMERIC(12,4) NOT NULL,
    price         NUMERIC(12,4) NOT NULL,
    total_amount  NUMERIC(14,4),               -- qty * price
    order_id      VARCHAR(50),                 -- KIS 주문번호
    commission    NUMERIC(10,4) DEFAULT 0,
    is_paper      BOOLEAN DEFAULT true,
    executed_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_swing_trades_position
    ON swing_trades (position_id);
CREATE INDEX IF NOT EXISTS idx_swing_trades_time
    ON swing_trades (executed_at DESC);

-- ─── 6. swing_snapshots: 일별 포트폴리오 스냅샷 (hypertable) ───
CREATE TABLE IF NOT EXISTS swing_snapshots (
    time              TIMESTAMPTZ NOT NULL DEFAULT now(),
    total_value_usd   NUMERIC(14,4),
    total_value_krw   NUMERIC(18,2),
    cash_usd          NUMERIC(14,4),
    invested_usd      NUMERIC(14,4),
    daily_pnl_usd     NUMERIC(12,4),
    daily_return       NUMERIC(10,6),
    cumulative_return  NUMERIC(10,6),
    max_drawdown       NUMERIC(10,6),
    open_positions     INT DEFAULT 0,
    exchange_rate      NUMERIC(10,2),            -- USD/KRW
    UNIQUE(time)
);

SELECT create_hypertable('swing_snapshots', by_range('time'),
       if_not_exists => true);

-- ─── 7. swing_config: 런타임 설정 ───
CREATE TABLE IF NOT EXISTS swing_config (
    key           VARCHAR(50) PRIMARY KEY,
    value         VARCHAR(200) NOT NULL,
    category      VARCHAR(30) NOT NULL,          -- strategy/risk/execution/notify
    description   VARCHAR(300),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- 기본 설정값 삽입
INSERT INTO swing_config (key, value, category, description) VALUES
    -- Strategy
    ('sma_short',        '50',     'strategy',  'Short SMA period'),
    ('sma_long',         '200',    'strategy',  'Long SMA period'),
    ('return_period',    '20',     'strategy',  'Momentum return lookback days'),
    ('return_rank_min',  '0.6',    'strategy',  'Min 20d return percentile (top 40%)'),
    ('breakout_days',    '5',      'strategy',  'Breakout lookback days'),
    ('volume_ratio_min', '1.5',    'strategy',  'Min volume ratio for surge'),
    -- Risk
    ('stop_loss_pct',    '-0.05',  'risk',      'Stop loss percentage'),
    ('take_profit_pct',  '0.10',   'risk',      'Take profit percentage'),
    ('max_positions',    '4',      'risk',      'Max concurrent positions'),
    ('position_pct',     '0.05',   'risk',      'Position size as % of account'),
    ('max_daily_entries', '1',     'risk',      'Max new entries per day'),
    -- Execution
    ('trading_mode',     'paper',  'execution', 'paper or live'),
    ('price_range_min',  '20',     'execution', 'Min stock price ($)'),
    ('price_range_max',  '80',     'execution', 'Max stock price ($)'),
    ('signal_expiry_hours', '24',  'execution', 'Hours before signal expires'),
    -- Notification
    ('telegram_enabled', 'true',   'notify',    'Enable Telegram alerts'),
    ('daily_summary',    'true',   'notify',    'Send daily P&L summary')
ON CONFLICT (key) DO NOTHING;

-- ─── 8. swing_backtest_runs: 백테스트 결과 ───
CREATE TABLE IF NOT EXISTS swing_backtest_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    initial_capital NUMERIC(14,4),
    final_value     NUMERIC(14,4),
    total_return    NUMERIC(10,6),
    cagr            NUMERIC(10,6),
    max_drawdown    NUMERIC(10,6),
    sharpe_ratio    NUMERIC(8,4),
    win_rate        NUMERIC(6,4),
    total_trades    INT,
    profit_factor   NUMERIC(8,4),
    avg_hold_days   NUMERIC(6,1),
    params          JSONB DEFAULT '{}',
    equity_curve    JSONB DEFAULT '[]',
    trades_log      JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ─── 9. swing_pipeline_log: 파이프라인 실행 로그 ───
CREATE TABLE IF NOT EXISTS swing_pipeline_log (
    log_id       BIGSERIAL PRIMARY KEY,
    step_name    VARCHAR(50) NOT NULL,
    status       VARCHAR(20) NOT NULL,    -- started/completed/failed
    elapsed_sec  NUMERIC(8,2),
    details      JSONB DEFAULT '{}',
    error_msg    TEXT,
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_swing_pipeline_log_time
    ON swing_pipeline_log (created_at DESC);

-- ============================================================
-- Done. Run: psql -U quant -d quantdb -f scripts/init_swing_db.sql
-- ============================================================
