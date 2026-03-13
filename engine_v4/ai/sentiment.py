"""SentimentAnalyzer — Claude API 기반 시그널 분석.

pending 시그널의 종목에 대해:
  1. yfinance로 최근 뉴스 헤드라인 수집
  2. 기술적 지표(indicators) 요약
  3. Claude API에 분석 요청 → 1-10 점수 + 분석 텍스트
  4. DB에 llm_score / llm_analysis / llm_analyzed_at 업데이트

API 키가 없으면 mock 모드로 동작 (로그 경고 후 기본 점수 반환).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import yfinance as yf

from engine_v4.data.storage import PostgresStore

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are a quantitative equity analyst. Analyze the following stock signal and provide:
1. A sentiment/confidence score from 1-10 (10 = highest conviction buy)
2. Brief reasoning (2-3 sentences)
3. Key risk factors (1-2 sentences)

Stock: {symbol}
Signal Type: {signal_type}
Entry Price: ${entry_price:.2f}
Stop Loss: ${stop_loss:.2f} ({sl_pct:+.1f}%)
Take Profit: ${take_profit:.2f} ({tp_pct:+.1f}%)

Technical Indicators:
- 20d Return Rank: {rank} (percentile among universe)
- Trend Aligned (Close > SMA50 > SMA200): {trend}
- 5-Day Breakout: {breakout}
- Volume Surge: {volume_surge}
- Current Price: ${close:.2f}
- SMA50: ${sma50:.2f}
- SMA200: ${sma200:.2f}

Recent News Headlines:
{news}

Respond in this exact JSON format (no markdown):
{{"score": <1-10>, "reasoning": "<2-3 sentences>", "risk_factors": "<1-2 sentences>", "news_summary": "<1 sentence summary of news sentiment>"}}"""

# Ollama용 간결 프롬프트 (CPU에서 빠른 처리를 위해)
OLLAMA_ANALYSIS_PROMPT = """Score this stock signal 1-10 (10=strong buy). JSON only.

{symbol} {signal_type} at ${entry_price:.2f} | SL ${stop_loss:.2f} | TP ${take_profit:.2f}
Trend: {trend} | Breakout: {breakout} | Volume: {volume_surge} | Rank: {rank}
News: {news_short}

{{"score":<1-10>,"reasoning":"<1 sentence>","risk_factors":"<1 sentence>","news_summary":"<1 sentence>"}}"""


class SentimentAnalyzer:
    """Claude API / Ollama 로컬 LLM 기반 시그널 분석기."""

    def __init__(self, pg: PostgresStore, api_key: str = "",
                 ollama_url: str = "", ollama_model: str = ""):
        self.pg = pg
        self.api_key = api_key
        self._client = None
        self._ollama_url = ollama_url or "http://localhost:11434"
        self._ollama_model = ollama_model or "qwen2.5:3b"
        self._ollama_available = False

        if self.api_key and self.api_key != "your_anthropic_key_here":
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
                logger.info("SentimentAnalyzer: Claude API initialized")
            except ImportError:
                logger.warning("SentimentAnalyzer: anthropic package not installed")
            except Exception as e:
                logger.warning(f"SentimentAnalyzer: Failed to init Claude client: {e}")

        if not self._client:
            # Ollama 로컬 LLM 사용 시도
            self._ollama_available = self._check_ollama()
            if self._ollama_available:
                logger.info(f"SentimentAnalyzer: Ollama ({self._ollama_model}) initialized")
            else:
                logger.info("SentimentAnalyzer: No Claude API / No Ollama — running in mock mode")

    def _check_ollama(self) -> bool:
        """Ollama 서버 + 모델 사용 가능 여부 확인."""
        import requests as req
        try:
            resp = req.get(f"{self._ollama_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            return any(self._ollama_model in m for m in models)
        except Exception:
            return False

    @property
    def is_live(self) -> bool:
        return self._client is not None or self._ollama_available

    @property
    def mode(self) -> str:
        if self._client:
            return "claude"
        if self._ollama_available:
            return "ollama"
        return "mock"

    def analyze_signal(self, signal_id: int) -> dict:
        """단일 시그널 AI 분석 → DB 업데이트.

        Returns: {"signal_id": ..., "score": ..., "analysis": ..., "mode": "live"|"mock"}
        """
        sig = self.pg.get_signal(signal_id)
        if not sig:
            raise ValueError(f"Signal {signal_id} not found")

        symbol = sig["symbol"]
        signal_type = sig["signal_type"]

        # 기술 지표 조회
        indicators = self.pg.get_indicator_history(symbol, days=5)
        latest_ind = indicators[-1] if indicators else {}

        # 뉴스 수집
        news_headlines = self._fetch_news(symbol)

        # 분석 실행
        entry_price = float(sig.get("entry_price") or 0)
        stop_loss = float(sig.get("stop_loss") or 0)
        take_profit = float(sig.get("take_profit") or 0)

        context = {
            "symbol": symbol,
            "signal_type": signal_type,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "sl_pct": ((stop_loss / entry_price) - 1) * 100 if entry_price else 0,
            "tp_pct": ((take_profit / entry_price) - 1) * 100 if entry_price else 0,
            "rank": f"{float(sig.get('return_20d_rank') or 0):.0%}",
            "trend": "Yes" if sig.get("trend_aligned") else "No",
            "breakout": "Yes" if sig.get("breakout_5d") else "No",
            "volume_surge": "Yes" if sig.get("volume_surge") else "No",
            "close": float(latest_ind.get("close") or entry_price),
            "sma50": float(latest_ind.get("sma_50") or 0),
            "sma200": float(latest_ind.get("sma_200") or 0),
            "news": news_headlines or "No recent news found.",
        }

        if self._client:
            result = self._call_claude(context)
        elif self._ollama_available:
            result = self._call_ollama(context)
        else:
            result = self._mock_analysis(context)

        # DB 업데이트
        self._update_signal_llm(signal_id, result["score"], result["analysis"])

        return {
            "signal_id": signal_id,
            "symbol": symbol,
            "score": result["score"],
            "analysis": result["analysis"],
            "mode": self.mode,
        }

    def analyze_pending(self) -> list[dict]:
        """모든 pending 시그널 분석."""
        signals = self.pg.get_signals(status="pending", limit=20)
        results = []
        for sig in signals:
            # 이미 분석된 시그널 스킵
            if sig.get("llm_score") is not None:
                continue
            try:
                result = self.analyze_signal(sig["signal_id"])
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to analyze signal {sig['signal_id']}: {e}")
        return results

    def _fetch_news(self, symbol: str, max_items: int = 5) -> str:
        """yfinance 뉴스 헤드라인 수집."""
        try:
            ticker = yf.Ticker(symbol)
            news = ticker.news or []
            headlines = []
            for item in news[:max_items]:
                title = item.get("title", "")
                publisher = item.get("publisher", "")
                if title:
                    headlines.append(f"- {title} ({publisher})")
            return "\n".join(headlines) if headlines else "No recent news found."
        except Exception as e:
            logger.warning(f"News fetch failed for {symbol}: {e}")
            return "News fetch failed."

    def _call_claude(self, context: dict) -> dict:
        """Claude API 호출."""
        prompt = ANALYSIS_PROMPT.format(**context)
        start = time.time()

        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )

            elapsed = time.time() - start
            text = response.content[0].text.strip()

            # JSON 파싱
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                # JSON 블록 추출 시도
                import re
                match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                else:
                    logger.warning(f"Claude response not JSON: {text[:200]}")
                    data = {"score": 5, "reasoning": text[:200], "risk_factors": "Parse error"}

            score = max(1, min(10, int(data.get("score", 5))))
            analysis = json.dumps({
                "reasoning": data.get("reasoning", ""),
                "risk_factors": data.get("risk_factors", ""),
                "news_summary": data.get("news_summary", ""),
                "model": "claude-haiku-4-5",
                "elapsed_sec": round(elapsed, 2),
            }, ensure_ascii=False)

            logger.info(f"Claude analysis for {context['symbol']}: "
                        f"score={score} in {elapsed:.1f}s")
            return {"score": score, "analysis": analysis}

        except Exception as e:
            logger.error(f"Claude API call failed: {e}")
            return self._mock_analysis(context, error=str(e))

    def _call_ollama(self, context: dict) -> dict:
        """Ollama 로컬 LLM 호출 (간결 프롬프트)."""
        import requests as req

        # 뉴스를 1줄로 축약
        news_raw = context.get("news", "No news")
        news_lines = [l.strip("- ").split("(")[0].strip() for l in news_raw.split("\n") if l.strip()]
        news_short = "; ".join(news_lines[:3]) if news_lines else "No news"
        ctx = {**context, "news_short": news_short[:200]}

        prompt = OLLAMA_ANALYSIS_PROMPT.format(**ctx)
        start = time.time()

        try:
            resp = req.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 150, "temperature": 0.3},
                },
                timeout=600,
            )
            elapsed = time.time() - start
            text = resp.json().get("response", "").strip()

            # JSON 파싱
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                import re
                match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                else:
                    logger.warning(f"Ollama response not JSON: {text[:200]}")
                    data = {"score": 5, "reasoning": text[:200], "risk_factors": "Parse error"}

            score = max(1, min(10, int(data.get("score", 5))))
            analysis = json.dumps({
                "reasoning": data.get("reasoning", ""),
                "risk_factors": data.get("risk_factors", ""),
                "news_summary": data.get("news_summary", ""),
                "model": f"ollama/{self._ollama_model}",
                "elapsed_sec": round(elapsed, 2),
            }, ensure_ascii=False)

            logger.info(f"Ollama analysis for {context['symbol']}: "
                        f"score={score} in {elapsed:.1f}s")
            return {"score": score, "analysis": analysis}

        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return self._mock_analysis(context, error=str(e))

    def _mock_analysis(self, context: dict, error: str | None = None) -> dict:
        """Mock 분석 — API 키 없을 때 기술적 지표 기반 점수."""
        score = 5  # 기본

        # 기술 지표로 가산/감산
        if context.get("trend") == "Yes":
            score += 1
        if context.get("breakout") == "Yes":
            score += 1
        if context.get("volume_surge") == "Yes":
            score += 1

        # rank 파싱 (예: "85%")
        try:
            rank_str = context.get("rank", "0%")
            rank_val = float(rank_str.replace("%", "")) / 100
            if rank_val >= 0.8:
                score += 1
            elif rank_val >= 0.9:
                score += 2
        except (ValueError, TypeError):
            pass

        score = max(1, min(10, score))

        analysis = json.dumps({
            "reasoning": f"Mock analysis based on technical indicators. "
                         f"Trend={'aligned' if context.get('trend') == 'Yes' else 'not aligned'}, "
                         f"Breakout={'confirmed' if context.get('breakout') == 'Yes' else 'no'}, "
                         f"Volume={'surging' if context.get('volume_surge') == 'Yes' else 'normal'}.",
            "risk_factors": "Mock mode — no LLM available. "
                            "Install Ollama (ollama pull qwen2.5:3b) or set ANTHROPIC_KEY for AI analysis.",
            "news_summary": "N/A (mock mode)",
            "model": "mock",
            "error": error,
        }, ensure_ascii=False)

        logger.info(f"Mock analysis for {context['symbol']}: score={score}")
        return {"score": score, "analysis": analysis}

    def _update_signal_llm(self, signal_id: int, score: int, analysis: str) -> None:
        """swing_signals에 LLM 분석 결과 업데이트."""
        with self.pg.get_conn() as conn:
            conn.execute("""
                UPDATE swing_signals
                SET llm_score = %s,
                    llm_analysis = %s,
                    llm_analyzed_at = now()
                WHERE signal_id = %s
            """, (score, analysis, signal_id))
            conn.commit()
