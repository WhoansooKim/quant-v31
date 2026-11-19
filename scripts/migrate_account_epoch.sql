-- 2026-11-19 사용자 결정: 원금 $2,000 으로 재시작(account epoch).
-- 직전 총자산 $1,647.65 → 입금 $352.35(swing_capital_events event 4) 로 $2,000 보충.
-- 재시작 전 누적: 실현 −$179.30(스윙 142건 −$139.89 · 코어 5건 −$39.41) · 수수료 −$99.93 · 미실현 −$73.11
--                 = trading_pnl −$352.35. 장부는 그대로, 수익률·낙폭만 이 시점을 0 으로 잰다(storage.get_account_basis).
-- account_epoch_time 은 엔진 재시작 뒤 설정(구 코드 스냅샷이 기준점 뒤에 섞이지 않도록).
INSERT INTO swing_config (key, value, category, description) VALUES
  ('account_epoch_pnl', '-352.35', 'strategy', '재시작 시점 누적 trading_pnl — 수익률 0 기준'),
  ('account_epoch_capital', '2000', 'strategy', '재시작 원금 — 수익률 분모'),
  ('account_epoch_time', '', 'strategy', '재시작 시각(ISO, tz) — 이후 스냅샷만 낙폭 계산')
ON CONFLICT (key) DO NOTHING;
