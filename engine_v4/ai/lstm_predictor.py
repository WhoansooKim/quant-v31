"""LSTMPredictor — 5일 후 상승 확률 예측 (PyTorch CPU).

2-layer 64-unit LSTM, 60-day lookback, 10 features, 5-day horizon.
주간 재학습 (토요일) + 일일 예측.

§22.AO-47 에서 검증 결함 **4개** 를 고쳤다. 이 모델 점수는 `intersection_technical_min=60`
게이트를 통해 라이브 진입 공급의 37% 를 거르고 있었다 — 그런데 보고 정확도 0.57~0.70 은
아래 결함들이 만든 값이었다.

🔴 1) 분할이 종목 기준이었다. all_X 를 종목별로 concat 한 뒤 `X_all[:80%]` 로 잘랐다.
     주석은 "time-ordered" 였지만 concat 순서가 종목-major 이므로 학습/검증이 **같은 날짜**를
     공유했다 → 시장 전체 움직임이 양쪽에 새어 들었다. 실측: 이 분할만 바로잡으면
     기준선대비 +4.13%p → **+0.03%p**.
🔴 2) 표준화가 전 구간 통계였다. means/stds 를 창 전체에서 뽑아 t 시점 샘플을 t 이후
     데이터로 표준화했다(선행정보). 기여는 +0.03%p 로 작았지만 누출은 누출이다.
🔴 3) 종목당 학습 시퀀스가 11개뿐이었다. days=400(거래일 275) 인데 sma200 이 199행을
     먹고 lookback 60 + horizon 5 가 더 먹어 i∈[259,270) → 11개. 200종목 × 11 = 2,197 =
     DB 에 기록된 total_samples 그 값이다. 게다가 그 11개 날짜가 **모든 종목에서 동일**해서
     (1) 의 종목 분할이 사실상 "같은 2주를 양쪽에 두는" 분할이 됐다.
🔴 4) 예측 경로에서 특성 2개가 항상 0 이었다. predict 는 days=lookback+100=160(거래일 109)
     을 받아 sma200 이 **100% 결손** → price_sma200_pct · sma50_sma200_pct 가 전부 NaN →
     `nan_to_num(nan=0.0)` 이 조용히 0 으로 메웠다. 학습은 실제 z 값을 봤다. 학습/서빙
     불일치다 — up_probability 가 0.0004 같은 극값으로 포화된 이유([[silent-failure-neutral-default]]).

수정: 학습·예측이 **같은 창(train_days)** 을 쓰고, 표준화는 시점 t 까지의 이동통계로만
하고(창 길이 비의존 → 1·2·4 동시 해소), 분할은 **날짜 경계 + horizon 엠바고**로 하고,
정확도는 반드시 **기준선(상승 비율)** 과 함께 기록한다 — 0.65 를 실력으로 읽을 수 없게.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

# ── Model save directory ──
MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
MODEL_DIR.mkdir(exist_ok=True)


# ═══════════════════════════════════════════════════════════
# LSTM Model Definition
# ═══════════════════════════════════════════════════════════

class LSTMModel(nn.Module):
    """2-layer LSTM for binary classification (up/down prediction)."""

    def __init__(self, input_size: int = 10, hidden_size: int = 64,
                 num_layers: int = 2, dropout: float = 0.2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
            nn.Sigmoid(),
        )

    def forward(self, x):
        # x: (batch, seq_len, features)
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # last timestep
        return self.fc(last_hidden).squeeze(-1)


# ═══════════════════════════════════════════════════════════
# Feature Engineering
# ═══════════════════════════════════════════════════════════

def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """10개 기술적 특성 계산.

    Input: DataFrame with columns [close, high, low, volume, sma50, sma200]
    Output: DataFrame with 10 normalized features.
    """
    feat = pd.DataFrame(index=df.index)

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    sma50 = df["sma50"].astype(float) if "sma50" in df else close.rolling(50).mean()
    sma200 = df["sma200"].astype(float) if "sma200" in df else close.rolling(200).mean()

    # 1) Returns (5d, 10d, 20d)
    feat["ret_5d"] = close.pct_change(5)
    feat["ret_10d"] = close.pct_change(10)
    feat["ret_20d"] = close.pct_change(20)

    # 2) Volatility (20d rolling std of returns)
    daily_ret = close.pct_change()
    feat["vol_20d"] = daily_ret.rolling(20).std()

    # 3) Volume ratio (vs 20d avg)
    vol_ma20 = volume.rolling(20).mean()
    feat["vol_ratio"] = volume / vol_ma20.replace(0, np.nan)

    # 4) RSI (14-day)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    feat["rsi_14"] = 100 - (100 / (1 + rs))

    # 5) Price vs SMA50 (%)
    feat["price_sma50_pct"] = (close - sma50) / sma50.replace(0, np.nan) * 100

    # 6) Price vs SMA200 (%)
    feat["price_sma200_pct"] = (close - sma200) / sma200.replace(0, np.nan) * 100

    # 7) SMA50 vs SMA200 (trend strength)
    feat["sma50_sma200_pct"] = (sma50 - sma200) / sma200.replace(0, np.nan) * 100

    # 8) High-Low range (volatility proxy)
    feat["hl_range_pct"] = (high - low) / close.replace(0, np.nan) * 100

    return feat


def _make_target(close: pd.Series, horizon: int = 5) -> pd.Series:
    """5일 후 상승 여부 (binary: 1=up, 0=down)."""
    future_ret = close.shift(-horizon) / close - 1
    return (future_ret > 0).astype(float)


def _causal_zscore(feat: pd.DataFrame, window: int = 252,
                   min_periods: int = 60, clip: float = 10.0) -> pd.DataFrame:
    """각 시점 t 를 **t 까지의** 이동통계로만 표준화한다 (결함 2·4 해소).

    창 전체 통계를 쓰면 t 시점 샘플이 t 이후 데이터로 표준화된다(선행정보). 또 학습 400일
    창과 예측 160일 창이 같은 날짜에 서로 다른 평균·표준편차를 만들어 학습/서빙이 어긋났다.
    이동통계는 **창 길이에 의존하지 않으므로** 두 문제가 같이 사라진다.
    표준편차 0 은 NaN 으로 둔다 — 0 으로 메우면 상수 특성이 조용히 섞인다."""
    mu = feat.rolling(window, min_periods=min_periods).mean()
    sd = feat.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    return ((feat - mu) / sd).clip(-clip, clip)


# ═══════════════════════════════════════════════════════════
# LSTM Predictor Class
# ═══════════════════════════════════════════════════════════

class LSTMPredictor:
    """LSTM 기반 모멘텀 예측기.

    - 학습: walk-forward (1년 학습 → 3개월 테스트)
    - 예측: 60일 lookback → 5일 후 상승 확률
    - 모델 저장/로드: PyTorch state_dict
    """

    def __init__(self, pg: PostgresStore, cache=None,
                 lookback: int = 60, horizon: int = 5,
                 hidden_size: int = 64, num_layers: int = 2,
                 epochs: int = 50, batch_size: int = 32,
                 learning_rate: float = 0.001,
                 train_days: int = 1100, zwin: int = 252):
        self.pg = pg
        self.cache = cache
        self.lookback = lookback
        self.horizon = horizon
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = learning_rate
        # 🔴 학습과 예측이 **같은 창**을 써야 한다(결함 4). sma200(199행) + 이동표준화
        #    창(252) + lookback(60) + horizon(5) 이 모두 들어가야 시퀀스가 생기므로
        #    거래일 520 행 ≈ 달력 1,100 일이 하한이다. 예측도 같은 값을 쓴다.
        self.train_days = train_days
        self.zwin = zwin
        self.n_features = 10
        self.model: LSTMModel | None = None
        self._version = "v1"

        # 최신 모델 로드 시도
        self._load_latest_model()

    def _load_latest_model(self):
        """저장된 최신 모델 로드."""
        model_path = MODEL_DIR / f"lstm_{self._version}.pt"
        if model_path.exists():
            try:
                self.model = LSTMModel(
                    input_size=self.n_features,
                    hidden_size=self.hidden_size,
                    num_layers=self.num_layers,
                )
                self.model.load_state_dict(torch.load(model_path, weights_only=True))
                self.model.eval()
                logger.info(f"LSTM model loaded: {model_path}")
            except Exception as e:
                logger.warning(f"LSTM model load failed: {e}")
                self.model = None

    @property
    def is_available(self) -> bool:
        """학습된 모델이 있는지 확인."""
        return self.model is not None

    # ─── Data Preparation ─────────────────────────────────

    def _get_price_data(self, symbol: str, days: int = 400,
                        min_rows: int = 0) -> pd.DataFrame | None:
        """DB에서 가격 데이터 조회 → DataFrame."""
        rows = self.pg.get_daily_prices(symbol, days=days)
        required = min_rows if min_rows > 0 else (self.lookback + self.horizon + 50)
        if not rows or len(rows) < required:
            return None

        df = pd.DataFrame(rows)
        for col in ["close", "high", "low", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # SMA 계산 (DB에 없을 수 있음)
        if "sma50" not in df.columns:
            df["sma50"] = df["close"].rolling(50).mean()
        if "sma200" not in df.columns:
            df["sma200"] = df["close"].rolling(200).mean()

        return df.dropna(subset=["close"]).reset_index(drop=True)

    def _prepare_sequences(self, features: np.ndarray, targets: np.ndarray,
                           dates: np.ndarray
                           ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """시계열 시퀀스 생성 (lookback window).

        🔴 **날짜를 함께 돌려준다.** 날짜가 없으면 시간 기준 분할을 할 수 없고, 종목별
           concat 을 인덱스로 자르는 순간 그것은 종목 분할이다(결함 1)."""
        X, y, d = [], [], []
        for i in range(self.lookback, len(features) - self.horizon):
            seq = features[i - self.lookback:i]
            if not np.isnan(seq).any() and not np.isnan(targets[i]):
                X.append(seq)
                y.append(targets[i])
                d.append(dates[i])
        return (np.array(X, dtype=np.float32), np.array(y, dtype=np.float32),
                np.array(d, dtype="datetime64[D]"))

    # ─── Training ─────────────────────────────────────────

    def train(self, symbols: list[str] | None = None) -> dict:
        """전체 유니버스 또는 지정 종목으로 LSTM 학습.

        **날짜 경계 80/20 분할 + horizon 엠바고 + 인과적 표준화** (§22.AO-47).
        Returns: {accuracy, baseline, edge_vs_baseline, auc_roc, train_samples, ...}
        """
        start = time.time()

        if not symbols:
            universe = self.pg.get_universe()
            symbols = [u["symbol"] for u in universe]

        logger.info(f"LSTM training started: {len(symbols)} symbols")

        all_X, all_y, all_d = [], [], []

        for symbol in symbols:
            try:
                df = self._get_price_data(symbol, days=self.train_days)
                if df is None:
                    continue

                # 🔴 표준화는 시점 t 까지의 이동통계로만 — 분할 전에 해도 누출이 없다.
                feat_norm = _causal_zscore(_compute_features(df), self.zwin)
                target = _make_target(df["close"], self.horizon)

                X, y, d = self._prepare_sequences(
                    feat_norm.values, target.values,
                    pd.to_datetime(df["time"]).values.astype("datetime64[D]"))
                if len(X) > 0:
                    all_X.append(X)
                    all_y.append(y)
                    all_d.append(d)
            except Exception as e:
                logger.debug(f"LSTM data prep {symbol}: {e}")
                continue

        if not all_X:
            logger.warning("LSTM training: no valid data")
            return {"error": "No valid training data"}

        X_all = np.concatenate(all_X)
        y_all = np.concatenate(all_y)
        d_all = np.concatenate(all_d)

        # ── 🔴 시간 기준 분할 (결함 1) ──────────────────────────
        # concat 은 종목-major 다. 인덱스로 자르면 "뒤쪽 20% 종목"이 검증이 되고
        # 학습/검증이 같은 날짜를 공유한다. 반드시 **날짜**로 자른다.
        order = np.argsort(d_all, kind="stable")
        X_all, y_all, d_all = X_all[order], y_all[order], d_all[order]
        uniq_dates = np.unique(d_all)
        if len(uniq_dates) < 60:
            msg = (f"날짜 {len(uniq_dates)}개뿐 — 시간 분할 불가. "
                   f"train_days={self.train_days} 를 늘려야 한다(결함 3).")
            logger.error(f"LSTM training: {msg}")
            return {"error": msg}

        cut = int(len(uniq_dates) * 0.8)
        split_date = uniq_dates[cut]
        # 🔴 엠바고: 타깃이 horizon 일 전방이라 학습 끝 horizon 일의 타깃 구간이
        #    검증 구간과 겹친다. 그 샘플을 버린다.
        embargo_date = uniq_dates[max(cut - self.horizon, 0)]
        tr_mask = d_all < embargo_date
        te_mask = d_all >= split_date
        X_train, y_train = X_all[tr_mask], y_all[tr_mask]
        X_test, y_test = X_all[te_mask], y_all[te_mask]
        if len(X_train) < 500 or len(X_test) < 100:
            msg = f"표본 부족: 학습 {len(X_train)} / 검증 {len(X_test)}"
            logger.error(f"LSTM training: {msg}")
            return {"error": msg}

        logger.info(f"LSTM data: {len(X_train)} train (~{uniq_dates[0]}~{embargo_date}), "
                    f"{len(X_test)} test ({split_date}~{uniq_dates[-1]}), "
                    f"{len(uniq_dates)} dates, embargo {self.horizon}d")

        # Create model
        model = LSTMModel(
            input_size=self.n_features,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
        )
        optimizer = torch.optim.Adam(model.parameters(), lr=self.lr)
        criterion = nn.BCELoss()

        # Training
        train_dataset = TensorDataset(
            torch.from_numpy(X_train), torch.from_numpy(y_train))
        train_loader = DataLoader(
            train_dataset, batch_size=self.batch_size, shuffle=True)

        model.train()
        best_loss = float("inf")
        patience_counter = 0

        for epoch in range(self.epochs):
            epoch_loss = 0.0
            for batch_X, batch_y in train_loader:
                optimizer.zero_grad()
                pred = model(batch_X)
                loss = criterion(pred, batch_y)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()

            avg_loss = epoch_loss / len(train_loader)

            # Early stopping
            if avg_loss < best_loss - 0.001:
                best_loss = avg_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= 10:
                    logger.info(f"LSTM early stop at epoch {epoch+1}")
                    break

            if (epoch + 1) % 10 == 0:
                logger.info(f"LSTM epoch {epoch+1}/{self.epochs}: loss={avg_loss:.4f}")

        # Evaluation
        model.eval()
        with torch.no_grad():
            test_pred = model(torch.from_numpy(X_test)).numpy()

        # Accuracy
        pred_binary = (test_pred > 0.5).astype(float)
        accuracy = float(np.mean(pred_binary == y_test))

        # 🔴 기준선 = '항상 상승' 예측 정확도 = 검증 구간 상승 비율.
        #    이게 없으면 정확도 0.65 를 실력으로 읽는다. 판정은 **기준선대비**로만 한다.
        baseline = float(np.mean(y_test > 0.5))
        baseline = max(baseline, 1.0 - baseline)   # 다수 클래스를 항상 찍는 쪽
        edge = accuracy - baseline

        # AUC-ROC
        try:
            from sklearn.metrics import roc_auc_score
            auc = float(roc_auc_score(y_test, test_pred))
        except Exception:
            auc = 0.0

        elapsed = time.time() - start

        # Save model
        model_path = MODEL_DIR / f"lstm_{self._version}.pt"
        torch.save(model.state_dict(), model_path)
        self.model = model
        logger.info(f"LSTM model saved: {model_path}")

        # Save training metadata to DB
        result = {
            "version": self._version,
            "accuracy": round(accuracy, 4),
            "baseline": round(baseline, 4),
            "edge_vs_baseline": round(edge, 4),
            "auc_roc": round(auc, 4),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "n_dates": int(len(uniq_dates)),
            "train_start": str(uniq_dates[0]),
            "train_end": str(embargo_date),
            "test_start": str(split_date),
            "test_end": str(uniq_dates[-1]),
            "epochs_trained": epoch + 1,
            "symbols_used": len(symbols),
            "elapsed_sec": round(elapsed, 1),
            "model_path": str(model_path),
        }

        self._save_model_metadata(result)
        logger.info(f"LSTM training done: accuracy={accuracy:.4f} "
                    f"baseline={baseline:.4f} edge={edge:+.4f} "
                    f"AUC={auc:.4f}, {elapsed:.1f}s")
        if edge <= 0:
            logger.warning(f"🔴 LSTM 기준선대비 {edge:+.4f} — 예측력 없음. "
                           f"multi_factor 블렌딩은 lstm_min_edge 에서 걸러진다.")

        return result

    def _save_model_metadata(self, result: dict) -> None:
        """학습 메타데이터 DB 저장."""
        try:
            with self.pg.get_conn() as conn:
                conn.execute("""
                    INSERT INTO swing_ml_models
                    (version, accuracy, baseline, edge_vs_baseline, auc_roc,
                     total_samples, n_dates, train_start, train_end,
                     test_start, test_end, model_path, status)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active')
                """, (
                    result["version"],
                    result["accuracy"],
                    result.get("baseline"),
                    result.get("edge_vs_baseline"),
                    result["auc_roc"],
                    result["train_samples"] + result["test_samples"],
                    result.get("n_dates"),
                    result.get("train_start"),
                    result.get("train_end"),
                    result.get("test_start"),
                    result.get("test_end"),
                    result["model_path"],
                ))
                # 이전 모델 archived 처리
                conn.execute("""
                    UPDATE swing_ml_models SET status = 'archived'
                    WHERE version = %s AND status = 'active'
                      AND model_id != (
                          SELECT model_id FROM swing_ml_models
                          WHERE version = %s ORDER BY trained_at DESC LIMIT 1
                      )
                """, (result["version"], result["version"]))
                conn.commit()
        except Exception as e:
            logger.error(f"Save LSTM metadata failed: {e}")

    # ─── Prediction ───────────────────────────────────────

    def predict(self, symbol: str) -> dict:
        """단일 종목 5일 후 상승 확률 예측.

        Returns: {symbol, up_probability, confidence, predicted_return, available}
        """
        defaults = {
            "symbol": symbol,
            "up_probability": 0.5,
            "confidence": 0.0,
            "predicted_return": 0.0,
            "available": False,
        }

        if not self.is_available:
            return defaults

        # 캐시 확인
        if self.cache:
            cached = self.cache.get_json(f"lstm_pred:{symbol}")
            if cached:
                return cached

        try:
            # 🔴 학습과 **같은 창**을 받는다(결함 4). days=lookback+100 은 거래일 109행
            #    이라 sma200 이 100% 결손 → 특성 2개가 전부 NaN 이었고, 아래 nan_to_num 이
            #    그걸 0 으로 메워 학습이 본 적 없는 입력을 모델에 먹였다.
            df = self._get_price_data(symbol, days=self.train_days,
                                      min_rows=self.lookback + 200 + 20)
            if df is None:
                return defaults

            feat_norm = _causal_zscore(_compute_features(df), self.zwin)

            # 마지막 lookback 윈도우
            last_seq = feat_norm.values[-self.lookback:]
            if np.isnan(last_seq).any():
                # 🔴 조용히 0 으로 메우지 않는다 — 메우면 학습/서빙 불일치가 숨는다.
                #    결손은 '예측 불가'로 보고하고 상위에서 LSTM 없이 가게 둔다.
                bad = int(np.isnan(last_seq).any(axis=0).sum())
                logger.warning(f"LSTM predict {symbol}: 특성 {bad}/{last_seq.shape[1]}개 "
                               f"결손 ({len(df)}행) — 예측 생략")
                return defaults

            # Prediction
            self.model.eval()
            with torch.no_grad():
                x = torch.from_numpy(last_seq.astype(np.float32)).unsqueeze(0)
                prob = float(self.model(x).item())

            # Confidence: 0.5에서 얼마나 먼 지 (0~1)
            confidence = abs(prob - 0.5) * 2

            # 예상 수익률 추정 (최근 20일 변동성 기반)
            recent_returns = df["close"].pct_change(5).dropna().tail(20)
            avg_move = float(recent_returns.abs().mean()) if len(recent_returns) > 0 else 0.02
            predicted_return = avg_move * (1 if prob > 0.5 else -1)

            result = {
                "symbol": symbol,
                "up_probability": round(prob, 4),
                "confidence": round(confidence, 4),
                "predicted_return": round(predicted_return, 4),
                "available": True,
                "model_version": self._version,
                "predicted_at": datetime.now().isoformat(),
            }

            # 캐시 저장 (6시간)
            if self.cache:
                self.cache.set_json(f"lstm_pred:{symbol}", result, ttl=21600)

            return result

        except Exception as e:
            logger.error(f"LSTM predict {symbol}: {e}")
            return defaults

    def predict_and_save(self, symbol: str) -> dict:
        """예측 + DB 저장."""
        result = self.predict(symbol)

        if result["available"]:
            try:
                with self.pg.get_conn() as conn:
                    conn.execute("""
                        INSERT INTO swing_ml_predictions
                        (symbol, model_version, up_probability,
                         predicted_return, confidence,
                         features_used, lookback_days, horizon_days)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        symbol, self._version,
                        result["up_probability"],
                        result["predicted_return"],
                        result["confidence"],
                        self.n_features, self.lookback, self.horizon,
                    ))
                    conn.commit()
            except Exception as e:
                logger.error(f"Save LSTM prediction failed: {e}")

        return result

    def predict_universe(self) -> list[dict]:
        """유니버스 전체 예측 + DB 저장."""
        universe = self.pg.get_universe()
        symbols = [u["symbol"] for u in universe]
        results = []

        for symbol in symbols:
            try:
                result = self.predict_and_save(symbol)
                if result["available"]:
                    results.append(result)
            except Exception as e:
                logger.debug(f"LSTM predict {symbol}: {e}")

        logger.info(f"LSTM predictions: {len(results)}/{len(symbols)} symbols")
        return results

    def get_model_info(self) -> dict:
        """현재 모델 정보."""
        info = {
            "available": self.is_available,
            "version": self._version,
            "lookback": self.lookback,
            "horizon": self.horizon,
            "hidden_size": self.hidden_size,
            "n_features": self.n_features,
        }

        # DB에서 최신 학습 정보
        try:
            with self.pg.get_conn() as conn:
                row = conn.execute("""
                    SELECT accuracy, baseline, edge_vs_baseline, auc_roc,
                           total_samples, n_dates, trained_at
                    FROM swing_ml_models
                    WHERE version = %s AND status = 'active'
                    ORDER BY trained_at DESC LIMIT 1
                """, (self._version,)).fetchone()
                if row:
                    info["accuracy"] = row["accuracy"]
                    # 🔴 정확도만 노출하면 호출부가 0.65 를 실력으로 읽는다(§22.AO-47).
                    info["baseline"] = row["baseline"]
                    info["edge_vs_baseline"] = row["edge_vs_baseline"]
                    info["auc_roc"] = row["auc_roc"]
                    info["total_samples"] = row["total_samples"]
                    info["n_dates"] = row["n_dates"]
                    info["trained_at"] = row["trained_at"].isoformat() if row["trained_at"] else None
        except Exception:
            pass

        return info
