-- §22.AO-27: swing_watchlist_alerts.direction 을 5-Layer TQM 값 집합에 맞춘다.
--
-- 문제: 테이블이 구 전략(connors_rsi2_atr) 기준으로 BUY/SELL/HOLD 3값만 허용했는데,
--       현재 전략 tqm_5layer 는 STRONG_BUY/BUY/NEUTRAL/SELL/STRONG_SELL 5값을 낸다.
--       그래서 STRONG_*/NEUTRAL 알림이 TQM 배포 이후 **전부 조용히 버려지고 있었다**
--       (2026-08-31 실측: 저장된 direction 이 SELL 152 / BUY 43 / HOLD 35 뿐).
--       insert 예외가 try 블록에 잡혀 경고 한 줄만 남고 signal_log upsert 까지 건너뛰었다.
--       → 가장 강한 매수 신호(STRONG_BUY)가 기록조차 안 됨.
--
-- 추가 함정: direction 이 VARCHAR(10) 인데 'STRONG_SELL' 은 11자다.
--            제약만 넓히면 길이에서 다시 실패하므로 컬럼도 함께 넓힌다.
--
-- 멱등(idempotent) — 여러 번 실행해도 안전.

BEGIN;

ALTER TABLE swing_watchlist_alerts
  ALTER COLUMN direction TYPE VARCHAR(16);

ALTER TABLE swing_watchlist_alerts
  DROP CONSTRAINT IF EXISTS swing_watchlist_alerts_direction_check;

-- HOLD 는 과거 35행 호환을 위해 유지한다.
ALTER TABLE swing_watchlist_alerts
  ADD CONSTRAINT swing_watchlist_alerts_direction_check
  CHECK (direction IN ('STRONG_BUY','BUY','NEUTRAL','HOLD','SELL','STRONG_SELL'));

COMMIT;

-- 검증:
--   SELECT pg_get_constraintdef(oid) FROM pg_constraint
--    WHERE conname = 'swing_watchlist_alerts_direction_check';
--   SELECT character_maximum_length FROM information_schema.columns
--    WHERE table_name='swing_watchlist_alerts' AND column_name='direction';  -- 16
