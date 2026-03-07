-- Phase B: Exit Strategy Enhancement — trailing stop + partial exit
-- 실행: docker exec quant-postgres psql -U quant -d quantdb -f /tmp/migrate_exit_strategy.sql

ALTER TABLE swing_positions
  ADD COLUMN IF NOT EXISTS partial_exited BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS trailing_stop_active BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS high_water_mark NUMERIC(12,4);

COMMENT ON COLUMN swing_positions.partial_exited IS 'True if partial exit (50%) has been executed';
COMMENT ON COLUMN swing_positions.trailing_stop_active IS 'True if trailing stop is activated (+5% gain)';
COMMENT ON COLUMN swing_positions.high_water_mark IS 'Highest price since entry (for trailing stop calc)';

INSERT INTO swing_config (key, value, category, description) VALUES
  ('trailing_stop_activation', '0.05', 'exit', 'Trailing stop activates at this gain % (e.g. 0.05 = +5%)'),
  ('trailing_stop_distance', '0.03', 'exit', 'Trailing stop distance from high water mark (e.g. 0.03 = -3%)'),
  ('partial_exit_threshold', '0.07', 'exit', 'Partial exit triggers at this gain % (e.g. 0.07 = +7%)'),
  ('partial_exit_pct', '0.5', 'exit', 'Fraction of position to close on partial exit (0.5 = 50%)')
ON CONFLICT (key) DO NOTHING;
