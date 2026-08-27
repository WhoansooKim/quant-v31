#!/usr/bin/env bash
# 주간: §22.AO-26 (A-1 rsi2 보유일 게이트 + A-3 시간청산 21일 + B 소수주식 사이징) 전진검증.
#
# 적용 2026-08-27:
#   A-1 rsi2_exit_min_hold_days 0 → 8      (rsi2 30건 실제 +3.39% vs 20일보유 +9.53%)
#   A-3 time_stop_days          15 → 21    (20일 신호지평 보장)
#   B   fractional_shares_enabled → true   (정수내림+강제1주 → 주가가중 왜곡 제거)
#   A-2 atr_hard_stop_multiplier 는 2.0 적용 후 **1.5 로 되돌림** (hard_stop 은 원래 옳게
#       자르고 있었음: n=11, 20일 갭 +0.17pp). 이 스크립트가 되돌림 유지 여부도 감시한다.
#
# 로컬 DB(5432)/.env 토큰 필요. user crontab 으로 매주 실행. 수동 실행도 가능.
set -uo pipefail

ENV_FILE=/home/quant/quant-v31/.env
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CUTOFF='2026-08-27'        # §22.AO-26 적용일
VERDICT_DATE='2026-09-10'  # 판정일 = 2주차. 사용자 지시 "2주차까지 보고 판정하자"(2026-08-27).
                           # 이유: A-1 게이트가 8일이라 1주차(9/3)에는 신규 진입분의 rsi2 청산
                           # 자격 자체가 생기지 않는다. 그 전 리포트는 전부 '중간 점검'이다.

PSQL() { docker exec quant-postgres psql -U quant -d quantdb -tA -c "$1" 2>/dev/null; }

# 0) config 유지 감시 — 하나라도 되돌아가면 검증 무효
CFG=$(PSQL "SELECT string_agg(key||'='||value,',' ORDER BY key) FROM swing_config
            WHERE key IN ('rsi2_exit_min_hold_days','time_stop_days','atr_hard_stop_multiplier',
                          'fractional_shares_enabled','allow_min_one_share','momentum_factor_active');")

# 1) A-1: rsi2 청산 — 보유일이 늘고 수익이 커져야 성공 (기준 n=37, hold 3.7d, +4.21%)
RSI2=$(PSQL "SELECT COUNT(*)||'|'||COALESCE(ROUND(AVG(hold_days)::numeric,1)::text,'')||'|'||
             COALESCE(ROUND(AVG(realized_pct*100)::numeric,2)::text,'')
             FROM swing_positions WHERE status='closed' AND exit_reason='rsi2_overbought'
               AND exit_time >= '${CUTOFF}';")

# 2) B: 진입 명목금액 산포 — 등가중이면 변동계수(CV)가 0 에 수렴해야 한다
#    (적용 전 30건은 \$38~\$249 로 CV 가 컸다 = 사실상 주가가중)
CVPOST=$(PSQL "SELECT COUNT(*)||'|'||COALESCE(ROUND((STDDEV(c)/NULLIF(AVG(c),0))::numeric,3)::text,'')||'|'||
               COALESCE(ROUND(MIN(c)::numeric,2)::text,'')||'|'||COALESCE(ROUND(MAX(c)::numeric,2)::text,'')
               FROM (SELECT entry_price*qty AS c FROM swing_positions
                     WHERE entry_time >= '${CUTOFF}' AND qty > 0) t;")
CVPRE=$(PSQL "SELECT COUNT(*)||'|'||COALESCE(ROUND((STDDEV(c)/NULLIF(AVG(c),0))::numeric,3)::text,'')||'|'||
              COALESCE(ROUND(MIN(c)::numeric,2)::text,'')||'|'||COALESCE(ROUND(MAX(c)::numeric,2)::text,'')
              FROM (SELECT entry_price*qty AS c FROM swing_positions
                    WHERE entry_time < '${CUTOFF}' AND qty > 0
                    ORDER BY entry_time DESC LIMIT 30) t;")

# 3) 등가중 vs 달러가중 괴리 — B 가 먹히면 두 값이 붙는다 (적용 전 +0.294% vs -0.332%)
GAP=$(PSQL "SELECT COUNT(*)||'|'||COALESCE(ROUND(AVG(realized_pct*100)::numeric,3)::text,'')||'|'||
            COALESCE(ROUND((SUM(realized_pnl)/NULLIF(SUM(entry_price*qty),0)*100)::numeric,3)::text,'')||'|'||
            COALESCE(ROUND(SUM(realized_pnl)::numeric,2)::text,'')
            FROM swing_positions WHERE status='closed' AND qty>0 AND exit_time >= '${CUTOFF}';")

# 4) 청산 사유 분포 — rsi2 비중이 줄고 trailing/time_stop 비중이 늘어야 의도대로
REASONS=$(PSQL "SELECT string_agg(exit_reason||':'||n,', ' ORDER BY n DESC)
                FROM (SELECT exit_reason, COUNT(*) n FROM swing_positions
                      WHERE status='closed' AND exit_time >= '${CUTOFF}'
                      GROUP BY exit_reason) t;")

# 5) 평균 보유일 전체 — 4.9일에서 늘어야 20일 신호지평에 근접
HOLD=$(PSQL "SELECT COALESCE(ROUND(AVG(hold_days)::numeric,1)::text,'')
             FROM swing_positions WHERE status='closed' AND exit_time >= '${CUTOFF}';")

NOW=$(TZ=Asia/Seoul date '+%m/%d %H:%M')

TODAY=$(TZ=Asia/Seoul date '+%Y-%m-%d')
# 경과 주 = 리포트 회차. 적용일 8/27 기준 9/3=1주차, 9/10=2주차(=판정일).
WEEK=$(( ( $(date -d "$TODAY" +%s) - $(date -d "$CUTOFF" +%s) ) / 604800 ))
IS_VERDICT=$([ "$TODAY" \< "$VERDICT_DATE" ] && echo 0 || echo 1)

MSG=$(CFG="$CFG" RSI2="$RSI2" CVPOST="$CVPOST" CVPRE="$CVPRE" GAP="$GAP" \
      REASONS="$REASONS" HOLD="$HOLD" NOW="$NOW" \
      WEEK="$WEEK" IS_VERDICT="$IS_VERDICT" VERDICT_DATE="$VERDICT_DATE" python3 - <<'PY'
import os
def f(x):
    try: return float(x)
    except Exception: return None
def parts(k, n):
    v = os.environ.get(k, "")
    return (v.split("|", n-1) + [""]*n)[:n] if v else [""]*n

now = os.environ["NOW"]; cfg = os.environ.get("CFG", "")
week = int(os.environ.get("WEEK", "1") or 1)
is_verdict = os.environ.get("IS_VERDICT", "0") == "1"
vdate = os.environ.get("VERDICT_DATE", "")
# 적용 전 기준값 (§22.AO-26 진단 실측)
B_RSI2_N, B_RSI2_HOLD, B_RSI2_PCT = 37, 3.7, 4.21
B_HOLD, B_EW, B_DW = 4.9, 0.294, -0.332

label = f"{week}주차" if week >= 1 else "적용 당일"
head = f"<b>🔬 §22.AO-26 {label} " + ("판정</b>" if is_verdict else "중간점검</b>")
L = [f"{head} ({now} KST)",
     "적용 8/27: rsi2 보유일게이트 8d · 시간청산 21d · 소수주식"]
if not is_verdict:
    L.append(f"⏳ 판정은 <b>{vdate}</b>(2주차). 그 전에는 지표만 본다 — "
             f"A-1 게이트가 8일이라 신규 진입분의 rsi2 청산 자격이 아직 안 생긴다.")
L.append("")

# 0) config 감시
L.append(f"<b>설정</b>: {cfg or '조회실패'}")
warn = []
if cfg:
    if "rsi2_exit_min_hold_days=8" not in cfg: warn.append("A-1 rsi2 게이트 되돌려짐")
    if "fractional_shares_enabled=true" not in cfg: warn.append("B 소수주식 꺼짐")
    if "allow_min_one_share=false" not in cfg: warn.append("B 강제1주 재활성")
    if "atr_hard_stop_multiplier=1.5" not in cfg: warn.append("A-2 스톱이 1.5 가 아님")
for w in warn:
    L.append(f"  ⚠️ {w} — 검증 무효")
L.append("")

# 1) A-1
n, hold, pct = [f(x) for x in parts("RSI2", 3)]
L.append("<b>A-1 rsi2 청산</b> (기준 n=37, 보유 3.7d, +4.21%)")
if n and n > 0:
    L.append(f"  {int(n)}건 · 보유 {hold:.1f}d · 평균 {pct:+.2f}%" if hold is not None else f"  {int(n)}건")
    if hold is not None and pct is not None:
        ok = hold >= B_RSI2_HOLD * 1.5 and pct >= B_RSI2_PCT
        if not is_verdict:
            L.append(f"  → 추이: 보유 {hold - B_RSI2_HOLD:+.1f}d, 수익 {pct - B_RSI2_PCT:+.2f}p (판정 보류)")
        elif n < 10:
            L.append(f"  → 🟡 {int(n)}건뿐 — 2주차에도 표본 부족. 3주차까지 연장 권고")
        else:
            L.append("  → " + ("✅ 보유↑ 수익↑ — A-1 유효" if ok
                     else "🔴 개선 안 됨 — rsi2_exit_min_hold_days 재검토"))
else:
    L.append("  아직 0건 — 게이트가 조기청산을 막고 있다는 뜻(긍정 신호). 표본 대기.")
    if is_verdict:
        L.append("  → 🟡 판정일인데 표본 0 — 3주차까지 연장 권고")
L.append("")

# 2) B 사이징 산포
pn, pcv, pmin, pmax = parts("CVPRE", 4)
qn, qcv, qmin, qmax = parts("CVPOST", 4)
L.append("<b>B 진입금액 산포</b> (등가중이면 CV→0)")
if pcv: L.append(f"  적용 전 {pn}건: CV {pcv} (${pmin}~${pmax})")
if qn and int(qn or 0) > 0:
    L.append(f"  적용 후 {qn}건: CV {qcv or '-'} (${qmin}~${qmax})")
    c = f(qcv)
    if c is not None:
        # B 는 진입 즉시 효과가 보이므로 1주차에도 판정 가능 (rsi2 와 달리 청산을 안 기다린다)
        L.append("  → " + ("✅ 등가중 복원" if c < 0.10 else "🔴 여전히 주가가중 — 사이징 경로 점검"))
else:
    L.append("  적용 후 신규 진입 0건 — 대기")
L.append("")

# 3) 등가중 vs 달러가중
gn, ew, dw, usd = [f(x) for x in parts("GAP", 4)]
L.append(f"<b>등가중 vs 달러가중</b> (적용 전 {B_EW:+.3f}% vs {B_DW:+.3f}%)")
if gn and gn > 0:
    L.append(f"  청산 {int(gn)}건: 등가중 {ew:+.3f}% vs 달러가중 {dw:+.3f}% (실현 ${usd:+.2f})")
    if ew is not None and dw is not None:
        closed = ew * dw > 0 and abs(ew - dw) < 0.3
        if not is_verdict:
            L.append(f"  → 추이: 괴리 {abs(ew - dw):.3f}p (적용 전 0.626p, 판정 보류)")
        else:
            L.append("  → " + ("✅ 괴리 해소(부호 일치)" if closed
                     else "🟡 아직 괴리 — 표본 누적 필요"))
else:
    L.append("  적용 후 청산 0건 — 대기")
L.append("")

# 4/5) 분포 + 보유일
h = f(os.environ.get("HOLD", ""))
if h is not None:
    L.append(f"<b>평균 보유일</b> {h:.1f}d (적용 전 {B_HOLD}d, 신호지평 20d)")
r = os.environ.get("REASONS", "")
if r: L.append(f"<b>청산 사유</b>: {r}")
L.append("")
if is_verdict:
    L.append("<b>판정 기준</b>: rsi2 보유일 5.5d↑ & 수익 +4.21%↑ (표본 10건↑)")
    L.append("  + 진입 CV&lt;0.10 + 등가중/달러가중 부호 일치 → A-1·B 유효")
    L.append("되돌리려면 rsi2_exit_min_hold_days=0 / fractional_shares_enabled=false.")
else:
    L.append(f"다음 {vdate} 리포트에서 판정한다. 그때 rsi2 표본이 10건 미만이면 3주차로 연장.")
print("\n".join(L))
PY
)

echo "$MSG"
if [ -n "$TOKEN" ] && [ -n "$CHAT" ]; then
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    -d chat_id="$CHAT" -d parse_mode=HTML --data-urlencode text="$MSG" >/dev/null
fi

# 세션 픽업용 결과 파일 (rsi2_review_result.txt 와 같은 규약)
OUT=/home/quant/quant-v31/scripts/ao26_review_result.txt
{ echo "PENDING_CLAUDE_REPORT"; echo "# §22.AO-26 주간 검증 — $(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M KST')";
  echo "$MSG" | sed 's/<[^>]*>//g'; } > "$OUT"
