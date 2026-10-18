"""튜너 이전 가중치 복귀 — 검증 전용(쓰기 없음).

1) swing_weight_history 를 최초 배치의 old_weight 에서 앞으로 재생해
   현재 swing_factor_weights 와 일치하는지 확인한다(감사추적 완전성).
2) multi_factor.REGIME_WEIGHTS 가 '튜너 이전 + §22.AO-26 C momentum' 과
   같은지 확인한다(technical 에서 momentum 몫을 덜어낸 설계).
"""
import sys
sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.data.storage import PostgresStore
from engine_v4.ai.multi_factor import MultiFactorScorer
from engine_v4.config.settings import get_config

cfg = get_config()
pg = PostgresStore(cfg.pg_dsn)
with pg.get_conn() as c:
    hist = c.execute("SELECT changed_at, regime, factor, old_weight, new_weight, reason "
                     "FROM swing_weight_history ORDER BY changed_at, id").fetchall()
    cur = {(r["regime"], r["factor"]): float(r["weight"])
           for r in c.execute("SELECT regime, factor, weight FROM swing_factor_weights").fetchall()}

# ── 1) 재생 ────────────────────────────────────────────────────────────────
state, first_seen = {}, {}
for r in hist:
    k = (r["regime"], r["factor"])
    ow, nw = float(r["old_weight"]), float(r["new_weight"])
    if k not in state:
        first_seen[k] = (ow, r["reason"])
    else:
        if abs(state[k] - ow) > 1e-6:
            print(f"  ⚠️ 끊김 {k} {r['changed_at']:%m-%d}: 재생 {state[k]:.4f} vs 기록 old {ow:.4f}")
    state[k] = nw

print("1) 이력 재생 → 현재 상태 일치 여부")
bad = [k for k in cur if abs(cur[k] - state.get(k, cur[k])) > 1e-6]
print(f"   재생 가능 {len(state)}/32 · 불일치 {len(bad)}" + (f" {bad}" if bad else " ✅"))

# ── 2) 튜너 이전 상태 = 튜너 배치의 최초 old_weight ───────────────────────
pre = {}
for k, (ow, reason) in first_seen.items():
    pre[k] = ow
for k in cur:
    pre.setdefault(k, cur[k])      # 이력에 없던 팩터(flow/value)는 현재값 그대로
print("\n2) 튜너 이전 상태(이력 최초 old_weight) — momentum 신설 전")
for rg in ("TRENDING", "SIDEWAYS", "HIGH_VOL", "MIXED"):
    row = {f: pre[(rg, f)] for (r2, f) in pre if r2 == rg}
    print(f"   {rg:9s} 합={sum(row.values()):.4f}  " +
          " ".join(f"{f}={v:.2f}" for f, v in sorted(row.items()) if v))

# ── 3) REGIME_WEIGHTS 와 비교 ─────────────────────────────────────────────
RW = MultiFactorScorer.REGIME_WEIGHTS
print("\n3) REGIME_WEIGHTS == 튜너이전 + (technical→momentum 이전) ?")
for rg in ("TRENDING", "SIDEWAYS", "HIGH_VOL", "MIXED"):
    w = RW[rg]
    s = sum(w.values())
    mom = w["momentum"]
    tech_ok = abs((pre[(rg, "technical")] - mom) - w["technical"]) < 1e-6
    others = all(abs(pre[(rg, f)] - w[f]) < 1e-6
                 for f in ("sentiment", "quality", "macro", "pead", "flow", "value"))
    print(f"   {rg:9s} 합={s:.4f} {'✅' if abs(s-1)<1e-9 else '🔴'}"
          f" · technical {pre[(rg,'technical')]:.2f}−{mom:.2f}={w['technical']:.2f} "
          f"{'✅' if tech_ok else '🔴'} · 나머지 동일 {'✅' if others else '🔴'}")

# ── 4) 적용 차이 ─────────────────────────────────────────────────────────
print("\n4) 적용될 변경 (현재 → 복귀)")
n = 0
for rg in ("TRENDING", "SIDEWAYS", "HIGH_VOL", "MIXED"):
    for f, tgt in sorted(RW[rg].items()):
        c0 = cur[(rg, f)]
        if abs(c0 - tgt) > 1e-6:
            print(f"   {rg:9s} {f:10s} {c0:.4f} → {tgt:.4f}  ({tgt-c0:+.4f})")
            n += 1
print(f"   변경 {n}건 / 유지 {32-n}건")

print("\n5) 레짐 분화 (technical 가중치 범위)")
print("   현재  : " + " ".join(f"{rg[:4]}={cur[(rg,'technical')]:.4f}" for rg in RW))
print("   복귀후: " + " ".join(f"{rg[:4]}={RW[rg]['technical']:.4f}" for rg in RW))
