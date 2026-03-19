-- Migration: 5-Layer Auto-Exit Strategy (ATR-based)
-- Adds columns for ATR tracking + time stop + RSI override

-- 1. swing_positions: 새 컬럼 추가
ALTER TABLE swing_positions
  ADD COLUMN IF NOT EXISTS atr_14 NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS entry_atr NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS hard_stop NUMERIC(12,4),
  ADD COLUMN IF NOT EXISTS auto_exit BOOLEAN DEFAULT false;

COMMENT ON COLUMN swing_positions.atr_14 IS 'ATR(14) at entry — used for ATR-based stops';
COMMENT ON COLUMN swing_positions.entry_atr IS 'ATR at time of entry (snapshot for R calculation)';
COMMENT ON COLUMN swing_positions.hard_stop IS 'Hard stop-loss price (1.5×ATR below entry)';
COMMENT ON COLUMN swing_positions.auto_exit IS 'True if this position was auto-exited (no manual approval)';

-- 2. swing_config: 새 설정 키 추가
INSERT INTO swing_config (key, value, category, description) VALUES
  ('auto_sell_enabled', 'true', 'exit', 'Enable automatic sell execution (no approval needed)'),
  ('atr_trailing_multiplier', '2.5', 'exit', 'ATR multiplier for trailing stop (2.5×ATR from HWM)'),
  ('atr_hard_stop_multiplier', '1.5', 'exit', 'ATR multiplier for hard stop-loss (1.5×ATR below entry)'),
  ('time_stop_days', '15', 'exit', 'Max trading days before forced exit (time stop)'),
  ('rsi2_exit_threshold', '90', 'exit', 'RSI(2) > this triggers immediate exit (sell on strength)'),
  ('atr_regime_high_vol', '3.0', 'exit', 'ATR trailing multiplier in high-volatility regime'),
  ('atr_regime_low_vol', '2.0', 'exit', 'ATR trailing multiplier in low-volatility regime'),
  ('atr_trailing_activation_r', '1.0', 'exit', 'Trailing activates after +1R profit (R = entry_atr)')
ON CONFLICT (key) DO NOTHING;
