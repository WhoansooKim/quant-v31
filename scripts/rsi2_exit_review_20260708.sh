#!/usr/bin/env bash
# 일회성: 2026-07-08 rsi2 출구 정책 변경(7/1 적용) 1주 전진검증.
# 변경: rsi2_exit_min_r 1.0→2.0, rsi2_exit_threshold 90→95 (승자 과조기절단 교정).
# 변경 후 청산 데이터로 rsi2 빈도↓ / 보유기간·수익↑ / 거래IC 개선 여부를 baseline 대비 평가해 Telegram 발송.
# 로컬 DB(5432)/.env 토큰 필요. systemd-run --user 로 예약 실행.
set -uo pipefail

ENV_FILE=/home/quant/quant-v31/.env
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CUTOFF='2026-07-01'   # 변경 적용일

PSQL() { docker exec quant-postgres psql -U quant -d quantdb -tA -c "$1" 2>/dev/null; }

# 1) 현재 config (되돌려지지 않았는지 확인)
CFG=$(PSQL "SELECT string_agg(key||'='||value,',') FROM swing_config WHERE key IN ('rsi2_exit_min_r','rsi2_exit_threshold');")
# 2) 변경 후 청산 사유별 성과
POST=$(PSQL "SELECT COALESCE(exit_reason,'?')||':'||COUNT(*)||':'||COALESCE(ROUND(AVG(realized_pct*100)::numeric,2)::text,'')||':'||COALESCE(ROUND(AVG(hold_days)::numeric,1)::text,'') FROM swing_positions WHERE status='closed' AND exit_time >= '${CUTOFF}' GROUP BY exit_reason ORDER BY COUNT(*) DESC;")
# 3) 변경 후 rsi2 청산만 집계
POSTR=$(PSQL "SELECT COUNT(*)||'|'||COALESCE(ROUND(AVG(realized_pct*100)::numeric,2)::text,'')||'|'||COALESCE(ROUND(AVG(hold_days)::numeric,1)::text,'') FROM swing_positions WHERE status='closed' AND exit_reason='rsi2_overbought' AND exit_time >= '${CUTOFF}';")
# 4) 변경 후 반사실: rsi2 청산 후 10일 추가상승
CF=$(PSQL "WITH r AS (SELECT symbol, exit_time::date xd, exit_price FROM swing_positions WHERE status='closed' AND exit_reason='rsi2_overbought' AND exit_time>='${CUTOFF}' AND exit_price IS NOT NULL), f AS (SELECT r.exit_price, (SELECT dp.close FROM daily_prices dp WHERE dp.symbol=r.symbol AND dp.time::date>=r.xd+make_interval(days=>10) ORDER BY dp.time ASC LIMIT 1) p10 FROM r) SELECT COUNT(*) FILTER (WHERE p10 IS NOT NULL)||'|'||COALESCE(ROUND(AVG((p10/exit_price-1)*100)::numeric,2)::text,'') FROM f;")
# 5) 최신 IC (거래 IC + 신호 IC)
IC=$(PSQL "SELECT report_date||'|'||COALESCE(rolling_30_information_coefficient::text,'')||'|'||COALESCE(rolling_signal_ic::text,'') FROM swing_daily_report WHERE rolling_30_information_coefficient IS NOT NULL ORDER BY report_date DESC LIMIT 1;")

NOW=$(TZ=Asia/Seoul date '+%m/%d %H:%M')

MSG=$(CFG="$CFG" POST="$POST" POSTR="$POSTR" CF="$CF" IC="$IC" NOW="$NOW" python3 - <<'PY'
import os
# baseline (변경 전 2026-07-01 시점)
BASE = {"rsi2_n":24, "rsi2_ret":2.43, "rsi2_days":1.9, "trade_ic":-0.117, "sig_ic":0.074, "cf10":8.53}
now=os.environ["NOW"]; cfg=os.environ.get("CFG",""); post=os.environ.get("POST","")
postr=os.environ.get("POSTR",""); cf=os.environ.get("CF",""); ic=os.environ.get("IC","")
def f(x):
    try: return float(x)
    except: return None
L=[f"<b>🔬 rsi2 출구 정책 1주 전진검증</b> ({now} KST)",
   "변경(7/1): min_r 1.0→2.0, threshold 90→95 — 승자 과조기절단 교정", ""]
# config 유지 확인
L.append(f"<b>설정 유지</b>: {cfg or '조회실패'}")
if cfg and ('rsi2_exit_min_r=2.0' not in cfg or 'rsi2_exit_threshold=95' not in cfg):
    L.append("  ⚠️ 값이 되돌려짐 — 검증 무효, 재적용 필요")
L.append("")
# rsi2 변경 후 vs baseline
rn=rr=rd=None
if postr and postr.count("|")>=2:
    a,b,c=postr.split("|",2); rn=f(a); rr=f(b); rd=f(c)
L.append("<b>rsi2 청산 (변경후 vs 기준)</b>")
if rn is not None and rn>0:
    L.append(f"  건수: {BASE['rsi2_n']}(기준누적) → 변경후 <b>{int(rn)}건</b>")
    if rr is not None: L.append(f"  평균수익: {BASE['rsi2_ret']:+.2f}% → <b>{rr:+.2f}%</b> ({rr-BASE['rsi2_ret']:+.2f})")
    if rd is not None: L.append(f"  평균보유: {BASE['rsi2_days']}일 → <b>{rd}일</b> ({rd-BASE['rsi2_days']:+.1f})")
else:
    L.append("  변경 후 rsi2 청산 0건 — min_r=2.0/thr=95 게이팅이 조기청산을 억제 중(긍정 신호). 표본 누적 필요.")
L.append("")
# 반사실 (여전히 돈 남기나)
if cf and cf.count("|")>=1:
    n,v=cf.split("|",1); n=f(n); v=f(v)
    if n and n>0:
        L.append(f"<b>반사실</b>: 변경후 rsi2 청산 {int(n)}건, 청산후 10일 {v:+.2f}% (기준 +8.53%)")
        if v is not None:
            L.append("  → "+("🟡 여전히 남김, 추가 조정 검토" if v>3 else "✅ 남김 축소(개선)"))
        L.append("")
# 청산 사유 분포
if post:
    L.append("<b>변경후 청산 사유</b>")
    for row in post.split("\n"):
        p=row.split(":")
        if len(p)>=4: L.append(f"  {p[0]}: {p[1]}건 평균{p[2]}% {p[3]}일")
    L.append("")
# IC
if ic and ic.count("|")>=2:
    rd2,t,s=ic.split("|",2); t=f(t); s=f(s)
    L.append("<b>IC</b>")
    if t is not None: L.append(f"  거래IC: {BASE['trade_ic']:+.3f} → <b>{t:+.3f}</b> ({t-BASE['trade_ic']:+.3f} {'↑' if t>BASE['trade_ic'] else '↓'})")
    if s is not None: L.append(f"  신호IC: {BASE['sig_ic']:+.3f} → <b>{s:+.3f}</b>")
    L.append("")
L.append("<i>판단: rsi2 청산 빈도↓·보유기간↑·거래IC 개선이면 변경 유효. 반사실이 여전히 큰 +면 min_r 추가 상향(2.5~3.0) 검토. 되돌리려면 min_r=1.0/thr=90.</i>")
print("\n".join(L))
PY
)

# Claude 세션 인수인계용 결과 파일 (다음 세션이 추가 설명 없이 읽고 보고)
RESULT_FILE=/home/quant/quant-v31/scripts/rsi2_review_result.txt
{
  echo "# rsi2 출구 정책 1주 전진검증 결과 — $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')"
  echo "# 상태: PENDING_CLAUDE_REPORT (Claude가 사용자에게 보고 후 이 줄을 REPORTED 로 바꿀 것)"
  echo "$MSG" | sed 's/<[^>]*>//g'
} > "$RESULT_FILE"

RESP=$(curl -s -m 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}")
echo "telegram resp: $RESP"
OK=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('ok',False))" 2>/dev/null)
if [ "$OK" = "True" ]; then
  echo "rsi2 전진검증 발송 완료"
  # 일회성: 성공 발송 후 자기 cron 라인 제거 (내년 재발화 방지)
  crontab -l 2>/dev/null | grep -v 'rsi2_exit_review_20260708' | crontab - 2>/dev/null && echo "cron 라인 자동 제거됨"
else
  echo "telegram send failed"
fi
