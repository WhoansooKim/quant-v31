#!/usr/bin/env bash
# 토요일 주간 하네스 사이클 결과 요약 (§22.AO-25 후속).
# 세션에서 `bash scripts/saturday_cycle_report.sh` 로 언제든 확인 가능.
set -uo pipefail
cd /home/quant/quant-v31
PSQL=(docker exec quant-postgres psql -U quant -d quantdb -c)

echo "════════ 토요일 주간 사이클 결과 ════════"
echo
echo "── 1) 사이클 잡 실행 이력 ──"
"${PSQL[@]}" "
SELECT step_name, status, created_at AT TIME ZONE 'Asia/Seoul' AS kst, left(details::text,60) AS detail
FROM swing_pipeline_log
WHERE step_name IN ('factor_ic','self_check','formula_lab','pead_collect')
  AND created_at > now() - interval '4 days'
ORDER BY created_at DESC LIMIT 10;"

echo "── 2) ①③ 검증 판정 (핵심) ──"
PYTHONPATH=/home/quant/quant-v31 /home/quant/miniconda3/envs/quant-v31/bin/python - <<'PY' 2>/dev/null
import sys, re; sys.path.insert(0,'/home/quant/quant-v31')
from engine_v4.data.storage import PostgresStore
from engine_v4.config.settings import get_config
from engine_v4.analysis.factor_ic import verdicts
pg=PostgresStore(get_config().pg_dsn)
with pg.get_conn() as c:
    rows=c.execute("""SELECT horizon_days, factor, ic, n_samples FROM swing_factor_ic
                      WHERE as_of=(SELECT MAX(as_of) FROM swing_factor_ic)""").fetchall()
hz={}
for r in rows:
    hz.setdefault(r["horizon_days"],{}).setdefault("factors",{})[r["factor"]]={"ic":float(r["ic"]),"n":r["n_samples"]}
v=verdicts({"horizons":hz})
for name,d in v.items():
    print(f"  {name}: {d['status']}")
    print(f"     {d['detail']}")
    if d.get("actionable"): print("     🔔 기준 충족 — 적용 검토 필요")
PY

echo "── 3) 자가진단 (최근) ──"
"${PSQL[@]}" "
SELECT check_name, status, severity, checked_at AT TIME ZONE 'Asia/Seoul' AS kst
FROM swing_self_check WHERE checked_at > now() - interval '4 days'
ORDER BY checked_at DESC, check_name LIMIT 8;"

echo "── 4) 가중치 자동 튜닝 변경분 ──"
"${PSQL[@]}" "
SELECT regime, factor, old_weight, new_weight, ROUND(ic_used,4) AS ic
FROM swing_weight_history WHERE changed_at > now() - interval '4 days'
ORDER BY changed_at DESC LIMIT 10;"

echo "── 5) 수식 신호 검증 ──"
"${PSQL[@]}" "
SELECT status, COUNT(*) FROM swing_signal_formulas
WHERE validated_at > now() - interval '4 days' GROUP BY 1;"
"${PSQL[@]}" "
SELECT left(name,34) AS name, ic_train, ic_test FROM swing_signal_formulas
WHERE status='validated' ORDER BY ic_min DESC NULLS LAST LIMIT 3;"
