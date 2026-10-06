# 세션 인수인계 — 2026-10-06 시스템 업데이트/재부팅

> 이 파일은 재부팅 직후 새 세션이 **가장 먼저** 읽는 용도다.
> 전체 맥락은 `project_status.md` (§22.AO-26 ~ AO-32, §24), 의사결정 맥락은
> `~/.claude/projects/-home-quant-quant-v31/memory/MEMORY.md` 에 있다.

## 0. 재부팅 직후 확인 (순서대로)

```bash
# ① 자동 점검 결과 — @reboot cron 이 남긴다
tail -20 scripts/v31_reboot_check.log

# ② 공백 감지 — 재부팅은 '공백'으로 잡혀 텔레그램이 온다(정상)
tail -5 scripts/gap_watch.log

# ③ 핵심 3종
systemctl is-active quant-engine-v4 quant-dashboard mnt-share-vbox
curl -s localhost:8001/health | python3 -m json.tool    # scheduler_jobs 32 기대
curl -s -X POST localhost:8001/harness/self-check/run   # 7/7 PASS 기대

# ④ 공백 동안 스톱이 집행되지 않았다 — 가격 백필 후 즉시 출구 점검
curl -s -X POST localhost:8001/exit-check/run
```

**예상되는 정상 신호**
- `gap_watch` 가 재부팅 공백을 탐지해 텔레그램 발송 + `exit-check/run` 자동 호출 → **정상 동작**이다.
- 토요일 오전에 재개했다면 `data_freshness` 가 가격 커버리지로 FAIL 할 수 있다 → 아래 §2-④ 참조(알려진 오탐).

## 1. ✅ systemd 유닛 적용 완료 (2026-10-06 17:32) — 단, 1차 방어는 미작동

`scripts/install_engine_unit.sh` 실행 완료. **재시작이 자동으로 끝난다(`kill -9` 불필요).**
→ 이제 `sudo systemctl restart quant-engine-v4` 또는 `kill PID` 로 재시작하면 30초 안에 끝난다.

### 🔴 다만 2차 방어(systemd SIGKILL)가 일을 하고 있다 — 미해결
실측 로그(17:32:19 → 17:32:49):
```
17:32:19.69  Waiting for connections to close
17:32:29.97  getUpdates HTTP 200          ← 종료 중인데 텔레그램 폴링이 계속 돈다
17:32:49.56  systemd: State 'stop-sigterm' timed out. Killing. → SIGKILL
             Failed with result 'timeout'
```
**30초는 정확히 `TimeoutStopSec` 값**이다. `--timeout-graceful-shutdown 15` 는 발동하지 않았다
(발동 시 찍히는 `Cancel N running task(s), timeout graceful shutdown exceeded` 로그가 없다).

**원인 (uvicorn 소스 확인, `uvicorn/server.py:271-301`)**
`timeout_graceful_shutdown` 은 `_wait_tasks_to_complete()`(연결 대기)**만** 덮는다.
그 뒤 `await self.lifespan.shutdown()`(line 301)은 **어떤 타임아웃도 없다**.
우리 `lifespan` 은 거기서 `telegram_bot.stop()` → `swing_scheduler.stop()` 를 호출한다.
- `swing_scheduler.stop()` → `shutdown(wait=False)` — 비차단, 문제 없음.
- 🔴 `telegram_bot.stop()`(notify/telegram_bot.py:70) → `self._task.cancel()` 후 `await self._task`.
  그런데 `_poll_loop` 의 `except asyncio.CancelledError: break` 가 **취소를 삼킨다**
  (CancelledError 를 재전파하지 않고 정상 종료로 바꾼다). 30초 long-poll 과 맞물려 종료가 늘어진다.

**영향**: 매 재시작이 SIGKILL 로 끝난다 → lifespan 정리 미실행, 진행 중 잡이 중간에 끊길 수 있다.
전부 Postgres 에 있어 데이터 유실 위험은 낮지만, `exit_check` 가 돌던 중이면 부분 기록 가능성이 있다.

**할 일 (우선순위 중)**
1. `_poll_loop` 의 `except asyncio.CancelledError:` → `raise` 로 재전파 (삼키지 말 것).
2. `telegram_bot.stop()` 의 `await self._task` 를 `asyncio.wait_for(..., timeout=5)` 로 감싸기.
3. `lifespan` 종료부 전체를 타임아웃으로 감싸는 것도 고려(uvicorn 이 안 해주므로).
4. 고친 뒤 `journalctl` 에서 `Failed with result 'timeout'` 이 사라지는지 확인.

*⚠️ 교훈: 1차 추정(텔레그램 폴링)이 맞았는데 "아웃바운드라 무관"이라며 기각했다.
무관한 것은 **연결 대기 단계**였고, 실제로는 그 다음 **lifespan 단계**를 막고 있었다.
§22.AO-32 문서의 "진범은 대시보드 keep-alive" 서술도 재검토 대상이다.*

## 2. 진행 중이던 작업 (우선순위순)

### ① 🔴 `composite_score_min` 이 죽은 키 — Phase 3F 레짐 적응이 통째로 무효
- `REGIME_PRESETS`(harness/regime_switcher.py)가 레짐별로 이 키를 쓴다(RISK_ON 58 / NEUTRAL 61 / RISK_OFF 70).
- 그런데 **이 키를 읽는 코드가 하나도 없다**. 진입이 실제로 읽는 건 `auto_approve_score_min`(= 61, **2026-05-14 이후 고정**).
- 레짐 적응의 두 레버가 **둘 다** 죽어 있다:
  - 진입 엄격도 → 읽는 코드 없음 (2026-09-24 확인)
  - 트레일 폭(`atr_trailing_multiplier`) → 브레이크이븐이 먼저 발동해 한 번도 안 쓰임 (§22.AO-26-C)
- 파생 문제: `variant_generator.TUNABLE_PARAMS` 에 `composite_score_min: (40,80)` 이 있는데
  백테스트 `_FIELD_MAP` 에는 **없다** → 변이가 이 값을 바꿔도 백테스트 결과가 안 변한다.
  §22.AO-19 의 "무력 키 계열" 변이(pending 16건 중 상당수)의 정체가 이것일 가능성이 높다.
- **할 일**: 키 연결(또는 일원화) + `TUNABLE_PARAMS`/`_FIELD_MAP` 정합.

### ② 🔴 승인 계층이 신호를 죽인다 — 다음 분석 대상
밴드별 IC 측정(2026-09-25, 점수 보유 시그널 180건 = 체결 117 + 미체결 63):
```
전체 IC        h=5d +0.2074 (p=0.011) · h=10d +0.1515 · h=20d +0.2153 (p=0.020)   ← 신호는 예측력이 있다
체결    n=71   IC = -0.0095 (p=0.937)   ← 우리가 산 것에서는 예측력 0
미체결  n=46   IC = +0.4869 (p=0.001)   ← 우리가 버린 것에서는 강함
같은 범위(45~79)로 맞춰도: 미체결 IC +0.4161 (p=0.008)  → 범위 절단으로 설명 안 됨
```
같은 점수대에서도 미체결이 더 좋다 (75+ 구간: 체결 중앙 **−9.61%**(n=4) vs 미체결 **+14.25%**(n=6)).
- **용의자**: 교집합 게이트(모멘텀 rank≥0.70 AND technical≥60)와 **LLM 게이트**(Ollama 3B, 신뢰도≥0.55).
  둘 다 composite_score 와 독립 기준으로 걸러 점수-수익 관계를 끊는다.
- **할 일**: `llm_gate` 결정 기록으로 **반사실 검증** — REJECT/DEFER 된 신호의 선행수익률을 보면
  게이트가 도움이 되는지 즉시 판정된다. 게이트별로 끄고 IC 회복을 보는 것도 방법.
- 주의: n 이 작다(밴드당 10~31). 미체결 신호엔 체결비용·슬리피지가 반영돼 있지 않다.

### ③ 65~70 점수 밴드만 흑자 — 문턱이 아니라 '밴드'일 가능성
h=20d 선행수익률 기준 (평균/중앙/승률 셋 다 65~70 이 최고):
```
<60    n=31  평균 +5.95%  중앙 -2.97%  승률 41.9%   ← 평균은 이상치 왜곡
60-65  n=27  평균 +1.98%  중앙 +0.50%  승률 55.6%
65-70  n=26  평균+11.41%  중앙 +7.60%  승률 76.9%   ← 유일한 스윗스팟
70-75  n=23  평균 +8.39%  중앙 +1.83%  승률 73.9%
75+    n=10  평균 +2.62%  중앙 +6.46%  승률 60.0%
```
실현손익 기준으로도 65~69 구간만 흑자(+$66.43), 75~79 는 8건 중 1승(−$30.42).
- `composite_score_min` 을 문턱이 아니라 **밴드**(min+max)로 쓰는 것이 데이터가 지지하는 유일한 변경.
- 단 과적합 위험이 크다 — 반드시 ①의 키 연결 문제를 먼저 해결하고, IC 로 검증할 것.

### ④ `data_freshness` 토요일 오탐 (저위험, 미해결)
`refresh_universe`(토 10:00) 직후 `self_check`(토 11:00)가 신규 편입 종목을 '가격 결손'으로 잡는다.
실측 2회: 2026-09-19 (89.0%, 178/200), 2026-10-03 (85.5%, 171/200). 며칠 뒤 자동 회복(현재 200/200).
- **할 일**: 신규 편입 종목에 유예기간(예: `added_at` 3일 이내 제외)을 주거나 self_check 를 수집 뒤로 옮긴다.
- 방치하면 §22.AO-28 의 '양치기 소년' 재발 — 진짜 결손을 놓친다.

### ⑤ 알려진 제약 (조치 불가/보류)
- **2026-09-22 봉 영구 결손**: yfinance 가 3가지 방식 모두에서 그날을 안 준다. 51/200 종목만 있다.
  하필 변동성 큰 날(SCHW −6%, 거래량 16.9M)이라 일봉 지표에 1일 구멍이 남는다.
- **엣지가 음(−)**: 청산 119건 기준 승률 43.7%, 거래당 −0.098%, 손익분기 승률 44.9% 미달.
  SPY +13.18% 대비 초과수익 −21.08pp. 회전율 개선은 '출혈 중단'이지 '엣지 생성'이 아니다(§22.AO-26-C).
- **AO-26 판정**: A-1 rsi2 는 표본 부족으로 계속 연장 중(3건). B 사이징은 ✅ 유효 확정(CV 0.010).

## 3. 현재 상태 (2026-10-06 17:20 KST)

| 항목 | 값 |
|---|---|
| 총자산 | **$1,857.69** (누적 **−7.12%**) |
| 포지션 | 오픈 4 / 청산 128 |
| 모드 | paper (`trading_mode=paper`, KIS 미연결) |
| 스케줄러 | 32 잡 |
| 자가진단 | **7/7 PASS** (커버리지 200/200) |
| git | `origin/main` 동기 |
| 백업 | `/mnt/share/*20261006*` (DB 156MB + secrets + crontab, 체크섬 검증 완료) |

## 4. 되돌리기 (문제 발생 시)

```bash
# §22.AO-26 config 7키 — 하나라도 풀리면 검증 무효 (판정 전까지 유지할 것)
#   rsi2_exit_min_hold_days=8 · time_stop_days=21 · fractional_shares_enabled=true
#   allow_min_one_share=false · min_position_notional_usd=5
#   atr_hard_stop_multiplier=1.5 · momentum_factor_active=true

# systemd 유닛 원복
sudo cp /etc/systemd/system/quant-engine-v4.service.bak.<타임스탬프> \
        /etc/systemd/system/quant-engine-v4.service && sudo systemctl daemon-reload

# 공백 감시 끄기
crontab -l | grep -v gap_watch | crontab -

# DB 복구 — project_status.md §26 (TimescaleDB 는 pre/post_restore 로 감싸야 한다)
```
