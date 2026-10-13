# 세션 인수인계 — 2026-10-11 출구 결함 교정 (§22.AO-43)

> 🔴 **가장 먼저 할 일: 엔진 재시작이 아직 안 됐다.**
> ```bash
> sudo systemctl restart quant-engine-v4 && sleep 25 && curl -s localhost:8001/health
> ```
> config 변경은 이미 라이브다(DB 에서 매번 읽는다). 그러나 `strategy/swing.py` 의
> **레거시 출구 차단은 재시작 전까지 적용되지 않는다** — 그때까지 고정 −5% 손절과
> SMA50 `trend_break` 가 계속 발동한다. 이것이 샤프 0.70 → 1.55 의 핵심 변경이다.

## 0. §22.AO-43 요약 — 7개월 손실의 주원인을 찾았다

출구가 **두 시스템으로 병렬** 운영됐고(`exit_manager` 5레이어 + `swing.py` 3조건)
손절 기준이 달랐다(1.5×ATR vs 고정 −5%). 더 결정적으로 `breakeven_trigger_r` 과
`atr_trailing_activation_r` 이 둘 다 1.0 이라 +1R 에서 동시 발동하는데
`trail_sl = hwm − 2.5×ATR` 은 +2.5R 전까지 본전선 아래다 → **본전 스톱이 항상 이기고
+1R~+2.5R 되돌림 거래가 전부 0% 로 청산**된다. 사유가 `atr_trailing_stop` 으로
**잘못 기록**돼 7개월간 보이지 않았고, 이름이 반대 방향(폭을 넓혀라)으로 유도했다.

측정 돌파: `swing_indicators` 가 7개월치뿐이어서(collector 가 최신 1일만 저장)
모든 백테스트가 라이브와 같은 창에 갇혀 있었다. `daily_prices` 의 15.6년 524만 봉으로
지표를 소급 계산(`hist_indicators`, 493만 행) → **56,340거래** 표본 확보.

| 구성 | CAGR | 낙폭 | 샤프 |
|---|---|---|---|
| 현행 전부 @29% (= 바꾸기 전) | +1.9% | −19.7% | 0.32 |
| config+코드 @29% | **+11.2%** | −21.2% | **1.55** |
| config+코드 @45% | **+17.5%** | −32.2% | **1.55** |
| 벤치마크: SPY 15.0% / QQQ 20.0% / MTUM 16.0% (낙폭 모두 ~−34%) | | | |

검증 4종 통과: 시뮬레이터 재현 상관 0.922(n=36 설정고정구간) · out-of-sample
2011~2018 +14.4% / 2019~2026 +21.1% · 월블록 부트스트랩 CI [+15.0,+22.7](현행은 0 포함) ·
순평균 음수인 해 0/16(현행 7/16) · trail 0.5~1.5 전부 양수(고원).

적용: `atr_trailing_multiplier` 2.5→**1.0** · `breakeven_enabled`→**false** ·
`rsi2_exit_min_hold_days` 8→**999** · `time_stop_days` 21→**60** ·
`swing_legacy_exit_enabled` 신규 **false** · regime_switcher 프리셋 →1.25/1.0/0.75
(🔴 `harness_regime_switch_enabled=true` 였으므로 프리셋을 안 고치면 되돌아간다)

🔴 **판정 전까지 이 6키를 되돌리지 말 것.** 사전등록 `prereg_exit_overhaul_ao43`.
판정 2027-01-31 또는 신규 n≥25 중 늦은 시점. 1차 기준 실현 **중앙값 > +0.50%**.
중단: 신규 n≥15 에서 중앙값 < −1.0% → 즉시 되돌림.
되돌리기: `swing_legacy_exit_enabled=true` · `atr_trailing_multiplier=2.5` ·
`breakeven_enabled=true` · `rsi2_exit_min_hold_days=8` · `time_stop_days=21`

**전진검증은 6시간 주기** `scripts/exit_watch.py` (cron `0 */6 * * *`).
변화가 있을 때만 발송한다. 수동 확인: `bash scripts/exit_watch.sh --force`

## 0-B. 투자율 45% — ✅ 적용 (사용자 결정 2026-10-12, §22.AO-44)

| 키 | 전 | 후 |
|---|---|---|
| `position_pct` | 0.05 | **0.10** |
| `max_total_exposure_pct` | 1.0 | **0.45** |

🔴 **두 키는 쌍이다.** `position_pct` 만 올리면 동시보유가 많은 날(최대 15개 전례)에
0.10×15×0.85 = **128%** 까지 간다. `max_total_exposure_pct` 가 백테스트 `target_deploy`
와 같은 하드캡 역할을 한다. 집행 검증: 5종목째 42.5% → 6종목째 정확히 45% 로 깎임 → 7종목째 거부.

**기대값(5슬롯@45%, 라이브 동시보유 실측 평균 5.0개 기준): CAGR +22.5% · 낙폭 −44.2% · 샤프 1.42.**
20슬롯의 −32% 는 슬롯이 차야 얻는 값이므로 라이브 기준이 아니다(이전 보고 정정).
투자율 목표대역 33~48%, **낙폭 중단 검토선 −30%** — `exit_watch` 가 6시간마다 본다.

⏳ **즉시 효과 없음**: 기존 포지션은 리사이즈되지 않는다. 신규 진입만 $164 규모로 들어가므로
월 ~5건 속도에서 42.5% 도달까지 **4~8주**. 그 사이 11% → 45% 계단식 상승.

### 다음 선택지 — 12슬롯 경로는 측정 후 **적용하지 않았다** (§22.AO-45)

`auto_approve_score_min` 61→0 은 7.4개월에 신호 **4건**만 늘린다(현재 설정에서 거르는 건
**0건**). 진짜 공급 제약은 `price_range_max=250` 이고 유니버스의 41% 를 제외하지만,
그 캡은 거래당 중앙값 **+0.21%p** 를 벌어준다(CI [−0.467,−0.027], n=54,312).
그리고 **수익을 맞춰 비교하면**(18.9 vs 18.8) 12슬롯의 연낙폭평균은 −8.9% 로 5슬롯과
**동일**하다 — "12슬롯이 낙폭을 줄인다"는 이전 보고는 수익이 4.8%p 낮은 설정을 비교한
착오였다. 가격 하한 $10 을 넣으면 12슬롯은 +19.7%/샤프1.60 이 아니라 **+14.1%/1.24** 다.

## 0-C. 진입 게이트 2개 측정 — dual_sort 끔 / LSTM 결함 수정 (§22.AO-46·47)

| 게이트 | 라이브 기각률 | 판정 | 조치 |
|---|---|---|---|
| `dual_sort_enabled` | 63% | CAGR 18.9→13.9%, 샤프 1.20→0.90 | **false 적용** |
| `intersection_technical_min=60` | 37% | 사실상 **LSTM 게이트**, 예측력 +0.03%p | 코드 수정 후 재측정 중 |

- **dual_sort**: value 팩터 15년 소급(1,499종목 151,802분기, Finnhub 무료 티어)으로 측정.
  거래당 차이는 0(CI [−0.170,+0.085])인데 포트폴리오는 5%p 빠진다 — 기각률이 모멘텀
  상위에서 더 높고(15.7%→23.8%) 포트폴리오는 상위부터 담기 때문. lag 45/60/90/180,
  슬롯 5/12 전부 동일. 🔴 **재활성화 전에** 소급 `pb`(분기)와 라이브 `pbAnnual` 불일치 해소 필요.
- **technical_score**: 가격점수(`tech_base`) 4,933,554행 소급 → three조건 후보 289,394건 중
  **60 미만 0건**. 게이트는 가격지표 쪽에서 구조적 무효이고 37% 기각은 전부 LSTM 이다.
  LSTM 검증 결함 4개를 고쳤다(분할·표준화·창길이·기준선).

  **판정 완료 — 결함을 다 고쳐도 예측력이 없다.** 표본 2,197→81,819, 날짜 11→431,
  날짜경계 분할 + 5일 엠바고로 재학습(`v2_fixed`): 정확도 0.4891 / 기준선 0.5090 /
  **기준선대비 −0.0198** / AUC **0.4853**(0.5 미만). 학습손실은 0.4154 까지 떨어졌다 — 암기다.
  워크포워드 4폴드×2시드 통합(n=13,975, 날짜블록 77): AUC 0.4975 **95%CI [0.4825,0.5133]**,
  기준선대비 −0.79%p **95%CI [−3.53,+1.96]%p** — 둘 다 '효과없음'을 포함한다.
  폴드2(기준선 59.99% 상승구간)에서 −12.62%p — 레짐이 바뀌면 적극적으로 틀린다.

  **조치**: `intersection_technical_min=60` 과 `lstm_enabled=true` 는 **그대로 둔다**.
  `lstm_min_edge=0.02` 가드가 막는다. 주간 재학습이 매주 edge 를 기록하므로 edge≥0.02 인
  모델이 나오면 자동 재활성화된다 — 측정 대역폭을 끄지 않는다.

  **엔진 재시작 완료 2026-10-13 22:57:30.** 공급 반사실: 기술게이트 기각 37.4% → 0%,
  3게이트 통과 월 3.8 → 5.7건(+50%), 복합점수 +4.2. 기각됐던 6신호 재점수화 **6/6 통과**.
  🔴 공급이 늘어도 노출은 `max_total_exposure_pct=0.45` 가 막는다 — 투자율 48% 초과면 캡 고장.
  `exit_watch` 에 진입 공급 블록을 넣어 6시간마다 기각률을 자동 대조한다(기준선 2026-10-13).

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

### ③ ⏳ mom_rank 문턱 0.86 — 관찰 중 (2026-10-11 적용, §22.AO-40)
**65~70 밴드는 기각**: 경계를 데이터에서 고른 것을 보정하니 max-stat p=0.10~0.39 로 유의하지 않다.
대신 진입 분해에서 **`mom_rank` 가 다중비교 보정을 통과한 유일 팩터**로 나왔다
(IC(MFE)=+0.323, Bonferroni p=2.5e-3, 문턱탐색 max-stat p=0.0368).
`intersection_momentum_min` 0.70 → **0.86** 적용.

🔴 **판정 전까지 이 값을 되돌리지 말 것.** 사전등록 기준선: `swing_harness_log` 의 `prereg_mom_rank_086`.
- 1차 기준: 신규 체결 거래당 실현 **중앙값 > 0%** (기준선 −0.55%)
- 2차: MFE 중앙 ≥ +4.5% · 승률 ≥ 50%  |  최소 n≥30
- **판정: 2027-01-31 또는 n≥30 중 늦은 시점.** n<30 이면 연장. 중앙값으로 판정(평균 금지).
- 변수는 하나만. `composite` 제외는 2026-10-11 에 측정해 **효과 0** 으로 확인돼 적용하지 않았다
  (실현중앙 동일 −0.39%, 연순수익 0.9%p 악화, 추가 16건 p=0.76 — §22.AO-41).
  `mom_rank≥0.86` 과 중복이기 때문이다. 재검토는 이 판정 이후.
  부수: `auto_approve_score_max=85` 는 7개월간 0건을 거른 **죽은 게이트**(동작 무변화, 기록만).
- 기대 크기는 연 −1.9% — 적자 축소이지 18% 경로가 아니다. 후반 구간 무효 위험 남음.

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
