-- §22.AO-37: 승인 경로 기록. 지금까지는 승인 시각으로 추정해야 했다
--   (auto_approve 는 22:00/01:30/04:30 KST 정시에만 도는 성질을 이용).
--   측정할 수 없으면 관리할 수 없다 — 경로를 직접 남긴다.
--   값: 'auto'(스케줄 게이트 통과) | 'manual'(수동 승인, 게이트 통과)
--       | 'manual_force'(수동 승인, 게이트 탈락인데 강제) | NULL(기록 전 과거분)
ALTER TABLE swing_signals ADD COLUMN IF NOT EXISTS approved_via VARCHAR(16);

COMMENT ON COLUMN swing_signals.approved_via IS
  '승인 경로: auto | manual | manual_force (§22.AO-37). NULL 은 기록 도입 전 과거분';

CREATE INDEX IF NOT EXISTS idx_swing_signals_approved_via
    ON swing_signals (approved_via) WHERE approved_via IS NOT NULL;
