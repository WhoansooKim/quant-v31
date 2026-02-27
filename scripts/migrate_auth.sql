-- ═══════════════════════════════════════
-- Quant V3.1 — Authentication Migration
-- users 테이블 + 기본 admin 계정
-- ═══════════════════════════════════════

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    VARCHAR(50) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 기본 admin 계정 (password: admin123)
-- BCrypt hash generated with cost factor 12
INSERT INTO users (username, password_hash)
VALUES ('admin', '$2b$12$glJCBTyIJ2LrYCppsZ.YmO6hTAadX.bGu2RxmFoBdSVXqE8wcC5cy')
ON CONFLICT (username) DO NOTHING;
