#!/usr/bin/env python
"""LSTM 시간분할 워크포워드 확정 검정 (§22.AO-47).

`lstm_validate.py` 는 경계 **하나**(2026-08-07)로 B안 정확도 51.79% / 기준선 51.76% 를 얻었다.
경계 한 개는 표본 하나다 — 판정에 쓰려면 ① 여러 경계 ② 시드 분산 ③ 신뢰구간이 있어야 한다.

🔴 추가로 바로잡는 것: **엠바고**. 타깃이 5일 전방이라 학습 마지막 5일 샘플의 타깃 구간이
   검증 구간과 겹친다. 학습에서 date > 분할경계-5영업일 샘플을 버린다.
🔴 신뢰구간은 **날짜 블록 부트스트랩**으로 낸다. 같은 날 200종목은 시장 전체 움직임을 공유하므로
   표본 7,133개가 아니라 날짜 블록 ~36개가 유효 표본이다([[compare-at-matched-return]] 과 같은 이유:
   표본 성질을 무시한 구간은 판정이 아니다).
"""
from __future__ import annotations
import argparse, sys, time
import numpy as np, pandas as pd

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore
from scripts.lstm_validate import load_panel, seqs, fit_eval, norm, LOOKBACK, HORIZON


def auc_of(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    if len(np.unique(y > 0.5)) < 2:
        return float("nan")
    return float(roc_auc_score(y > 0.5, p))


def block_ci(dates: np.ndarray, y: np.ndarray, p: np.ndarray, reps: int = 2000):
    """날짜 블록 부트스트랩 → (AUC CI, 정확도-기준선 CI)."""
    uq = np.unique(dates)
    idx = {d: np.where(dates == d)[0] for d in uq}
    rng = np.random.default_rng(0)
    aucs, edges = [], []
    for _ in range(reps):
        pick = rng.choice(uq, size=len(uq), replace=True)
        sel = np.concatenate([idx[d] for d in pick])
        ys, ps = y[sel], p[sel]
        a = auc_of(ys, ps)
        if a == a:
            aucs.append(a)
        acc = float(((ps > 0.5) == (ys > 0.5)).mean())
        edges.append((acc - float((ys > 0.5).mean())) * 100)
    q = lambda v: (round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4))
    return q(aucs), q(edges)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--seeds", type=int, default=2)
    a = ap.parse_args()

    pg = PostgresStore(get_config().pg_dsn)
    t0 = time.time()
    panel = load_panel(pg, a.days, a.top)
    S = seqs(panel)
    dates = np.array([s[1] for s in S])
    X = np.stack([s[2] for s in S]).astype(np.float32)
    y = np.array([s[3] for s in S], dtype=np.float32)
    o = np.argsort(dates, kind="stable")
    X, y, dates = X[o], y[o], dates[o]
    uq = np.unique(dates)
    print(f"시퀀스 {len(S):,}건 / 날짜 {len(uq)}개 {uq[0]} ~ {uq[-1]}  ({time.time()-t0:.0f}초)",
          flush=True)

    # 뒤쪽 40% 를 fold 개로 쪼개 검증, 학습은 확장 윈도우 + 5영업일 엠바고
    start = int(len(uq) * 0.60)
    bounds = np.linspace(start, len(uq), a.folds + 1).astype(int)
    rows, pool = [], []
    for k in range(a.folds):
        d0, d1 = uq[bounds[k]], uq[bounds[k + 1] - 1]
        te = (dates >= d0) & (dates <= d1)
        emb = uq[max(bounds[k] - HORIZON, 0)]           # 🔴 엠바고: 타깃 겹침 제거
        tr = dates < emb
        if tr.sum() < 2000 or te.sum() < 200:
            continue
        Xtr, Xte = norm(X[tr], X[te])
        for sd_ in range(a.seeds):
            acc, auc, pr = fit_eval(Xtr, y[tr], Xte, y[te], a.epochs, seed=sd_)
            b = float((y[te] > 0.5).mean())
            rows.append({"fold": k + 1, "seed": sd_, "검증시작": str(d0), "검증끝": str(d1),
                         "학습": int(tr.sum()), "검증": int(te.sum()),
                         "기준선": round(b * 100, 2), "정확도": round(acc * 100, 2),
                         "AUC": round(auc, 4), "기준선대비": round((acc - b) * 100, 2)})
            print(rows[-1], flush=True)
            if sd_ == 0:
                pool.append((dates[te], y[te], pr))

    df = pd.DataFrame(rows)
    print("\n" + df.to_string(index=False), flush=True)
    print(f"\n폴드·시드 {len(df)}개  기준선대비 중앙 {df['기준선대비'].median():+.2f}%p "
          f"평균 {df['기준선대비'].mean():+.2f}%p  AUC 중앙 {df['AUC'].median():.4f}")
    print(f"기준선을 넘은 경우: {(df['기준선대비'] > 0).sum()}/{len(df)}")

    dd = np.concatenate([p[0] for p in pool])
    yy = np.concatenate([p[1] for p in pool])
    pp = np.concatenate([p[2] for p in pool])
    (al, ah), (el, eh) = block_ci(dd, yy, pp)
    print(f"\n통합 n={len(yy):,} (날짜블록 {len(np.unique(dd))}개)")
    print(f"  AUC        {auc_of(yy, pp):.4f}  95%CI [{al:.4f}, {ah:.4f}]   (무작위=0.5)")
    print(f"  기준선대비 {((pp>0.5)==(yy>0.5)).mean()*100 - (yy>0.5).mean()*100:+.2f}%p"
          f"  95%CI [{el:+.2f}, {eh:+.2f}]%p   (효과없음=0)")
    print(f"\n총 {time.time()-t0:.0f}초")
