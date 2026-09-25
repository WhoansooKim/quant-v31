#!/usr/bin/env bash
# 실행 공백 감지 — VM 일시정지(suspend)·정전·장기 정지를 재개 직후에 알린다 (§22.AO-31).
#
# 왜 필요한가 (2026-09-22~24 실측): VM 이 41.9시간 멈춰 있었는데 아무도 몰랐다.
#   - `@reboot` cron 은 **재부팅에만** 걸린다. suspend/resume 은 재부팅이 아니라 안 돈다
#     (uptime 은 계속 증가하고 systemd 서비스도 active 를 유지한다).
#   - 그 사이 미국장 2세션이 통째로 지나갔고 exit_check 가 한 번도 안 돌아
#     **스톱이 집행되지 않았다**(HPQ 가 브레이크이븐 32.45 대신 31.93 에 청산됐다).
#   - data_freshness 자가진단은 토 11:00 에만 돌아 공백 중에는 실행되지 않는다.
#
# 원리: 하트비트 파일에 매 실행 시각을 적는다. 다음 실행에서 간격이 기대치보다 크면
#   그만큼 **우리가 멈춰 있었다**는 뜻이다(멈춘 동안은 이 스크립트도 안 돈다).
#
# 사용: */5 * * * * gap_watch.sh     (cron)
set -uo pipefail

ENV_FILE=/home/quant/quant-v31/.env
BEAT=/home/quant/quant-v31/scripts/.gap_watch.beat
LOG=/home/quant/quant-v31/scripts/gap_watch.log
THRESH_MIN=${GAP_THRESHOLD_MIN:-20}          # 이 분 이상 끊기면 공백으로 본다
NOW=$(date +%s)

PSQL() { docker exec quant-postgres psql -U quant -d quantdb -tA -c "$1" 2>/dev/null; }

PREV=$(cat "$BEAT" 2>/dev/null || echo "")
echo "$NOW" > "$BEAT"

# 첫 실행이면 기준선만 세우고 끝낸다
[ -n "$PREV" ] || { echo "[$(date '+%F %T')] 하트비트 초기화" >> "$LOG"; exit 0; }

GAP=$(( (NOW - PREV) / 60 ))
[ "$GAP" -ge "$THRESH_MIN" ] || exit 0       # 정상 — 조용히 종료

KST=$(TZ=Asia/Seoul date '+%m/%d %H:%M')
FROM=$(TZ=Asia/Seoul date -d "@$PREV" '+%m/%d %H:%M')
HRS=$(awk -v g="$GAP" 'BEGIN{printf "%.1f", g/60}')

# 공백 동안 무엇을 놓쳤나
OPEN=$(PSQL "SELECT count(*) FROM swing_positions WHERE status='open'")
LASTJOB=$(PSQL "SELECT to_char(max(created_at) AT TIME ZONE 'Asia/Seoul','MM/DD HH24:MI') FROM swing_pipeline_log")
LASTBAR=$(PSQL "SELECT max(time)::date FROM daily_prices")
LASTEXIT=$(PSQL "SELECT to_char(max(created_at) AT TIME ZONE 'Asia/Seoul','MM/DD HH24:MI')
                   FROM swing_pipeline_log WHERE step_name='exit_check' AND status='completed'")

# 오픈 포지션이 있으면 exit_check 를 즉시 돌린다 — 다음 스케줄까지 기다리면 스톱이 늦는다
ACTION="(오픈 0건 — 조치 불필요)"
AUTO=$(PSQL "SELECT value FROM swing_config WHERE key='gap_watch_auto_exit_check'")
if [ "${OPEN:-0}" -gt 0 ] 2>/dev/null && [ "${AUTO:-true}" != "false" ]; then
  RC=$(curl -s -m 20 -o /dev/null -w '%{http_code}' -X POST http://localhost:8001/exit-check/run)
  ACTION="exit_check 즉시 실행 요청 → HTTP $RC"
fi

MSG="<b>⏸️ 실행 공백 감지</b> ($KST)
<b>${HRS}시간</b> 멈춰 있었다 ($FROM → $KST)
재부팅이 아니라 정지/일시정지다 — @reboot 검증은 돌지 않는다.

마지막 잡      : $LASTJOB
마지막 exit_check: $LASTEXIT
마지막 가격 봉  : $LASTBAR
오픈 포지션    : ${OPEN}건

조치: $ACTION
⚠️ 공백 동안 스톱이 집행되지 않았다. 가격 백필과 포지션 확인 필요."

echo "[$(TZ=Asia/Seoul date '+%F %T')] 공백 ${HRS}h ($FROM → $KST) open=${OPEN} action=${ACTION}" >> "$LOG"

TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
  curl -s -m 20 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}" >/dev/null
fi
