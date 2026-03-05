-- User settings (투자금 등)
CREATE TABLE IF NOT EXISTS user_settings (
    user_id INT PRIMARY KEY REFERENCES users(id),
    initial_capital NUMERIC(18,2) NOT NULL DEFAULT 100000.00,
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO user_settings (user_id, initial_capital)
SELECT id, 100000.00 FROM users ON CONFLICT DO NOTHING;
