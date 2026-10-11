-- 과거 지표 소급 계산 (§22.AO-43)
-- 왜: collector.compute_indicators 는 롤링을 300일 이력으로 계산하지만 **최신 1일만** 저장한다.
--     그래서 swing_indicators 는 7개월(2026-03~10)뿐이고, 모든 백테스트가 그 창에 갇혀 있었다.
--     라이브 130건과 같은 구간이므로 **out-of-sample 검증이 한 번도 없었다.**
-- daily_prices 에는 2011-02 ~ 2026-10, 1540종목, 524만 봉이 이미 있다. 지표는 전부 가격에서 나온다.
-- 🔴 라이브 swing_indicators 는 건드리지 않는다(엔진이 get_latest_indicators 로 읽는다).
--     별도 테이블에 쓴다.

DROP TABLE IF EXISTS hist_indicators;
CREATE TABLE hist_indicators (
    time            timestamptz NOT NULL,
    symbol          varchar(10) NOT NULL,
    close           numeric(12,4),
    volume          bigint,
    sma_50          numeric(12,4),
    sma_200         numeric(12,4),
    return_20d      double precision,
    return_20d_rank double precision,   -- 날짜별 횡단면 백분위
    high_5d         numeric(12,4),
    volume_avg_20d  double precision,
    volume_ratio    double precision,
    dollar_vol_20d  double precision,   -- 유동성 — 시점 유니버스 재구성용
    trend_aligned   boolean,
    breakout_5d     boolean,
    univ_size       int,                -- 그 날짜의 횡단면 크기(폭 추적용)
    PRIMARY KEY (time, symbol)
);
SELECT create_hypertable('hist_indicators', 'time', chunk_time_interval => INTERVAL '1 year');

-- 롤링 지표: collector.compute_indicators 와 동일 정의
--   sma_50=rolling(50), sma_200=rolling(200), return_20d=pct_change(20),
--   high_5d=close.shift(1).rolling(5).max(), volume_avg_20d=rolling(20),
--   trend_aligned=(close>sma50 & sma50>sma200), breakout_5d=close>high_5d*(1-margin), margin=0
WITH roll AS (
    SELECT time, symbol, close, volume,
           avg(close)  OVER w50  AS sma_50,
           avg(close)  OVER w200 AS sma_200,
           lag(close, 20) OVER wsym AS close_20d_ago,
           max(close)  OVER w5prev AS high_5d,
           avg(volume) OVER w20 AS volume_avg_20d,
           avg(close * volume) OVER w20 AS dollar_vol_20d,
           count(*)    OVER w200cnt AS n200
    FROM daily_prices
    WINDOW wsym AS (PARTITION BY symbol ORDER BY time),
           w50  AS (PARTITION BY symbol ORDER BY time ROWS BETWEEN 49 PRECEDING AND CURRENT ROW),
           w200 AS (PARTITION BY symbol ORDER BY time ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
           w200cnt AS (PARTITION BY symbol ORDER BY time ROWS BETWEEN 199 PRECEDING AND CURRENT ROW),
           w5prev AS (PARTITION BY symbol ORDER BY time ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
           w20  AS (PARTITION BY symbol ORDER BY time ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
), base AS (
    -- sma_200 이 200봉을 다 채운 행만 — 라이브 코드도 sma_200 NaN 이면 건너뛴다
    SELECT *, (close / NULLIF(close_20d_ago, 0) - 1)::double precision AS return_20d
    FROM roll WHERE n200 >= 200 AND close_20d_ago IS NOT NULL
)
INSERT INTO hist_indicators
SELECT time, symbol, close, volume, sma_50, sma_200, return_20d,
       -- percent_rank() = (rank-1)/(n-1), 동순위는 최소순위 → 라이브의
       -- sorted_returns.index(v)/(n-1) 과 동일 정의
       percent_rank() OVER (PARTITION BY time ORDER BY return_20d) AS return_20d_rank,
       high_5d, volume_avg_20d,
       (volume / NULLIF(volume_avg_20d, 0))::double precision AS volume_ratio,
       dollar_vol_20d,
       (close > sma_50 AND sma_50 > sma_200) AS trend_aligned,
       (close > high_5d) AS breakout_5d,
       count(*) OVER (PARTITION BY time) AS univ_size
FROM base;

CREATE INDEX ON hist_indicators (symbol, time DESC);
