"""SocialSentimentCollector — Reddit + StockTwits 감성 수집 및 분석.

Reddit: PRAW (4 subreddits, 무료 60 req/min)
StockTwits: REST API (무료 200 req/hour)
감성 분석: Ollama 로컬 LLM 또는 규칙 기반 fallback
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# ── StockTwits ────────────────────────────────────────
STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"

# ── Reddit subreddits ─────────────────────────────────
SUBREDDITS = ["wallstreetbets", "stocks", "investing", "StockMarket"]

# ── Ticker pattern ────────────────────────────────────
_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
_WORD_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")


class SocialSentimentCollector:
    """Reddit + StockTwits 소셜 감성 수집기."""

    def __init__(self, pg, cache=None,
                 reddit_client_id: str = "",
                 reddit_client_secret: str = "",
                 ollama_url: str = "http://localhost:11434",
                 ollama_model: str = "qwen2.5:3b"):
        self.pg = pg
        self.cache = cache
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model

        # Reddit client (optional)
        self.reddit = None
        if reddit_client_id and reddit_client_secret:
            try:
                import praw
                self.reddit = praw.Reddit(
                    client_id=reddit_client_id,
                    client_secret=reddit_client_secret,
                    user_agent="QuantV4-SocialSentiment/1.0",
                )
                logger.info("Reddit client initialized")
            except Exception as e:
                logger.warning(f"Reddit init failed: {e}")

    # ═══════════════════════════════════════════════════
    # StockTwits (always available, no auth needed)
    # ═══════════════════════════════════════════════════

    def get_stocktwits(self, symbol: str) -> dict:
        """StockTwits 감성 데이터 수집.

        Returns: {bullish_count, bearish_count, bullish_ratio, mention_count, sentiment_score}
        """
        cache_key = f"stocktwits:{symbol}"
        if self.cache:
            cached = self.cache.get_json(cache_key)
            if cached:
                return cached

        defaults = {
            "source": "stocktwits",
            "symbol": symbol,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "bullish_ratio": 0.5,
            "mention_count": 0,
            "sentiment_score": 0.0,
            "available": False,
        }

        try:
            resp = requests.get(
                f"{STOCKTWITS_BASE}/streams/symbol/{symbol}.json",
                timeout=10,
                headers={"User-Agent": "QuantV4/1.0"},
            )
            if resp.status_code != 200:
                logger.debug(f"StockTwits {symbol}: HTTP {resp.status_code}")
                return defaults

            data = resp.json()
            messages = data.get("messages", [])
            if not messages:
                return defaults

            bullish = 0
            bearish = 0
            neutral = 0
            for msg in messages:
                s = msg.get("entities", {}).get("sentiment", {})
                if s:
                    basic = s.get("basic", "")
                    if basic == "Bullish":
                        bullish += 1
                    elif basic == "Bearish":
                        bearish += 1
                    else:
                        neutral += 1
                else:
                    neutral += 1

            total_voted = bullish + bearish
            ratio = bullish / total_voted if total_voted > 0 else 0.5

            # sentiment_score: -100 ~ +100
            # ratio 0.5 = 0, ratio 1.0 = +100, ratio 0.0 = -100
            sentiment_score = (ratio - 0.5) * 200

            result = {
                "source": "stocktwits",
                "symbol": symbol,
                "bullish_count": bullish,
                "bearish_count": bearish,
                "neutral_count": neutral,
                "bullish_ratio": round(ratio, 3),
                "mention_count": len(messages),
                "sentiment_score": round(sentiment_score, 1),
                "available": True,
            }

            if self.cache:
                self.cache.set_json(cache_key, result, ttl=3600)

            return result

        except Exception as e:
            logger.error(f"StockTwits {symbol} error: {e}")
            return defaults

    # ═══════════════════════════════════════════════════
    # Reddit
    # ═══════════════════════════════════════════════════

    def get_reddit(self, symbol: str, hours: int = 24) -> dict:
        """Reddit 감성 데이터 수집.

        Returns: {mention_count, sentiment_score, bullish_ratio, top_posts, available}
        """
        cache_key = f"reddit:{symbol}"
        if self.cache:
            cached = self.cache.get_json(cache_key)
            if cached:
                return cached

        defaults = {
            "source": "reddit",
            "symbol": symbol,
            "mention_count": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "bullish_ratio": 0.5,
            "sentiment_score": 0.0,
            "top_posts": [],
            "available": False,
        }

        if not self.reddit:
            return defaults

        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            posts = []

            for sub_name in SUBREDDITS:
                try:
                    subreddit = self.reddit.subreddit(sub_name)
                    for post in subreddit.new(limit=50):
                        post_time = datetime.utcfromtimestamp(post.created_utc)
                        if post_time < cutoff:
                            continue

                        title = post.title or ""
                        body = (post.selftext or "")[:500]
                        text = f"{title} {body}"

                        # Check if symbol is mentioned
                        if self._mentions_symbol(text, symbol):
                            posts.append({
                                "title": title[:200],
                                "score": post.score,
                                "comments": post.num_comments,
                                "subreddit": sub_name,
                                "created": post_time.isoformat(),
                                "text": text[:300],
                            })
                except Exception as e:
                    logger.debug(f"Reddit r/{sub_name} error: {e}")
                    continue

            if not posts:
                return defaults

            # Sort by engagement (score + comments)
            posts.sort(key=lambda p: p["score"] + p["comments"], reverse=True)
            top_posts = posts[:5]

            # Sentiment analysis via Ollama or rule-based
            bullish, bearish, neutral = self._analyze_reddit_sentiment(posts, symbol)
            total_voted = bullish + bearish
            ratio = bullish / total_voted if total_voted > 0 else 0.5
            sentiment_score = (ratio - 0.5) * 200

            result = {
                "source": "reddit",
                "symbol": symbol,
                "mention_count": len(posts),
                "bullish_count": bullish,
                "bearish_count": bearish,
                "neutral_count": neutral,
                "bullish_ratio": round(ratio, 3),
                "sentiment_score": round(sentiment_score, 1),
                "top_posts": [
                    {"title": p["title"], "score": p["score"],
                     "comments": p["comments"], "subreddit": p["subreddit"]}
                    for p in top_posts
                ],
                "available": True,
            }

            if self.cache:
                self.cache.set_json(cache_key, result, ttl=3600)

            return result

        except Exception as e:
            logger.error(f"Reddit {symbol} error: {e}")
            return defaults

    def _mentions_symbol(self, text: str, symbol: str) -> bool:
        """텍스트에 심볼이 언급되는지 확인."""
        # $AAPL 형태
        if f"${symbol}" in text:
            return True
        # 단어로 매치 (대문자, 2글자 이상)
        words = set(re.findall(r"\b[A-Z]{2,5}\b", text))
        return symbol in words

    def _analyze_reddit_sentiment(
        self, posts: list[dict], symbol: str
    ) -> tuple[int, int, int]:
        """Reddit 게시글 감성 분석. Returns (bullish, bearish, neutral)."""
        bullish = 0
        bearish = 0
        neutral = 0

        # Try Ollama batch analysis
        try:
            texts = [p["text"][:200] for p in posts[:10]]
            combined = "\n---\n".join(
                f"Post {i+1}: {t}" for i, t in enumerate(texts)
            )

            prompt = (
                f"Analyze the sentiment of these social media posts about ${symbol} stock. "
                f"For each post, classify as BULLISH, BEARISH, or NEUTRAL.\n"
                f"Return ONLY a JSON array of strings like [\"BULLISH\",\"NEUTRAL\",\"BEARISH\",...]\n\n"
                f"{combined}"
            )

            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 200},
                },
                timeout=60,
            )

            if resp.status_code == 200:
                raw = resp.json().get("response", "")
                # Extract JSON array
                match = re.search(r"\[.*?\]", raw, re.DOTALL)
                if match:
                    sentiments = json.loads(match.group())
                    for s in sentiments:
                        s = s.upper().strip()
                        if "BULL" in s:
                            bullish += 1
                        elif "BEAR" in s:
                            bearish += 1
                        else:
                            neutral += 1
                    return bullish, bearish, neutral
        except Exception as e:
            logger.debug(f"Ollama sentiment failed, using rule-based: {e}")

        # Fallback: rule-based sentiment
        bull_words = {"buy", "bullish", "moon", "rocket", "long", "calls",
                      "undervalued", "breakout", "squeeze", "dip", "hold"}
        bear_words = {"sell", "bearish", "puts", "short", "overvalued",
                      "crash", "dump", "avoid", "drop", "tank"}

        for post in posts:
            text_lower = post["text"].lower()
            b_count = sum(1 for w in bull_words if w in text_lower)
            s_count = sum(1 for w in bear_words if w in text_lower)

            if b_count > s_count:
                bullish += 1
            elif s_count > b_count:
                bearish += 1
            else:
                neutral += 1

        return bullish, bearish, neutral

    # ═══════════════════════════════════════════════════
    # Combined: both sources
    # ═══════════════════════════════════════════════════

    def get_social_sentiment(self, symbol: str) -> dict:
        """Reddit + StockTwits 통합 소셜 감성.

        Returns: {combined_score, reddit, stocktwits, velocity, mention_count}
        """
        st = self.get_stocktwits(symbol)
        rd = self.get_reddit(symbol)

        # 가중 합산: Reddit 60% + StockTwits 40%
        rd_score = rd["sentiment_score"] if rd["available"] else 0
        st_score = st["sentiment_score"] if st["available"] else 0

        if rd["available"] and st["available"]:
            combined = rd_score * 0.6 + st_score * 0.4
        elif rd["available"]:
            combined = rd_score
        elif st["available"]:
            combined = st_score
        else:
            combined = 0.0

        total_mentions = rd["mention_count"] + st["mention_count"]

        # 극단적 긍정 감점 (과열 경고)
        if combined > 80 and total_mentions > 30:
            combined = combined * 0.8  # 20% dampening
            logger.info(f"{symbol}: extreme bullish sentiment dampened ({combined:.0f})")

        return {
            "symbol": symbol,
            "combined_score": round(combined, 1),
            "mention_count": total_mentions,
            "reddit": rd,
            "stocktwits": st,
            "analyzed_at": datetime.now().isoformat(),
        }

    # ═══════════════════════════════════════════════════
    # DB 저장
    # ═══════════════════════════════════════════════════

    def save_sentiment(self, symbol: str, data: dict) -> None:
        """소셜 감성 결과를 DB에 저장."""
        try:
            import psycopg
            with psycopg.connect(self.pg.dsn) as conn:
                with conn.cursor() as cur:
                    # Reddit
                    rd = data.get("reddit", {})
                    if rd.get("available"):
                        cur.execute("""
                            INSERT INTO swing_social_sentiment
                            (symbol, source, mention_count, bullish_count, bearish_count,
                             neutral_count, bullish_ratio, sentiment_score, top_posts)
                            VALUES (%s, 'reddit', %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            symbol, rd["mention_count"], rd["bullish_count"],
                            rd["bearish_count"], rd["neutral_count"],
                            rd["bullish_ratio"], rd["sentiment_score"],
                            json.dumps(rd.get("top_posts", [])),
                        ))

                    # StockTwits
                    st = data.get("stocktwits", {})
                    if st.get("available"):
                        cur.execute("""
                            INSERT INTO swing_social_sentiment
                            (symbol, source, mention_count, bullish_count, bearish_count,
                             neutral_count, bullish_ratio, sentiment_score)
                            VALUES (%s, 'stocktwits', %s, %s, %s, %s, %s, %s)
                        """, (
                            symbol, st["mention_count"], st["bullish_count"],
                            st["bearish_count"], st["neutral_count"],
                            st["bullish_ratio"], st["sentiment_score"],
                        ))

                conn.commit()
        except Exception as e:
            logger.error(f"Save social sentiment error: {e}")

    # ═══════════════════════════════════════════════════
    # Batch: collect for all universe
    # ═══════════════════════════════════════════════════

    def collect_all(self) -> dict:
        """유니버스 전체 종목 소셜 감성 수집.

        Returns: {collected, symbols, errors}
        """
        symbols = [s["symbol"] for s in self.pg.get_universe()]
        collected = 0
        errors = 0

        for symbol in symbols:
            try:
                data = self.get_social_sentiment(symbol)
                if data["mention_count"] > 0:
                    self.save_sentiment(symbol, data)
                    collected += 1
                time.sleep(0.5)  # rate limit
            except Exception as e:
                logger.error(f"Social collect {symbol}: {e}")
                errors += 1

        logger.info(f"Social sentiment collected: {collected}/{len(symbols)} symbols, {errors} errors")
        return {"collected": collected, "total": len(symbols), "errors": errors}
