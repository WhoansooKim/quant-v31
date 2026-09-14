#!/usr/bin/env bash
# 다음 exit_check 실행 결과를 기다렸다가 텔레그램으로 보고한다 (§22.AO-29 후속).
# 사용자 요청(2026-09-14 23:0x): "23:30 exit_check 결과도 텔레그램으로 보내달라".
# 계기: 23:01 이벤트 스캔이 INTC critical price_drop 을 잡았고, 실시간가 96.66 이
#       하드스톱 97.14 를 이탈한 상태였다. 23:30 exit_check 가 청산하는지 확인한다.
#
# 사용법: exit_check_report.sh [대기분]  — 기본 50분
set -uo pipefail

ENV_FILE=/home/quant/quant-v31/.env
LOG=/home/quant/quant-v31/scripts/exit_check_report.log
WAIT_MIN=${1:-50}
WATCH="INTC HPE"          # 이번에 주시하는 종목

PSQL() { docker exec quant-postgres psql -U quant -d quantdb -tA -c "$1" 2>/dev/null; }

# 0) 기준선 — 지금까지의 마지막 exit_check completed id
BASE=$(PSQL "SELECT coalesce(max(log_id),0) FROM swing_pipeline_log
              WHERE step_name='exit_check' AND status='completed'" | tr -d ' ')
BASE=${BASE:-0}

# 1) 새 exit_check 완료 대기
NEWID=""
for _ in $(seq 1 "$WAIT_MIN"); do
  NEWID=$(PSQL "SELECT log_id FROM swing_pipeline_log
                 WHERE step_name='exit_check' AND status='completed' AND log_id > $BASE
                 ORDER BY log_id LIMIT 1" | tr -d ' ')
  [ -n "$NEWID" ] && break
  sleep 60
done

NOW=$(TZ=Asia/Seoul date '+%m/%d %H:%M KST')

if [ -z "$NEWID" ]; then
  MSG="<b>🛑 exit_check 결과 — 🔴 미실행</b> ($NOW)
${WAIT_MIN}분 대기했으나 새 <code>exit_check</code> 완료 기록이 없다.
확인: <code>curl -s localhost:8001/scheduler</code> (exit_check_1 월~금 23:30 KST)"
else
  RUN=$(PSQL "SELECT to_char(created_at AT TIME ZONE 'Asia/Seoul','MM/DD HH24:MI')
                FROM swing_pipeline_log WHERE log_id=$NEWID")
  SUM=$(PSQL "SELECT 'positions='||coalesce(details->>'positions','?')
                   ||' scan_exits='||coalesce(details->>'scan_exits','?')
                   ||' auto_executed='||coalesce(details->>'auto_executed','?')
                   ||' partial='||coalesce(details->>'partial_exits','?')
                FROM swing_pipeline_log WHERE log_id=$NEWID")

  # 2) 방금 청산된 포지션
  CLOSED=$(PSQL "SELECT coalesce(string_agg(
                   symbol||' '||exit_reason||' @'||round(exit_price,2)
                   ||' ('||to_char(realized_pct*100,'FM990.00')||'% , \$'||round(realized_pnl,2)||')', E'\n  '
                   ORDER BY exit_time), '없음')
                 FROM swing_positions
                  WHERE status='closed' AND exit_time > now() - interval '25 minutes'")

  # 3) 주시 종목 현황
  WATCHLINE=""
  for S in $WATCH; do
    ROW=$(PSQL "SELECT status||'|'||round(coalesce(current_price,exit_price),2)
                     ||'|'||round(coalesce(hard_stop,0),2)
                     ||'|'||to_char(coalesce(realized_pct,unrealized_pct)*100,'FM990.00')
                  FROM swing_positions WHERE symbol='$S' ORDER BY position_id DESC LIMIT 1")
    [ -n "$ROW" ] && WATCHLINE="${WATCHLINE}
  ${S}: $(echo "$ROW" | awk -F'|' '{printf "%s · 가격 %s · 스톱 %s · %s%%", $1, $2, $3, $4}')"
  done

  OPEN=$(PSQL "SELECT count(*) FROM swing_positions WHERE status='open'")
  VAL=$(PSQL "SELECT round(total_value_usd,2)||' (누적 '||to_char(cumulative_return*100,'FM990.00')||'%)'
                FROM swing_snapshots ORDER BY time DESC LIMIT 1")

  MSG="<b>🛑 exit_check 결과</b> ($NOW)
실행: <b>$RUN</b>
$SUM

<b>청산된 포지션</b>(최근 25분)
  $CLOSED

<b>주시 종목</b>$WATCHLINE

오픈 <b>${OPEN}</b>건 · 총자산 ${VAL}"
fi

echo "[$NOW] $(echo "$MSG" | sed 's/<[^>]*>//g' | tr '\n' ' ')" >> "$LOG"

TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
  RC=$(curl -s -m 20 -o /dev/null -w '%{http_code}' -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
       -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}")
  echo "  telegram HTTP $RC" >> "$LOG"; echo "telegram HTTP $RC"
else
  echo "  🔴 텔레그램 크레덴셜 없음" >> "$LOG"
fi
