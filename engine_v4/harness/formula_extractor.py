"""3J 앞단: 논문 초록 → 수식 추출 (§22.AO-23).

`weekly_research` 가 모은 논문 초록은 지금까지 **텍스트로만 쌓였다**. 거기서 신호를 뽑아
`swing_signal_formulas` 에 넣는 단계가 비어 있어, 3J(수식 검증)가 늘 pending 0 이었다.
그 연결고리를 채운다.

**안전 구조**: LLM 이 무엇을 뱉든 `signal_dsl.validate()` 화이트리스트를 통과해야만 저장된다.
악의적/잘못된 출력은 저장 단계에서 거부되므로 임의 코드 실행 경로가 생기지 않는다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from engine_v4.harness.knowledge import log_action
from engine_v4.harness.signal_dsl import ALLOWED_FUNCS, ALLOWED_NAMES, FormulaError, validate

logger = logging.getLogger(__name__)

# ⚠️ 소형 모델(3B)은 JSON 구조 + 다중 출력을 요구하면 설명문만 뱉는다(실측).
# ①(§22.AO-11)과 같은 교훈 — **예시 기반 단일 출력**을 요구해야 한다.
# 실측: JSON 요구 → 설명문 / 예시+평문 한 줄 요구 → `-(close / ts_mean(close, 20) - 1)` 정확 산출.
EXTRACT_PROMPT = """Convert this research finding into ONE trading signal formula.

Finding: {summary}

Use only these: {names}
and these functions: {funcs}
and operators + - * / ( )

Higher value must mean MORE attractive to buy (add a leading minus to flip if needed).

Example finding: "stocks trading above their 50-day average underperform next month"
Example answer: -(close / ts_mean(close, 50) - 1)

Example finding: "high turnover predicts lower returns"
Example answer: -ts_mean(volume, 20)

If the finding cannot be written with these ingredients (it is about news, options,
macro, fundamentals, or model architecture), answer exactly: NONE

Answer with the formula only, nothing else:"""


def _llm(pg, prompt: str, ollama_url: str, ollama_model: str,
         claude=None) -> str | None:
    try:
        if claude:
            r = claude.messages.create(model="claude-haiku-4-5-20251001", max_tokens=500,
                                       messages=[{"role": "user", "content": prompt}])
            return r.content[0].text
        import requests
        r = requests.post(f"{ollama_url}/api/generate",
                          json={"model": ollama_model, "prompt": prompt, "stream": False,
                                "options": {"num_predict": 400, "temperature": 0.2}},
                          timeout=300)
        return r.json().get("response", "")
    except Exception as e:
        logger.warning(f"formula extraction LLM failed: {e}")
        return None


def _parse_formulas(text: str | None, knowledge_id: int) -> list[dict]:
    """LLM 출력에서 수식 목록을 뽑는다.

    소형 모델은 형식을 자주 어긴다 — `{"formulas": [...]}` 뿐 아니라 맨 리스트 `[...]` 로도
    답한다(실측). 둘 다 받아들이되, 내용 검증은 어차피 화이트리스트가 한다.
    """
    if not text:
        return []
    stripped = text.strip()
    # 평문 수식 한 줄 (권장 경로). NONE 이면 추출 없음.
    if stripped.upper().startswith("NONE"):
        return []
    # 코드펜스(```)를 걷어내고 첫 유효 줄을 본다
    lines = [ln.strip().strip("`").strip() for ln in stripped.splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("```")]
    first = lines[0] if lines else ""
    if first and not first.startswith(("{", "[")) and len(first) <= 200:
        # 설명문이 아니라 수식처럼 보이는지 — 허용 이름/함수가 하나라도 있어야 한다
        if any(tok in first for tok in ALLOWED_NAMES | set(ALLOWED_FUNCS)):
            return [{"expression": first}]
    for pattern in (r"\[.*\]", r"\{.*\}"):
        m = re.search(pattern, text, re.DOTALL)
        if not m:
            continue
        try:
            data = json.loads(m.group())
        except Exception:
            continue
        if isinstance(data, dict):
            # 단일 수식 객체를 그대로 뱉는 경우도 받는다
            if "expression" in data:
                items = [data]
            else:
                items = data.get("formulas") or data.get("signals") or []
        elif isinstance(data, list):
            items = data
        else:
            continue
        items = [f for f in items if isinstance(f, dict) and f.get("expression")]
        if items:
            return items
    logger.debug(f"knowledge {knowledge_id}: 수식 목록 파싱 실패")
    return []


def extract_from_knowledge(pg, knowledge_id: int, ollama_url: str = "http://localhost:11434",
                           ollama_model: str = "qwen2.5:3b", claude=None) -> dict[str, Any]:
    with pg.get_conn() as conn:
        row = conn.execute(
            "SELECT knowledge_id, title, summary, source_url FROM swing_knowledge "
            "WHERE knowledge_id = %s", (knowledge_id,)).fetchone()
    if not row:
        return {"knowledge_id": knowledge_id, "error": "not_found"}

    # 본문 우선 (§22.AO-24). 초록에는 수식 정의가 거의 없어 추출 품질이 낮았다.
    body, body_status = "", "skipped"
    if pg.get_config_value("formula_fulltext_enabled", "true") == "true":
        try:
            from engine_v4.harness.paper_fetch import fetch_relevant
            body, body_status = fetch_relevant(
                row.get("source_url") or "",
                max_chars=int(float(pg.get_config_value("formula_fulltext_chars", "4000"))))
        except Exception as e:
            logger.debug(f"knowledge {knowledge_id} 본문 수집 실패: {e}")
            body_status = "error"

    source_text = body if body else (row["summary"] or "")[:1200]
    prompt = EXTRACT_PROMPT.format(
        summary=f'{(row["title"] or "")[:200]}. {source_text}',
        names=", ".join(sorted(ALLOWED_NAMES)),
        funcs=", ".join(sorted(ALLOWED_FUNCS)),
    )
    text = _llm(pg, prompt, ollama_url, ollama_model, claude)
    proposed = _parse_formulas(text, knowledge_id)
    if proposed:
        for f in proposed:
            f.setdefault("name", (row["title"] or f"k{knowledge_id}")[:60])

    accepted, rejected = [], []
    for f in proposed[:3]:
        expr = str(f.get("expression", "")).strip()
        name = str(f.get("name", "") or f"k{knowledge_id}")[:60]
        if not expr:
            continue
        try:
            validate(expr)          # ← 화이트리스트 관문. 여기서 막히면 저장되지 않는다
        except FormulaError as e:
            rejected.append({"expression": expr[:120], "reason": str(e)[:120]})
            continue
        with pg.get_conn() as conn:
            r = conn.execute("""
                INSERT INTO swing_signal_formulas
                    (name, expression, source, knowledge_id, extracted_by)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (expression) DO NOTHING RETURNING formula_id
            """, (name, expr, f"knowledge#{knowledge_id}: {(row['title'] or '')[:120]}",
                  knowledge_id, "claude" if claude else f"ollama/{ollama_model}")).fetchone()
            conn.commit()
        if r:
            accepted.append({"formula_id": r["formula_id"], "name": name, "expression": expr})

    summary = {"knowledge_id": knowledge_id, "proposed": len(proposed),
               "accepted": len(accepted), "rejected": len(rejected),
               "source": body_status, "source_chars": len(source_text),
               "accepted_list": accepted, "rejected_list": rejected[:3]}
    with pg.get_conn() as conn:
        conn.execute("""
            INSERT INTO swing_formula_extraction
                (knowledge_id, proposed, accepted, rejected, detail)
            VALUES (%s,%s,%s,%s,%s::jsonb)
            ON CONFLICT (knowledge_id) DO UPDATE SET
                attempted_at = now(), proposed = EXCLUDED.proposed,
                accepted = EXCLUDED.accepted, rejected = EXCLUDED.rejected,
                detail = EXCLUDED.detail
        """, (knowledge_id, len(proposed), len(accepted), len(rejected),
              json.dumps(summary, ensure_ascii=False, default=str)))
        conn.commit()
    return summary


def extract_pending(pg, max_items: int = 8, **llm_kwargs) -> dict[str, Any]:
    """아직 시도하지 않은 논문 지식에서 수식 추출."""
    if pg.get_config_value("formula_extract_enabled", "true") != "true":
        return {"enabled": False}
    with pg.get_conn() as conn:
        ids = [r["knowledge_id"] for r in conn.execute("""
            SELECT k.knowledge_id FROM swing_knowledge k
            LEFT JOIN swing_formula_extraction e USING (knowledge_id)
            WHERE e.knowledge_id IS NULL
              AND k.source_type IN ('paper','arxiv','research')
            ORDER BY k.applicability_score DESC NULLS LAST, k.knowledge_id DESC
            LIMIT %s
        """, (max_items,)).fetchall()]
    if not ids:
        return {"checked": 0}
    results = [extract_from_knowledge(pg, i, **llm_kwargs) for i in ids]
    acc = sum(r.get("accepted", 0) for r in results)
    rej = sum(r.get("rejected", 0) for r in results)
    out = {"checked": len(results), "accepted": acc, "rejected": rej, "results": results}
    log_action(pg, "formula_extract", "completed",
               details={"checked": len(results), "accepted": acc, "rejected": rej})
    logger.info(f"Formula extraction: {len(results)}건 → 채택 {acc} / 거부 {rej}")
    return out
