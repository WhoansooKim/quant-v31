-- Pipeline Log — 파이프라인/스케줄러 실행 기록
CREATE TABLE IF NOT EXISTS pipeline_log (
    id BIGSERIAL,
    time TIMESTAMPTZ NOT NULL DEFAULT now(),
    job_type VARCHAR(30) NOT NULL,   -- 'daily_pipeline','data_collection','sentiment_scan','hmm_retrain','mv_refresh'
    status VARCHAR(20) NOT NULL,     -- 'started','completed','failed'
    duration_sec DOUBLE PRECISION,
    details JSONB,
    error_msg TEXT,
    PRIMARY KEY (id, time)
);
SELECT create_hypertable('pipeline_log', 'time', if_not_exists => TRUE);
