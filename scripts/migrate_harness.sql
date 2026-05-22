-- Phase 3 Autonomous Evolution Harness — DB schema

-- ─── swing_knowledge ──────────────────────────────
-- 외부 리서치(논문/블로그/포럼/뉴스) 영구 저장
CREATE TABLE IF NOT EXISTS swing_knowledge (
    knowledge_id BIGSERIAL PRIMARY KEY,
    source_type VARCHAR(20) NOT NULL,       -- paper | blog | forum | news | seed
    source_url TEXT,
    source_name VARCHAR(100),               -- e.g. "Tetlock 2007", "Quantpedia", "Dalio All-Weather"
    title TEXT NOT NULL,
    summary TEXT,                           -- LLM-generated summary
    key_insights JSONB,                     -- ["insight1", "insight2", ...]
    strategy_hypothesis JSONB,              -- {filter: "...", entry: "...", exit: "..."}
    applicability_score INT DEFAULT 50,     -- 0-100 (LLM judges relevance to our system)
    regime_relevance VARCHAR(20),           -- BULL | BEAR | SIDEWAYS | ALL
    tags TEXT[],                            -- ['momentum', 'mean-reversion', 'sentiment', ...]
    tested BOOLEAN DEFAULT FALSE,
    backtest_run_id BIGINT,                 -- FK to swing_backtest_runs when tested
    source_tier NUMERIC(3,2) DEFAULT 0.5,   -- 1.0 Reuters/SEC, 0.6 Finnhub, 0.3 blog
    published_at TIMESTAMPTZ,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_source_type ON swing_knowledge(source_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_regime ON swing_knowledge(regime_relevance);
CREATE INDEX IF NOT EXISTS idx_knowledge_collected ON swing_knowledge(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_knowledge_applicability ON swing_knowledge(applicability_score DESC);


-- ─── swing_strategy_variants ────────────────────
-- LLM이 생성한 전략 변이 — 백테스트 후 자동 배포 여부 결정
CREATE TABLE IF NOT EXISTS swing_strategy_variants (
    variant_id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    config_diff JSONB NOT NULL,             -- {key: new_value} — only fields that differ from baseline
    based_on_knowledge_ids BIGINT[],        -- swing_knowledge refs that inspired this variant
    based_on_baseline_run_id BIGINT,        -- which backtest is the baseline

    -- Generation context
    generated_by VARCHAR(20),               -- "claude" | "ollama" | "manual"
    generation_prompt TEXT,
    generation_reasoning TEXT,

    -- Validation
    status VARCHAR(20) DEFAULT 'pending',   -- pending | testing | validated | rejected | deployed | rolled_back
    backtest_90d_run_id BIGINT,
    backtest_180d_run_id BIGINT,
    backtest_365d_run_id BIGINT,
    baseline_sqn DOUBLE PRECISION,
    variant_sqn DOUBLE PRECISION,
    baseline_sharpe DOUBLE PRECISION,
    variant_sharpe DOUBLE PRECISION,
    sqn_delta DOUBLE PRECISION,
    sharpe_delta DOUBLE PRECISION,
    rejection_reason TEXT,

    -- Deployment
    deployed_at TIMESTAMPTZ,
    rollback_at TIMESTAMPTZ,
    rollback_reason TEXT,
    trades_under_variant INT DEFAULT 0,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_variants_status ON swing_strategy_variants(status);
CREATE INDEX IF NOT EXISTS idx_variants_created ON swing_strategy_variants(created_at DESC);


-- ─── swing_harness_log ───────────────────────────
-- 모든 자율 동작 감사 로그 (research, generate, backtest, deploy, rollback, regime_switch)
CREATE TABLE IF NOT EXISTS swing_harness_log (
    log_id BIGSERIAL PRIMARY KEY,
    action VARCHAR(50) NOT NULL,            -- e.g. "research_collect", "variant_generated", "auto_deployed"
    status VARCHAR(20) NOT NULL,            -- "started" | "completed" | "failed"
    details JSONB,
    related_knowledge_id BIGINT,
    related_variant_id BIGINT,
    error_msg TEXT,
    elapsed_sec NUMERIC(8,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_harness_log_action ON swing_harness_log(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_harness_log_created ON swing_harness_log(created_at DESC);


-- ─── Admin RBAC for /harness ──
INSERT INTO user_role_permissions (role, page_path) VALUES ('admin', '/harness')
    ON CONFLICT DO NOTHING;


-- ─── Config keys for harness ──
INSERT INTO swing_config (key, value, category, description, updated_at) VALUES
  ('harness_research_enabled', 'true', 'harness', '주간 자율 리서치 활성화', NOW()),
  ('harness_variant_gen_enabled', 'false', 'harness', '월간 변이 생성기 활성화 (Week 3 활성화)', NOW()),
  ('harness_auto_deploy_enabled', 'false', 'harness', '자동 배포 활성화 (Week 4 활성화). Live는 절대 자동 안 됨', NOW()),
  ('harness_regime_switch_enabled', 'false', 'harness', '매크로 자동 전환 활성화 (Week 2 활성화)', NOW()),
  ('harness_sqn_delta_min', '0.3', 'harness', '변이 통과 SQN 최소 개선 폭', NOW()),
  ('harness_sharpe_delta_min', '0.2', 'harness', '변이 통과 Sharpe 최소 개선 폭', NOW()),
  ('harness_min_backtest_trades', '30', 'harness', '변이 통과 위한 최소 백테스트 거래 수', NOW()),
  ('harness_rollback_consecutive_losses', '5', 'harness', '연속 손실 자동 롤백 임계값', NOW()),
  ('harness_rollback_sqn_drop', '0.5', 'harness', 'SQN 악화 시 자동 롤백 임계값', NOW())
ON CONFLICT (key) DO UPDATE SET
  value = EXCLUDED.value, description = EXCLUDED.description, updated_at = NOW();
