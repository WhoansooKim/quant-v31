#!/usr/bin/env bash
# 재부팅 직후 자동 실행(@reboot cron) — V3.1 레거시가 다시 뜨지 않는지 + V4/대시보드 정상 가동 검증.
# 2026-11-22 텔레그램 정리: 스윙 은퇴 후 '토요일 사이클 5 · 팩터 가중치 그리드'는 의미가 없어(잡 3개는 은퇴 해제됨)
#   다음 재부팅에 정상인데 FAIL 이 뜨는 구조였다 → 코어 잡 등록 + 마지막 코어 배분 상태로 교체.
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
# 스케줄러 잡 수. 엔진이 떠도 잡 등록이 실패하면 자동 운영이 통째로 멈춘다.
# 2026-09-14: 기대치 29 를 스크립트에 박아뒀더니, 잡을 3개 추가하자(이벤트/EDGAR 스캔)
#   정상인데 FAIL 이 되는 구조였다 — §22.AO-28 의 팩터 가중치 28 과 똑같은 함정.
#   기대치를 DB(swing_config.expected_scheduler_jobs)로 옮겨 잡 추가와 같은 커밋에서 갱신한다.
JOBS=$(curl -s -m 15 http://localhost:8001/health 2>/dev/null \
       | python3 -c 'import sys,json;print(json.load(sys.stdin).get("scheduler_jobs","?"))' 2>/dev/null || echo "?")
JOBS_EXPECTED=$(docker exec quant-postgres psql -U quant -d quantdb -tAc \
       "SELECT value FROM swing_config WHERE key='expected_scheduler_jobs'" 2>/dev/null | tr -d ' ')
[ -n "$JOBS_EXPECTED" ] || JOBS_EXPECTED="?"
# 코어 운용에 꼭 필요한 잡이 등록돼 있는가 (core_allocate 화~토 00:30 · self_check 토 11:00)
COREJOBS=$(curl -s -m 15 http://localhost:8001/scheduler 2>/dev/null \
          | python3 -c "import sys,json;d=json.load(sys.stdin);js=d.get('jobs',d);print(sum(1 for j in js if str(j.get('id')) in ('core_allocate','self_check')))" 2>/dev/null || echo "?")
# 마지막 코어 배분 상태 (재부팅 전 실패가 있었으면 여기서 보인다)
LASTCORE=$(docker exec quant-postgres psql -U quant -d quantdb -tAc \
          "SELECT status || ' ' || to_char(created_at AT TIME ZONE 'Asia/Seoul','MM/DD HH24:MI') FROM swing_pipeline_log WHERE step_name='core_allocate' ORDER BY created_at DESC LIMIT 1" 2>/dev/null | tr -s ' ')
[ -n "$LASTCORE" ] || LASTCORE="?"

# 판정: V3.1 미가동 + V4 정상 + 잡수 기대치 일치 + 코어 잡 등록 + 마지막 코어 배분 성공 + 시계 정상 이면 PASS
PROBLEMS=""
[ "$V31_ENG_A" = "inactive" ] && [ "$V31_SCH_A" = "inactive" ] && [ "$P8000" = "DOWN" ] \
  || PROBLEMS="$PROBLEMS V3.1재가동"
[ "$V4_A" = "active" ] && [ "$P8001" = "UP" ] || PROBLEMS="$PROBLEMS V4다운"
case "$JOBS_EXPECTED" in
  ""|*[!0-9]*) PROBLEMS="$PROBLEMS 잡기대치조회실패" ;;
  *) [ "$JOBS" = "$JOBS_EXPECTED" ] || PROBLEMS="$PROBLEMS 잡수=$JOBS(기대$JOBS_EXPECTED)" ;;
esac
[ "$COREJOBS" = "2" ] || PROBLEMS="$PROBLEMS 코어잡=$COREJOBS(기대2)"
case "$LASTCORE" in completed*) ;; *) PROBLEMS="$PROBLEMS 마지막코어배분=$LASTCORE" ;; esac
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
  스케줄러 잡          : $JOBS (기대 $JOBS_EXPECTED) / 코어 잡 $COREJOBS (기대 2: core_allocate·self_check)
  마지막 코어 배분     : $LASTCORE
  시계/외부망          : $CLOCK_OK"

echo "$REPORT" >> "$LOG"
echo "----" >> "$LOG"

# 텔레그램 발송 (best-effort)
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
  MSG="<b>🔁 재부팅 후 엔진 검증</b>
$VERDICT
$NOW
V3.1: engine=$V31_ENG_A/$V31_ENG_E · scheduler=$V31_SCH_A/$V31_SCH_E
포트8000=$P8000 · gRPC50051=$P50051
V4(8001)=$V4_A · Dashboard(5000)=$DASH_A
스케줄러 잡=$JOBS/$JOBS_EXPECTED · 코어 잡=$COREJOBS/2
마지막 코어 배분=$LASTCORE · 시계=$CLOCK_OK"
  curl -s -m 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}" >/dev/null 2>&1
fi
