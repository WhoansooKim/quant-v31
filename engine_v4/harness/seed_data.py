"""Seed data — classic + modern strategy knowledge.

Run once at harness initialization to populate swing_knowledge with proven
strategies from academic + practitioner literature. variant_generator will
use these as prior knowledge when proposing new strategies.
"""

from __future__ import annotations

import logging
from datetime import datetime

from engine_v4.data.storage import PostgresStore
from engine_v4.harness.knowledge import add_knowledge, list_knowledge

logger = logging.getLogger(__name__)


SEED_ENTRIES = [
    # ─── 학술 — Momentum & Trend Following ───
    {
        "source_name": "Faber 2007 — Tactical Asset Allocation",
        "source_url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461",
        "title": "10-Month SMA Tactical Asset Allocation",
        "summary": "Hold asset when price > 10M SMA, otherwise cash. Reduces MDD ~50% with comparable returns.",
        "key_insights": [
            "10-month moving average for monthly bars (≈200d for daily)",
            "Binary on/off rule reduces emotional decisions",
            "Works across asset classes (equities, commodities, REITs)",
            "Whipsaw cost ~5%/yr but MDD reduction worth it",
        ],
        "strategy_hypothesis": {
            "entry": "QQQ daily close > SMA(200) AND VIX < 25",
            "exit": "QQQ daily close < SMA(200) OR VIX > 30",
            "sizing": "fixed (100% in / 0% out)",
        },
        "applicability_score": 85,
        "regime_relevance": "ALL",
        "tags": ["trend-following", "regime-filter", "MDD-control"],
        "source_tier": 0.9,
    },
    {
        "source_name": "Jegadeesh-Titman 1993 — Momentum",
        "source_url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1993.tb04702.x",
        "title": "Cross-Sectional Momentum (3-12 month winners)",
        "summary": "Stocks ranked by 3-12M past returns; top decile outperforms bottom 1%/month over 12 months. Reverses at 36+ months.",
        "key_insights": [
            "Rank universe by 6M return; buy top 20%, hold 3-6 months",
            "Effect strong in trending markets, weak in choppy",
            "Crash risk in market reversals (e.g., March 2009)",
            "Combine with quality (Fama-French) to reduce crash risk",
        ],
        "strategy_hypothesis": {
            "entry": "return_6M_rank > 0.80 AND volume_ratio > 1.2",
            "exit": "hold 5-15d OR ATR trailing 2.5x",
            "filter": "Avoid mean-reversion regime (VIX > 30)",
        },
        "applicability_score": 95,
        "regime_relevance": "BULL",
        "tags": ["momentum", "cross-sectional", "ranking"],
        "source_tier": 1.0,
    },
    {
        "source_name": "Antonacci 2014 — Dual Momentum",
        "source_url": "https://www.dualmomentum.net/",
        "title": "Dual Momentum (Relative + Absolute)",
        "summary": "Use BOTH cross-sectional (vs peers) AND time-series (vs cash) momentum. Filters out bear markets.",
        "key_insights": [
            "Relative: best of (QQQ, EFA, IWM, ...) over 12M",
            "Absolute: only invest if winner > 12M T-bill return",
            "When neither beats T-bill → 100% bonds/cash",
            "Reduces MDD vs pure cross-sectional momentum",
        ],
        "strategy_hypothesis": {
            "entry": "relative_rank top 20% AND return_12M > risk_free_rate",
            "exit": "relative_rank drops below 50% OR return_12M < risk_free",
        },
        "applicability_score": 88,
        "regime_relevance": "ALL",
        "tags": ["dual-momentum", "regime-filter", "absolute-momentum"],
        "source_tier": 0.95,
    },

    # ─── 학술 — Mean Reversion ───
    {
        "source_name": "Connors 2008 — RSI(2) Mean Reversion",
        "source_url": "https://www.amazon.com/Short-Term-Trading-Strategies-That-Work/dp/0980003083",
        "title": "RSI(2) < 5 buy, > 90 sell on SMA200 trending markets",
        "summary": "2-period RSI < 5 in uptrend (SMA200) = oversold dip. Exit RSI > 70 or +5%. Avg hold 3-5d.",
        "key_insights": [
            "Works only when close > SMA(200) — trend filter critical",
            "Avg holding 3-5 days, not multi-week",
            "Edge of ~0.4% per trade (small, needs scale)",
            "Disabled in our V4 May 2026 — was exiting winners too early",
        ],
        "strategy_hypothesis": {
            "entry": "close > SMA(200) AND RSI(2) < 5 AND volume_ratio > 1.0",
            "exit": "RSI(2) > 70 OR hold > 5d OR -5%",
            "sizing": "small (5-10% per position)",
        },
        "applicability_score": 50,  # Known to underperform vs our hold-to-target
        "regime_relevance": "BULL",
        "tags": ["mean-reversion", "RSI", "short-term"],
        "source_tier": 0.85,
    },

    # ─── 학술 — News & Sentiment ───
    {
        "source_name": "Tetlock 2007 — Media Sentiment",
        "source_url": "https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2007.01232.x",
        "title": "Giving Content to Investor Sentiment — Media Pessimism Predicts Returns",
        "summary": "High pessimism in WSJ predicts 1-week downward pressure followed by mean reversion. Effect lasts 5 days.",
        "key_insights": [
            "Pessimism % from negative word count in financial media",
            "Predicts short-term price pressure, NOT long-term value",
            "Reverses over 1 week — fade extreme pessimism",
            "Effect strongest for small-cap stocks",
        ],
        "strategy_hypothesis": {
            "filter": "sentiment_score < -0.5 (very negative) for 3 consecutive days → contrarian setup",
            "entry": "sentiment recovery (today > yesterday > 2 days ago) + price stabilization",
        },
        "applicability_score": 70,
        "regime_relevance": "ALL",
        "tags": ["sentiment", "news", "mean-reversion", "contrarian"],
        "source_tier": 1.0,
    },
    {
        "source_name": "Da-Engelberg-Gao 2011 — Google SVI Attention",
        "source_url": "https://www3.nd.edu/~zda/google.pdf",
        "title": "Investor Attention via Google Search Volume",
        "summary": "Spikes in Google Search Volume Index (SVI) predict 2-week price increase followed by reversal — retail attention.",
        "key_insights": [
            "SVI spike → +2 weeks higher prices",
            "Followed by 12-month reversal (retail FOMO)",
            "r/wsb attention is a similar (modern) proxy — Bradley 2024",
            "High retail attention = contrarian fade signal",
        ],
        "strategy_hypothesis": {
            "filter": "Reddit mention count > 90th percentile = contrarian signal",
            "action": "do NOT chase retail attention surges; consider fading",
        },
        "applicability_score": 75,
        "regime_relevance": "ALL",
        "tags": ["attention", "retail", "social", "contrarian"],
        "source_tier": 0.95,
    },

    # ─── 학술 — Factor Investing ───
    {
        "source_name": "Fama-French 1993, 2015 — Multi-Factor Model",
        "source_url": "https://en.wikipedia.org/wiki/Fama%E2%80%93French_three-factor_model",
        "title": "Market + Size + Value + Profitability + Investment factors",
        "summary": "5-factor model: market beta, SMB (small-cap), HML (value), RMW (profitability), CMA (low investment).",
        "key_insights": [
            "Profitability factor (RMW) — robust predictor",
            "Combine factors: e.g., small + value + quality",
            "Multi-factor smooths single-factor cycle risk",
            "Our V4 uses 6-factor (Tech/Sent/Flow/Quality/Value/Macro)",
        ],
        "strategy_hypothesis": {
            "scoring": "composite = Σ(factor_score × weight) regime-adaptive weights",
            "rebalance": "monthly or on regime change",
        },
        "applicability_score": 90,
        "regime_relevance": "ALL",
        "tags": ["factor", "academic", "multi-factor"],
        "source_tier": 1.0,
    },
    {
        "source_name": "Novy-Marx 2013 — Quality (GP/A)",
        "source_url": "https://rnm.simon.rochester.edu/research/OSoV.pdf",
        "title": "Gross Profitability is the 'Other Side of Value'",
        "summary": "GP/Assets (gross profit / total assets) predicts returns. High-GP firms outperform — clean quality measure.",
        "key_insights": [
            "GP/A is more predictive than ROA, ROE (avoids accounting manipulation)",
            "Combined with value (P/B) gives best results",
            "Our V4 watchlist TQM uses this",
        ],
        "strategy_hypothesis": {
            "filter": "GP/A > universe median AND P/B < 5",
        },
        "applicability_score": 80,
        "regime_relevance": "ALL",
        "tags": ["quality", "fundamental", "factor"],
        "source_tier": 1.0,
    },

    # ─── 학술 — Risk & Sizing ───
    {
        "source_name": "Thorp/Kelly 1956 — Kelly Criterion",
        "source_url": "https://en.wikipedia.org/wiki/Kelly_criterion",
        "title": "Kelly Position Sizing — f = (bp-q)/b",
        "summary": "Optimal bet size = (win% × win_size - loss%)/win_size. Use 25-50% (fractional Kelly) for noisy estimates.",
        "key_insights": [
            "Full Kelly maximizes log return but extremely volatile",
            "Quarter-Kelly (25%) standard in practice",
            "Requires reliable win-rate estimate (≥100 trades)",
            "Our watchlist TQM uses Quarter-Kelly",
        ],
        "strategy_hypothesis": {
            "sizing": "position_pct = 0.25 × ((win_rate × avg_win - (1-win_rate)) / avg_win)",
            "cap": "position_pct ≤ 25%",
        },
        "applicability_score": 85,
        "regime_relevance": "ALL",
        "tags": ["position-sizing", "risk", "kelly"],
        "source_tier": 1.0,
    },
    {
        "source_name": "Tharp 1998 — Trade Your Way to Financial Freedom",
        "source_url": "https://vantharpinstitute.com/tharp-think-trading-concepts/",
        "title": "R-multiples + Expectancy + SQN",
        "summary": "R = (exit - entry) / (entry - stop). Expectancy = E[R]. SQN = (mean_R / std_R) × √N. SQN > 1.6 = good.",
        "key_insights": [
            "R-multiples normalize across position sizes",
            "Expectancy >0 = positive edge",
            "SQN 1.6 = good, 2.0 = excellent, 0.5 = below average",
            "Our V4 currently SQN 0.81 — below average",
        ],
        "strategy_hypothesis": {
            "metric": "Track expectancy + SQN, target SQN > 1.6",
        },
        "applicability_score": 90,
        "regime_relevance": "ALL",
        "tags": ["metrics", "psychology", "expectancy"],
        "source_tier": 1.0,
    },

    # ─── 실무 — Macro ───
    {
        "source_name": "Dalio — Bridgewater All-Weather",
        "source_url": "https://www.bridgewater.com/research-library/the-all-weather-strategy/",
        "title": "All-Weather Portfolio (Risk Parity)",
        "summary": "Diversify by economic regime (growth↑/↓, inflation↑/↓), not by asset class. Use risk parity weighting.",
        "key_insights": [
            "4 economic regimes: Growth↑Inflation↑ (commodities), Growth↑Inflation↓ (stocks), Growth↓Inflation↑ (TIPS), Growth↓Inflation↓ (bonds)",
            "Risk parity: equal risk contribution per asset, not equal capital",
            "Rebalance quarterly",
            "Our V4 doesn't follow All-Weather but principles inform regime detection",
        ],
        "strategy_hypothesis": {
            "regime_detection": "VIX + yield_curve + dollar + copper-gold ratio",
            "regime_action": "Different position_pct + sector tilts per regime",
        },
        "applicability_score": 70,
        "regime_relevance": "ALL",
        "tags": ["macro", "diversification", "regime"],
        "source_tier": 1.0,
    },

    # ─── 실무 — Technical Analysis (다른 시스템) ───
    {
        "source_name": "Wyckoff 1931 — Volume Spread Analysis",
        "source_url": "https://en.wikipedia.org/wiki/Wyckoff_method",
        "title": "Accumulation/Distribution via Volume Spread Analysis",
        "summary": "Smart money leaves footprints in volume + price spread patterns. 4 phases: Accumulation, Markup, Distribution, Markdown.",
        "key_insights": [
            "High volume on narrow spread = effort vs result mismatch",
            "Spring: false breakdown then rally (accumulation end)",
            "Upthrust: false breakout then drop (distribution end)",
            "Useful for entry confirmation (volume confirms breakout)",
        ],
        "strategy_hypothesis": {
            "entry_filter": "Spring pattern: low > prev_low - 0.5*ATR AND close > prev_high",
            "volume_check": "current_volume > 1.5 × volume_avg_20d",
        },
        "applicability_score": 65,
        "regime_relevance": "SIDEWAYS",
        "tags": ["technical", "volume", "wyckoff", "smart-money"],
        "source_tier": 0.85,
    },
    {
        "source_name": "Carter 2010 — TTM Squeeze",
        "source_url": "https://www.simplertrading.com/squeeze",
        "title": "Bollinger Band + Keltner Channel Squeeze",
        "summary": "BB inside KC = low volatility consolidation; release = breakout direction follows momentum.",
        "key_insights": [
            "BB(20,2) inside KC(20,1.5) = squeeze on",
            "Squeeze release + positive momentum (MACD or LinReg slope) = breakout",
            "Squeeze fired vs squeeze on = signal vs setup",
            "Our V4 watchlist TQM uses this (Layer 3)",
        ],
        "strategy_hypothesis": {
            "entry": "BB inside KC for ≥5d AND BB breaks above KC AND volume > avg",
        },
        "applicability_score": 80,
        "regime_relevance": "ALL",
        "tags": ["technical", "volatility", "squeeze", "carter"],
        "source_tier": 0.9,
    },
    {
        "source_name": "O'Neil — IBD CAN SLIM",
        "source_url": "https://www.investors.com/ibd-university/can-slim/",
        "title": "CAN SLIM (Current earnings, Annual growth, New, Supply, Leader, Institutional, Market)",
        "summary": "Buy stocks with C: ≥25% EPS growth Q-over-Q, A: ≥25% yearly, N: new product/mgmt, S: float, L: leader (RS Rating ≥80), I: institutional, M: bull market.",
        "key_insights": [
            "RS Rating = relative performance vs S&P 500 last 52 weeks",
            "Buy at cup-with-handle or flat base breakout, not chasing",
            "Sell at -8% from purchase or breakdown",
            "Our V4 watchlist TQM uses IBD RS Rating (Layer 2)",
        ],
        "strategy_hypothesis": {
            "filter": "RS Rating ≥ 80 AND EPS growth ≥ 25% AND market uptrend",
        },
        "applicability_score": 80,
        "regime_relevance": "BULL",
        "tags": ["growth", "earnings", "RS-rating", "oneil"],
        "source_tier": 0.9,
    },
    {
        "source_name": "Weinstein 1988 — Stage Analysis",
        "source_url": "https://www.amazon.com/Secrets-Profiting-Bull-Bear-Markets/dp/1556231423",
        "title": "4-Stage Market Cycle (Accumulation → Advancing → Distribution → Declining)",
        "summary": "Trade only Stage 2 (advancing). Identify via SMA30 slope + price above. Avoid Stage 4 (declining).",
        "key_insights": [
            "Stage 1: sideways consolidation (basing)",
            "Stage 2: uptrend (BUY only here)",
            "Stage 3: topping",
            "Stage 4: downtrend (AVOID)",
            "Our V4 watchlist TQM uses Weinstein stages",
        ],
        "strategy_hypothesis": {
            "filter": "Stage 2 only: close > SMA(150) AND SMA(150) slope positive",
        },
        "applicability_score": 80,
        "regime_relevance": "ALL",
        "tags": ["stage-analysis", "weinstein", "trend"],
        "source_tier": 0.9,
    },

    # ─── 현대 — LLM/ML ───
    {
        "source_name": "Lopez-Lira & Tang 2023 — ChatGPT for stocks",
        "source_url": "https://arxiv.org/abs/2304.07619",
        "title": "Can ChatGPT Forecast Stock Price Movements?",
        "summary": "GPT-4 hit ~90% portfolio-day hit rate for headline reactions. Strongest for small caps + negative news.",
        "key_insights": [
            "LLM classification of news adds alpha",
            "Effect strongest for negative news + small caps",
            "Decay over 1-5 days",
            "Use LLM for: news classification, narrative generation, NOT direct trading",
        ],
        "strategy_hypothesis": {
            "use_llm_for": "news sentiment + entry signal validation, NOT real-time price action",
        },
        "applicability_score": 85,
        "regime_relevance": "ALL",
        "tags": ["LLM", "news", "GPT", "ML"],
        "source_tier": 1.0,
    },
    {
        "source_name": "Papasotiriou et al. 2025 — MarketSenseAI 2.0",
        "source_url": "https://arxiv.org/abs/2502.00415",
        "title": "Multi-Agent LLM with RAG over 10-K/10-Q/macro",
        "summary": "Chain-of-Agents + RAG achieved 125.9% cumulative S&P 100 return (2023-2024) vs index 73.5%.",
        "key_insights": [
            "Multi-agent: news agent + fundamentals agent + macro agent + synthesizer",
            "RAG over filings + earnings calls",
            "Daily batch (not real-time)",
            "Useful pattern for our daily post-market analysis",
        ],
        "strategy_hypothesis": {
            "architecture": "Multi-agent LLM with RAG over fundamentals + news + macro",
        },
        "applicability_score": 75,
        "regime_relevance": "ALL",
        "tags": ["LLM", "multi-agent", "RAG", "modern"],
        "source_tier": 0.95,
    },

    # ─── Counter-Example — Survivorship Bias 경고 ───
    {
        "source_name": "Barber-Odean 2000 — Individual Investors",
        "source_url": "https://faculty.haas.berkeley.edu/odean/papers/returns/individual_investor_performance_final.pdf",
        "title": "Trading is Hazardous to Your Wealth — Individuals Underperform",
        "summary": "Active individual traders underperform passive by 6.5%/yr due to overtrading, commissions, behavioral biases.",
        "key_insights": [
            "Individual traders avg -1.5% vs market",
            "Commission drag is significant",
            "Overtrading correlates with worse returns",
            "WARNING: confirms hard difficulty of beating market",
            "Implication: focus on execution quality, low turnover, edge validation",
        ],
        "strategy_hypothesis": {
            "discipline": "Minimize turnover, validate edge with N≥30 before parameter changes",
        },
        "applicability_score": 95,  # very high — warning to keep us honest
        "regime_relevance": "ALL",
        "tags": ["warning", "behavioral", "commission", "discipline"],
        "source_tier": 1.0,
    },
]


def seed_knowledge_base(pg: PostgresStore, force: bool = False) -> dict:
    """Insert seed data. Idempotent — skips if seed entries already exist (by source_name).

    Returns {inserted, skipped, total}.
    """
    inserted = 0
    skipped = 0

    # Get existing seed source_names
    existing = list_knowledge(pg, source_type="seed", limit=500)
    existing_names = {e["source_name"] for e in existing}

    for entry in SEED_ENTRIES:
        if not force and entry["source_name"] in existing_names:
            skipped += 1
            continue
        try:
            add_knowledge(
                pg,
                source_type="seed",
                source_name=entry["source_name"],
                title=entry["title"],
                source_url=entry.get("source_url"),
                summary=entry["summary"],
                key_insights=entry.get("key_insights"),
                strategy_hypothesis=entry.get("strategy_hypothesis"),
                applicability_score=entry.get("applicability_score", 50),
                regime_relevance=entry.get("regime_relevance", "ALL"),
                tags=entry.get("tags", []),
                source_tier=entry.get("source_tier", 0.5),
            )
            inserted += 1
        except Exception as e:
            logger.warning(f"Seed insert failed for {entry['source_name']}: {e}")

    return {"inserted": inserted, "skipped": skipped, "total": len(SEED_ENTRIES)}
