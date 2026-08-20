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

# ── 2026-08-20 추가: 조용히 실패하면 하네스가 멈추는 항목들 ──
# 시계 skew: 스냅샷 복구/재부팅 후 시계가 과거면 Yahoo SSL "not yet valid" 로 전 수집 마비(2026-08-18 실측)
CLOCK_OK=$(curl -sI -m 10 https://www.google.com 2>/dev/null | grep -qi '^date:' && echo OK || echo FAIL)
# 스케줄러 잡 수 (기대 29). 엔진이 떠도 잡 등록이 실패하면 자동 운영이 통째로 멈춘다
JOBS=$(curl -s -m 15 http://localhost:8001/health 2>/dev/null \
       | python3 -c 'import sys,json;print(json.load(sys.stdin).get("scheduler_jobs","?"))' 2>/dev/null || echo "?")
# DB 팩터 가중치 (하네스 3I 가 쓰는 진실. 비어 있으면 하드코딩 폴백으로 조용히 되돌아간다)
WEIGHTS=$(docker exec quant-postgres psql -U quant -d quantdb -tAc \
          "SELECT COUNT(*) FROM swing_factor_weights" 2>/dev/null || echo "?")
# 토요일 사이클 등록 여부
SATJOBS=$(curl -s -m 15 http://localhost:8001/scheduler 2>/dev/null \
          | python3 -c "import sys,json;d=json.load(sys.stdin);js=d.get('jobs',d);print(sum(1 for j in js if str(j.get('id')) in ('factor_ic','self_check','formula_lab','pead_collect','weekly_research')))" 2>/dev/null || echo "?")

# 판정: V3.1 미가동 + V4 정상 + 잡 29 + 가중치 28 + 시계 정상 이면 PASS
PROBLEMS=""
[ "$V31_ENG_A" = "inactive" ] && [ "$V31_SCH_A" = "inactive" ] && [ "$P8000" = "DOWN" ] \
  || PROBLEMS="$PROBLEMS V3.1재가동"
[ "$V4_A" = "active" ] && [ "$P8001" = "UP" ] || PROBLEMS="$PROBLEMS V4다운"
[ "$JOBS" = "29" ] || PROBLEMS="$PROBLEMS 잡수=$JOBS(기대29)"
[ "$SATJOBS" = "5" ] || PROBLEMS="$PROBLEMS 토요일사이클=$SATJOBS(기대5)"
[ "$WEIGHTS" = "28" ] || PROBLEMS="$PROBLEMS 팩터가중치=$WEIGHTS(기대28)"
[ "$CLOCK_OK" = "OK" ] || PROBLEMS="$PROBLEMS 시계/네트워크이상"
if [ -z "$PROBLEMS" ]; then
  VERDICT="✅ PASS — 재부팅 후 전 항목 정상"
else
  VERDICT="🔴 FAIL —$PROBLEMS"
fi

REPORT="[$NOW] $VERDICT ($UPTIME)
  V3.1 quant-engine    : active=$V31_ENG_A enabled=$V31_ENG_E (port8000=$P8000, grpc50051=$P50051)
  V3.1 quant-scheduler : active=$V31_SCH_A enabled=$V31_SCH_E
  V4   quant-engine-v4 : active=$V4_A enabled=$V4_E (port8001=$P8001)
  Dashboard            : active=$DASH_A enabled=$DASH_E (port5000=$P5000)
  스케줄러 잡          : $JOBS (기대 29) / 토요일 사이클 $SATJOBS (기대 5)
  팩터 가중치(DB)      : $WEIGHTS 행 (기대 28) — 비면 하드코딩 폴백
  시계/외부망          : $CLOCK_OK"

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
V4(8001)=$V4_A · Dashboard(5000)=$DASH_A
스케줄러 잡=$JOBS/29 · 토요일사이클=$SATJOBS/5
팩터가중치(DB)=$WEIGHTS/28 · 시계=$CLOCK_OK"
  curl -s -m 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}" >/dev/null 2>&1
fi
