"""MultiFactorScorer — 기술(40%) + 감성(30%) + 수급(30%) 복합 스코어링.

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
    """멀티팩터 스코어링 엔진.

    Technical Score (40%): 기존 지표 기반 (rank, trend, breakout, volume)
    Sentiment Score (30%): Finnhub 뉴스 + Claude 감성분석
    Flow Score (30%): 내부자 거래 + 애널리스트 추천
    """

    def __init__(self, pg: PostgresStore, finnhub: FinnhubClient,
                 anthropic_key: str = ""):
        self.pg = pg
        self.finnhub = finnhub
        self.anthropic_key = anthropic_key
        self._claude = None

        if anthropic_key and anthropic_key not in ("", "your_anthropic_key_here"):
            try:
                import anthropic
                self._claude = anthropic.Anthropic(api_key=anthropic_key)
                logger.info("MultiFactorScorer: Claude API ready")
            except (ImportError, Exception) as e:
                logger.warning(f"MultiFactorScorer: Claude unavailable: {e}")

    def score_signal(self, signal_id: int) -> dict:
        """단일 시그널 멀티팩터 스코어링.

        Returns: {signal_id, technical, sentiment, flow, composite, detail}
        """
        sig = self.pg.get_signal(signal_id)
        if not sig:
            raise ValueError(f"Signal {signal_id} not found")

        symbol = sig["symbol"]
        start = time.time()

        # 가중치 로드
        w_tech = float(self.pg.get_config_value("factor_weight_technical", "0.4"))
        w_sent = float(self.pg.get_config_value("factor_weight_sentiment", "0.3"))
        w_flow = float(self.pg.get_config_value("factor_weight_flow", "0.3"))

        # 1) Technical Score
        tech_result = self._calc_technical(sig)

        # 2) Sentiment Score (Finnhub news + Claude)
        sent_result = self._calc_sentiment(symbol)

        # 3) Flow Score (insider + analyst recommendations)
        flow_result = self._calc_flow(symbol)

        # Composite
        composite = (
            tech_result["score"] * w_tech +
            sent_result["score"] * w_sent +
            flow_result["score"] * w_flow
        )

        elapsed = time.time() - start

        detail = {
            "technical": tech_result,
            "sentiment": sent_result,
            "flow": flow_result,
            "weights": {"technical": w_tech, "sentiment": w_sent, "flow": w_flow},
            "elapsed_sec": round(elapsed, 2),
            "scored_at": datetime.now().isoformat(),
        }

        # DB 저장
        self._update_signal_factors(
            signal_id,
            technical=tech_result["score"],
            sentiment=sent_result["score"],
            flow=flow_result["score"],
            composite=round(composite, 1),
            detail=detail,
        )

        logger.info(f"Factor score {symbol}: T={tech_result['score']:.0f} "
                     f"S={sent_result['score']:.0f} F={flow_result['score']:.0f} "
                     f"→ C={composite:.1f} ({elapsed:.1f}s)")

        return {
            "signal_id": signal_id,
            "symbol": symbol,
            "technical_score": tech_result["score"],
            "sentiment_score": sent_result["score"],
            "flow_score": flow_result["score"],
            "composite_score": round(composite, 1),
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
        """기술적 지표 기반 점수 (0-100).

        Components:
        - Momentum rank: 0-40 points (rank percentile * 40)
        - Trend alignment: 0-25 points
        - Breakout: 0-20 points
        - Volume surge: 0-15 points
        """
        rank = float(sig.get("return_20d_rank") or 0)
        trend = bool(sig.get("trend_aligned"))
        breakout = bool(sig.get("breakout_5d"))
        volume = bool(sig.get("volume_surge"))

        momentum_pts = min(40, rank * 40)  # rank 1.0 = 40pts
        trend_pts = 25 if trend else 0
        breakout_pts = 20 if breakout else 0
        volume_pts = 15 if volume else 0

        score = momentum_pts + trend_pts + breakout_pts + volume_pts

        return {
            "score": round(min(100, score), 1),
            "momentum": round(momentum_pts, 1),
            "trend": trend_pts,
            "breakout": breakout_pts,
            "volume": volume_pts,
        }

    # ─── Sentiment Score (0-100) ─────────────────────────

    def _calc_sentiment(self, symbol: str) -> dict:
        """뉴스 감성 점수 (0-100).

        Finnhub 뉴스 → Claude 감성분석 또는 rule-based fallback.
        """
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

    # ─── Flow Score (0-100) ──────────────────────────────

    def _calc_flow(self, symbol: str) -> dict:
        """수급/기관 흐름 점수 (0-100).

        Components:
        - Insider transactions: net buy = positive (0-50 pts)
        - Analyst recommendations: buy ratio (0-50 pts)
        """
        if not self.finnhub.is_available:
            return {"score": 50, "source": "default",
                    "insider": {}, "recommendations": {}}

        # Insider transactions
        insider = self.finnhub.get_insider_transactions(symbol)
        insider_score = self._insider_score(insider)

        # Analyst recommendations
        recs = self.finnhub.get_recommendation_trends(symbol)
        rec_score = self._recommendation_score(recs)

        score = insider_score * 0.5 + rec_score * 0.5

        return {
            "score": round(min(100, score), 1),
            "source": "finnhub",
            "insider_score": round(insider_score, 1),
            "recommendation_score": round(rec_score, 1),
            "insider": {
                "net_shares": insider.get("net_shares", 0),
                "buys": insider.get("total_buys", 0),
                "sells": insider.get("total_sells", 0),
            },
            "recommendations": recs,
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

    # ─── DB Update ───────────────────────────────────────

    def _update_signal_factors(self, signal_id: int, *,
                               technical: float, sentiment: float,
                               flow: float, composite: float,
                               detail: dict) -> None:
        """swing_signals에 팩터 점수 업데이트."""
        with self.pg.get_conn() as conn:
            conn.execute("""
                UPDATE swing_signals
                SET technical_score = %s,
                    sentiment_score = %s,
                    flow_score = %s,
                    composite_score = %s,
                    factor_detail = %s,
                    factor_scored_at = now()
                WHERE signal_id = %s
            """, (technical, sentiment, flow, composite,
                  json.dumps(detail, ensure_ascii=False, default=str),
                  signal_id))
            conn.commit()
