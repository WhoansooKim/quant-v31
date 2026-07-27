#!/usr/bin/env bash
# 주간(매주): 손익비 개선(①번, 2026-07-27 적용) 전진검증.
# 변경: take_profit_pct 0.20→0.50 (고정 TP 비활성화, ATR 트레일링+부분익절 지배).
# 적용 전(~07-26) vs 적용 후(07-27~) 청산 데이터로 손익비/평균승%/청산사유 분포 변화를 Telegram 발송.
# 로컬 DB(5432)/.env 토큰 필요. user crontab 으로 매주 실행.
set -uo pipefail

ENV_FILE=/home/quant/quant-v31/.env
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CUTOFF='2026-07-27'   # ①번 적용일

PSQL() { docker exec quant-postgres psql -U quant -d quantdb -tA -c "$1" 2>/dev/null; }

# config 유지
CFG=$(PSQL "SELECT string_agg(key||'='||value,',') FROM swing_config WHERE key IN ('take_profit_pct','atr_trailing_multiplier','partial_exit_r');")
# 적용 후 청산: 손익비/평균승%/평균패%/건수
POST=$(PSQL "SELECT COUNT(*)||'|'||COALESCE(ROUND((AVG(realized_pct*100) FILTER (WHERE realized_pct>0))::numeric,2)::text,'')||'|'||COALESCE(ROUND((AVG(realized_pct*100) FILTER (WHERE realized_pct<=0))::numeric,2)::text,'')||'|'||COALESCE(ROUND((COUNT(*) FILTER (WHERE realized_pct>0)::numeric/NULLIF(COUNT(*),0)*100),0)::text,'') FROM swing_positions WHERE status='closed' AND exit_time>='${CUTOFF}';")
# 적용 전 baseline (직전 30건)
PRE=$(PSQL "SELECT COUNT(*)||'|'||COALESCE(ROUND((AVG(realized_pct*100) FILTER (WHERE realized_pct>0))::numeric,2)::text,'')||'|'||COALESCE(ROUND((AVG(realized_pct*100) FILTER (WHERE realized_pct<=0))::numeric,2)::text,'') FROM (SELECT realized_pct FROM swing_positions WHERE status='closed' AND exit_time<'${CUTOFF}' AND realized_pct IS NOT NULL ORDER BY exit_time DESC LIMIT 30) t;")
# 적용 후 청산 사유 분포 (take_profit↓ atr_trailing/partial↑ 기대)
REASONS=$(PSQL "SELECT string_agg(exit_reason||':'||n,', ') FROM (SELECT exit_reason, COUNT(*) n FROM swing_positions WHERE status='closed' AND exit_time>='${CUTOFF}' GROUP BY exit_reason ORDER BY n DESC) t;")

NOW=$(TZ=Asia/Seoul date '+%m/%d %H:%M')

MSG=$(CFG="$CFG" POST="$POST" PRE="$PRE" REASONS="$REASONS" NOW="$NOW" python3 - <<'PY'
import os
def f(x):
    try: return float(x)
    except: return None
now=os.environ["NOW"]; cfg=os.environ.get("CFG",""); post=os.environ.get("POST","")
pre=os.environ.get("PRE",""); reasons=os.environ.get("REASONS","")
# baseline 상수 (백테스트 C안 목표): 승 +13.9%, 손익비 2.57
BASE_WIN=13.9; BASE_PAYOFF=2.57
L=[f"<b>📈 손익비 개선(①번) 주간 검증</b> ({now} KST)",
   "변경(7/27): take_profit 0.20→0.50 — 트레일링+부분익절 지배", ""]
L.append(f"<b>설정 유지</b>: {cfg or '조회실패'}")
if cfg and 'take_profit_pct=0.50' not in cfg:
    L.append("  ⚠️ take_profit 이 되돌려짐 — 검증 무효")
L.append("")
# 적용 후
n=w=lo=wr=None
if post and post.count("|")>=3:
    a,b,c,d=post.split("|",3); n=f(a); w=f(b); lo=f(c); wr=f(d)
L.append("<b>적용 후 청산 (7/27~)</b>")
if n and n>0:
    payoff = (w/abs(lo)) if (w is not None and lo and lo<0) else None
    L.append(f"  청산 {int(n)}건 · 승률 {wr:.0f}%" if wr is not None else f"  청산 {int(n)}건")
    if w is not None: L.append(f"  평균 승 <b>{w:+.2f}%</b> (백테스트 목표 +{BASE_WIN}%)")
    if lo is not None: L.append(f"  평균 패 {lo:+.2f}%")
    if payoff is not None: L.append(f"  <b>손익비 {payoff:.2f}</b> (백테스트 목표 {BASE_PAYOFF})")
    # 판정
    if payoff is not None:
        L.append("  → "+("✅ 손익비 개선 궤도" if payoff>=2.0 else "🟡 표본 부족/관찰 필요"))
else:
    L.append("  적용 후 청산 아직 0건 — 표본 누적 대기(오픈 유지 중이면 긍정 신호).")
L.append("")
# baseline 비교
if pre and pre.count("|")>=2:
    pn,pw,pl=pre.split("|",2); pn=f(pn); pw=f(pw)
    if pw is not None:
        L.append(f"<b>기준(적용 전 직전 {int(pn) if pn else '?'}건)</b>: 평균 승 {pw:+.2f}%")
        if w is not None and pw: L.append(f"  승 수익 변화: {pw:+.2f}% → {w:+.2f}% ({w-pw:+.2f}p)")
    L.append("")
if reasons:
    L.append(f"<b>청산 사유(적용후)</b>: {reasons}")
    L.append("<i>기대: take_profit↓, atr_trailing_stop/partial_exit↑</i>")
L.append("")
L.append("<i>판단: 평균 승%·손익비 상승 + take_profit 청산 비중 감소면 ①번 유효. 되돌리려면 take_profit_pct=0.20.</i>")
print("\n".join(L))
PY
)

# Claude 세션 인수인계 결과 파일 (누적 갱신)
{
  echo "# 손익비 개선(①번) 주간 검증 — $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"
  echo "$MSG" | sed 's/<[^>]*>//g'
} > /home/quant/quant-v31/scripts/payoff_review_result.txt

RESP=$(curl -s -m 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}")
OK=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('ok',False))" 2>/dev/null)
[ "$OK" = "True" ] && echo "payoff 주간검증 발송 완료" || echo "telegram send failed: $RESP"
