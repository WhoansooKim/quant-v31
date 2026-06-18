#!/usr/bin/env bash
# 일회성: 2026-07-02 오전 IC 추세 재측정 (6/18 커밋 fea7a34 IC 음수 교정 4종 후속 검증).
# 6/17 기준치 대비 rolling_signal_ic / factor_ic_detail / rolling_30 거래 IC 변화 + 4종 패치 효과를
# 평가해 텔레그램으로 발송. 로컬 DB(5432)/.env 토큰 필요. systemd-run --user 로 예약 실행.
set -uo pipefail

ENV_FILE=/home/quant/quant-v31/.env
TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')
CHAT=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"' \r')

PSQL() { docker exec quant-postgres psql -U quant -d quantdb -tA -c "$1" 2>/dev/null; }

# 최신 리포트 (signal IC 산출된 행) — report_date, trade IC, signal IC, N, factor JSON, 승률, 기대값
LATEST=$(PSQL "SELECT report_date||'|'||COALESCE(rolling_30_information_coefficient::text,'')||'|'||COALESCE(rolling_signal_ic::text,'')||'|'||COALESCE(rolling_signal_ic_n::text,'')||'|'||COALESCE(factor_ic_detail::text,'{}')||'|'||COALESCE(ROUND((rolling_30_win_rate*100)::numeric,0)::text,'')||'|'||COALESCE(ROUND(rolling_30_expectancy_pct::numeric,2)::text,'') FROM swing_daily_report WHERE rolling_signal_ic IS NOT NULL ORDER BY report_date DESC LIMIT 1;")

NOW=$(TZ=Asia/Seoul date '+%m/%d %H:%M')

# 메시지 구성 (python: baseline 대비 델타 + 요인별 비교 + 패치 평가)
MSG=$(LATEST="$LATEST" NOW="$NOW" python3 - <<'PY'
import os, json

# 6/17 기준치 (커밋 fea7a34 deploy 시점)
BASE_TRADE_IC = -0.1395
BASE_SIG_IC   = 0.0892
BASE_SIG_N    = 47
BASE_FAC = {"technical": -0.0539, "sentiment": 0.0575, "flow": -0.356,
            "quality": 0.2155, "value": -0.3629, "macro": -0.0417}

now = os.environ.get("NOW", "")
raw = os.environ.get("LATEST", "").strip()

def arrow(delta, good_up=True):
    if abs(delta) < 1e-9: return "→"
    up = delta > 0
    return "↑" if (up == good_up) else "↓"

if not raw or raw.count("|") < 6:
    print(f"<b>📐 IC 추세 재측정</b> ({now} KST)\n\n재측정 가능한 리포트(rolling_signal_ic)가 없습니다. 스케줄러 daily_report 생성 여부를 확인하세요.")
    raise SystemExit(0)

rd, trade, sig, n, facj, win, expv = (raw.split("|", 6) + [""]*7)[:7]
def f(x):
    try: return float(x)
    except: return None
trade_ic = f(trade); sig_ic = f(sig)
try: fac = json.loads(facj) if facj else {}
except: fac = {}

lines = [f"<b>📐 IC 추세 재측정</b> (기준 6/17 → 최신 {rd}, {now} KST)",
         "커밋 <code>fea7a34</code> IC 음수 교정 4종 후속 검증",
         ""]

# 1) 핵심 IC
lines.append("<b>핵심 IC</b>")
if trade_ic is not None:
    d = trade_ic - BASE_TRADE_IC
    lines.append(f"  거래 IC: {BASE_TRADE_IC:+.3f} → <b>{trade_ic:+.3f}</b> ({d:+.3f} {arrow(d,True)})")
else:
    lines.append(f"  거래 IC: {BASE_TRADE_IC:+.3f} → — (없음)")
if sig_ic is not None:
    d = sig_ic - BASE_SIG_IC
    lines.append(f"  신호 IC(fwd5d): {BASE_SIG_IC:+.3f} → <b>{sig_ic:+.3f}</b> ({d:+.3f} {arrow(d,True)})  N {BASE_SIG_N}→{n or '?'}")
else:
    lines.append(f"  신호 IC(fwd5d): {BASE_SIG_IC:+.3f} → — (없음)")
if win: lines.append(f"  승률 {win}% · 기대값 {expv}%")
lines.append("")

# 2) 요인별 IC (재보정 D 검증: quality↑ 유지 / flow·value 음수 완화 기대)
lines.append("<b>요인별 IC (6/17 → 최신)</b>")
order = ["quality","sentiment","technical","macro","flow","value"]
for k in order:
    b = BASE_FAC.get(k); c = fac.get(k)
    if c is None:
        lines.append(f"  {k}: {b:+.3f} → —")
    else:
        c = float(c); d = c - b
        lines.append(f"  {k}: {b:+.3f} → <b>{c:+.3f}</b> ({d:+.3f})")
lines.append("")

# 3) 패치 평가 (자동 판정)
lines.append("<b>4종 패치 평가</b>")
# A/B: 거래 IC 회복 (음수 → 0 근접/양전)
if trade_ic is not None:
    if trade_ic >= 0: lines.append("  A/B 신호·청산분리+RSI2승자보호: ✅ 거래 IC 양전")
    elif trade_ic > BASE_TRADE_IC: lines.append("  A/B 신호·청산분리+RSI2승자보호: 🟡 거래 IC 개선(회복 중)")
    else: lines.append("  A/B 신호·청산분리+RSI2승자보호: 🔴 거래 IC 미개선")
# D: quality 양수 유지 + flow/value 음수 완화
q = fac.get("quality"); fl = fac.get("flow"); va = fac.get("value")
if q is not None:
    q=float(q)
    qok = "✅" if q>0 else "🔴"
    lines.append(f"  D 요인 재보정(quality): {qok} quality IC {q:+.3f}")
if fl is not None and va is not None:
    fl=float(fl); va=float(va)
    relieved = (fl > BASE_FAC['flow']) and (va > BASE_FAC['value'])
    lines.append(f"  D flow/value 단기역예측: {'✅ 완화' if relieved else '🟡 지속'} (flow {fl:+.3f} / value {va:+.3f})")
lines.append("")
lines.append("<i>판단: 신호 IC 양수 유지 + 거래 IC 회복 시 4종 패치 유효. 미회복 시 청산정책(RSI2 게이팅 R/수익 임계) 재조정 검토.</i>")

print("\n".join(lines))
PY
)

RESP=$(curl -s -m 15 -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d chat_id="${CHAT}" -d parse_mode=HTML --data-urlencode text="${MSG}")
echo "telegram resp: $RESP"
OK=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('ok',False))" 2>/dev/null)
[ "$OK" = "True" ] && echo "IC 재측정 발송 완료" || echo "telegram send failed"
