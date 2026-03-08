"""SEC EDGAR RSS Monitor — 공시 모니터링.

SEC EDGAR full-text search RSS:
  https://efts.sec.gov/LATEST/search-index?q=SYMBOL&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD&forms=8-K,13F-HR

SEC EDGAR company filings RSS:
  https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=&CIK=SYMBOL&type=8-K&dateb=&owner=include&count=5&search_text=&action=getcompany&output=atom
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

import httpx

from engine_v4.events.models import Event

logger = logging.getLogger(__name__)

# SEC requires identifying User-Agent
_HEADERS = {
    "User-Agent": "QuantV4 SwingTrader admin@quant-v4.local",
    "Accept": "application/json",
}

# EDGAR EFTS (Full-Text Search) JSON API
_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

# Important filing types and their severity
_FILING_SEVERITY = {
    "8-K": "warning",       # Material events (earnings, M&A, leadership)
    "8-K/A": "warning",     # Amended 8-K
    "13F-HR": "info",       # Institutional holdings (quarterly)
    "13F-HR/A": "info",     # Amended 13F
    "4": "info",            # Insider trading (Form 4)
    "SC 13D": "warning",    # >5% ownership (activist)
    "SC 13D/A": "warning",
    "SC 13G": "info",       # >5% passive
    "10-Q": "info",         # Quarterly report
    "10-K": "info",         # Annual report
}

# 8-K item types that are critical
_CRITICAL_8K_ITEMS = {
    "1.01",  # Entry into Material Agreement
    "1.02",  # Termination of Material Agreement
    "2.01",  # Acquisition/Disposition
    "2.04",  # Triggering Events (default)
    "2.05",  # Costs for Exit/Disposal
    "2.06",  # Material Impairments
    "4.01",  # Auditor Changes
    "4.02",  # Non-reliance on Financial Statements
    "5.01",  # Change in Control
    "5.02",  # Departure/Appointment of Officers
}


class EdgarRssMonitor:
    """SEC EDGAR 공시 모니터링 — EFTS JSON API."""

    def __init__(self):
        self._last_scan: dict[str, datetime] = {}  # symbol -> last scan time
        self._seen_accessions: set[str] = set()     # dedup by accession number
        self._min_interval = 1.2  # SEC rate limit: 10 req/sec

    def scan_filings(self, symbols: list[str],
                     days_back: int = 3,
                     forms: str = "8-K,4,SC 13D") -> list[Event]:
        """여러 종목의 최근 SEC 공시 스캔."""
        all_events: list[Event] = []

        for symbol in symbols:
            try:
                events = self._scan_symbol(symbol, days_back, forms)
                all_events.extend(events)
                time.sleep(self._min_interval)  # SEC rate limit
            except Exception as e:
                logger.warning(f"EDGAR scan failed for {symbol}: {e}")

        logger.info(f"EDGAR scan: {len(all_events)} filings found "
                    f"for {len(symbols)} symbols")
        return all_events

    def _scan_symbol(self, symbol: str, days_back: int,
                     forms: str) -> list[Event]:
        """단일 종목 SEC 공시 스캔 (EFTS JSON API)."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)

        params = {
            "q": f'"{symbol}"',
            "dateRange": "custom",
            "startdt": start_date.strftime("%Y-%m-%d"),
            "enddt": end_date.strftime("%Y-%m-%d"),
            "forms": forms,
        }

        try:
            with httpx.Client(timeout=15, headers=_HEADERS) as client:
                resp = client.get(_EFTS_URL, params=params)

                if resp.status_code == 403:
                    # EFTS might block; fall back to company search
                    return self._scan_symbol_atom(symbol, days_back, forms)

                if resp.status_code != 200:
                    logger.debug(f"EDGAR API {resp.status_code} for {symbol}")
                    return []

                data = resp.json()
                hits = data.get("hits", {}).get("hits", [])

        except Exception:
            # Fall back to atom feed
            return self._scan_symbol_atom(symbol, days_back, forms)

        events = []
        for hit in hits[:10]:  # Max 10 per symbol
            source = hit.get("_source", {})
            accession = source.get("file_num", "") or hit.get("_id", "")
            form_type = source.get("form_type", "")
            filing_date = source.get("file_date", "")
            display_names = source.get("display_names", [])
            entity = display_names[0] if display_names else symbol

            # Dedup
            dedup_key = f"{symbol}:{accession}:{form_type}"
            if dedup_key in self._seen_accessions:
                continue
            self._seen_accessions.add(dedup_key)

            # Severity
            severity = _FILING_SEVERITY.get(form_type, "info")

            events.append(Event(
                event_type="sec_filing",
                symbol=symbol,
                severity=severity,
                title=f"{symbol} SEC {form_type} filed ({filing_date})",
                detail={
                    "form_type": form_type,
                    "filing_date": filing_date,
                    "entity": entity,
                    "accession": accession,
                    "source": "edgar_efts",
                },
            ))

        return events

    def _scan_symbol_atom(self, symbol: str, days_back: int,
                          forms: str) -> list[Event]:
        """Fallback: SEC EDGAR Atom feed로 스캔."""
        form_list = forms.split(",")
        events = []

        for form_type in form_list[:3]:  # Limit form types
            url = (
                f"https://www.sec.gov/cgi-bin/browse-edgar"
                f"?action=getcompany&company=&CIK={symbol}"
                f"&type={form_type.strip()}&dateb=&owner=include"
                f"&count=5&search_text=&action=getcompany&output=atom"
            )

            try:
                with httpx.Client(timeout=15, headers=_HEADERS) as client:
                    resp = client.get(url)
                    if resp.status_code != 200:
                        continue

                    # Parse Atom XML simply
                    text = resp.text
                    entries = self._parse_atom_entries(text, symbol, form_type.strip())
                    events.extend(entries)

                time.sleep(self._min_interval)
            except Exception as e:
                logger.debug(f"EDGAR Atom failed for {symbol} {form_type}: {e}")

        return events

    def _parse_atom_entries(self, xml_text: str, symbol: str,
                            form_type: str) -> list[Event]:
        """Simple Atom XML parser (no lxml dependency)."""
        import re

        events = []
        entries = re.findall(r'<entry>(.*?)</entry>', xml_text, re.DOTALL)

        cutoff = datetime.now() - timedelta(days=7)

        for entry_xml in entries[:5]:
            # Extract fields
            title_match = re.search(r'<title[^>]*>(.*?)</title>', entry_xml)
            updated_match = re.search(r'<updated>(.*?)</updated>', entry_xml)
            link_match = re.search(r'<link[^>]*href="([^"]*)"', entry_xml)
            accession_match = re.search(
                r'accession-nunber.*?>(.*?)<', entry_xml)

            title = title_match.group(1) if title_match else f"{form_type} filing"
            updated = updated_match.group(1) if updated_match else ""
            link = link_match.group(1) if link_match else ""
            accession = (accession_match.group(1) if accession_match
                         else link[-20:] if link else "")

            # Date filter
            try:
                filing_dt = datetime.fromisoformat(
                    updated.replace("Z", "+00:00")).replace(tzinfo=None)
                if filing_dt < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

            # Dedup
            dedup_key = f"{symbol}:{accession}:{form_type}"
            if dedup_key in self._seen_accessions:
                continue
            self._seen_accessions.add(dedup_key)

            severity = _FILING_SEVERITY.get(form_type, "info")

            events.append(Event(
                event_type="sec_filing",
                symbol=symbol,
                severity=severity,
                title=f"{symbol} SEC {form_type}: {title[:100]}",
                detail={
                    "form_type": form_type,
                    "filing_date": updated[:10] if updated else "",
                    "link": link,
                    "accession": accession,
                    "source": "edgar_atom",
                },
            ))

        return events
