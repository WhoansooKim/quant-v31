"""MultiFactorScorer — 6팩터 복합 스코어링 (Tier 1 + Macro Overlay).

기술(25-30%) + 감성(15-25%) + 수급(10%) + 퀄리티(15-25%) + 밸류(15-25%) + 매크로(10-20%)
레짐 적응형 가중치: ADX/VIX 기반 동적 팩터 배분.
매크로 오버레이: VIX + HY 스프레드 + Gold/SPY + 수익률 곡선 + 구리/금 + BTC.
시그널 생성 후 호출되어 각 팩터 점수를 계산하고 DB에 저장.
Finnhub API 없으면 기술 점수만 계산 (graceful degradation).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from engine_v4.ai.data_feeds import FinnhubClient
from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

# ─── Sentiment Prompt ────────────────────────────────────

SENTIMENT_PROMPT = """Analyze these news headlines for {symbol} and rate overall sentiment.

Headlines:
{headlines}

Rate the news sentiment from 0-100 where:
- 0-20: Very negative (lawsuits, fraud, major losses)
- 20-40: Negative (downgrades, missed earnings, layoffs)
- 40-60: Neutral (routine updates, mixed news)
- 60-80: Positive (upgrades, beats, growth)
- 80-100: Very positive (breakthroughs, major wins)

Respond in JSON only: {{"sentiment_score": <0-100>, "summary": "<1 sentence>"}}"""


class MultiFactorScorer:
    """멀티팩터 스코어링 엔진 (6-Factor Regime-Adaptive + Macro Overlay).

    Technical Score: 기존 지표 기반 + LSTM 블렌딩
    Sentiment Score: Finnhub 뉴스 + Claude/Ollama + 소셜 감성
    Flow Score: 내부자 거래 + 애널리스트 추천
    Quality Score: ROE, 마진, 부채비율, 수익안정성
    Value Score: P/E, P/B, FCF Yield, EV/EBITDA
    Macro Score: VIX + HY 스프레드 + Gold/SPY + 수익률 곡선 + 구리/금 + BTC

    레짐 적응형: ADX>25 TRENDING, ADX<20 SIDEWAYS, VIX>25 HIGH_VOL
    HIGH_VOL 시 매크로 비중 20%로 확대 (위기 감지 강화)
    """

    # Regime-adaptive weight profiles (6 factors, sum = 1.0)
    REGIME_WEIGHTS = {
        "TRENDING":  {"technical": 0.30, "sentiment": 0.15, "flow": 0.10, "quality": 0.15, "value": 0.20, "macro": 0.10},
        "SIDEWAYS":  {"technical": 0.18, "sentiment": 0.12, "flow": 0.10, "quality": 0.25, "value": 0.20, "macro": 0.15},
        "HIGH_VOL":  {"technical": 0.20, "sentiment": 0.15, "flow": 0.10, "quality": 0.20, "value": 0.15, "macro": 0.20},
        "MIXED":     {"technical": 0.25, "sentiment": 0.18, "flow": 0.10, "quality": 0.17, "value": 0.18, "macro": 0.12},
    }

    def __init__(self, pg: PostgresStore, finnhub: FinnhubClient,
                 anthropic_key: str = "",
                 ollama_url: str = "", ollama_model: str = "",
                 cache=None, social_collector=None,
                 lstm_predictor=None, macro_scorer=None,
                 crowding_monitor=None):
        self.pg = pg
        self.finnhub = finnhub
        self.cache = cache  # RedisCache (optional, for factor momentum)
        self.social = social_collector  # SocialSentimentCollector (optional)
        self.lstm = lstm_predictor  # LSTMPredictor (optional)
        self.macro = macro_scorer  # MacroScorer (optional)
        self.crowding = crowding_monitor  # FactorCrowdingMonitor (optional)
        self.anthropic_key = anthropic_key
        self._claude = None
        self._ollama_url = ollama_url or "http://localhost:11434"
        self._ollama_model = ollama_model or "qwen2.5:3b"
        self._ollama_available = False

        if anthropic_key and anthropic_key not in ("", "your_anthropic_key_here"):
            try:
                import anthropic
                self._claude = anthropic.Anthropic(api_key=anthropic_key)
                logger.info("MultiFactorScorer: Claude API ready")
            except (ImportError, Exception) as e:
                logger.warning(f"MultiFactorScorer: Claude unavailable: {e}")

        if not self._claude:
            self._ollama_available = self._check_ollama()
            if self._ollama_available:
                logger.info(f"MultiFactorScorer: Ollama ({self._ollama_model}) ready")

    def _check_ollama(self) -> bool:
        """Ollama 서버 + 모델 사용 가능 여부 확인."""
        import requests
        try:
            resp = requests.get(f"{self._ollama_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return any(self._ollama_model in m for m in models)
        except Exception:
            return False

    def score_signal(self, signal_id: int) -> dict:
        """단일 시그널 6팩터 스코어링 (레짐 적응형 + 매크로 오버레이).

        Returns: {signal_id, technical, sentiment, flow, quality, value, macro, composite, regime, detail}
        """
        sig = self.pg.get_signal(signal_id)
        if not sig:
            raise ValueError(f"Signal {signal_id} not found")

        symbol = sig["symbol"]
        start = time.time()

        # 레짐 감지 + 가중치 결정
        regime_adaptive = self.pg.get_config_value("regime_adaptive_weights", "true") == "true"
        if regime_adaptive:
            regime = self._detect_regime(symbol)
            weights = self.REGIME_WEIGHTS[regime]
        else:
            regime = "MIXED"
            macro_w = float(self.pg.get_config_value("macro_weight", "0.10"))
            weights = {
                "technical": float(self.pg.get_config_value("factor_weight_technical", "0.25")),
                "sentiment": float(self.pg.get_config_value("factor_weight_sentiment", "0.18")),
                "flow": float(self.pg.get_config_value("factor_weight_flow", "0.10")),
                "quality": float(self.pg.get_config_value("factor_weight_quality", "0.19")),
                "value": float(self.pg.get_config_value("factor_weight_value", "0.18")),
                "macro": macro_w,
            }

        # Factor Momentum: 최근 성과 기반 가중치 틸트
        factor_momentum_enabled = self.pg.get_config_value(
            "factor_momentum_enabled", "true") == "true"
        weights, momentum_applied = self._apply_factor_momentum(
            weights, factor_momentum_enabled)

        # 1) Technical Score
        tech_result = self._calc_technical(sig)

        # 2) Sentiment Score (Finnhub news + Claude)
        sent_result = self._calc_sentiment(symbol)

        # 3) Flow Score (insider + analyst recommendations)
        flow_result = self._calc_flow(symbol)

        # 4) Quality Score (ROE, margins, debt, stability)
        quality_result = self._calc_quality(symbol)

        # 5) Value Score (P/E, P/B, FCF yield, EV/EBITDA)
        value_result = self._calc_value(symbol)

        # 6) Macro Score (크로스 에셋 매크로 오버레이)
        macro_result = self._calc_macro()

        # Composite (6-factor weighted)
        composite = (
            tech_result["score"] * weights["technical"] +
            sent_result["score"] * weights["sentiment"] +
            flow_result["score"] * weights["flow"] +
            quality_result["score"] * weights["quality"] +
            value_result["score"] * weights["value"] +
            macro_result["score"] * weights.get("macro", 0.10)
        )

        elapsed = time.time() - start

        detail = {
            "technical": tech_result,
            "sentiment": sent_result,
            "flow": flow_result,
            "quality": quality_result,
            "value": value_result,
            "macro": macro_result,
            "regime": regime,
            "weights": weights,
            "regime_adaptive": regime_adaptive,
            "factor_momentum_applied": momentum_applied,
            "elapsed_sec": round(elapsed, 2),
            "scored_at": datetime.now().isoformat(),
        }

        # DB 저장
        self._update_signal_factors(
            signal_id,
            technical=tech_result["score"],
            sentiment=sent_result["score"],
            flow=flow_result["score"],
            quality=quality_result["score"],
            value=value_result["score"],
            macro=macro_result["score"],
            composite=round(composite, 1),
            detail=detail,
        )

        logger.info(f"Factor score {symbol} [{regime}]: T={tech_result['score']:.0f} "
                     f"S={sent_result['score']:.0f} F={flow_result['score']:.0f} "
                     f"Q={quality_result['score']:.0f} V={value_result['score']:.0f} "
                     f"M={macro_result['score']:.0f} → C={composite:.1f} ({elapsed:.1f}s)")

        return {
            "signal_id": signal_id,
            "symbol": symbol,
            "technical_score": tech_result["score"],
            "sentiment_score": sent_result["score"],
            "flow_score": flow_result["score"],
            "quality_score": quality_result["score"],
            "value_score": value_result["score"],
            "macro_score": macro_result["score"],
            "composite_score": round(composite, 1),
            "regime": regime,
            "detail": detail,
        }

    def score_pending_signals(self) -> list[dict]:
        """모든 pending 시그널 스코어링."""
        signals = self.pg.get_signals(status="pending", limit=20)
        results = []
        for sig in signals:
            if sig.get("composite_score") is not None:
                continue  # already scored
            try:
                result = self.score_signal(sig["signal_id"])
                results.append(result)
            except Exception as e:
                logger.error(f"Factor scoring failed for signal {sig['signal_id']}: {e}")
        return results

    # ─── Technical Score (0-100) ─────────────────────────

    def _calc_technical(self, sig: dict) -> dict:
        """기술적 지표 + LSTM 예측 기반 점수 (0-100).

        기본 Components (LSTM 미적용 시):
        - Momentum rank: 0-40 points (rank percentile * 40)
        - Trend alignment: 0-25 points
        - Breakout: 0-20 points
        - Volume surge: 0-15 points

        LSTM 적용 시: 기존 점수 * (1 - lstm_weight) + LSTM 점수 * lstm_weight
        """
        rank = float(sig.get("return_20d_rank") or 0)
        trend = bool(sig.get("trend_aligned"))
        breakout = bool(sig.get("breakout_5d"))
        volume = bool(sig.get("volume_surge"))

        momentum_pts = min(40, rank * 40)  # rank 1.0 = 40pts
        trend_pts = 25 if trend else 0
        breakout_pts = 20 if breakout else 0
        volume_pts = 15 if volume else 0

        base_score = momentum_pts + trend_pts + breakout_pts + volume_pts

        result = {
            "score": round(min(100, base_score), 1),
            "momentum": round(momentum_pts, 1),
            "trend": trend_pts,
            "breakout": breakout_pts,
            "volume": volume_pts,
            "lstm": None,
        }

        # LSTM 블렌딩
        lstm_enabled = self.pg.get_config_value("lstm_enabled", "true") == "true"
        if lstm_enabled and self.lstm and self.lstm.is_available:
            symbol = sig.get("symbol", "")
            try:
                pred = self.lstm.predict(symbol)
                if pred.get("available"):
                    min_accuracy = float(self.pg.get_config_value(
                        "lstm_min_accuracy", "0.53"))
                    model_info = self.lstm.get_model_info()
                    model_accuracy = model_info.get("accuracy", 0)

                    if model_accuracy >= min_accuracy:
                        lstm_weight = float(self.pg.get_config_value(
                            "lstm_weight_in_technical", "0.5"))
                        # LSTM score: up_probability * 100
                        lstm_score = pred["up_probability"] * 100
                        blended = base_score * (1 - lstm_weight) + lstm_score * lstm_weight
                        result["score"] = round(min(100, blended), 1)
                        result["lstm"] = {
                            "up_probability": pred["up_probability"],
                            "confidence": pred["confidence"],
                            "lstm_score": round(lstm_score, 1),
                            "weight": lstm_weight,
                            "model_accuracy": model_accuracy,
                        }
                        logger.debug(f"LSTM blend {symbol}: base={base_score:.0f} "
                                     f"lstm={lstm_score:.0f} → {blended:.0f}")
            except Exception as e:
                logger.debug(f"LSTM blend failed for {symbol}: {e}")

        return result

    # ─── Sentiment Score (0-100) ─────────────────────────

    def _calc_sentiment(self, symbol: str) -> dict:
        """뉴스 + 소셜 감성 점수 (0-100).

        News (Finnhub → Claude/Ollama) + Social (Reddit+StockTwits) 가중 합산.
        social_enabled=true 시: 뉴스 60% + 소셜 40%.
        social_enabled=false 또는 소셜 불가 시: 뉴스 100%.
        """
        # 1) 뉴스 감성 점수
        news_result = self._calc_news_sentiment(symbol)

        # 2) 소셜 감성 점수 (optional)
        social_enabled = self.pg.get_config_value("social_enabled", "true") == "true"
        social_result = None

        if social_enabled and self.social:
            try:
                social_data = self.social.get_social_sentiment(symbol)
                if social_data.get("mention_count", 0) > 0:
                    # combined_score: -100~+100 → 0~100 스케일로 변환
                    raw = social_data["combined_score"]
                    social_score = max(0, min(100, (raw + 100) / 2))
                    social_result = {
                        "score": round(social_score, 1),
                        "combined_raw": raw,
                        "mention_count": social_data["mention_count"],
                        "reddit": social_data.get("reddit", {}),
                        "stocktwits": social_data.get("stocktwits", {}),
                    }
            except Exception as e:
                logger.warning(f"Social sentiment failed for {symbol}: {e}")

        # 3) 가중 합산
        social_weight = float(self.pg.get_config_value(
            "social_weight_in_sentiment", "0.4"))
        news_weight = 1.0 - social_weight

        if social_result:
            final_score = (news_result["score"] * news_weight +
                           social_result["score"] * social_weight)
            source = f"news({news_weight:.0%})+social({social_weight:.0%})"
        else:
            final_score = news_result["score"]
            source = news_result.get("source", "news_only")

        return {
            "score": round(final_score, 1),
            "source": source,
            "news": news_result,
            "social": social_result,
            "social_enabled": social_enabled,
            "social_weight": social_weight if social_result else 0,
        }

    def _calc_news_sentiment(self, symbol: str) -> dict:
        """뉴스 감성 점수 (0-100). Finnhub → Claude/Ollama/rule-based."""
        if not self.finnhub.is_available:
            return {"score": 50, "source": "default", "news_count": 0,
                    "summary": "No Finnhub API key"}

        news = self.finnhub.get_company_news(symbol, days=7)
        if not news:
            return {"score": 50, "source": "no_news", "news_count": 0,
                    "summary": "No recent news found"}

        # Claude API로 뉴스 감성분석
        if self._claude:
            return self._claude_sentiment(symbol, news)

        # Ollama 로컬 LLM으로 뉴스 감성분석
        if self._ollama_available:
            return self._ollama_sentiment(symbol, news)

        # Fallback: 뉴스 개수 기반 간이 점수 (뉴스 많으면 약간 긍정)
        score = min(70, 40 + len(news) * 3)
        return {
            "score": score,
            "source": "rule_based",
            "news_count": len(news),
            "summary": f"{len(news)} articles found (mock scoring)",
        }

    def _claude_sentiment(self, symbol: str, news: list[dict]) -> dict:
        """Claude API로 뉴스 감성분석."""
        headlines = "\n".join(
            f"- {n['headline']} ({n['source']})" for n in news[:8]
        )
        prompt = SENTIMENT_PROMPT.format(symbol=symbol, headlines=headlines)

        try:
            response = self._claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            import re
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                data = json.loads(text)

            score = max(0, min(100, int(data.get("sentiment_score", 50))))
            return {
                "score": score,
                "source": "claude",
                "news_count": len(news),
                "summary": data.get("summary", ""),
            }
        except Exception as e:
            logger.warning(f"Claude sentiment failed for {symbol}: {e}")
            return {
                "score": 50,
                "source": "claude_error",
                "news_count": len(news),
                "summary": str(e)[:100],
            }

    def _ollama_sentiment(self, symbol: str, news: list[dict]) -> dict:
        """Ollama 로컬 LLM으로 뉴스 감성분석."""
        import requests

        headlines = "\n".join(
            f"- {n['headline']} ({n['source']})" for n in news[:8]
        )
        prompt = SENTIMENT_PROMPT.format(symbol=symbol, headlines=headlines)

        try:
            resp = requests.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 120, "temperature": 0.3},
                },
                timeout=300,
            )
            text = resp.json().get("response", "").strip()

            import re
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                data = json.loads(text)

            score = max(0, min(100, int(data.get("sentiment_score", 50))))
            return {
                "score": score,
                "source": f"ollama/{self._ollama_model}",
                "news_count": len(news),
                "summary": data.get("summary", ""),
            }
        except Exception as e:
            logger.warning(f"Ollama sentiment failed for {symbol}: {e}")
            score = min(70, 40 + len(news) * 3)
            return {
                "score": score,
                "source": "ollama_error",
                "news_count": len(news),
                "summary": str(e)[:100],
            }

    # ─── Flow Score (0-100) ──────────────────────────────

    def _calc_flow(self, symbol: str) -> dict:
        """수급/기관 흐름 점수 (0-100).

        Components:
        - Insider transactions: net buy = positive (30%)
        - Analyst recommendations: buy ratio (30%)
        - Short interest (yfinance): SIR-based contrarian signal (20%)
        - Crowding: factor ETF overlap penalty (20%)
        """
        if not self.finnhub.is_available:
            si_data = self._yf_short_interest(symbol)
            si_score = self._short_interest_score(si_data)
            crowd_data = self._get_crowding(symbol)
            crowd_score = self._crowding_score(crowd_data)
            score = 50 * 0.3 + 50 * 0.3 + si_score * 0.2 + crowd_score * 0.2
            return {"score": round(min(100, score), 1), "source": "partial",
                    "insider": {}, "recommendations": {},
                    "short_interest": si_data, "crowding": crowd_data}

        # Insider transactions
        insider = self.finnhub.get_insider_transactions(symbol)
        insider_score = self._insider_score(insider)

        # Analyst recommendations
        recs = self.finnhub.get_recommendation_trends(symbol)
        rec_score = self._recommendation_score(recs)

        # Short interest (yfinance — replaces Finnhub premium)
        si_data = self._yf_short_interest(symbol)
        si_score = self._short_interest_score(si_data)

        # Crowding (factor ETF overlap)
        crowd_data = self._get_crowding(symbol)
        crowd_score = self._crowding_score(crowd_data)

        score = (insider_score * 0.3 + rec_score * 0.3 +
                 si_score * 0.2 + crowd_score * 0.2)

        return {
            "score": round(min(100, score), 1),
            "source": "finnhub+yfinance",
            "insider_score": round(insider_score, 1),
            "recommendation_score": round(rec_score, 1),
            "short_interest_score": round(si_score, 1),
            "crowding_score": round(crowd_score, 1),
            "insider": {
                "net_shares": insider.get("net_shares", 0),
                "buys": insider.get("total_buys", 0),
                "sells": insider.get("total_sells", 0),
            },
            "recommendations": recs,
            "short_interest": si_data,
            "crowding": crowd_data,
        }

    @staticmethod
    def _insider_score(insider: dict) -> float:
        """내부자 거래 점수 (0-100).
        Net buy = 높은 점수, Net sell = 낮은 점수.
        """
        net = insider.get("net_shares", 0)
        count = insider.get("transaction_count", 0)

        if count == 0:
            return 50  # no data = neutral

        if net > 0:
            # Net buying: 50-100 range
            return min(100, 50 + min(50, net / 10000 * 10))
        else:
            # Net selling: 0-50 range
            return max(0, 50 - min(50, abs(net) / 10000 * 10))

    @staticmethod
    def _recommendation_score(recs: dict) -> float:
        """애널리스트 추천 점수 (0-100).
        Buy 비율 높으면 높은 점수.
        """
        total = (recs.get("strong_buy", 0) + recs.get("buy", 0) +
                 recs.get("hold", 0) + recs.get("sell", 0) +
                 recs.get("strong_sell", 0))

        if total == 0:
            return 50  # no data = neutral

        buy_weight = recs.get("strong_buy", 0) * 100 + recs.get("buy", 0) * 75
        hold_weight = recs.get("hold", 0) * 50
        sell_weight = recs.get("sell", 0) * 25 + recs.get("strong_sell", 0) * 0

        return (buy_weight + hold_weight + sell_weight) / total

    @staticmethod
    def _yf_short_interest(symbol: str) -> dict:
        """yfinance에서 공매도 잔고 데이터 조회."""
        try:
            import yfinance as yf
            info = yf.Ticker(symbol).info
            shares_short = info.get("sharesShort", 0) or 0
            short_ratio = info.get("shortRatio", 0) or 0
            short_pct_float = info.get("shortPercentOfFloat", 0) or 0
            shares_prior = info.get("sharesShortPriorMonth", 0) or 0

            change_pct = 0.0
            if shares_prior > 0:
                change_pct = round((shares_short - shares_prior) / shares_prior * 100, 2)

            return {
                "short_ratio": round(float(short_ratio), 2),
                "short_pct_float": round(float(short_pct_float) * 100, 2),
                "change_pct": change_pct,
                "available": shares_short > 0,
                "source": "yfinance",
            }
        except Exception as e:
            logger.warning(f"yfinance short interest failed for {symbol}: {e}")
            return {"short_ratio": 0, "short_pct_float": 0, "change_pct": 0,
                    "available": False, "source": "error"}

    @staticmethod
    def _short_interest_score(si_data: dict) -> float:
        """공매도 잔고 기반 점수 (0-100).

        SIR (Short Interest Ratio, days to cover):
        - SIR > 10 days: 과도한 공매도 → bearish (20)
        - SIR 5-10 days: 보통 수준 (50)
        - SIR < 5 days: 낮은 공매도 → bullish (70)
        - SIR 하락 시: short covering momentum → +15 boost
        """
        if not si_data.get("available", False):
            return 50  # no data = neutral

        sir = si_data.get("short_ratio", 0)
        change_pct = si_data.get("change_pct", 0)

        # Base score from SIR level
        if sir > 10:
            score = 20
        elif sir > 5:
            score = 50
        else:
            score = 70

        # Short covering momentum: SI declining (change_pct < 0) = bullish
        if change_pct < -5:
            score = min(100, score + 15)

        return score

    def _get_crowding(self, symbol: str) -> dict:
        """FactorCrowdingMonitor에서 종목 크라우딩 데이터 조회."""
        if not self.crowding:
            return {"factor_count": 0, "risk_level": "unknown",
                    "factor_memberships": [], "available": False}
        try:
            result = self.crowding.get_crowding_score(symbol)
            result["available"] = True
            return result
        except Exception as e:
            logger.warning(f"Crowding check failed for {symbol}: {e}")
            return {"factor_count": 0, "risk_level": "unknown",
                    "factor_memberships": [], "available": False}

    @staticmethod
    def _crowding_score(crowd_data: dict) -> float:
        """팩터 크라우딩 기반 점수 (0-100).

        크라우딩이 높으면 리스크가 높음 → 낮은 점수.
        - 0 factors: 75 (독립적 = 좋음)
        - 1 factor: 65
        - 2 factors: 50 (moderate risk)
        - 3+ factors: 30 (high crowding risk)
        """
        if not crowd_data.get("available", False):
            return 50  # no data = neutral

        count = crowd_data.get("factor_count", 0)
        if count == 0:
            return 75
        elif count == 1:
            return 65
        elif count == 2:
            return 50
        else:
            return 30

    # ─── Regime Detection ─────────────────────────────────

    def _detect_regime(self, symbol: str) -> str:
        """ADX + VIX 기반 시장 레짐 감지.

        Returns: TRENDING | SIDEWAYS | HIGH_VOL | MIXED
        """
        import yfinance as yf
        import numpy as np

        try:
            # VIX 확인
            vix_data = yf.download("^VIX", period="5d", interval="1d", progress=False)
            vix = float(vix_data["Close"].iloc[-1].item()) if len(vix_data) > 0 else 20.0

            if vix > 25:
                return "HIGH_VOL"

            # ADX 계산 (SPY 기준 — 시장 전체 트렌드)
            spy = yf.download("SPY", period="30d", interval="1d", progress=False)
            if len(spy) < 14:
                return "MIXED"

            high = spy["High"].values.flatten()
            low = spy["Low"].values.flatten()
            close = spy["Close"].values.flatten()

            # True Range + Directional Movement
            tr_list = []
            plus_dm_list = []
            minus_dm_list = []
            for i in range(1, len(high)):
                tr = max(high[i] - low[i],
                         abs(high[i] - close[i-1]),
                         abs(low[i] - close[i-1]))
                tr_list.append(tr)

                up_move = high[i] - high[i-1]
                down_move = low[i-1] - low[i]
                plus_dm_list.append(up_move if up_move > down_move and up_move > 0 else 0)
                minus_dm_list.append(down_move if down_move > up_move and down_move > 0 else 0)

            period = 14
            if len(tr_list) < period:
                return "MIXED"

            # Wilder smoothing
            atr = np.mean(tr_list[:period])
            plus_di = np.mean(plus_dm_list[:period])
            minus_di = np.mean(minus_dm_list[:period])

            for i in range(period, len(tr_list)):
                atr = (atr * (period - 1) + tr_list[i]) / period
                plus_di = (plus_di * (period - 1) + plus_dm_list[i]) / period
                minus_di = (minus_di * (period - 1) + minus_dm_list[i]) / period

            if atr == 0:
                return "MIXED"

            plus_di_val = 100 * plus_di / atr
            minus_di_val = 100 * minus_di / atr
            dx = abs(plus_di_val - minus_di_val) / (plus_di_val + minus_di_val + 1e-10) * 100
            adx = dx  # simplified — single-point ADX approximation

            if adx > 25:
                return "TRENDING"
            elif adx < 20:
                return "SIDEWAYS"
            else:
                return "MIXED"

        except Exception as e:
            logger.warning(f"Regime detection failed: {e}")
            return "MIXED"

    # ─── Factor Momentum ─────────────────────────────────

    def _apply_factor_momentum(self, weights: dict, enabled: bool) -> tuple[dict, bool]:
        """팩터 모멘텀 기반 가중치 틸트.

        최근 1개월 성과 상위 2개 팩터에 +5%, 하위 1개 팩터에 -5%.
        Redis 캐시 key: factor_momentum.

        Returns: (adjusted_weights, momentum_applied)
        """
        if not enabled or not self.cache:
            return weights, False

        try:
            momentum_data = self.cache.get_json("factor_momentum")
            if not momentum_data or "ranked" not in momentum_data:
                return weights, False

            ranked = momentum_data["ranked"]
            # Need at least 3 factors to boost top 2 and reduce bottom 1
            if len(ranked) < 3:
                return weights, False

            adjusted = dict(weights)
            top_2 = ranked[:2]
            bottom_1 = ranked[-1]

            for factor in top_2:
                if factor in adjusted:
                    adjusted[factor] += 0.05

            if bottom_1 in adjusted:
                adjusted[bottom_1] = max(0.05, adjusted[bottom_1] - 0.05)

            # Normalize so weights sum to 1.0
            total = sum(adjusted.values())
            if total > 0:
                adjusted = {k: v / total for k, v in adjusted.items()}

            logger.info(f"Factor momentum applied: boost={top_2}, reduce=[{bottom_1}]")
            return adjusted, True

        except Exception as e:
            logger.warning(f"Factor momentum failed: {e}")
            return weights, False

    # ─── Quality Score (0-100) ────────────────────────────

    def _calc_quality(self, symbol: str) -> dict:
        """퀄리티 팩터 점수 (0-100).

        Components:
        - ROE: 0-30 points (높을수록 좋음)
        - Gross Margin: 0-25 points (높을수록 좋음)
        - Debt/Equity: 0-25 points (낮을수록 좋음)
        - Earnings Stability: 0-20 points (EPS 성장 일관성)
        """
        if not self.finnhub.is_available:
            return {"score": 50, "source": "default", "detail": "No Finnhub API"}

        fin = self.finnhub.get_basic_financials(symbol)
        if not fin:
            return {"score": 50, "source": "no_data", "detail": "No financial data"}

        # ROE (0-30pts): >20% = 30, 15-20% = 25, 10-15% = 20, 5-10% = 15, <5% = 5
        roe = fin.get("roe") or fin.get("roe_annual")
        if roe is not None:
            if roe >= 20:
                roe_pts = 30
            elif roe >= 15:
                roe_pts = 25
            elif roe >= 10:
                roe_pts = 20
            elif roe >= 5:
                roe_pts = 15
            elif roe >= 0:
                roe_pts = 5
            else:
                roe_pts = 0  # negative ROE
        else:
            roe_pts = 15  # no data = neutral

        # Gross Margin (0-25pts): >50% = 25, 30-50% = 20, 15-30% = 15, <15% = 5
        gm = fin.get("gross_margin")
        if gm is not None:
            if gm >= 50:
                gm_pts = 25
            elif gm >= 30:
                gm_pts = 20
            elif gm >= 15:
                gm_pts = 15
            else:
                gm_pts = 5
        else:
            gm_pts = 12  # no data = neutral

        # Debt/Equity (0-25pts): <0.3 = 25, 0.3-0.7 = 20, 0.7-1.5 = 15, >1.5 = 5
        de = fin.get("debt_equity")
        if de is not None:
            if de < 0.3:
                de_pts = 25
            elif de < 0.7:
                de_pts = 20
            elif de < 1.5:
                de_pts = 15
            else:
                de_pts = 5
        else:
            de_pts = 12  # no data = neutral

        # Earnings Stability (0-20pts): EPS growth consistency
        eps3 = fin.get("eps_growth_3y")
        eps5 = fin.get("eps_growth_5y")
        if eps3 is not None and eps5 is not None:
            # Both positive + consistent = high stability
            if eps3 > 0 and eps5 > 0:
                stability_pts = 20 if abs(eps3 - eps5) < 10 else 15
            elif eps3 > 0 or eps5 > 0:
                stability_pts = 10
            else:
                stability_pts = 3
        elif eps3 is not None:
            stability_pts = 15 if eps3 > 0 else 5
        else:
            stability_pts = 10  # no data = neutral

        score = roe_pts + gm_pts + de_pts + stability_pts

        return {
            "score": round(min(100, score), 1),
            "source": "finnhub",
            "roe_pts": roe_pts,
            "gross_margin_pts": gm_pts,
            "debt_equity_pts": de_pts,
            "stability_pts": stability_pts,
            "raw": {
                "roe": roe,
                "gross_margin": gm,
                "debt_equity": de,
                "eps_growth_3y": eps3,
                "eps_growth_5y": eps5,
            },
        }

    # ─── Value Score (0-100) ──────────────────────────────

    def _calc_value(self, symbol: str) -> dict:
        """밸류 팩터 점수 (0-100).

        Components:
        - P/E Ratio: 0-30 points (낮을수록 좋음, 적정밸류)
        - P/B Ratio: 0-25 points (낮을수록 좋음)
        - FCF Yield: 0-25 points (높을수록 좋음)
        - EV/EBITDA: 0-20 points (낮을수록 좋음)
        """
        if not self.finnhub.is_available:
            return {"score": 50, "source": "default", "detail": "No Finnhub API"}

        fin = self.finnhub.get_basic_financials(symbol)
        if not fin:
            return {"score": 50, "source": "no_data", "detail": "No financial data"}

        # P/E Ratio (0-30pts): <10 = 30, 10-15 = 25, 15-20 = 20, 20-30 = 10, >30 = 5
        pe = fin.get("pe_ttm") or fin.get("pe_ratio")
        if pe is not None and pe > 0:
            if pe < 10:
                pe_pts = 30
            elif pe < 15:
                pe_pts = 25
            elif pe < 20:
                pe_pts = 20
            elif pe < 30:
                pe_pts = 10
            else:
                pe_pts = 5
        elif pe is not None and pe <= 0:
            pe_pts = 0  # negative earnings
        else:
            pe_pts = 15  # no data = neutral

        # P/B Ratio (0-25pts): <1 = 25, 1-2 = 20, 2-3 = 15, 3-5 = 10, >5 = 3
        pb = fin.get("pb_ratio")
        if pb is not None and pb > 0:
            if pb < 1:
                pb_pts = 25
            elif pb < 2:
                pb_pts = 20
            elif pb < 3:
                pb_pts = 15
            elif pb < 5:
                pb_pts = 10
            else:
                pb_pts = 3
        else:
            pb_pts = 12  # no data = neutral

        # FCF Yield (0-25pts): >8% = 25, 5-8% = 20, 3-5% = 15, 1-3% = 10, <1% = 3
        fcf = fin.get("fcf_yield")
        if fcf is not None:
            if fcf >= 8:
                fcf_pts = 25
            elif fcf >= 5:
                fcf_pts = 20
            elif fcf >= 3:
                fcf_pts = 15
            elif fcf >= 1:
                fcf_pts = 10
            else:
                fcf_pts = 3
        else:
            fcf_pts = 12  # no data = neutral

        # EV/EBITDA (0-20pts): <8 = 20, 8-12 = 15, 12-18 = 10, >18 = 5
        ev = fin.get("ev_ebitda")
        if ev is not None and ev > 0:
            if ev < 8:
                ev_pts = 20
            elif ev < 12:
                ev_pts = 15
            elif ev < 18:
                ev_pts = 10
            else:
                ev_pts = 5
        else:
            ev_pts = 10  # no data = neutral

        score = pe_pts + pb_pts + fcf_pts + ev_pts

        return {
            "score": round(min(100, score), 1),
            "source": "finnhub",
            "pe_pts": pe_pts,
            "pb_pts": pb_pts,
            "fcf_yield_pts": fcf_pts,
            "ev_ebitda_pts": ev_pts,
            "raw": {
                "pe": pe,
                "pb": pb,
                "fcf_yield": fcf,
                "ev_ebitda": ev,
            },
        }

    # ─── Macro Score (0-100) ─────────────────────────────

    def _calc_macro(self) -> dict:
        """매크로 오버레이 점수 (0-100). MacroScorer 호출 or 중립 50."""
        macro_enabled = self.pg.get_config_value("macro_enabled", "true") == "true"
        if not macro_enabled or not self.macro:
            return {"score": 50.0, "source": "disabled", "regime": "NEUTRAL"}

        try:
            result = self.macro.calc_macro_score()
            return {
                "score": result["macro_score"],
                "source": "macro_scorer",
                "regime": result["regime"],
                "risk_off": result["risk_off"].get("score", 50),
                "yield_curve": result["yield_curve"].get("score", 50),
                "copper_gold": result["copper_gold"].get("score", 50),
                "dollar_trend": result["dollar_trend"].get("score", 50),
                "btc_momentum": result["btc_momentum"].get("score", 50),
            }
        except Exception as e:
            logger.warning(f"Macro scoring failed: {e}")
            return {"score": 50.0, "source": "error", "regime": "NEUTRAL"}

    # ─── DB Update ───────────────────────────────────────

    def _update_signal_factors(self, signal_id: int, *,
                               technical: float, sentiment: float,
                               flow: float, quality: float, value: float,
                               macro: float = 50.0,
                               composite: float, detail: dict) -> None:
        """swing_signals에 6팩터 점수 업데이트."""
        with self.pg.get_conn() as conn:
            conn.execute("""
                UPDATE swing_signals
                SET technical_score = %s,
                    sentiment_score = %s,
                    flow_score = %s,
                    quality_score = %s,
                    value_score = %s,
                    macro_score = %s,
                    composite_score = %s,
                    factor_detail = %s,
                    factor_scored_at = now()
                WHERE signal_id = %s
            """, (technical, sentiment, flow, quality, value, macro, composite,
                  json.dumps(detail, ensure_ascii=False, default=str),
                  signal_id))
            conn.commit()
