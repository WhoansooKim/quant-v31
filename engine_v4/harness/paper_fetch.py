"""논문 본문 수집 (§22.AO-24).

초록만으로는 수식 정의가 거의 없어 추출 품질이 낮았다(§22.AO-23).
arxiv HTML 본문을 받아 **신호 정의가 있을 법한 문단만** 골라 LLM 에 넘긴다.

- PDF 는 압축 스트림이라 파싱 실패 이력이 있어(2026-08-19) **HTML 만** 시도한다.
- 본문 전체는 5만자를 넘어 소형 모델 컨텍스트에 안 들어가므로, 정의 키워드가 있는
  문단만 추려 상한을 둔다.
"""

from __future__ import annotations

import logging
import re

import requests

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) quant-v31 research"}

# 신호 정의가 들어있을 법한 문단을 고르는 단서
DEF_KEYWORDS = (
    "we define", "is defined as", "is computed as", "we compute", "is calculated",
    "signal is", "factor is", "we construct", "defined by", "given by",
    "moving average", "rolling", "past returns", "turnover", "volatility",
    "volume", "reversal", "momentum", "spread", "ratio of", "log of",
    "standardized", "z-score", "rank", "percentile", "correlation between",
)

# 본문에서 건너뛸 구간
SKIP_HEADINGS = ("references", "bibliography", "acknowledg", "appendix a.1",
                 "declaration", "funding", "conflict of interest")


def to_html_url(url: str) -> str | None:
    """arxiv abs/pdf URL → HTML 본문 URL."""
    if not url:
        return None
    m = re.search(r"arxiv\.org/(?:abs|pdf|html)/([0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?)", url)
    if not m:
        return None
    return f"https://arxiv.org/html/{m.group(1)}"


def fetch_text(url: str, timeout: int = 30) -> str | None:
    """arxiv HTML 본문을 평문으로. 실패 시 None."""
    html_url = to_html_url(url)
    if not html_url:
        return None
    try:
        r = requests.get(html_url, headers=_UA, timeout=timeout)
        if r.status_code != 200 or len(r.text) < 2000:
            logger.debug(f"본문 없음({r.status_code}): {html_url}")
            return None
    except Exception as e:
        logger.debug(f"본문 수집 실패 {html_url}: {e}")
        return None

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text("\n")
    except Exception as e:
        logger.warning(f"HTML 파싱 실패: {e}")
        return None

    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def relevant_chunks(text: str, max_chars: int = 4000, max_paras: int = 12) -> str:
    """신호 정의가 있을 법한 문단만 추려 상한 내로 자른다."""
    if not text:
        return ""
    paras, cur = [], []
    for ln in text.splitlines():
        low = ln.lower()
        if any(h in low for h in SKIP_HEADINGS):
            break                      # 참고문헌 이후는 버린다
        if len(ln) < 40:               # 제목·캡션·짧은 줄은 문단 경계로
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        cur.append(ln)
    if cur:
        paras.append(" ".join(cur))

    scored = []
    for p in paras:
        low = p.lower()
        hits = sum(1 for k in DEF_KEYWORDS if k in low)
        if hits:
            scored.append((hits, p))
    scored.sort(key=lambda x: -x[0])

    out, total = [], 0
    for _, p in scored[:max_paras]:
        p = p[:1200]
        if total + len(p) > max_chars:
            break
        out.append(p)
        total += len(p)
    return "\n\n".join(out)


def fetch_relevant(url: str, max_chars: int = 4000) -> tuple[str, str]:
    """(본문요약, 상태) 반환. 상태: fulltext / no_html / no_relevant."""
    text = fetch_text(url)
    if not text:
        return "", "no_html"
    chunks = relevant_chunks(text, max_chars=max_chars)
    if not chunks:
        return "", "no_relevant"
    return chunks, "fulltext"
