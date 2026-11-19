-- 2026-11-19 §22.AO-71 첫 J 편입 후속: swing_config.value VARCHAR(200) → TEXT.
-- core_j_ranking(상위 30 순위 + 점수 JSON, 약 1.2KB)이 200자를 넘어 _after_orders 가 주문 뒤 실패했다
-- (core_shadow 미기록 · 텔레그램 미발송 · pipeline_log details 누락). 주문 자체와 core_j_last_rebal 은 정상 기록됨.
ALTER TABLE swing_config ALTER COLUMN value TYPE TEXT;
