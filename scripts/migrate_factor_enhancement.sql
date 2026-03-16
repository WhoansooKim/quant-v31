-- Tier 1: Factor Enhancement Migration
-- Quality + Value 팩터 컬럼 추가 + 새 가중치 설정

-- 1. swing_signals에 새 팩터 점수 컬럼
ALTER TABLE swing_signals
  ADD COLUMN IF NOT EXISTS quality_score FLOAT,
  ADD COLUMN IF NOT EXISTS value_score FLOAT;

-- 2. swing_config에 새 가중치 + 레짐 적응 설정
INSERT INTO swing_config (key, value) VALUES
  ('factor_weight_quality', '0.2'),
  ('factor_weight_value', '0.2'),
  ('regime_adaptive_weights', 'true'),
  ('factor_momentum_enabled', 'true')
ON CONFLICT (key) DO NOTHING;

-- 3. 기존 가중치 조정 (T40+S30+F30 → T30+S20+F10+Q20+V20)
UPDATE swing_config SET value = '0.3' WHERE key = 'factor_weight_technical';
UPDATE swing_config SET value = '0.2' WHERE key = 'factor_weight_sentiment';
UPDATE swing_config SET value = '0.1' WHERE key = 'factor_weight_flow';
