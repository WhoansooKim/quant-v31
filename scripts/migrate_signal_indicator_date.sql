-- §22.AO-62 중복 ENTRY 가드: 시그널이 "어느 봉에서 나왔는지" 를 기록한다.
--
-- 왜: daily_pipeline 이 하루 3회(07:00 장후 / 21:30 장전 / 02:00 장중) 돌면서
--     scan_entries 를 매번 호출한다. 같은 지표 봉으로 같은 종목 시그널이 반복 생성됐다 —
--     2026-07-28 BAC 는 5회(00:12/00:20/05:00/09:54/12:30), 5번째가 체결됐다.
--     🔴 이것은 장부 문제가 아니라 **게이트를 하루에 3~5번 다시 굴리는 것**이다.
--     rank 0.92 경계 아래 종목이 하루에 여러 번 기회를 얻는다(다중비교).
--
-- 날짜(time::date)로 묶을 수 없는 이유: 22:00 UTC 와 다음날 12:30 UTC 스캔이 **같은**
--     지표 봉(금요일 종가)을 쓴다. UTC 날짜가 달라 중복으로 안 잡힌다. 그래서 봉 날짜를 쓴다.
--
-- 유니크 인덱스를 못 쓰는 이유: swing_signals 는 하이퍼테이블이고 유니크 인덱스는
--     파티션 키(time) 포함을 강제한다 → (symbol, indicator_date) 불변식을 DB 에서 못 건다.
--     그래서 가드는 scan_entries **한 곳**에 둔다(세 호출부가 모두 이 함수를 지난다, §22.AO-37).

ALTER TABLE swing_signals ADD COLUMN IF NOT EXISTS indicator_date date;

COMMENT ON COLUMN swing_signals.indicator_date IS
  '§22.AO-62 이 시그널을 만든 swing_indicators 봉의 날짜. 같은 봉+같은 종목 재생성 차단용.';

-- 소급: 각 ENTRY 행에 그 시각 이전의 가장 최근 지표 봉 날짜를 채운다.
-- (배포 직후 첫 스캔에서 기존 행이 NULL 이라 가드를 못 걸고 한 번 중복되는 것을 막는다)
UPDATE swing_signals s SET indicator_date = b.d
FROM (SELECT DISTINCT time::date d FROM swing_indicators) b
WHERE s.indicator_date IS NULL AND s.signal_type = 'ENTRY'
  AND b.d = (SELECT max(i.time::date) FROM swing_indicators i WHERE i.time <= s.time);

CREATE INDEX IF NOT EXISTS idx_swing_signals_bar
  ON swing_signals (indicator_date, symbol) WHERE signal_type = 'ENTRY';
