"""LSTMPredictor — 5일 후 상승 확률 예측 (PyTorch CPU).

2-layer 64-unit LSTM, 60-day lookback, 10 features, 5-day horizon.
Walk-forward validation: 학습(1년) → 테스트(3개월) 슬라이딩.
주간 재학습 (토요일) + 일일 예측.
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
                 learning_rate: float = 0.001):
        self.pg = pg
        self.cache = cache
        self.lookback = lookback
        self.horizon = horizon
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = learning_rate
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

    def _prepare_sequences(self, features: np.ndarray, targets: np.ndarray
                           ) -> tuple[np.ndarray, np.ndarray]:
        """시계열 시퀀스 생성 (lookback window)."""
        X, y = [], []
        for i in range(self.lookback, len(features) - self.horizon):
            seq = features[i - self.lookback:i]
            if not np.isnan(seq).any() and not np.isnan(targets[i]):
                X.append(seq)
                y.append(targets[i])
        return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)

    # ─── Training ─────────────────────────────────────────

    def train(self, symbols: list[str] | None = None) -> dict:
        """전체 유니버스 또는 지정 종목으로 LSTM 학습.

        Walk-forward: 전체 데이터의 80% 학습, 20% 검증.
        Returns: {accuracy, auc_roc, train_samples, test_samples, ...}
        """
        start = time.time()

        if not symbols:
            universe = self.pg.get_universe()
            symbols = [u["symbol"] for u in universe]

        logger.info(f"LSTM training started: {len(symbols)} symbols")

        all_X, all_y = [], []

        for symbol in symbols:
            try:
                df = self._get_price_data(symbol, days=400)
                if df is None:
                    continue

                features_df = _compute_features(df)
                target = _make_target(df["close"], self.horizon)

                # Normalize features (z-score per feature)
                feat_values = features_df.values
                means = np.nanmean(feat_values, axis=0)
                stds = np.nanstd(feat_values, axis=0)
                stds[stds == 0] = 1
                feat_norm = (feat_values - means) / stds

                X, y = self._prepare_sequences(feat_norm, target.values)
                if len(X) > 0:
                    all_X.append(X)
                    all_y.append(y)
            except Exception as e:
                logger.debug(f"LSTM data prep {symbol}: {e}")
                continue

        if not all_X:
            logger.warning("LSTM training: no valid data")
            return {"error": "No valid training data"}

        X_all = np.concatenate(all_X)
        y_all = np.concatenate(all_y)

        # Train/test split (80/20 — time-ordered, not random)
        split_idx = int(len(X_all) * 0.8)
        X_train, X_test = X_all[:split_idx], X_all[split_idx:]
        y_train, y_test = y_all[:split_idx], y_all[split_idx:]

        logger.info(f"LSTM data: {len(X_train)} train, {len(X_test)} test samples")

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
            "auc_roc": round(auc, 4),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "epochs_trained": epoch + 1,
            "symbols_used": len(symbols),
            "elapsed_sec": round(elapsed, 1),
            "model_path": str(model_path),
        }

        self._save_model_metadata(result)
        logger.info(f"LSTM training done: accuracy={accuracy:.4f}, "
                    f"AUC={auc:.4f}, {elapsed:.1f}s")

        return result

    def _save_model_metadata(self, result: dict) -> None:
        """학습 메타데이터 DB 저장."""
        try:
            with self.pg.get_conn() as conn:
                conn.execute("""
                    INSERT INTO swing_ml_models
                    (version, accuracy, auc_roc, total_samples, model_path, status)
                    VALUES (%s, %s, %s, %s, %s, 'active')
                """, (
                    result["version"],
                    result["accuracy"],
                    result["auc_roc"],
                    result["train_samples"] + result["test_samples"],
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
            df = self._get_price_data(symbol, days=self.lookback + 100,
                                     min_rows=self.lookback + 20)
            if df is None:
                return defaults

            features_df = _compute_features(df)
            feat_values = features_df.values

            # Normalize
            means = np.nanmean(feat_values, axis=0)
            stds = np.nanstd(feat_values, axis=0)
            stds[stds == 0] = 1
            feat_norm = (feat_values - means) / stds

            # 마지막 lookback 윈도우
            last_seq = feat_norm[-self.lookback:]
            if np.isnan(last_seq).any():
                # NaN 처리 (0으로 대체)
                last_seq = np.nan_to_num(last_seq, nan=0.0)

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
                    SELECT accuracy, auc_roc, total_samples, trained_at
                    FROM swing_ml_models
                    WHERE version = %s AND status = 'active'
                    ORDER BY trained_at DESC LIMIT 1
                """, (self._version,)).fetchone()
                if row:
                    info["accuracy"] = row["accuracy"]
                    info["auc_roc"] = row["auc_roc"]
                    info["total_samples"] = row["total_samples"]
                    info["trained_at"] = row["trained_at"].isoformat() if row["trained_at"] else None
        except Exception:
            pass

        return info
