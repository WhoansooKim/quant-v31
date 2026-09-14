#!/usr/bin/env bash
# 23:00 events_scan_open 첫 자동 실행 결과를 기다렸다가 텔레그램으로 보고한다 (§22.AO-29).
# 사용자 요청(2026-09-14): "23시 스캔 끝나면 결과 텔레그램으로 알려달라".
# 일회성 — 첫 실행 검증용이다. 상시 리포트가 필요하면 cron 에 걸 것.
set -uo pipefail

ENV_FILE=/home/quant/quant-v31/.env
LOG=/home/quant/quant-v31/scripts/events_scan_report.log
WAIT_MIN=${1:-50}

PSQL() { docker exec quant-postgres psql -U quant -d quantdb -tA -c "$1" 2>/dev/null; }

# ── 1) events_scan 기록이 남을 때까지 대기 ──
FOUND=0
for _ in $(seq 1 "$WAIT_MIN"); do
  N=$(PSQL "SELECT count(*) FROM swing_pipeline_log
             WHERE step_name='events_scan' AND created_at > now() - interval '90 minutes'" | tr -d ' ')
  if [ "${N:-0}" -ge 1 ] 2>/dev/null; then FOUND=1; break; fi
  sleep 60
done

NOW=$(TZ=Asia/Seoul date '+%m/%d %H:%M KST')

if [ "$FOUND" -ne 1 ]; then
  MSG="<b>🔭 이벤트 스캔 첫 자동 실행 — 🔴 미실행</b> ($NOW)
${WAIT_MIN}분을 기다렸으나 <code>events_scan</code> 기록이 없다.
잡 등록은 됐는지 확인 필요: <code>curl -s localhost:8001/scheduler</code>
(기대 32잡, events_scan_open 월~금 23:00 KST)"
else
  # ── 2) 잡 결과 ──
  JOB=$(PSQL "SELECT status||' / found='||coalesce(details->>'found','?')||' processed='||coalesce(details->>'processed','?')
                FROM swing_pipeline_log WHERE step_name='events_scan'
               ORDER BY log_id DESC LIMIT 1")
  KST=$(PSQL "SELECT to_char(created_at AT TIME ZONE 'Asia/Seoul','MM/DD HH24:MI')
                FROM swing_pipeline_log WHERE step_name='events_scan' ORDER BY log_id DESC LIMIT 1")
  # ── 3) 실제 저장된 이벤트 (중복 제거 후 남은 것) ──
  NEW=$(PSQL "SELECT count(*) FROM swing_events WHERE created_at > now() - interval '20 minutes'")
  BREAK=$(PSQL "SELECT coalesce(string_agg(severity||' '||event_type||' '||c,', ' ORDER BY c DESC),'없음')
                  FROM (SELECT severity, event_type, count(*) c FROM swing_events
                         WHERE created_at > now() - interval '20 minutes'
                         GROUP BY 1,2) t")
  ALERTABLE=$(PSQL "SELECT count(*) FROM swing_events
                     WHERE created_at > now() - interval '20 minutes'
                       AND severity IN ('critical','warning')")
  # ── 4) 중복 제거 실적 (로그에서) ──
  SKIP=$(journalctl -u quant-engine-v4 --since "-25 min" --no-pager 2>/dev/null \
         | grep -o 'Event dedup: [0-9]* duplicates skipped' | tail -1)
  [ -n "$SKIP" ] || SKIP="(중복 로그 없음)"
  DUP=$(PSQL "SELECT count(*) FROM (SELECT event_type,symbol,title FROM swing_events
                WHERE created_at > now() - interval '6 hours'
                GROUP BY 1,2,3 HAVING count(*)>1) t")

  MSG="<b>🔭 이벤트 스캔 첫 자동 실행</b> ($NOW)
실행: <b>$KST</b> · $JOB

<b>새로 저장된 이벤트</b>: ${NEW}건
  $BREAK
<b>알림 대상</b>(warning/critical): ${ALERTABLE}건

<b>중복 제거</b>: $SKIP
중복 잔존 그룹(6시간): <b>${DUP}</b> (0이어야 정상)

<i>22:02 수동 스캔에서 이미 47건을 저장했으므로, 이번 회차는 대부분 중복으로 걸러지는 것이 정상이다.</i>"
fi

echo "[$NOW] $(echo "$MSG" | sed 's/<[^>]*>//g' | tr '\n' ' ')" >> "$LOG"

TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
  RC=$(curl -s -m 20 -o /dev/null -w '%{http_code}' -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
       -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}")
  echo "  telegram HTTP $RC" >> "$LOG"
  echo "telegram HTTP $RC"
else
  echo "  🔴 텔레그램 크레덴셜 없음" >> "$LOG"
fi
