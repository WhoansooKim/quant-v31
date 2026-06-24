#!/usr/bin/env bash
# 재부팅 직후 자동 실행(@reboot cron) — V3.1 레거시가 다시 뜨지 않는지 + V4/대시보드 정상 가동 검증.
# 결과를 로그 + 텔레그램으로 남겨 재접속한 Claude/사용자가 즉시 확인 가능하게 함.
set -uo pipefail

LOG=/home/quant/quant-v31/scripts/v31_reboot_check.log
ENV_FILE=/home/quant/quant-v31/.env

# 부팅 직후 서비스 안정화 대기 (systemd 기동 + V4 스케줄러 로딩)
sleep 90

ST() { systemctl is-active "$1" 2>/dev/null; }
EN() { systemctl is-enabled "$1" 2>/dev/null; }
PORT() { ss -tlnp 2>/dev/null | grep -q ":$1 " && echo UP || echo DOWN; }

V31_ENG_A=$(ST quant-engine);    V31_ENG_E=$(EN quant-engine)
V31_SCH_A=$(ST quant-scheduler); V31_SCH_E=$(EN quant-scheduler)
V4_A=$(ST quant-engine-v4);      V4_E=$(EN quant-engine-v4)
DASH_A=$(ST quant-dashboard);    DASH_E=$(EN quant-dashboard)
P8000=$(PORT 8000); P50051=$(PORT 50051); P8001=$(PORT 8001); P5000=$(PORT 5000)
NOW=$(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S KST')
UPTIME=$(uptime -p 2>/dev/null)

# 판정: V3.1 둘 다 inactive + 8000 down 이면 PASS
if [ "$V31_ENG_A" = "inactive" ] && [ "$V31_SCH_A" = "inactive" ] && [ "$P8000" = "DOWN" ]; then
  VERDICT="✅ PASS — 재부팅 후 V3.1 안 뜸"
else
  VERDICT="🔴 FAIL — V3.1 재가동 의심 (확인 필요)"
fi

REPORT="[$NOW] $VERDICT ($UPTIME)
  V3.1 quant-engine    : active=$V31_ENG_A enabled=$V31_ENG_E (port8000=$P8000, grpc50051=$P50051)
  V3.1 quant-scheduler : active=$V31_SCH_A enabled=$V31_SCH_E
  V4   quant-engine-v4 : active=$V4_A enabled=$V4_E (port8001=$P8001)
  Dashboard            : active=$DASH_A enabled=$DASH_E (port5000=$P5000)"

echo "$REPORT" >> "$LOG"
echo "----" >> "$LOG"

# 텔레그램 발송 (best-effort)
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
  MSG="<b>🔁 재부팅 후 V3.1 검증</b>
$VERDICT
$NOW
V3.1: engine=$V31_ENG_A/$V31_ENG_E · scheduler=$V31_SCH_A/$V31_SCH_E
포트8000=$P8000 · gRPC50051=$P50051
V4(8001)=$V4_A · Dashboard(5000)=$DASH_A"
  curl -s -m 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}" >/dev/null 2>&1
fi
