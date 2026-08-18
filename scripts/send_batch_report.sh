#!/usr/bin/env bash
# 변이 검증 배치 결과 → Telegram 요약 발송 (§22.AO 후속)
set -uo pipefail
cd /home/quant/quant-v31

TOKEN=$(grep TELEGRAM_BOT_TOKEN .env | cut -d= -f2 | tr -d '"'"'"'' | xargs)
CHAT=$(grep TELEGRAM_CHAT_ID .env | cut -d= -f2 | tr -d '"'"'"'' | xargs)

PSQL=(docker exec quant-postgres psql -U quant -d quantdb -tAc)

VALIDATED=$("${PSQL[@]}" "SELECT COALESCE(string_agg('  • v' || variant_id || ' ' || name || ' (SQNd ' || to_char(COALESCE(sqn_delta,0),'FMS9990.999') || ', Sharped ' || to_char(COALESCE(sharpe_delta,0),'FMS9990.999') || ')', E'\n' ORDER BY variant_id), '  (없음)') FROM swing_strategy_variants WHERE status='validated';")
COUNTS=$("${PSQL[@]}" "SELECT string_agg(format('%s %s', status, n), ' / ' ORDER BY status) FROM (SELECT status, COUNT(*) n FROM swing_strategy_variants GROUP BY status) t;")
ZERO=$("${PSQL[@]}" "SELECT COUNT(*) FROM swing_strategy_variants WHERE rejection_reason LIKE 'sqn_delta=0.0%';")
INCONS=$("${PSQL[@]}" "SELECT COUNT(*) FROM swing_strategy_variants WHERE rejection_reason='inconsistent_across_periods';")
DONE=$(grep -c '\[INFO\] validate_pending: \[' scripts/validate_pending_variants.log || echo 0)
ELAPSED=$(grep '=== 완료' scripts/validate_pending_variants.log | tail -1 | sed 's/.*총 //')

TEXT=$(cat <<MSG
<b>🧪 변이 검증 배치 완료</b>  (${DONE}/23건, ${ELAPSED:-진행중})

<b>✅ 통과</b>
${VALIDATED}

<b>📊 전체</b>  ${COUNTS}
 · Δ0.0 측정불가: ${ZERO}건
 · 구간 비일관 기각: ${INCONS}건

<b>🔍 핵심</b>
· 기존 validated 2건(v17·v18)은 <b>낡은 baseline이 만든 허상</b> — 라이브 정합 후 전부 기각. v18은 SharpeΔ +0.99 → −0.42로 역전. <b>배포 보류가 옳았음</b>
· 집중 사이징 계열 6건 전부 기각 — SQN은 거래수 증가로 부풀고 Sharpe는 음수. <b>7/28 20개×5% 분산 정책 유지 근거</b>
· 무력 키 발견: atr_trailing_multiplier / rsi2_exit_threshold / take_profit_pct / stop_loss_pct → 백테스트가 측정 못 함

<b>⚠️ 한계</b>
진입 선별이 라이브(6팩터)와 다름(돌파규칙) → <b>절대 수익률은 예측치 아님</b>, 상대 비교용

<b>▶️ 다음</b>
고정손절 폴백 복원 → 영향 변이 재평가 → rsi2 min_r 게이트 실험
MSG
)

curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" -d parse_mode=HTML \
  --data-urlencode text="${TEXT}" | python3 -c "import sys,json;d=json.load(sys.stdin);print('telegram sent:', d.get('ok'))"
