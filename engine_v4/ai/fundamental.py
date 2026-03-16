"""FundamentalAnalyzer — SEC 10-Q/10-K 기반 LLM 펀더멘탈 분석 (Tier 2.1).

시그널 승인 전 기업의 최신 SEC 공시(10-Q/10-K)를 분석하여
fundamental_score (0-100)를 생성.

스코어링 배분:
  Revenue Growth (30%): QoQ/YoY 매출 성장률
  Margin Trend (25%): 영업이익률 변화
  Debt Health (20%): 부채비율 변화, 만기 구조
  Management Guidance (25%): 구체적 수치 vs 모호한 표현

데이터 소스:
  1차: SEC EDGAR (EdgarRssMonitor) — 최신 10-Q/10-K 공시 메타데이터
  2차: Finnhub basic financials — 재무 지표 fallback
  분석: Claude Haiku 4.5 또는 Ollama 로컬 LLM
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime

from engine_v4.ai.data_feeds import FinnhubClient
from engine_v4.events.edgar import EdgarRssMonitor

logger = logging.getLogger(__name__)

# ─── LLM Prompt ──────────────────────────────────────────

FUNDAMENTAL_PROMPT = """You are a financial analyst evaluating {symbol}'s fundamentals for swing trading suitability.

Analyze the following financial data and SEC filing information:

{financial_data}

Score the company on these 4 dimensions (each 0-100):

1. **Revenue Growth (30% weight)**: QoQ and YoY revenue growth rate.
   - 80-100: >20% YoY growth, accelerating
   - 60-80: 10-20% growth, stable
   - 40-60: 0-10% growth, slowing
   - 20-40: Flat or slight decline
   - 0-20: Significant revenue decline

2. **Margin Trend (25% weight)**: Operating margin changes over recent quarters.
   - 80-100: Expanding margins, >20% operating margin
   - 60-80: Stable margins, 10-20% operating margin
   - 40-60: Slightly declining margins
   - 20-40: Compressing margins significantly
   - 0-20: Negative or severely deteriorating margins

3. **Debt Health (20% weight)**: Debt ratio, coverage, maturity structure.
   - 80-100: Net cash or very low debt, strong coverage
   - 60-80: Conservative debt levels, good coverage
   - 40-60: Moderate debt, adequate coverage
   - 20-40: High leverage, tight coverage
   - 0-20: Dangerous debt levels, refinancing risk

4. **Management Guidance (25% weight)**: Based on available data quality and outlook.
   - 80-100: Strong specific forward guidance with concrete numbers
   - 60-80: Positive outlook with some specifics
   - 40-60: Neutral or no guidance available
   - 20-40: Cautious or vague negative outlook
   - 0-20: Negative guidance, warnings

Respond in JSON only:
{{
  "fundamental_score": <weighted average 0-100>,
  "revenue_growth": <0-100>,
  "margin_trend": <0-100>,
  "debt_health": <0-100>,
  "guidance": <0-100>,
  "summary": "<2-3 sentence analysis>"
}}"""


class FundamentalAnalyzer:
    """SEC 10-Q/10-K 기반 LLM 펀더멘탈 분석기.

    Claude Haiku 4.5 우선, 없으면 Ollama fallback.
    분석 결과는 Redis에 7일 TTL로 캐싱.
    """

    def __init__(self, finnhub: FinnhubClient,
                 edgar: EdgarRssMonitor | None = None,
                 anthropic_key: str = "",
                 ollama_url: str = "", ollama_model: str = ""):
        self.finnhub = finnhub
        self.edgar = edgar or EdgarRssMonitor()
        self.anthropic_key = anthropic_key
        self._claude = None
        self._ollama_url = ollama_url or "http://localhost:11434"
        self._ollama_model = ollama_model or "qwen2.5:3b"
        self._ollama_available = False

        # Claude API 초기화
        if anthropic_key and anthropic_key not in ("", "your_anthropic_key_here"):
            try:
                import anthropic
                self._claude = anthropic.Anthropic(api_key=anthropic_key)
                logger.info("FundamentalAnalyzer: Claude API ready")
            except (ImportError, Exception) as e:
                logger.warning(f"FundamentalAnalyzer: Claude unavailable: {e}")

        # Ollama fallback
        if not self._claude:
            self._ollama_available = self._check_ollama()
            if self._ollama_available:
                logger.info(f"FundamentalAnalyzer: Ollama ({self._ollama_model}) ready")

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

    @property
    def mode(self) -> str:
        """현재 LLM 모드 반환."""
        if self._claude:
            return "claude"
        if self._ollama_available:
            return f"ollama/{self._ollama_model}"
        return "rule_based"

    def analyze(self, symbol: str) -> dict:
        """종목 펀더멘탈 분석 — 메인 엔트리포인트.

        Returns: {
            fundamental_score: 0-100,
            revenue_growth: 0-100,
            margin_trend: 0-100,
            debt_health: 0-100,
            guidance: 0-100,
            summary: str,
            source: str,
            data_sources: list,
            analyzed_at: str,
        }
        """
        start = time.time()
        data_sources = []

        # 1) SEC EDGAR — 최신 10-Q/10-K 공시 메타데이터 수집
        edgar_info = self._get_edgar_filings(symbol)
        if edgar_info:
            data_sources.append("edgar")

        # 2) Finnhub — 재무 지표
        financials = self._get_finnhub_financials(symbol)
        if financials:
            data_sources.append("finnhub")

        # 3) 데이터가 전혀 없으면 기본값 반환
        if not edgar_info and not financials:
            logger.warning(f"FundamentalAnalyzer: No data available for {symbol}")
            return {
                "fundamental_score": 50,
                "revenue_growth": 50,
                "margin_trend": 50,
                "debt_health": 50,
                "guidance": 50,
                "summary": "No financial data available — neutral default score",
                "source": "no_data",
                "data_sources": [],
                "analyzed_at": datetime.now().isoformat(),
                "elapsed_sec": round(time.time() - start, 2),
            }

        # 4) 재무 데이터 구조화 (LLM 프롬프트용)
        financial_data = self._format_financial_data(symbol, financials, edgar_info)

        # 5) LLM 분석
        if self._claude:
            result = self._claude_analyze(symbol, financial_data)
        elif self._ollama_available:
            result = self._ollama_analyze(symbol, financial_data)
        else:
            result = self._rule_based_analyze(symbol, financials)

        elapsed = time.time() - start
        result["data_sources"] = data_sources
        result["analyzed_at"] = datetime.now().isoformat()
        result["elapsed_sec"] = round(elapsed, 2)

        logger.info(
            f"Fundamental {symbol}: score={result['fundamental_score']} "
            f"(RG={result['revenue_growth']} MT={result['margin_trend']} "
            f"DH={result['debt_health']} G={result['guidance']}) "
            f"[{result['source']}] {elapsed:.1f}s"
        )

        return result

    # ─── Data Collection ──────────────────────────────────

    def _get_edgar_filings(self, symbol: str) -> list[dict]:
        """SEC EDGAR에서 최신 10-Q/10-K 공시 메타데이터 조회."""
        try:
            events = self.edgar.scan_filings(
                [symbol], days_back=120, forms="10-Q,10-K"
            )
            filings = []
            for ev in events:
                detail = ev.detail if hasattr(ev, "detail") else {}
                filings.append({
                    "form_type": detail.get("form_type", ""),
                    "filing_date": detail.get("filing_date", ""),
                    "title": ev.title if hasattr(ev, "title") else "",
                    "accession": detail.get("accession", ""),
                })
            return filings
        except Exception as e:
            logger.warning(f"EDGAR lookup failed for {symbol}: {e}")
            return []

    def _get_finnhub_financials(self, symbol: str) -> dict:
        """Finnhub에서 기본 재무 지표 조회."""
        if not self.finnhub.is_available:
            return {}
        try:
            return self.finnhub.get_basic_financials(symbol) or {}
        except Exception as e:
            logger.warning(f"Finnhub financials failed for {symbol}: {e}")
            return {}

    def _format_financial_data(self, symbol: str,
                                financials: dict,
                                edgar_info: list[dict]) -> str:
        """LLM 프롬프트용 재무 데이터 구조화."""
        parts = [f"=== {symbol} Financial Summary ===\n"]

        # Finnhub 재무 지표
        if financials:
            parts.append("## Key Financial Metrics (Finnhub)")
            metric_labels = {
                "pe_ratio": "P/E Ratio (Normalized)",
                "pe_ttm": "P/E TTM",
                "pb_ratio": "P/B Ratio",
                "ps_ratio": "P/S Ratio",
                "ev_ebitda": "EV/EBITDA",
                "roe": "ROE TTM (%)",
                "roe_annual": "ROE Annual (%)",
                "net_margin": "Net Margin TTM (%)",
                "gross_margin": "Gross Margin TTM (%)",
                "operating_margin": "Operating Margin TTM (%)",
                "debt_equity": "Debt/Equity",
                "current_ratio": "Current Ratio",
                "revenue_growth_3y": "Revenue Growth 3Y (%)",
                "eps_growth_3y": "EPS Growth 3Y (%)",
                "eps_growth_5y": "EPS Growth 5Y (%)",
                "dividend_yield": "Dividend Yield (%)",
                "beta": "Beta",
                "52w_high": "52-Week High",
                "52w_low": "52-Week Low",
                "fcf_yield": "FCF Yield (%)",
            }
            for key, label in metric_labels.items():
                val = financials.get(key)
                if val is not None:
                    parts.append(f"  {label}: {val}")

        # SEC EDGAR 공시 정보
        if edgar_info:
            parts.append("\n## Recent SEC Filings (EDGAR)")
            for f in edgar_info[:5]:
                parts.append(
                    f"  {f['form_type']} — Filed: {f['filing_date']} "
                    f"| {f['title']}"
                )

        # 데이터 없는 경우
        if not financials and not edgar_info:
            parts.append("No financial data available.")

        return "\n".join(parts)

    # ─── LLM Analysis ────────────────────────────────────

    def _claude_analyze(self, symbol: str, financial_data: str) -> dict:
        """Claude API로 펀더멘탈 분석."""
        prompt = FUNDAMENTAL_PROMPT.format(
            symbol=symbol, financial_data=financial_data
        )

        try:
            response = self._claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            # JSON 파싱
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                data = json.loads(text)

            return self._validate_result(data, source="claude")

        except Exception as e:
            logger.warning(f"Claude fundamental analysis failed for {symbol}: {e}")
            return self._fallback_result(
                source="claude_error",
                summary=f"Claude analysis error: {str(e)[:100]}",
            )

    def _ollama_analyze(self, symbol: str, financial_data: str) -> dict:
        """Ollama 로컬 LLM으로 펀더멘탈 분석."""
        import requests

        prompt = FUNDAMENTAL_PROMPT.format(
            symbol=symbol, financial_data=financial_data
        )

        try:
            resp = requests.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 200, "temperature": 0.3},
                },
                timeout=90,
            )
            text = resp.json().get("response", "").strip()

            # JSON 파싱
            match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                data = json.loads(text)

            return self._validate_result(
                data, source=f"ollama/{self._ollama_model}"
            )

        except Exception as e:
            logger.warning(f"Ollama fundamental analysis failed for {symbol}: {e}")
            return self._fallback_result(
                source="ollama_error",
                summary=f"Ollama analysis error: {str(e)[:100]}",
            )

    def _rule_based_analyze(self, symbol: str, financials: dict) -> dict:
        """LLM 없을 때 룰 기반 펀더멘탈 점수 (Finnhub 지표 기반).

        각 카테고리별 Finnhub 지표를 매핑하여 점수 산출.
        """
        if not financials:
            return self._fallback_result(
                source="rule_based_no_data",
                summary="No financial data — neutral default",
            )

        # Revenue Growth (30%): revenue_growth_3y, eps_growth_3y 기반
        rev_growth = financials.get("revenue_growth_3y")
        eps_growth = financials.get("eps_growth_3y")
        if rev_growth is not None:
            if rev_growth >= 20:
                rg_score = 85
            elif rev_growth >= 10:
                rg_score = 70
            elif rev_growth >= 5:
                rg_score = 55
            elif rev_growth >= 0:
                rg_score = 40
            else:
                rg_score = 20
        elif eps_growth is not None:
            # EPS 성장률로 대체
            if eps_growth >= 15:
                rg_score = 75
            elif eps_growth >= 5:
                rg_score = 60
            elif eps_growth >= 0:
                rg_score = 45
            else:
                rg_score = 25
        else:
            rg_score = 50  # 데이터 없음 = 중립

        # Margin Trend (25%): operating_margin, gross_margin, net_margin
        op_margin = financials.get("operating_margin")
        gross_margin = financials.get("gross_margin")
        net_margin = financials.get("net_margin")

        margin_val = op_margin or gross_margin or net_margin
        if margin_val is not None:
            if margin_val >= 25:
                mt_score = 85
            elif margin_val >= 15:
                mt_score = 70
            elif margin_val >= 8:
                mt_score = 55
            elif margin_val >= 0:
                mt_score = 35
            else:
                mt_score = 15
        else:
            mt_score = 50

        # Debt Health (20%): debt_equity, current_ratio
        de_ratio = financials.get("debt_equity")
        current_ratio = financials.get("current_ratio")

        if de_ratio is not None:
            if de_ratio < 0.3:
                dh_score = 90
            elif de_ratio < 0.7:
                dh_score = 75
            elif de_ratio < 1.0:
                dh_score = 60
            elif de_ratio < 1.5:
                dh_score = 40
            else:
                dh_score = 20
        elif current_ratio is not None:
            if current_ratio >= 2.0:
                dh_score = 80
            elif current_ratio >= 1.5:
                dh_score = 65
            elif current_ratio >= 1.0:
                dh_score = 45
            else:
                dh_score = 25
        else:
            dh_score = 50

        # Guidance (25%): 룰 기반에서는 데이터 제한적 → 중립 기본
        # EPS 성장 일관성으로 대체 추정
        eps5 = financials.get("eps_growth_5y")
        if eps_growth is not None and eps5 is not None:
            if eps_growth > 0 and eps5 > 0:
                g_score = 70
            elif eps_growth > 0 or eps5 > 0:
                g_score = 55
            else:
                g_score = 30
        elif eps_growth is not None:
            g_score = 60 if eps_growth > 0 else 35
        else:
            g_score = 50

        # 가중 평균 계산
        fundamental = (
            rg_score * 0.30 +
            mt_score * 0.25 +
            dh_score * 0.20 +
            g_score * 0.25
        )

        summary_parts = []
        if rev_growth is not None:
            summary_parts.append(f"Rev growth 3Y: {rev_growth:.1f}%")
        if margin_val is not None:
            margin_name = "op" if op_margin else ("gross" if gross_margin else "net")
            summary_parts.append(f"{margin_name} margin: {margin_val:.1f}%")
        if de_ratio is not None:
            summary_parts.append(f"D/E: {de_ratio:.2f}")

        return {
            "fundamental_score": round(fundamental, 1),
            "revenue_growth": rg_score,
            "margin_trend": mt_score,
            "debt_health": dh_score,
            "guidance": g_score,
            "summary": "; ".join(summary_parts) if summary_parts else "Rule-based scoring from Finnhub metrics",
            "source": "rule_based",
        }

    # ─── Helpers ──────────────────────────────────────────

    @staticmethod
    def _validate_result(data: dict, source: str) -> dict:
        """LLM 응답 데이터 검증 + 정규화."""
        def _clamp(val, default=50):
            try:
                return max(0, min(100, int(val)))
            except (TypeError, ValueError):
                return default

        rg = _clamp(data.get("revenue_growth"))
        mt = _clamp(data.get("margin_trend"))
        dh = _clamp(data.get("debt_health"))
        g = _clamp(data.get("guidance"))

        # fundamental_score가 있으면 사용, 없으면 가중 평균 계산
        fs = data.get("fundamental_score")
        if fs is not None:
            fs = _clamp(fs)
        else:
            fs = round(rg * 0.30 + mt * 0.25 + dh * 0.20 + g * 0.25, 1)

        return {
            "fundamental_score": fs,
            "revenue_growth": rg,
            "margin_trend": mt,
            "debt_health": dh,
            "guidance": g,
            "summary": str(data.get("summary", ""))[:500],
            "source": source,
        }

    @staticmethod
    def _fallback_result(source: str, summary: str) -> dict:
        """에러/데이터 없을 때 기본 결과."""
        return {
            "fundamental_score": 50,
            "revenue_growth": 50,
            "margin_trend": 50,
            "debt_health": 50,
            "guidance": 50,
            "summary": summary,
            "source": source,
        }
