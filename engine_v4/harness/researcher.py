"""Weekly autonomous research agent.

Runs every Sunday 10:00 KST. Collects fresh quant trading content from
external sources, uses Ollama to extract key insights + strategy hypotheses,
and stores in swing_knowledge for use by variant_generator.

Sources (graceful degradation — any failure logged but doesn't stop pipeline):
  - arxiv.org/q-fin (quantitative finance papers)
  - SSRN (financial economics — RSS not available, skip unless API key)
  - Quantpedia (free preview blog posts)
  - Reddit r/algotrading (top weekly via JSON API)

Pipeline:
  1. fetch_each_source() → raw items
  2. dedup vs swing_knowledge (URL match)
  3. ollama_extract() per item → summary + insights + hypothesis + score
  4. add_knowledge() — persist
  5. telegram_digest() — top 5 by applicability
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any

import requests

from engine_v4.data.storage import PostgresStore
from engine_v4.harness.knowledge import add_knowledge, list_knowledge, log_action
from engine_v4.notify.telegram import TelegramNotifier

logger = logging.getLogger(__name__)

USER_AGENT = "QuantV4-Researcher/1.0 (educational)"
HTTP_TIMEOUT = 15

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen2.5:3b"  # use larger model for research extraction (better quality)


# ─── Source fetchers (each returns list[dict] with {url, title, abstract, source, published_at}) ───

def fetch_arxiv_qfin(max_items: int = 15) -> list[dict]:
    """arxiv.org q-fin papers — last 7 days."""
    try:
        url = ("http://export.arxiv.org/api/query?"
               "search_query=cat:q-fin.TR+OR+cat:q-fin.PM+OR+cat:q-fin.ST"
               "&sortBy=submittedDate&sortOrder=descending"
               f"&max_results={max_items}")
        resp = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return []
        # Simple regex parse (avoid xml dep)
        text = resp.text
        items: list[dict] = []
        entries = re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL)
        for e in entries[:max_items]:
            id_m = re.search(r"<id>(.*?)</id>", e)
            title_m = re.search(r"<title>(.*?)</title>", e, re.DOTALL)
            abstract_m = re.search(r"<summary>(.*?)</summary>", e, re.DOTALL)
            published_m = re.search(r"<published>(.*?)</published>", e)
            if not id_m or not title_m:
                continue
            items.append({
                "url": id_m.group(1).strip(),
                "title": re.sub(r"\s+", " ", title_m.group(1)).strip(),
                "abstract": re.sub(r"\s+", " ", (abstract_m.group(1) if abstract_m else "")).strip()[:1500],
                "source": "arxiv.q-fin",
                "source_tier": 1.0,
                "published_at": published_m.group(1) if published_m else None,
            })
        return items
    except Exception as e:
        logger.warning(f"arxiv fetch failed: {e}")
        return []


def fetch_reddit_algotrading(max_items: int = 10) -> list[dict]:
    """Reddit r/algotrading top weekly via JSON API (no auth needed for public)."""
    try:
        url = f"https://www.reddit.com/r/algotrading/top.json?t=week&limit={max_items}"
        resp = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return []
        data = resp.json()
        items: list[dict] = []
        for child in data.get("data", {}).get("children", [])[:max_items]:
            d = child.get("data", {})
            if d.get("score", 0) < 50:
                continue  # noise filter
            items.append({
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "title": d.get("title", "")[:200],
                "abstract": (d.get("selftext") or "")[:1500],
                "source": "reddit.r/algotrading",
                "source_tier": 0.4,
                "published_at": datetime.fromtimestamp(d.get("created_utc", time.time())).isoformat(),
            })
        return items
    except Exception as e:
        logger.warning(f"reddit fetch failed: {e}")
        return []


def fetch_reddit_quantfinance(max_items: int = 10) -> list[dict]:
    """Reddit r/quantfinance top weekly."""
    try:
        url = f"https://www.reddit.com/r/quantfinance/top.json?t=week&limit={max_items}"
        resp = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return []
        data = resp.json()
        items: list[dict] = []
        for child in data.get("data", {}).get("children", [])[:max_items]:
            d = child.get("data", {})
            if d.get("score", 0) < 30:
                continue
            items.append({
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "title": d.get("title", "")[:200],
                "abstract": (d.get("selftext") or "")[:1500],
                "source": "reddit.r/quantfinance",
                "source_tier": 0.5,
                "published_at": datetime.fromtimestamp(d.get("created_utc", time.time())).isoformat(),
            })
        return items
    except Exception as e:
        logger.warning(f"reddit quantfinance fetch failed: {e}")
        return []


def fetch_quantocracy(max_items: int = 10) -> list[dict]:
    """Quantocracy RSS — aggregator of quant blogs."""
    try:
        url = "https://quantocracy.com/feed/"
        resp = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return []
        text = resp.text
        items: list[dict] = []
        entries = re.findall(r"<item>(.*?)</item>", text, re.DOTALL)
        for e in entries[:max_items]:
            url_m = re.search(r"<link>(.*?)</link>", e)
            title_m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", e, re.DOTALL)
            desc_m = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", e, re.DOTALL)
            pub_m = re.search(r"<pubDate>(.*?)</pubDate>", e)
            if not url_m or not title_m:
                continue
            items.append({
                "url": url_m.group(1).strip(),
                "title": re.sub(r"\s+", " ", title_m.group(1)).strip(),
                "abstract": re.sub(r"<[^>]+>", " ", desc_m.group(1) if desc_m else "")[:1500],
                "source": "quantocracy",
                "source_tier": 0.7,
                "published_at": pub_m.group(1) if pub_m else None,
            })
        return items
    except Exception as e:
        logger.warning(f"quantocracy fetch failed: {e}")
        return []


# ─── LLM extraction (Ollama) ───

def _ollama_extract(item: dict, ollama_url: str = OLLAMA_URL,
                     model: str = OLLAMA_MODEL, timeout: int = 60) -> dict[str, Any]:
    """Use Ollama to extract structured insights from a raw item."""
    prompt = f"""You are a quant trading research assistant. Read this article and extract structured insights.

ARTICLE:
Title: {item.get('title', '')}
Source: {item.get('source', '')}
Abstract/Body: {item.get('abstract', '')[:1200]}

Extract the following in JSON format:
- summary (1-2 sentences in Korean)
- key_insights (list of 2-5 strings in Korean, each ≤30 words)
- strategy_hypothesis (object with optional keys: filter, entry, exit, sizing — describe in code-like pseudocode)
- applicability_score (0-100, how applicable to a momentum swing trading system on US equities)
- regime_relevance (one of: BULL, BEAR, SIDEWAYS, ALL)
- tags (list of 2-5 lowercase keywords, e.g. ["momentum", "mean-reversion"])

Output JSON only:
{{"summary":"...","key_insights":[...],"strategy_hypothesis":{{}},"applicability_score":N,"regime_relevance":"...","tags":[...]}}"""

    try:
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json={
                "model": model, "prompt": prompt,
                "format": "json", "stream": False,
                "keep_alive": "30m",
                "options": {
                    "temperature": 0.2, "num_predict": 800,
                    "num_ctx": 4096, "num_thread": 4,
                },
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            return {}
        raw = resp.json().get("response", "")
        try:
            import json as _json
            return _json.loads(raw)
        except Exception:
            return {}
    except Exception as e:
        logger.warning(f"Ollama extract failed for {item.get('title','')[:50]}: {e}")
        return {}


# ─── Main pipeline ───

def run_research(pg: PostgresStore, notifier: TelegramNotifier | None = None) -> dict[str, Any]:
    """Full weekly research run."""
    t0 = time.time()
    log_action(pg, "research_run", "started")

    # 1. Fetch from all sources
    raw_items: list[dict] = []
    for fetcher, label in [
        (fetch_arxiv_qfin, "arxiv"),
        (fetch_reddit_algotrading, "reddit_algo"),
        (fetch_reddit_quantfinance, "reddit_quant"),
        (fetch_quantocracy, "quantocracy"),
    ]:
        try:
            items = fetcher()
            logger.info(f"Researcher: {label} → {len(items)} items")
            raw_items.extend(items)
        except Exception as e:
            logger.warning(f"Source {label} failed: {e}")

    # 2. Dedup vs existing knowledge by URL
    existing = list_knowledge(pg, limit=500)
    existing_urls = {e.get("source_url") for e in existing if e.get("source_url")}
    new_items = [i for i in raw_items if i["url"] not in existing_urls]
    logger.info(f"Researcher: {len(raw_items)} fetched, {len(new_items)} new after dedup")

    # 3. LLM extract for each new item (cap to 30 to limit time)
    inserted_ids: list[int] = []
    skipped_low_quality = 0
    for item in new_items[:30]:
        ext = _ollama_extract(item)
        if not ext or not ext.get("summary"):
            skipped_low_quality += 1
            continue
        # Filter very low applicability
        applicability = int(ext.get("applicability_score", 50))
        if applicability < 30:
            skipped_low_quality += 1
            continue
        try:
            source_type = "paper" if "arxiv" in item["source"] else (
                "forum" if "reddit" in item["source"] else "blog"
            )
            kid = add_knowledge(
                pg,
                source_type=source_type,
                source_url=item["url"],
                source_name=item["source"],
                title=item["title"],
                summary=ext.get("summary", ""),
                key_insights=ext.get("key_insights", []),
                strategy_hypothesis=ext.get("strategy_hypothesis", {}),
                applicability_score=applicability,
                regime_relevance=ext.get("regime_relevance", "ALL"),
                tags=ext.get("tags", []),
                source_tier=item.get("source_tier", 0.5),
                published_at=_parse_date(item.get("published_at")),
            )
            inserted_ids.append(kid)
        except Exception as e:
            logger.warning(f"add_knowledge failed for {item['title'][:50]}: {e}")

    elapsed = time.time() - t0
    summary = {
        "fetched": len(raw_items),
        "new_after_dedup": len(new_items),
        "inserted": len(inserted_ids),
        "skipped_low_quality": skipped_low_quality,
        "elapsed_sec": round(elapsed, 1),
    }
    log_action(pg, "research_run", "completed", details=summary, elapsed_sec=elapsed)

    # 4. Telegram digest — top 5 newly inserted by applicability
    if notifier and inserted_ids:
        try:
            top = sorted(
                [get_knowledge_for_digest(pg, kid) for kid in inserted_ids],
                key=lambda k: k.get("applicability_score", 0) if k else 0,
                reverse=True,
            )[:5]
            msg = _format_research_digest(top, summary)
            asyncio.run(notifier.send(msg))
        except Exception as e:
            logger.warning(f"Research digest send failed: {e}")

    return summary


def get_knowledge_for_digest(pg: PostgresStore, kid: int) -> dict | None:
    from engine_v4.harness.knowledge import get_knowledge as _get
    return _get(pg, kid)


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(s)
        except Exception:
            return None


def _format_research_digest(top: list[dict], summary: dict) -> str:
    lines = [
        "🔬 *Weekly Research Digest*",
        "",
        f"Fetched: {summary['fetched']} | New: {summary['new_after_dedup']} | Inserted: {summary['inserted']} | Time: {summary['elapsed_sec']}s",
        "",
        "*Top 5 by Applicability*",
    ]
    for i, k in enumerate(top, 1):
        if not k:
            continue
        title = (k.get("title") or "")[:80]
        score = k.get("applicability_score", "?")
        src = k.get("source_name") or ""
        lines.append(f"{i}. [{score}] {title}")
        lines.append(f"   _{src}_")
        summary_text = (k.get("summary") or "")[:120]
        if summary_text:
            lines.append(f"   {summary_text}")
        lines.append("")
    lines.append("View all: /analysis → Harness tab")
    return "\n".join(lines)
