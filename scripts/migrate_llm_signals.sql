-- Phase A-1: LLM Sentiment Overlay — swing_signals에 AI 분석 컬럼 추가
-- 실행: docker exec quant-postgres psql -U quant -d quantdb -f /tmp/migrate_llm_signals.sql

ALTER TABLE swing_signals
  ADD COLUMN IF NOT EXISTS llm_score INTEGER,
  ADD COLUMN IF NOT EXISTS llm_analysis TEXT,
  ADD COLUMN IF NOT EXISTS llm_analyzed_at TIMESTAMPTZ;

COMMENT ON COLUMN swing_signals.llm_score IS 'AI sentiment score 1-10 (10=strongest buy)';
COMMENT ON COLUMN swing_signals.llm_analysis IS 'LLM analysis JSON: reasoning, news summary, risk factors';
COMMENT ON COLUMN swing_signals.llm_analyzed_at IS 'When AI analysis was performed';
