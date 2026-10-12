#!/usr/bin/env python
"""LSTM 게이트 검증 — 분할을 종목 기준에서 시간 기준으로 바꾸면 정확도가 남는가 (§22.AO-47).

왜: `intersection_technical_min=60` 은 이름과 달리 **전부 LSTM 게이트**다.
  소급 실측 — 15.6년 289,394 후보에서 가격지표 부분(tech_base) 최소 **60.1**, 60 미만 **0건**.
  three조건(추세25+돌파20+거래량15=60점)을 통과하면 모멘텀 0점이어도 60 이상이기 때문이다.
  그런데 라이브에서는 이 게이트가 공급의 37% 를 거른다 → 거르는 주체는 LSTM 블렌딩이다
  (technical = 가격점수×0.5 + up_probability×100×0.5).

🔴 라이브 학습 코드(`ai/lstm_predictor.py:train`)의 검증 결함 2개:
  1) **분할이 종목 기준이다.** all_X 를 종목별로 concat 한 뒤 X_all[:80%] / X_all[80%:] 로
     자른다. 주석은 "time-ordered, not random" 이지만 concat 순서가 종목-major 이므로
     학습/검증이 **같은 날짜 구간을 공유**한다 → 시장 전체 움직임이 양쪽에 새어 든다.
  2) **정규화가 전 구간 통계를 쓴다.** means/stds 를 400일 창 전체로 계산해 모든 샘플에
     적용한다 → t 시점 샘플이 t 이후 데이터의 평균·표준편차로 정규화된다.
  추가로 타깃이 5일 전방이라 인접 샘플이 4일을 공유한다(유효 표본 ≈ n/5).

이 스크립트는 **같은 데이터·같은 모델**로 분할과 정규화만 바로잡아 정확도를 다시 재고,
기준선(항상 '상승' 예측 시 정확도 = 상승 비율)과 대조한다.
"""
from __future__ import annotations
import argparse, sys, time
import numpy as np, pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.ai.lstm_predictor import LSTMModel, _compute_features, _make_target
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

LOOKBACK, HORIZON = 60, 5


def load_panel(pg, days: int, top: int):
    """상위 유동성 종목의 가격 패널. 라이브는 daily_prices 를 쓰지만 과거 구간은
    hist_prices_adj(분할 역조정)가 유일한 15년 소스다."""
    with pg.get_conn() as c:
        return pd.DataFrame(c.execute("""
            WITH liq AS (
              SELECT symbol, avg(dollar_vol_20d) dv FROM hist_indicators
              WHERE time > (SELECT max(time) FROM hist_indicators) - (%s || ' days')::interval
              GROUP BY symbol ORDER BY dv DESC NULLS LAST LIMIT %s)
            SELECT p.symbol, p.time::date AS time, p.open::float, p.high::float,
                   p.low::float, p.close::float, p.volume::float,
                   h.sma_50::float AS sma50, h.sma_200::float AS sma200
            FROM hist_prices_adj p
            JOIN liq ON liq.symbol = p.symbol
            LEFT JOIN hist_indicators h ON h.symbol=p.symbol AND h.time=p.time
            WHERE p.time > (SELECT max(time) FROM hist_prices_adj) - (%s || ' days')::interval
            ORDER BY p.symbol, p.time""", (days, top, days)).fetchall())


def seqs(panel: pd.DataFrame):
    """종목별 (X, y, date) — 정규화는 **하지 않는다**(분할 후에 해야 하므로)."""
    out = []
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("time").reset_index(drop=True)
        if len(g) < LOOKBACK + HORIZON + 60:
            continue
        f = _compute_features(g)
        t = _make_target(g["close"], HORIZON)
        fv, tv, dv = f.values, t.values, g["time"].values
        for i in range(LOOKBACK, len(fv) - HORIZON):
            s = fv[i - LOOKBACK:i]
            if np.isnan(s).any() or np.isnan(tv[i]):
                continue
            out.append((sym, dv[i], s, tv[i]))
    return out


def fit_eval(Xtr, ytr, Xte, yte, epochs: int, seed: int = 0):
    torch.manual_seed(seed)
    m = LSTMModel(input_size=Xtr.shape[2], hidden_size=64, num_layers=2)
    opt = torch.optim.Adam(m.parameters(), lr=0.001)
    crit = nn.BCELoss()
    dl = DataLoader(TensorDataset(torch.from_numpy(Xtr), torch.from_numpy(ytr)),
                    batch_size=256, shuffle=True)
    m.train()
    best, bad = float("inf"), 0
    for _ in range(epochs):
        tot = 0.0
        for bx, by in dl:
            opt.zero_grad()
            loss = crit(m(bx), by)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            tot += loss.item()
        avg = tot / len(dl)
        if avg < best - 1e-4:
            best, bad = avg, 0
        else:
            bad += 1
            if bad >= 5:
                break
    m.eval()
    with torch.no_grad():
        pr = m(torch.from_numpy(Xte)).numpy().ravel()
    acc = float(((pr > 0.5) == (yte.ravel() > 0.5)).mean())
    try:
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(yte.ravel(), pr))
    except Exception:
        auc = float("nan")
    return acc, auc, pr


def norm(tr: np.ndarray, te: np.ndarray):
    """🔴 정규화 통계는 **학습 구간에서만** 뽑는다 (라이브는 전 구간에서 뽑는다)."""
    mu = np.nanmean(tr.reshape(-1, tr.shape[2]), axis=0)
    sd = np.nanstd(tr.reshape(-1, tr.shape[2]), axis=0)
    sd[sd == 0] = 1
    return ((tr - mu) / sd).astype(np.float32), ((te - mu) / sd).astype(np.float32)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=400, help="라이브와 같은 400일이 기본")
    ap.add_argument("--top", type=int, default=200)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--folds", type=int, default=1, help=">1 이면 시간 워크포워드")
    a = ap.parse_args()
    pg = PostgresStore(get_config().pg_dsn)
    t0 = time.time()
    panel = load_panel(pg, a.days, a.top)
    print(f"패널 {len(panel):,}행 / {panel.symbol.nunique()}종목 "
          f"{panel.time.min()} ~ {panel.time.max()}", flush=True)
    S = seqs(panel)
    print(f"시퀀스 {len(S):,}건  ({time.time()-t0:.0f}초)", flush=True)
    syms = np.array([s[0] for s in S])
    dates = np.array([s[1] for s in S])
    X = np.stack([s[2] for s in S]).astype(np.float32)
    y = np.array([s[3] for s in S], dtype=np.float32)   # 1-D (라이브 _prepare_sequences 와 동일 — 모델 출력도 1-D)
    base = float((y > 0.5).mean())
    print(f"\n기준선: '항상 상승' 정확도 = 상승 비율 = **{base*100:.2f}%**")

    rows = []
    # ── A. 라이브 방식 재현: 종목 기준 분할 + 전구간 정규화
    order = np.lexsort((dates, syms))            # 종목-major (라이브 concat 순서)
    Xs, ys = X[order], y[order]
    cut = int(len(Xs) * 0.8)
    mu = np.nanmean(Xs.reshape(-1, Xs.shape[2]), axis=0)
    sd = np.nanstd(Xs.reshape(-1, Xs.shape[2]), axis=0); sd[sd == 0] = 1
    Xn = ((Xs - mu) / sd).astype(np.float32)     # 🔴 전 구간 통계 (누출)
    acc, auc, _ = fit_eval(Xn[:cut], ys[:cut], Xn[cut:], ys[cut:], a.epochs)
    rows.append({"방식": "A. 라이브 재현 (종목분할 + 전구간정규화)",
                 "학습": cut, "검증": len(Xs)-cut, "정확도": round(acc*100, 2),
                 "AUC": round(auc, 4), "기준선대비": round((acc-base)*100, 2)})
    print(rows[-1], flush=True)

    # ── B. 시간 기준 분할 + 인과적 정규화
    o2 = np.argsort(dates, kind="stable")
    Xt, yt, dt = X[o2], y[o2], dates[o2]
    cut2 = int(len(Xt) * 0.8)
    split_date = dt[cut2]
    Xtr, Xte = norm(Xt[:cut2], Xt[cut2:])
    acc, auc, _ = fit_eval(Xtr, yt[:cut2], Xte, yt[cut2:], a.epochs)
    rows.append({"방식": f"B. 시간분할 + 인과정규화 (경계 {split_date})",
                 "학습": cut2, "검증": len(Xt)-cut2, "정확도": round(acc*100, 2),
                 "AUC": round(auc, 4), "기준선대비": round((acc-base)*100, 2)})
    print(rows[-1], flush=True)

    # ── C. 누출 요인 분리: 시간분할 + 전구간정규화 (정규화만 누출)
    muA = np.nanmean(Xt.reshape(-1, Xt.shape[2]), axis=0)
    sdA = np.nanstd(Xt.reshape(-1, Xt.shape[2]), axis=0); sdA[sdA == 0] = 1
    XnA = ((Xt - muA) / sdA).astype(np.float32)
    acc, auc, _ = fit_eval(XnA[:cut2], yt[:cut2], XnA[cut2:], yt[cut2:], a.epochs)
    rows.append({"방식": "C. 시간분할 + 전구간정규화 (정규화만 누출)",
                 "학습": cut2, "검증": len(Xt)-cut2, "정확도": round(acc*100, 2),
                 "AUC": round(auc, 4), "기준선대비": round((acc-base)*100, 2)})
    print(rows[-1], flush=True)

    print("\n" + pd.DataFrame(rows).to_string(index=False))
    print(f"\n총 {time.time()-t0:.0f}초")
