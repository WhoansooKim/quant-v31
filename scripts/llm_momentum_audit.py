#!/usr/bin/env python
"""LLM 모멘텀 판정 감사 (§22.AO-48).

왜 필요했나: KO 가 **같은 지표·같은 가중치**로 07:00 에 composite 65.5, 21:30 에 59.8 이
나왔다. 차이의 전부가 `llm_momentum` 50 → 25 였고(가중 0.2305 — technical 0.239 에 이어
두 번째), 그런데 **어느 쪽이 맞는지 기록만으로는 알 수 없었다** — 점수와 함께 판정 근거가
된 뉴스를 저장하지 않았기 때문이다. 재현 불가능한 입력에 0.23 가중이 걸려 있고 게이트는 61 이다.

이제 `swing_llm_momentum_audit` 이 프롬프트에 **실제로 들어간** 헤드라인과 지문(sha1 12자),
양 단계의 원문 응답을 남긴다. 그래서 다음 두 가지를 구분할 수 있다:
  · 지문 같음 + 판정 다름  → LLM 불안정 (temperature=0.0 이므로 있으면 안 된다)
  · 지문 다름              → 뉴스가 바뀐 것 (정상)

사용:
  llm_momentum_audit.py            # 요약 + 지문 충돌
  llm_momentum_audit.py --symbol KO  # 한 종목의 판정 이력과 근거
"""
from __future__ import annotations
import argparse, sys

sys.path.insert(0, "/home/quant/quant-v31")
from engine_v4.config.settings import get_config
from engine_v4.data.storage import PostgresStore


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()
    pg = PostgresStore(get_config().pg_dsn)

    with pg.get_conn() as c:
        if a.symbol:
            rows = c.execute("""
                SELECT time, fingerprint, rel_word, dir_word, score, confidence, damped,
                       news_fetched, news_used, headlines
                FROM swing_llm_momentum_audit
                WHERE symbol = %s AND time > now() - (%s || ' days')::interval
                ORDER BY time DESC""", (a.symbol, a.days)).fetchall()
            for r in rows:
                print(f"\n{r['time']:%m-%d %H:%M}  지문 {r['fingerprint']}  "
                      f"①{r['rel_word']} ②{r['dir_word']} → {r['score']}"
                      f"{' (감쇠)' if r['damped'] else ''}"
                      f"  뉴스 {r['news_used']}/{r['news_fetched']}")
                for h in (r["headlines"] or []):
                    print(f"    - {h.get('h','')}")
            return

        print("── 판정 분포 ──")
        for r in c.execute("""
            SELECT COALESCE(dir_word, '①에서 NO/오류') 판정, count(*) n,
                   round(avg(score)::numeric, 1) 평균점수
            FROM swing_llm_momentum_audit
            WHERE time > now() - (%s || ' days')::interval
            GROUP BY 1 ORDER BY n DESC""", (a.days,)).fetchall():
            print(f"  {r['판정']:16s} {r['n']:4d}건  평균 {r['평균점수']}")

        # 🔴 핵심 검사: 같은 입력에 다른 판정이 나온 적이 있는가
        print("\n── 지문 충돌 (같은 뉴스, 다른 판정) ──")
        conf = c.execute("""
            SELECT symbol, fingerprint, count(*) n,
                   count(DISTINCT COALESCE(rel_word,'-') || '/' || COALESCE(dir_word,'-')) 판정종류,
                   string_agg(DISTINCT COALESCE(rel_word,'-')||'/'||COALESCE(dir_word,'-'), ' vs ') 판정들,
                   min(score) 최소, max(score) 최대
            FROM swing_llm_momentum_audit
            WHERE time > now() - (%s || ' days')::interval
            GROUP BY 1,2 HAVING count(*) > 1 AND count(DISTINCT
                   COALESCE(rel_word,'-') || '/' || COALESCE(dir_word,'-')) > 1
            ORDER BY 1""", (a.days,)).fetchall()
        if not conf:
            print("  없음 — temperature=0.0 이 의도대로 결정적이다."
                  " composite 가 흔들렸다면 원인은 LLM 이 아니라 뉴스 변경이다.")
        else:
            for r in conf:
                print(f"  🔴 {r['symbol']} {r['fingerprint']}: {r['판정들']}"
                      f"  점수 {r['최소']}~{r['최대']} ({r['n']}회)")

        # 같은 종목이 지문만 바뀌며 점수가 흔들린 폭
        print("\n── 종목별 점수 변동 (지문 변경 = 뉴스 변경) ──")
        for r in c.execute("""
            SELECT symbol, count(*) n, count(DISTINCT fingerprint) 지문수,
                   min(score) 최소, max(score) 최대, max(score)-min(score) 변동
            FROM swing_llm_momentum_audit
            WHERE time > now() - (%s || ' days')::interval
            GROUP BY 1 HAVING count(*) > 1 ORDER BY 6 DESC NULLS LAST LIMIT 15""",
            (a.days,)).fetchall():
            flag = "  ⚠️ composite 에 " + f"{r['변동'] * 0.2305:.1f}점 영향" if r["변동"] else ""
            print(f"  {r['symbol']:6s} {r['n']:3d}회 지문 {r['지문수']}종  "
                  f"{r['최소']:.0f}~{r['최대']:.0f}{flag}")


if __name__ == "__main__":
    main()
