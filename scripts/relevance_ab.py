#!/usr/bin/env python
"""①단계 관련성 판정 A/B — 표본의 72%를 버리는 그 판정을 고칠 수 있는가 (§22.AO-51).

왜: `llm_momentum` 은 ①(종목 고유 뉴스인가) → ②(방향) 2단 분해인데, 실측 결과
①에서 **93건 중 67건(72%)** 이 기각되어 강제 중립 50 이 된다(§22.AO-49).
그러면 ②를 아무리 손봐도 4건 중 3건은 ②에 도달하지 못한다. 그리고 저장된 근거를 보니
"Why ServiceNow (NOW) Stock Is Trading Up Today" 같은 명백한 자기 회사 뉴스가 NO 였다.

가설: 프롬프트가 **티커만** 주는데 헤드라인은 **회사명**으로 쓴다
  ("ServiceNow"/"Walt Disney"/"Danaher"). 3B 모델이 티커→회사명 매핑을 못 한다.
  게다가 NOW·MO 같은 티커는 영어 단어라 "news about NOW" 가 모호하다.

세 팔을 같은 뉴스에 돌린다:
  A. 현행 프롬프트 (티커만)
  B. 회사명 + 티커를 주는 프롬프트
  R. **결정적 규칙** — 회사명 핵심어 또는 티커가 헤드라인에 등장하는가 (LLM 없음)

R 을 기준선으로 둔다. 관련성은 '판단'이 아니라 **문자열 일치 문제**일 수 있고,
그렇다면 ①에 LLM 을 쓸 이유가 없다 — 판단이 필요한 곳은 ②뿐이다.
"""
from __future__ import annotations

import argparse
import re
import sys

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.ai.data_feeds import FinnhubClient
from engine_v4.ai.multi_factor import RELEVANCE_PROMPT, MultiFactorScorer
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore

# 회사명 꼬리 제거 — "The Walt Disney Company" → "Walt Disney"
_SUFFIX = re.compile(
    r"\b(inc|incorporated|corp|corporation|company|co|plc|ltd|limited|holdings?|"
    r"group|sa|nv|ag|lp|llc|trust|class\s+[abc]|the)\b\.?", re.I)

RELEVANCE_PROMPT_V2 = """Headlines:
{headlines}

Question: Is at least one headline above about the company {company} (stock ticker
{symbol})? A headline counts if it names the company or its ticker as the subject —
including stories about its share price moving, analyst ratings, earnings, guidance,
contracts, partnerships, products, lawsuits, or regulatory decisions.

Answer NO only if every headline is about OTHER companies or is generic market
commentary that does not name {company}.

Answer with one word only: YES or NO"""


def core_names(company: str) -> list[str]:
    """회사명에서 매칭에 쓸 핵심어들. 'Coca-Cola' 처럼 하이픈도 그대로 둔다."""
    c = _SUFFIX.sub(" ", company or "")
    c = re.sub(r"[,\.]", " ", c)
    c = re.sub(r"\s+", " ", c).strip()
    if not c:
        return []
    out = [c]
    # 첫 단어가 충분히 길면 그것도 후보 ("ServiceNow", "Danaher", "Medtronic")
    first = c.split()[0]
    if len(first) >= 5 and first.lower() != c.lower():
        out.append(first)
    return out


def rule_relevant(symbol: str, company: str, heads: list[str]) -> tuple[bool, str]:
    """결정적 규칙. 반환 (관련있음, 근거)."""
    names = core_names(company)
    for h in heads:
        for n in names:
            if n and n.lower() in h.lower():
                return True, f"회사명 '{n}'"
        # 티커는 대문자 경계로만 — 'NOW'/'MO' 가 영어 단어인 경우를 피한다
        if re.search(rf"\({re.escape(symbol)}\)", h) or \
           re.search(rf"(?<![A-Za-z]){re.escape(symbol)}(?![A-Za-z])", h):
            return True, f"티커 '{symbol}'"
    return False, "일치 없음"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--show-disagree", action="store_true")
    a = ap.parse_args()

    cfg = get_config()
    pg = PostgresStore(cfg.pg_dsn)
    fh = FinnhubClient(cfg.finnhub_api_key)
    if not fh.is_available:
        print("Finnhub 사용 불가 — 중단"); return
    sc = MultiFactorScorer(pg, fh, ollama_url=cfg.ollama_url,
                           ollama_model=cfg.ollama_model)

    with pg.get_conn() as c:
        rows = c.execute("""
            SELECT u.symbol, coalesce(s.company_name, '') AS company
              FROM swing_universe u
              LEFT JOIN symbols s ON s.ticker = u.symbol
             WHERE u.is_active
             ORDER BY u.symbol
             LIMIT %s""", (a.limit,)).fetchall()

    tally = {"A_yes": 0, "B_yes": 0, "R_yes": 0, "n": 0,
             "A_fn": 0, "B_fn": 0, "A_fp": 0, "B_fp": 0, "no_name": 0}
    disagree = []
    for r in rows:
        sym, comp = r["symbol"], r["company"]
        if not comp:
            tally["no_name"] += 1
            continue
        news = fh.get_company_news(sym, days=7)
        if not news:
            continue
        used = news[:8]                      # 라이브와 동일
        heads = [n["headline"] for n in used]
        block = "\n".join(f"- {h}" for h in heads)

        rel_r, why_r = rule_relevant(sym, comp, heads)
        aw, _ = sc._llm_word(RELEVANCE_PROMPT.format(symbol=sym, headlines=block),
                             {"YES", "NO"})
        bw, _ = sc._llm_word(RELEVANCE_PROMPT_V2.format(symbol=sym, company=comp,
                                                        headlines=block), {"YES", "NO"})
        tally["n"] += 1
        tally["R_yes"] += rel_r
        tally["A_yes"] += (aw == "YES")
        tally["B_yes"] += (bw == "YES")
        if rel_r and aw != "YES":
            tally["A_fn"] += 1
        if not rel_r and aw == "YES":
            tally["A_fp"] += 1
        if rel_r and bw != "YES":
            tally["B_fn"] += 1
        if not rel_r and bw == "YES":
            tally["B_fp"] += 1
        flag = "" if (aw == bw and (aw == "YES") == rel_r) else "  ← 불일치"
        print(f"{sym:<6} {comp[:28]:<28} R={'YES' if rel_r else 'NO ':<3}({why_r[:14]:<14}) "
              f"A={aw or '?':<3} B={bw or '?':<3}{flag}", flush=True)
        if flag:
            disagree.append((sym, comp, rel_r, aw, bw, heads))

    n = max(tally["n"], 1)
    print(f"\n표본 {tally['n']}종목 (회사명 없어 제외 {tally['no_name']})")
    print(f"  R 결정적규칙  YES {tally['R_yes']:>3} ({tally['R_yes']/n:.0%})")
    print(f"  A 현행(티커)  YES {tally['A_yes']:>3} ({tally['A_yes']/n:.0%})  "
          f"R기준 거짓음성 {tally['A_fn']} · 거짓양성 {tally['A_fp']}")
    print(f"  B 회사명포함  YES {tally['B_yes']:>3} ({tally['B_yes']/n:.0%})  "
          f"R기준 거짓음성 {tally['B_fn']} · 거짓양성 {tally['B_fp']}")

    if a.show_disagree:
        print("\n── 불일치 상세 ──")
        for sym, comp, rr, aw, bw, heads in disagree:
            print(f"\n{sym} ({comp})  R={'YES' if rr else 'NO'} A={aw} B={bw}")
            for h in heads[:5]:
                print(f"    - {h[:110]}")


if __name__ == "__main__":
    main()
