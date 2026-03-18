-- ═══════════════════════════════════════
-- User Management Migration
-- email, role, is_approved 컬럼 추가
-- ═══════════════════════════════════════

ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_approved BOOLEAN DEFAULT false;

-- 기존 admin 계정 업데이트
UPDATE users SET role = 'admin', is_approved = true WHERE username = 'admin';
