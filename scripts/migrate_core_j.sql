-- §22.AO-71 코어 70% + J 30% (사용자 결정 2026-11-18) + 섀도 기록(core_only · b_offJ)
-- Run: docker exec -i quant-postgres psql -U quant -d quantdb < scripts/migrate_core_j.sql
BEGIN;
INSERT INTO swing_config (key, value, category, description) VALUES
 ('core_j_weight', '0.3', 'core', 'J 슬리브 비중(0=끔). 나머지는 추세 코어 (§22.AO-71)'),
 ('core_j_k', '10', 'core', 'J 보유 종목 수'),
 ('core_j_hold_rank', '30', 'core', 'J 보유 유지 순위 한도(밴드)'),
 ('core_j_min_dv', '20000000', 'core', 'J 적격: 50일 평균 거래대금 하한(USD)'),
 ('core_j_min_px', '10', 'core', 'J 적격: 종가 하한(USD)'),
 ('core_j_last_rebal', '', 'core', 'J 마지막 교체 월(YYYY-MM, 미국 동부). 빈 값이면 다음 실행에 교체'),
 ('core_j_ranking', '', 'core', 'J 마지막 순위(JSON, 상위 hold_rank)')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS core_shadow (
    time      TIMESTAMPTZ NOT NULL DEFAULT now(),
    variant   TEXT        NOT NULL,      -- core_only | b_offJ
    equity    NUMERIC     NOT NULL,
    frac      NUMERIC     NOT NULL,      -- 추세 on 비율
    holdings  JSONB       NOT NULL,      -- {심볼: 수량, _cash: 현금}
    details   JSONB
);
SELECT create_hypertable('core_shadow', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_core_shadow_variant ON core_shadow (variant, time DESC);
COMMIT;
