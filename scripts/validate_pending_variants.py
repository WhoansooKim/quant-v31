"""pending 변이 일괄 백테스트 (§22.AO 후속).

DB 뮤텍스(_claim_slot)를 그대로 쓰므로 스케줄러 잡과 충돌하지 않는다.
한 건 실패해도 다음으로 넘어가고, 진행 상황을 한 줄씩 남긴다.
"""
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("validate_pending")

sys.path.insert(0, "/home/quant/quant-v31")

from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore
from engine_v4.harness.auto_backtest import recover_stuck_testing, validate_variant

pg = PostgresStore(get_config().pg_dsn)
recover_stuck_testing(pg)

from engine_v4.harness.auto_backtest import _FIELD_MAP, _FLAG_MAP, _baseline_config

# 러너가 시뮬레이션하지 않는 키만 건드리는 변이는 baseline 과 100% 동일한 백테스트가
# 돌아 delta 가 정확히 0.0 으로 나온다 → 품질과 무관한 부당 기각. 아예 건너뛴다(§22.AO-3).
EFFECTIVE = set(_FIELD_MAP) | set(_FLAG_MAP)

# 매핑은 됐지만 실제로는 결과를 못 바꾸는 키 (2026-08-18 배치에서 전건 실증, §22.AO-5).
#   atr_trailing_multiplier : 트레일링 청산 0건 — time_stop 이 선점
#   rsi2_exit_threshold     : rsi2_exit_min_r=2.0 게이트에 막힘 (임계 60/70/80/95 전부 동일)
#   take_profit_pct         : use_atr_trailing=True 면 고정 TP 를 검사하지 않음(의도된 설계)
# 중복 판정 서명에서 빼야 v33 같은 '무력 키만 다른 쌍둥이'가 걸러진다.
INERT = {"atr_trailing_multiplier", "rsi2_exit_threshold", "take_profit_pct"}

with pg.get_conn() as conn:
    all_rows = conn.execute(
        "SELECT variant_id, name, config_diff FROM swing_strategy_variants "
        "WHERE status = 'pending' ORDER BY created_at, variant_id"
    ).fetchall()

BASE = _baseline_config(pg)


def _same_as_baseline(key, val) -> bool:
    """변이 값이 현행 config 와 같으면 no-op (variant 27 유형)."""
    cur = BASE.get(key)
    if cur is None:
        return False
    try:
        return abs(float(cur) - float(val)) < 1e-9
    except (TypeError, ValueError):
        return str(cur).strip().lower() == str(val).strip().lower()


rows, skipped, dupes, noops = [], [], [], []
seen: dict[str, int] = {}
for r in all_rows:
    diff = r["config_diff"] or {}
    if isinstance(diff, str):
        import json as _json
        diff = _json.loads(diff)
    eff = {k: v for k, v in diff.items() if k in EFFECTIVE}
    if not eff:
        skipped.append(r)
        continue
    # 현행값과 동일한 항목은 제외 — 전부 동일하면 아무것도 안 바꾸는 변이다.
    eff = {k: v for k, v in eff.items() if not _same_as_baseline(k, v)}
    if not eff:
        noops.append(r)
        continue
    # 무력 키를 뺀 서명이 같으면 러너 관점에서 완전히 동일한 변이 → 대표 1건만 평가.
    # 폐기가 아니라 pending 보류: 러너가 나머지 키를 지원하게 되면 다시 살아난다.
    sig_keys = {k: v for k, v in eff.items() if k not in INERT}
    if not sig_keys:
        skipped.append(r)     # 무력 키만 남음 → 측정 불가
        continue
    sig = repr(sorted(sig_keys.items()))
    if sig in seen:
        dupes.append((r, seen[sig]))
        continue
    seen[sig] = r["variant_id"]
    rows.append(r)

if noops:
    log.warning(
        f"현행값과 동일해 무의미한 {len(noops)}건 건너뜀(pending 유지): "
        + ", ".join(f"{r['variant_id']}({r['name']})" for r in noops)
    )

if skipped:
    log.warning(
        f"러너 미구현 키만 가진 {len(skipped)}건 건너뜀(pending 유지): "
        + ", ".join(f"{r['variant_id']}({r['name']})" for r in skipped)
    )
if dupes:
    log.warning(
        f"유효키 중복 {len(dupes)}건 건너뜀(pending 보류): "
        + ", ".join(f"{r['variant_id']}→대표 {rep}" for r, rep in dupes)
    )

log.info(f"=== 평가가능 {len(rows)}건 검증 시작 (전체 pending {len(all_rows)}건) ===")
t_all = time.time()
tally = {"validated": 0, "rejected": 0, "other": 0}

for i, r in enumerate(rows, 1):
    vid, name = r["variant_id"], r["name"]
    t0 = time.time()
    try:
        res = validate_variant(pg, vid)
        st = res.get("status", "?")
        tally[st if st in tally else "other"] += 1
        log.info(
            f"[{i}/{len(rows)}] variant {vid} ({name}) -> {st} "
            f"| period={res.get('primary_period')} trades={res.get('variant_trades')} "
            f"| sqnΔ={res.get('sqn_delta')} sharpeΔ={res.get('sharpe_delta')} "
            f"| reason={res.get('rejection_reason') or res.get('reason')} "
            f"| {time.time() - t0:.0f}s"
        )
    except Exception as e:
        tally["other"] += 1
        log.exception(f"[{i}/{len(rows)}] variant {vid} ({name}) FAILED: {e}")

log.info(
    f"=== 완료: {tally} | 총 {(time.time() - t_all) / 60:.1f}분 ==="
)
