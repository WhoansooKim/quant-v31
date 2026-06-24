-- 집중 리스크 캡 (Concentration Cap) — 소액계좌 고가주 과집중 차단
-- 배경: $1000 계좌에서 QCOM($226) 등 고가주가 `if qty<=0: qty=1` 강제로 1주 진입 →
--       단일 종목 24% 과집중 → -9% 갭 한 방이 포트 -2%. 과거 33거래 중 entry>$200 3건이
--       전부 손실(-$37.45)로 전체 순손실(-$25.34)을 초과. 이들 제거 시 +$12.12 흑자 전환.
-- 캡: 1) 리스크(스톱거리) 2) 단일종목 명목 3) 총노출. 1주조차 캡 초과면 진입 거부.
INSERT INTO swing_config (key, value, category, description) VALUES
    ('concentration_cap_enabled', 'true', 'risk', '집중 리스크 캡 활성화 (리스크/명목/총노출 3중 한도)'),
    ('max_position_pct_cap',      '0.20', 'risk', '단일 종목 명목가치 상한 (계좌 대비) — 1주가 초과하면 진입 거부'),
    ('max_risk_per_trade_pct',    '0.015','risk', '거래당 최대 리스크 (스톱거리×수량 / 계좌)'),
    ('max_total_exposure_pct',    '0.90', 'risk', '전체 포지션 명목가치 합 상한 (계좌 대비)')
    ON CONFLICT (key) DO NOTHING;
