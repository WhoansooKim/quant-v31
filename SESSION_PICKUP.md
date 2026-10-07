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

## 1. ✅ 종료 문제 해결 완료 (2026-10-07, §22.AO-34)

재시작이 **16초에 정상 종료**된다. SIGKILL 없음, `Failed with result 'timeout'` 없음,
lifespan 정리(`Scheduler stopped` → `Swing Engine V4 stopped`)까지 완료.
`sudo systemctl restart quant-engine-v4` 또는 `kill PID` 둘 다 정상 동작한다.

원인은 `telegram_bot._poll_loop` 가 `except asyncio.CancelledError: break` 로 **취소를 삼킨** 것이었다
(앞서 세 번 잘못 짚었다 — 상세는 `project_status.md` §22.AO-34).
수정: CancelledError 재전파 · `stop()` 에 `wait_for(timeout=5)` · lifespan 종료부에 10초 상한.

## 2. 진행 중이던 작업 (우선순위순)

### ① ✅ `composite_score_min` 죽은 키 — 완료 (2026-10-07, §22.AO-35)
프리셋이 `auto_approve_score_min`(실제 읽는 키)을 쓰게 고쳤다. **단 기본은 꺼둠**
(`regime_entry_strictness_enabled=false`) — RISK_ON 프리셋 58 은 밴드 실측 중앙 −2.97% 인
최악 구간이라, 켜는 것은 밴드 재설계(③)와 함께 판단할 사항이다.
부수 발견: 변이 탐색 노브 **22개 중 9개(41%)** 가 백테스트 미반영 → 자동 필터로 13개만 탐색하게
했고, 전 키가 무효인 pending 변이 5건을 소급 기각(16→11). 상세는 `project_status.md` §22.AO-35.

### ② ✅ 승인 계층 분석 — 완료 (2026-10-07, §22.AO-36)
**가설이 뒤집혔다.** 게이트는 좋은 필터다(교집합: 거른 것 중앙 −2.29% vs 통과 +5.26%, p=0.002).
LLM 게이트는 기각 이력 **0건**(25건 전부 APPROVE)으로 무혐의.
🔴 진짜 원인: **진입 경로가 둘인데 기준이 다르다.** `POST /signals/{id}/approve`(대시보드 버튼)는
`validate_entry` 하나만 하고 게이트를 **전혀 안 본다**. 실측 체결의 **87%가 이 경로**이고
게이트 활성 구간에서 그중 71%가 교집합 탈락분이다 → 체결 IC ≈ 0 의 원인.
⚠️ "우회가 손실을 유발했다"는 인과는 미입증(해당 구간 n=24, p=0.4867).
**권고 1·2 적용 완료** (2026-10-07, §22.AO-37): 수동 승인에 게이트 적용(`force=true` 로 우회,
`approved_via='manual_force'` 기록) · 승인 경로 DB 기록(`swing_signals.approved_via`).
게이트 로직은 `evaluate_basic_gates()` 로 공용화해 두 경로가 한 곳을 쓴다.
**권고 3 적용 완료** (§22.AO-37): `GET /signals/gate-status` 신설 + 대시보드 pending 행에
`게이트 통과/탈락` 칩(사유 툴팁) · 탈락 시 한글 사유 표시 · 해당 행에 `⚠️ 강제 승인` 버튼.
판정은 엔진에서만 한다(임계값 C# 복제 금지 — §22.AO-35 함정).
**권고 4 적용 완료** (§22.AO-38): `skipped_list` + 범주별 집계(`skip_reasons`) + 당시 `thresholds` 를
`pipeline_log` 에 저장. 이제 "어느 게이트가 무엇을 걸렀나"를 재계산 없이 바로 볼 수 있다.
⚠️ 같은 작업 중 §22.AO-37 리팩터가 `run_auto_approve` 를 깨뜨린 것(`NameError`)을 발견해 고쳤다 —
구문 검사만 하고 실행하지 않은 탓이다. 상세 §22.AO-38.
진단 도구: `scripts/gate_audit.py`. 상세: `project_status.md` §22.AO-36.

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

### ④ ✅ `data_freshness` 토요일 오탐 — 완료 (2026-10-07, §22.AO-39)
근본 원인은 잡 순서였다: `refresh_universe`(토 10:00)가 편입하는데 가격 수집은 같은 날 07:00 에
이미 끝났고 다음은 월 07:00. → `refresh_universe` 가 **편입 직후 즉시 수집**하도록 고쳐
공백 자체를 없앴다. 안전망으로 신규 편입 3일 유예(`self_check_new_symbol_grace_days`)를 두되
`price_new_pending` 으로 **반드시 보고**한다. §22.AO-30 급 결손(22/200=89%)은 여전히 FAIL.

### ⑤ ✅ gap_watch 시계 역행 가드 — 완료 (2026-10-07, §22.AO-34)
부팅 직후 RTC 가 ~1분간 과거로 읽히는 것을 실측(저널에 42.1h 공백이 찍혔다).
그 창에 cron 이 걸리면 42시간 공백 오탐이 났을 것이다. 가드 3종 추가:
`NTPSynchronized=no` 판정 보류 · 시계 역행 시 건너뜀 · 하트비트 손상값 재설정. 검증 5종 통과.

### ⑥ 알려진 제약 (조치 불가/보류)
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
