# Quant V4 Swing Trading System — Project Status

> Last updated: **2026-08-14** (Opus 4.8)
> Purpose: Session continuity — 이 파일 + 메모리(MEMORY.md)만 보면 Claude 재시작 후 즉시 이어서 작업 가능.

## ⭐ 2026-08-14 현재 상태 스냅샷 (재개 시 여기부터)

**한 줄 요약:** paper 모드, 총자산 ~$1,915(자본 $2,000, TWR −4.26%), 오픈 11개. 18% 목표 위해 백테스트 검증
기반 개선 진행 중. **다음 할 일 = 하락장 방어(Tier 1~3), §25 참조.**

**재부팅/재시작 후 자동 점검 (복붙):**
```bash
systemctl is-active quant-engine-v4 quant-dashboard           # active active 이어야
curl -s http://localhost:8001/health | python3 -m json.tool   # status ok
ss -ltnp | grep -E ':8000|:50051' || echo "V3.1 clear(OK)"     # 나오면 V3.1 부활(§13 조치)
cat /home/quant/quant-v31/scripts/payoff_review_result.txt 2>/dev/null   # 주간 재평가 결과(있으면 사용자 보고)
git -C /home/quant/quant-v31 log --oneline -3                  # 최신 커밋 확인
```

**현재 라이브 config (백테스트 검증 완료 스택, 2026-08-14):**
| key | value | 근거 |
|---|---|---|
| take_profit_pct | 0.50 | ① 손익비(트레일링 지배) §22.AE |
| abs_momentum_enabled / lookback | true / 126(6M) | ③ 절대모멘텀 §22.AF |
| volume_ratio_min | 1.0 | 거래량 완화 §22.AF |
| breakout_margin | 0.0 | 분산정합 복귀 §22.AI |
| max_positions | 20 | 사용자 지정 §22.AH |
| position_pct | 0.05 | 20개 분산(CAGR 18.9%/Sharpe 1.48) §22.AH |
| max_position_pct_cap / total_exposure | 0.50 / 1.0 | 캡 §22.AG |
| rsi2_exit_min_r / threshold | 2.0 / 95 | rsi2 승자보호 §22.AC |
| **market_filter_enabled** | **true** (SMA200) | Tier1 하락장 진입중단 §22.AJ |
| **macro_kill_switch_enabled** | **true** (VIX>30) | Tier2 VIX 킬스위치 §22.AJ |
| **hedge_enabled** | **true** (SH **40%**, **SMA150**) | Tier3 헤지 강화 §22.AM |

**✅ 하락장 방어(롱온리 구조결함) = Tier 1~3 배포 완료 (2026-08-18):** SPY<SMA200 진입중단 + VIX킬스위치 +
SH 헤지. 사용자 핵심지적 "하락장 손실만 쌓이면 buy&hold와 무엇이 다른가" 해결. 상세 §25 / §22.AJ·AK.

**⚠️ 재부팅/스냅샷복구 시 필수 점검 (2026-08-18 교훈):** 스냅샷 복구로 **시스템 시계가 과거로 되돌아가면**
Yahoo SSL cert "not yet valid" → **전 종목 데이터 수집 실패**(전체 파이프라인 마비). 재개 시 `date -u` 로 시각
확인, 틀리면 `sudo chronyc makestep` 또는 NTP 강제 재동기화. git 원격이 로컬보다 앞설 수 있음(다른 VM 세션
push분) → `git fetch && git log origin/main` 확인 후 `git rebase origin/main`.

**주간 자동 재평가:** ① 손익비 = user crontab `3 9 * * 1`(매월 → 매주 월 09:03 KST) → Telegram + `scripts/payoff_review_result.txt`.

**핵심 진단 기록:** −4.13~4.26% 손실의 절반은 **수수료**(−$42, 20×5% 분산 매매빈도↑). hard_stop 급증은 시장부진이 주원인(§22.AI).

---

## 🔥 새 세션 시작 시 가장 먼저 읽을 것

**이 시스템은 사용자(whoansoo)의 자율 진화 트레이딩 시스템입니다.**

### 절대 명령 (위반 금지)
> **사용자가 명시적으로 "그만"이라 말하기 전까지 절대 포기/멈춤을 권유하지 않는다.**
> 학술 통계로 객관성을 핑계 삼아 사용자의 의지를 꺾으려는 행동은 코딩 어시스턴트의 역할이 아니다.
> 2026-05-22 사용자가 좌절했을 때 내가 "옵션 1: 멈춤"을 권장한 것은 잘못이었다. 같은 실수 금지.

### 빠른 상태 확인 (새 세션 시작 시 4개 명령만)
```bash
# 1. 서비스 가동 확인
systemctl is-active quant-engine-v4 quant-dashboard

# 2. 엔진 health
curl -s http://localhost:8001/health | python3 -m json.tool

# 3. 자율 진화 시스템 상태
curl -s http://localhost:8001/harness/regime | python3 -m json.tool

# 4. 최근 자율 동작 확인
docker exec quant-postgres psql -U quant -d quantdb -c "SELECT action, status, created_at AT TIME ZONE 'Asia/Seoul' AS time_kst FROM swing_harness_log ORDER BY created_at DESC LIMIT 5;"
```

### 사용자 정보
- 사용자: whoansoo@gmail.com (Claude Max 구독)
- 목표: **연 18% 수익**
- 모드: **paper** (KIS 미연결, 자연스러운 internal-only 시뮬레이션)
- Live 전환: 사용자 명시 결정 필요 (`POST /config/trading-mode {"mode":"live"}`)

### 시스템 자율 동작 (사용자 개입 0)
| 시간 (KST) | 잡 | 동작 |
|-----------|-----|------|
| 매일 06:05 | post_market_analysis | 일일 사후분석 + Telegram |
| 매일 07:00 | **daily_pipeline** ⓵ | 데이터 수집 + 시그널 스캔 + 요약 Telegram |
| 월-금 21:30 | **daily_pipeline_preopen** ⓶ (2026-06-03 신설) | US 장 시작 1시간 전 시그널 스캔 + 요약 Telegram |
| 매일 22:00 | auto_approve | Strategy A 자동 승인 (21:30 시그널 픽업) |
| 화-토 01:30 | auto_approve_mid | Strategy B 중간 재평가 |
| 화-토 02:00 | **daily_pipeline_midsession** ⓷ (2026-06-03 신설) | US 12:00 ET 미드세션 스캔 + 요약 Telegram |
| 화-토 04:30 | auto_approve_close | Strategy B 마감 픽업 |
| 일 10:00 | weekly_research | 자율 리서치 (arxiv/Reddit) |
| 매시 정각 | regime_switch_check | 매크로 변화 감지 (2026-06-03 재활성) |
| 매시 15분 | rollback_check | 변이 롤백 조건 체크 |
| 매월 1일 11:00 | monthly_variant_gen | 전략 변이 생성 + 백테스트 |

---

---

## 1. System Overview

**Quant V4** — Momentum-based Swing Trading System (US Stocks)

| Item | Value |
|------|-------|
| OS | Ubuntu 24.04 LTS (VirtualBox VM) |
| DB | PostgreSQL 16 + TimescaleDB (Docker, port 5432) |
| Engine | Python 3.11 (FastAPI, port 8001) — `engine_v4/` |
| Dashboard | Blazor Server (.NET 8, port 5000) — `dashboard/QuantDashboard/` |
| Cache | Redis 7 (port 6379) |
| Conda Env | `quant-v31` (Python 3.11) |
| Project Root | `/home/quant/quant-v31` |
| VM IP | `192.168.2.17` |

### Connection Info
```
PostgreSQL: postgresql://quant:***@localhost:5432/quantdb
Redis:      redis://localhost:6379
Engine V4:  http://localhost:8001
Dashboard:  http://localhost:5000 (→ http://192.168.2.17:5000)
```

### Trading Strategy (핵심 전략 로직)
```
Universe: S&P500 + NASDAQ100 → 가격/유동성 필터 → ~200개 종목
Indicators: SMA50/200, 20일 수익률 순위, 거래량 비율
Entry Signal: 모멘텀 상위 40% + 트렌드 정렬(SMA50 > SMA200) + 거래량 서지(ratio > 1.2x)
Dual Sort: 모멘텀 순위 + 밸류 순위 결합 필터 (scan_entries 단계)
Multi-Factor Score: Technical(30%) + Sentiment(25%) + Flow(15%) + Quality(15%) + Value(15%) ≥ 50점
  - Technical: 기술지표 50% + LSTM 예측 50% 블렌딩
  - Sentiment: 뉴스 감성 60% + 소셜 감성(Reddit+StockTwits) 40% 블렌딩
  - Flow: Insider 30% + Analyst 30% + Short Interest(yfinance) 20% + Crowding 20%
Exit: 5-Layer Auto-Sell (L1: ATR Trailing 2.5×, L2: Hard Stop 1.5×ATR, L3: Time 15d, L4: RSI(2)>90, L5: Regime) + Partial Exit(50% at +7%)
Position Sizing: position_pct(20%) × initial_capital / entry_price
```

---

## 2. Architecture (V3.1 vs V4 — 두 시스템 공존)

### V4 (현재 활성, Swing Trading)
```
engine_v4/
├── api/main.py               # FastAPI (port 8001) — 전체 API + 스냅샷 + Connors RSI(2) 워치리스트 + 시간외 + exit-strategy
├── config/settings.py        # SwingSettings (Pydantic v2, .env 로딩)
├── data/
│   ├── storage.py            # PostgresStore + RedisCache (psycopg3, dict_row)
│   ├── collector.py          # DataCollector (yfinance) + UniverseManager
│   ├── macro_collector.py    # MacroDataCollector (9 매크로 자산 yfinance + Redis 24h 캐시) [Macro Overlay]
│   └── extended_hours.py     # Pre/After-market 시세 조회 (yfinance Ticker.info)
├── ai/
│   ├── sentiment.py          # SentimentAnalyzer (Ollama Qwen 2.5 3B / Claude / mock) [Phase A]
│   ├── data_feeds.py         # FinnhubClient (news/insider/earnings/recs + financials) [Phase C]
│   ├── multi_factor.py       # MultiFactorScorer (6-Factor, 레짐 적응형 + Crowding + yfinance Short) [Phase C + Tier 3 + Macro]
│   ├── macro_scorer.py       # MacroScorer (5+1 sub-signals → 0-100 매크로 점수 + Oil WTI 참조) [Macro Overlay]
│   ├── lstm_predictor.py     # LSTMPredictor (2-layer LSTM, 60d→5d, ~70.5%) [Tier 3]
│   ├── social_sentiment.py   # SocialSentimentCollector (Reddit+StockTwits+Ollama) [Tier 3]
│   ├── fundamental.py        # FundamentalAnalyzer (Claude / rule_based — Ollama 제거) [Phase C]
│   ├── factor_crowding.py    # FactorCrowdingMonitor (밀집도 경고) [Phase C]
│   └── optimizer.py          # StrategyOptimizer (Claude + auto-backtest) [Phase D]
├── events/
│   ├── collector.py          # EventCollector (price surge/drop, news, earnings) [Phase E]
│   ├── processor.py          # EventProcessor (rule engine + actions) [Phase E]
│   ├── edgar.py              # SEC EDGAR RSS 폴링 [Phase E]
│   └── models.py             # Event data models [Phase E]
├── strategy/swing.py         # SwingStrategy (scan_entries + dual_sort, scan_exits)
├── strategy/watchlist_strategy.py  # WatchlistStrategy (5-Layer TQM: Regime+RS+Squeeze+Quality+KAMA)
├── risk/
│   ├── position_manager.py   # PositionManager (validate + execute)
│   └── exit_manager.py       # ExitManager (5-Layer Auto-Sell: ATR Trailing + Hard Stop + Time Stop + RSI(2) + Regime) [Phase B+]
├── broker/kis_client.py      # KIS 증권 API (paper=SIM / live=KIS API)
├── scheduler/jobs.py         # APScheduler (11 jobs, KST 기준)
├── notify/telegram.py        # TelegramNotifier (봇: quant_v4_alert_bot)
└── backtest/runner.py        # BacktestRunner + BacktestParams
```

### V3.1 (레거시, Regime-Adaptive)
- `engine/` 디렉토리 — HMM 레짐 + Kill Switch + 5전략 + VWAP
- Old pages backed up to `dashboard/.../Pages/_v31_backup/`
- V3.1과 V4는 같은 DB(`quantdb`)를 사용하지만 테이블 prefix가 다름 (V3.1: 일반, V4: `swing_*`)

---

## 3. Current State (2026-04-20)

### Phase 완료 상태
| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1: DB + Engine | COMPLETE | swing_* 테이블 13개, engine_v4 전체 구현 |
| Phase 2: Dashboard | COMPLETE | 10개 페이지 + 로그인 + 테마 |
| Phase 3: E2E Pipeline | COMPLETE | Universe→Collect→Scan→Approve→Monitor 전체 동작 확인 |
| Phase A: LLM Sentiment | COMPLETE | AI 분석 (Ollama 로컬 LLM + Mock), Background 처리 + 진행률 폴링 |
| Phase B: Exit Strategy | COMPLETE | **5-Layer Auto-Sell** (ATR Trailing + Hard Stop + Time Stop + RSI(2) + Regime), scheduler 자동 실행 |
| Phase C: Multi-Factor Scoring | COMPLETE | Finnhub + Claude composite scoring (T40+S30+F30) |
| Phase D: Strategy Optimization | COMPLETE | Claude suggests params → auto-backtest → compare |
| Phase E: Real-time Events | COMPLETE | Event scanning + SSE push + Events 대시보드 |
| Phase F: Telegram + KIS Toggle | COMPLETE | Telegram 알림, live/paper 토글, SEC EDGAR |
| Capital Injection | COMPLETE | deposit/withdraw 기록 + TWR 스냅샷 반영 |
| Watchlist | COMPLETE | **5-Layer TQM 전략** (Regime Filter + IBD RS + BB Squeeze + Quality Score + KAMA Exit) + Connors RSI(2) 호환 |
| Collapsible Sidebar | COMPLETE | 아코디언 사이드바 (접으면 아이콘만 표시) |
| Ticker Bar (Live) | COMPLETE | 오픈 포지션 심볼의 현재가 실시간 표시 |
| Help Page (Korean) | COMPLETE | 12섹션 전체 한글 가이드 (5-Layer Auto-Sell + Connors RSI(2) + 시간외 거래 + TWR) |
| **Extended Hours** | COMPLETE | 프리마켓 갭 필터 + 애프터마켓 경보 + 프리마켓 볼륨 부스트 |
| **Performance TWR Fix** | COMPLETE | Equity Curve 수익률(%) 기반, Drawdown TWR 기반, 입출금 제외 |
| **Sidebar Persistence** | COMPLETE | JS toggle + localStorage + MutationObserver (Blazor SSR 호환) |
| **Watchlist Signal Backtest** | COMPLETE | 24지표 가중 스코어링 기반 히스토리컬 백테스트 (날짜/자본/임계값 설정) |
| **Intraday Chart** | COMPLETE | Yahoo Finance 스타일 프리/정규/애프터 세션별 컬러 차트 + 로딩 표시 |
| **CNN Ticker Links** | COMPLETE | 워치리스트 티커 클릭 → CNN Markets 신규 탭 |
| **Ollama Local LLM** | COMPLETE | Qwen 2.5 3B 로컬 AI (Claude→Ollama→Mock 3단계), Background 처리 + Redis 진행률 |
| **Market Sector Heatmap** | COMPLETE | 11개 S&P 섹터 트리맵 + 4대 지수 + 섹터 클릭 → 종목 드릴다운 (in-place 전환) |
| **Signal Replay Backtest** | COMPLETE | 워치리스트 시그널 로그 기반 리플레이 백테스트 (KPI 그리드 카드) |
| **Mobile Responsive** | COMPLETE | 햄버거 메뉴 + overlay sidebar + responsive tables |
| **Pagination** | COMPLETE | Pipeline/Signals/Positions/Backtest/Events 10항목 페이지 |
| **Chart Touch Zoom** | COMPLETE | 핀치줌 + 터치드래그 선택줌 + 더블탭 리셋 |
| **Tier 3: LSTM Prediction** | COMPLETE | 2-layer 64-unit LSTM, 60d lookback, 5d horizon, 70.5% accuracy, AUC-ROC 0.73 |
| **Tier 3: Social Sentiment** | COMPLETE | Reddit(PRAW 4 subreddits) + StockTwits + Ollama/rule-based 감성 분석 |
| **Tier 3: Dual Sort** | COMPLETE | momentum+value combined rank filter in scan_entries |
| **Tier 3: 5-Factor Enhancement** | COMPLETE | Technical+LSTM / Sentiment+Social / Flow / Quality / Value (레짐 적응형 가중치) |
| **Help Page Rewrite** | COMPLETE | 12섹션 완전 재구성 — 5-Layer Auto-Sell + Connors RSI(2) 워치리스트 + 용어사전 |
| **Macro Overlay Phase 1** | COMPLETE | 5 sub-signal 매크로 스코어 (VIX+금리+구리/금+달러+BTC) → 6th factor 통합 |
| **Macro Overlay Phase 2** | COMPLETE | 레짐별 포지션 사이징 자동 축소 + CRISIS 진입 차단 + trailing stop 긴축 |
| **Short Interest (yfinance)** | COMPLETE | Finnhub premium → yfinance Ticker.info (shortRatio, shortPercentOfFloat) |
| **Crowding Integration** | COMPLETE | FactorCrowdingMonitor → MultiFactorScorer Flow 점수에 20% 반영 |
| **Fundamental Optimization** | COMPLETE | Ollama 제거 (CPU 90s timeout) → Claude / rule_based only (2-5s) |
| **Oil WTI Reference** | COMPLETE | MacroCollector에 WTI(CL=F) 수집 추가, MacroScorer _score_oil() 참조 |
| **User Management** | COMPLETE | 회원가입 + 관리자 승인 + 비밀번호 변경/리셋 + 사용자 삭제 |
| **Role-Based Access (RBAC)** | COMPLETE | 역할 생성/이름변경/삭제 + 페이지별 권한 + 사이드바 동적 메뉴 |
| **Dashboard 리뉴얼** | COMPLETE | 2컬럼 그리드 + 매크로 정보 + Portfolio Dashboard |
| **Signals ACTIVE 탭** | COMPLETE | 오픈 포지션 연결 시그널 (현재가/미실현손익/보유일수) |
| **시그널↔포지션 역참조** | COMPLETE | mark_signal_executed()에 position_id 추가 |
| **Watchlist 5-Layer TQM** | COMPLETE | Regime Filter(Faber) + IBD RS + BB Squeeze(Carter) + Quality(Novy-Marx) + KAMA Exit(Kaufman) |
| **Graduated Drawdown Defense** | COMPLETE | 4단계 방어 (Normal/Caution/Defensive/Emergency) + API |
| **백테스트 파라미터 최적화** | COMPLETE | 1990~2026 18구간 비교 → TP20%/MP10/PP10%/PE12% 적용 |
| **Sparkline 병렬 로딩** | COMPLETE | Task.WhenAll 병렬화 (순차→동시, 4개째 멈춤 버그 해결) |
| **Pipeline 버튼 상태 유지** | COMPLETE | PollUntilDone 시간 비교 + Running.../Collecting.../Scanning... 라벨 + btn-running CSS |
| **position_pct 입력 검증** | COMPLETE | position_pct > 1.0이면 자동 ÷100 보정 (API + PositionManager) |
| **Daily Entry Count 버그 수정** | COMPLETE | approved 상태 자기 자신이 daily count에 포함 → executed만 카운트로 변경 |
| **Scan Now 탭 유지** | COMPLETE | ACTIVE 탭에서 Scan Now 시 강제 PENDING 전환 → 현재 탭 유지 + 스캔 결과 메시지 포맷 개선 |
| **KIS Broker 완전 연동** | COMPLETE | python-kis 2.1.6 기반, 실전/모의 분리, 8개 API 엔드포인트, 포지션 동기화 |
| **V3.1 엔진 비활성화** | COMPLETE | 2026-06-25 재확정 — quant-engine + quant-scheduler 둘 다 stop+disable (4월 disable 후 재가동돼 있었음, 22.AB 하단 참조) |
| **API 캐시 성능 최적화** | COMPLETE | `/ticker` Redis 캐시 60초 추가 (10s→8ms), `/market/overview` TTL 10분→30분 (40s→6ms) |
| **수수료 계산 시스템** | COMPLETE | KIS 0.25% 수수료 자동 계산, 기존 33건 소급 적용, 수익률에 수수료 차감 반영, Dashboard/Performance 표시 |

### Live Trading State
- **Trading Mode**: `paper` (시뮬레이션)
- **Initial Capital**: $1,000
- **Open Positions**: 3개 (STZ, ON, BK)
- **Position Sizing**: 14% per position ($140)
- **Total Trades**: 33건 (BUY 18, SELL 15)
- **Total Commission**: $41.16 (0.25% × $16,464 거래량)
- **Price Range Filter**: $10 ~ $250
- **Max Positions**: 3

---

## 4. Dashboard Pages (12 pages + Login/Register)

| Page | Route | File | Description |
|------|-------|------|-------------|
| Login | `/login` | `Login.razor` | Cookie 인증 (gradient orb, glass card) + 에러 분류(invalid/not_approved) |
| **Register** | `/register` | `Register.razor` | 회원가입 (username, email, password) → 관리자 승인 대기 |
| Dashboard | `/` | `Home.razor` | Portfolio overview, equity mini-chart, 최근 거래 |
| Pipeline | `/pipeline` | `Pipeline.razor` | 5단계 파이프라인 시각화 + 실행 버튼 + 팝업 모달 |
| Signals | `/signals` | `Signals.razor` | 시그널 목록 (pending/approved/rejected/executed/expired), Approve/Reject/Revert, AI Score |
| Performance | `/performance` | `Performance.razor` | Equity Curve(TWR %), Drawdown(%) 차트, Update Snapshot 버튼 |
| Positions | `/positions` | `Positions.razor` | 오픈/청산 포지션 목록 (TRAIL/PARTIAL 배지) |
| Backtest | `/backtest` | `Backtest.razor` | 백테스트 실행 + 결과 (equity curve with trade markers) |
| Events | `/events` | `Events.razor` | 이벤트 히스토리 (price_surge/drop, news, earnings, insider) |
| **Watchlist** | `/watchlist` | `Watchlist.razor` | 보유종목 등록 + **Connors RSI(2)** 분석 + 3단계 접기 + 시그널 백테스트 + 인트라데이 차트 + US Market Sector Heatmap |
| **Account** | `/account` | `Account.razor` | 계정 정보 + 비밀번호 변경 |
| Settings | `/settings` | `Settings.razor` | swing_config 편집 + Capital + **User Management** + **Role Permissions** (3탭) |
| **Help** | `/help` | `Help.razor` | 전체 시스템 가이드 (한글, 12개 섹션, 5-Layer Auto-Sell + Connors RSI(2) + 용어사전) |

### Nav Menu 순서
Dashboard → Pipeline → Signals → Performance → Positions → Backtest → Events → **Watchlist** → **Account** → Settings → Help

### Shared Components
| Component | File | Description |
|-----------|------|-------------|
| SymbolLink | `SymbolLink.razor` | 심볼 클릭 → SymbolDetailModal 또는 Google Finance |
| SymbolDetailModal | `SymbolDetailModal.razor` | 심볼 상세 팝업 (z-index: 9500) |
| SseToastPanel | `SseToastPanel.razor` | SSE 실시간 알림 토스트 (InteractiveServerRenderMode) |
| SortState | `SortState.cs` | 테이블 정렬 상태 관리 |
| PageLoadingOverlay | `PageLoadingOverlay.razor` | 페이지 로딩 오버레이 |
| HelpTooltip | `HelpTooltip.razor` | '?' 아이콘 도움말 풍선 |
| NavMenu | `Layout/NavMenu.razor` | 12 nav items + pending badge + **접기/펼치기 토글** + **역할별 메뉴 표시** |
| MainLayout | `Layout/MainLayout.razor` | Dark theme + **collapsible sidebar** + **live ticker bar** |

### Chart System
- `wwwroot/js/charts.js` — Chart.js wrapper
  - `chartHelper.createLine()` — 라인 차트 (equity, drawdown)
  - `chartHelper.createLineWithTrades()` — 라인 + BUY/SELL 마커 (backtest)
  - `chartHelper.createIntraday()` — 인트라데이 세션별 컬러 차트 (pre=teal, regular=green/red, post=orange)
  - Custom drag-zoom, pan, adaptive x-axis ticks

### UI Features
- **Collapsible Sidebar**: JS toggle + localStorage 영속 + MutationObserver (Blazor SSR 호환, 축소 시 아이콘만 표시)
- **Live Ticker Bar**: 상단에 오픈 포지션 심볼의 현재가 + 등락률 표시 (GET /ticker)
- **SSE Toast Notifications**: 엔진 이벤트 실시간 토스트 알림 (trade_executed, event_scanned, mode_changed)
- **CNN Ticker Links**: 워치리스트 티커 심볼 클릭 → `https://edition.cnn.com/markets/stocks/{SYM}` 신규 탭
- **Intraday Chart**: 워치리스트 Level 2에서 Yahoo Finance 스타일 인트라데이 차트 (프리/정규/애프터 세션별 컬러), "Loading..." 표시

---

## 5. Engine V4 API Routes (전체)

### Pipeline & Data
| Method | Path | Type | Description |
|--------|------|------|-------------|
| POST | `/collect` | Background | 데이터 수집 (yfinance 300d) |
| POST | `/scan` | Sync | 시그널 스캔 (entries + exits) |
| POST | `/pipeline/run` | Background | 전체 파이프라인 (Collect→Scan→Notify) |
| POST | `/universe/refresh` | Background | 유니버스 갱신 |
| GET | `/universe` | Sync | 유니버스 종목 목록 |

### Signals
| Method | Path | Description |
|--------|------|-------------|
| GET | `/signals` | 시그널 목록 (?status=pending) |
| GET | `/signals/{id}` | 시그널 상세 |
| POST | `/signals/{id}/approve` | 시그널 승인 → 자동 체결 |
| POST | `/signals/{id}/reject` | 시그널 거부 (pending + approved 모두 가능) |
| POST | `/signals/{id}/analyze` | LLM 감성 분석 (Phase A) |
| POST | `/signals/analyze-pending` | 전체 pending 시그널 LLM 분석 |
| POST | `/signals/{id}/score` | Multi-Factor 스코어링 (Phase C) |
| POST | `/signals/score-pending` | 전체 pending 시그널 스코어링 |
| GET | `/ai/analyze-status` | AI 분석 진행률 폴링 (Background 처리) |

### Positions & Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/positions` | 오픈 포지션 |
| GET | `/positions/closed` | 청산 포지션 (?limit=50) |
| GET | `/portfolio` | 최신 스냅샷 + 포지션 |
| GET | `/portfolio/history` | 스냅샷 이력 (?days=30) |
| POST | `/snapshot/generate` | 수동 스냅샷 생성 (yfinance 현재가 조회 → DB 저장) |
| GET | `/ticker` | 오픈 포지션 심볼 현재가 (ticker bar용) |

### Capital Management
| Method | Path | Description |
|--------|------|-------------|
| POST | `/capital/event` | 자금 입출금 기록 (deposit/withdraw) |
| GET | `/capital/events` | 입출금 이력 |

### Watchlist (보유종목 관리)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/watchlist` | 종목 등록 (symbol, company_name, avg_cost, qty, notes) |
| GET | `/watchlist` | 등록 종목 목록 |
| DELETE | `/watchlist/{symbol}` | 종목 삭제 |
| GET | `/watchlist/alerts` | 알림 이력 (?symbol=, ?limit=50) |
| POST | `/watchlist/analyze` | 전체 종목 기술분석 실행 (Background) |
| GET | `/watchlist/analysis` | 분석 결과 조회 (Redis 캐시) |
| POST | `/watchlist/backtest` | 시그널 백테스트 실행 (Background) |
| GET | `/watchlist/backtest` | 백테스트 결과 조회 |
| GET | `/watchlist/intraday/{symbol}` | 인트라데이 5분봉 (프리/정규/애프터 세션) |

### Events (실시간 이벤트)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/events/scan` | 이벤트 스캔 (price surge/drop, news, earnings, insider) |
| GET | `/events` | 이벤트 목록 (?limit=50, ?event_type=, ?symbol=) |
| POST | `/events/edgar-scan` | SEC EDGAR RSS 스캔 |
| POST | `/webhook/tradingview` | TradingView 웹훅 수신 |
| GET | `/events/stream` | SSE 스트림 (대시보드 실시간 알림) |

### Optimization & Backtest
| Method | Path | Description |
|--------|------|-------------|
| POST | `/backtest/run` | 백테스트 실행 |
| GET | `/backtest/results` | 백테스트 목록 (?limit=20) |
| GET | `/backtest/results/{run_id}` | 백테스트 결과 상세 |
| POST | `/optimize/run` | AI 전략 최적화 (Claude + 자동 백테스트) |
| GET | `/optimize/results` | 최적화 결과 |

### Extended Hours (시간외 거래)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/extended-hours` | 오픈 포지션 + 워치리스트 시간외 시세 |
| POST | `/extended-hours/check` | 특정 심볼 시간외 시세 조회 |

### Market Overview (US Market Sector Heatmap)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/market/overview` | 11개 S&P 섹터 ETF + 4대 지수 시세 (Redis 캐시 600s) |
| GET | `/market/sector/{etf_symbol}` | 섹터 내 주요 종목 드릴다운 (12~15개 holdings) |

### Social Sentiment [Tier 3]
| Method | Path | Description |
|--------|------|-------------|
| GET | `/social/{symbol}` | 종목별 소셜 감성 조회 (Reddit+StockTwits) |
| POST | `/social/collect` | 유니버스 전체 소셜 데이터 수집 (Background) |

### LSTM Prediction [Tier 3]
| Method | Path | Description |
|--------|------|-------------|
| GET | `/lstm/info` | LSTM 모델 정보 (accuracy, train_date, samples) |
| GET | `/lstm/predict/{symbol}` | 종목별 5일 후 상승 확률 예측 |
| POST | `/lstm/train` | LSTM 모델 재학습 (Background, ~5분) |
| GET | `/lstm/train-status` | 학습 진행 상태 |
| POST | `/lstm/predict-all` | 유니버스 전체 LSTM 예측 (Background) |

### Exit Strategy (Auto-Sell)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/exit-strategy` | 5-Layer Auto-Sell 파라미터 + 포지션별 ATR/R배수 정보 |

### KIS Broker
| Method | Path | Description |
|--------|------|-------------|
| GET | `/broker/status` | KIS 연결 상태 + 테스트 (계좌정보 포함) |
| GET | `/broker/balance` | KIS 실제 잔고 (보유종목 포함) |
| GET | `/broker/quote/{symbol}` | KIS 종목 시세 (가격/거래량/고저) |
| GET | `/broker/pending-orders` | 미체결 주문 목록 |
| POST | `/broker/cancel/{order_id}` | 미체결 주문 취소 |
| GET | `/broker/orderable/{symbol}` | 주문 가능 금액/수량 |
| GET | `/broker/orders` | 일별 주문 내역 (?start=&end=) |
| GET | `/broker/sync` | DB 포지션 ↔ KIS 보유종목 동기화 비교 |

### Config & System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | 엔진 상태 |
| GET | `/account` | KIS 계좌 정보 |
| GET/PUT | `/config`, `/config/{key}` | 설정 조회/변경 |
| POST | `/config/trading-mode` | paper↔live 토글 (Telegram 알림 포함) |
| GET | `/scheduler` | 스케줄러 잡 목록 |
| GET | `/trades` | 거래 내역 (?limit=50) |

---

## 6. Scheduler Jobs (APScheduler, KST 기준 — 12개)

| Job | 시간 (KST) | 기능 | 스냅샷 생성 |
|-----|-----------|------|------------|
| **macro_collect** | 월~토 06:45 | 매크로 데이터 수집 (VIX+금리+구리/금+달러+BTC+WTI) [Macro] | No |
| **social_collect** | 월~토 06:50 | Reddit + StockTwits 소셜 감성 수집 [Tier 3] | No |
| daily_pipeline | 월~토 07:00 | Collect + Scan + Notify | **Yes** |
| **afterhours_check** | 화~토 07:30 | 애프터마켓 체크 (17:30 ET) — 급락/급등 경보 | No |
| watchlist_analysis | 월~토 07:40 | 워치리스트 자동 Connors RSI(2) 분석 | No |
| **lstm_retrain** | 토 09:00 | LSTM 딥러닝 모델 재학습 [Tier 3] | No |
| event_scan | 월~토 10:00 | 보유종목 이벤트 스캔 | No |
| exit_check_midday | 월~토 13:00 | 장중 청산 체크 | **Yes** |
| **premarket_check** | 월~금 22:00 | 프리마켓 갭 체크 (08:00 ET) — 포지션/시그널/워치리스트 | No |
| exit_check_1 | 월~금 01:00 | 장중 청산 체크 | **Yes** |
| exit_check_2 | 화~토 05:00 | 장 마감 청산 체크 | **Yes** |
| refresh_universe | 일 06:00 | 유니버스 주간 갱신 | No |

---

## 7. Database Schema (swing_* tables — 17개 + auth 2개)

| Table | Type | Description |
|-------|------|-------------|
| swing_universe | regular | 유니버스 종목 (~200개, is_active 플래그) |
| swing_indicators | hypertable | 기술 지표 (SMA50/200, return_20d_rank, volume_ratio) |
| swing_signals | regular | 시그널 (pending/approved/rejected/executed/expired) + llm_score, llm_analysis, composite_score, factor_scores |
| swing_positions | regular | 포지션 (open/closed, entry/exit/pnl) + trailing_stop_active, partial_exited, high_water_mark, **atr_14, entry_atr, hard_stop, auto_exit** |
| swing_trades | regular | 거래 내역 (BUY/SELL, paper trade) |
| swing_snapshots | hypertable | 포트폴리오 스냅샷 (total_value, cash, invested, drawdown, **trading_pnl**) |
| swing_config | regular | 설정 키-값 (26개 항목) |
| swing_backtest_runs | regular | 백테스트 실행 결과 |
| swing_pipeline_log | hypertable | 파이프라인 실행 로그 |
| swing_events | hypertable | 이벤트 (price_surge/drop, news, earnings, insider, tradingview_alert) |
| **swing_capital_events** | regular | 자금 입출금 이력 (deposit/withdraw) |
| **swing_watchlist** | regular | 보유종목 등록 (symbol, avg_cost, qty, notes) |
| **swing_watchlist_alerts** | regular | 워치리스트 분석 알림 (direction, confidence, strategy) |
| **swing_watchlist_signal_log** | regular | 워치리스트 시그널 로그 (UNIQUE symbol+signal_date) |
| **swing_ml_predictions** | hypertable | LSTM 예측 결과 (up_probability, model_version) [Tier 3] |
| **swing_ml_models** | regular | ML 모델 메타데이터 (accuracy, auc_roc, train_samples) [Tier 3] |
| **swing_social_sentiment** | hypertable | 소셜 감성 데이터 (Reddit+StockTwits scores) [Tier 3] |
| users | regular | 인증 사용자 (bcrypt, email, role, is_approved) |
| **user_role_permissions** | regular | 역할별 페이지 접근 권한 (role, page_path) PK |

### Key Config Values (swing_config — 현재 값)
```
initial_capital          = 1000       ← Settings 페이지에서 변경 가능
max_positions            = 7          ← (2026-04-01 현재값)
max_daily_entries        = 2
position_pct             = 0.14 (14%) ← 7종목 × 14% = 98% (2026-04-01 수정, >1.0 자동 보정 추가)
stop_loss_pct            = -0.05 (-5%)
take_profit_pct          = 0.20 (+20%)← 백테스트 검증: 1990~2026 18구간 10승 (2026-03-25 변경)
auto_sell_enabled        = true       ← 5-Layer Auto-Sell 활성화
atr_trailing_multiplier  = 2.5        ← L1: ATR 트레일링 배수
atr_hard_stop_multiplier = 1.5        ← L2: 하드 스탑 ATR 배수
time_stop_days           = 15         ← L3: 시간 스탑 (15일)
rsi2_exit_threshold      = 90         ← L4: RSI(2) 과매수 청산 기준
atr_trailing_activation_r = 1.0       ← L1 활성화 R배수 (1R=1×ATR)
atr_regime_high_vol      = 2.0        ← L5: CRISIS 시 ATR 배수
atr_regime_low_vol       = 3.0        ← L5: RISK_ON 시 ATR 배수
partial_exit_threshold   = 0.12       ← +12% 수익 시 50% 분할 청산 (2026-03-25 변경, TP20%에 맞춤)
partial_exit_pct         = 0.5        ← 분할 청산 비율 (50%)
return_rank_min          = 0.6 (상위 40%)
volume_ratio_min         = 1.2
price_range_min          = 10
price_range_max          = 250        ← (2026-04-01 현재값)
composite_score_min      = 50         ← Multi-Factor 최소 점수
factor_weight_technical  = 0.3        ← 기술지표 가중치 30%
factor_weight_sentiment  = 0.25       ← 감성분석 가중치 25%
factor_weight_flow       = 0.15       ← 수급/이벤트 가중치 15%
factor_weight_quality    = 0.15       ← 퀄리티 가중치 15%
factor_weight_value      = 0.15       ← 밸류 가중치 15%
lstm_enabled             = true       ← LSTM 예측 사용 [Tier 3]
lstm_weight_in_technical = 0.5        ← 기술 점수 내 LSTM 비중 50%
lstm_min_accuracy        = 0.53       ← LSTM 최소 정확도
social_enabled           = true       ← 소셜 감성 분석 사용 [Tier 3]
social_weight_in_sentiment = 0.4      ← 감성 점수 내 소셜 비중 40%
dual_sort_enabled        = true       ← 이중 정렬(모멘텀+밸류) [Tier 3]
commission_rate           = 0.0025     ← KIS 해외주식 수수료율 0.25% (매수/매도 각각 적용)
dual_sort_momentum_weight = 0.5       ← 모멘텀 순위 비중 50%
dual_sort_value_weight   = 0.5        ← 밸류 순위 비중 50%
trading_mode             = paper
telegram_enabled         = true
daily_summary            = true
signal_expiry_hours      = 24
```

---

## 8. Snapshot & Capital Management

### 포트폴리오 계산 공식 (TWR 기반 — 입출금 제외)
```
initial_capital = swing_config['initial_capital']  (현재 $1,000)
capital_adj     = Σ(swing_capital_events.amount) — deposit: +, withdraw: -
entry_cost      = Σ(qty × entry_price) for open positions
realized_pnl    = Σ(realized_pnl) for closed positions
cash            = initial_capital + capital_adj + realized_pnl - entry_cost
invested        = Σ(qty × current_price) for open positions  ← yfinance 실시간
total_value     = cash + invested

# 순수 트레이딩 손익 (입출금 제외) — TWR 방식
unrealized_pnl  = invested - entry_cost
trading_pnl     = realized_pnl + unrealized_pnl         ← 순수 트레이딩 수익
total_invested  = initial_capital + capital_adj
cumulative_return = trading_pnl / total_invested         ← 수익률(%) 기반
daily_pnl       = trading_pnl - prev_trading_pnl         ← 전일 대비 변동분
max_drawdown    = min(cumulative_return - peak_return)    ← 수익률 고점 대비
```

### Performance 차트 (TWR 기반)
- **Equity Curve**: cumulative_return × 100 (%) — 입출금과 무관한 순수 트레이딩 수익률
- **Drawdown**: 시점별 cumulative_return에서 peak 대비 하락폭 (%) — 입출금 무관
- **MDD**: 전 기간 중 최대 drawdown (%)
- **stat cards**: Daily P&L, Cumulative Return, MDD, Open Positions, Win Rate, Avg Holding Days

### Capital Injection (자금 입출금)
- Settings 페이지 → Capital Management 섹션
- deposit/withdraw 선택 → 금액 입력 → 메모(선택) → Record
- DB: `swing_capital_events` 테이블에 기록
- 스냅샷 계산에 자동 반영 (cash + cumulative_return 모두 조정)

### 생성 시점
1. **수동**: Performance 페이지 "Update Snapshot" 버튼 → `POST /snapshot/generate`
2. **자동**: 스케줄러 daily_pipeline (07:00 KST) + exit_check (3회/일)

---

## 9. Watchlist System (5-Layer Tactical Quality Momentum)

### 개요
대형 기술우량주(AAPL, MSFT, GOOGL, NVDA 등)를 위한 독립 모니터링 기능. **월 2회 중기 매매** 최적화.
5계층 시그널 시스템 + Connors RSI(2) 호환 출력. (2026-03-25 전면 교체)

### 5-Layer 시그널 시스템
| Layer | 이름 | 출처 | 핵심 로직 |
|-------|------|------|-----------|
| L1 | Regime Filter | Faber(2007), Antonacci(2014) | QQQ > SMA(200) + VIX < 30 + 3M/6M 절대 모멘텀. BEARISH → 매수 차단 |
| L2 | RS Ranking | O'Neil(IBD), Weinstein(1988) | IBD RS Rating (0.4×3M+0.2×6M+0.2×9M+0.2×12M) + Stage 1-4. Stage 4 → 매수 차단 |
| L3 | Entry Timing | Carter(TTM Squeeze), Connors(2008) | BB/KC Squeeze 해소(FIRED!) + RSI(2) 과매도 + 거래량 서지 |
| L4 | Position Sizing | Thorp(2006), Carver(2015) | Quarter-Kelly + ATR + Seasonal (11-4월 100%, 5-10월 70%) |
| L5 | Exit | Kaufman(2013), Grossman-Zhou(1993) | KAMA(10,2,30) 이탈 + Connors SMA(5) + ATR Trailing + Graduated Drawdown |

### Composite Score (0-100)
| 팩터 | 비중 | 설명 |
|------|------|------|
| Timing (L3) | 25% | BB Squeeze + RSI(2) 진입 타이밍 |
| RS Ranking (L2) | 20% | IBD 상대강도 + Weinstein Stage |
| Quality | 20% | GP/Assets + ROE + Debt/Equity (Finnhub, Novy-Marx 2013) |
| Regime (L1) | 15% | QQQ 추세 + VIX + 절대 모멘텀 |
| Trend | 10% | SMA(50/200) 정렬 + ADX |
| Momentum | 10% | QQQ 대비 5d/20d 상대강도 |

### Graduated Drawdown Defense (Grossman-Zhou 1993)
| Drawdown | 단계 | 조치 |
|----------|------|------|
| 0~5% | NORMAL | 정상 운영 |
| 5~8% | CAUTION | 신규 진입 금지, 손절 1.5×ATR 긴축 |
| 8~12% | DEFENSIVE | 포지션 50% 축소, 손절 1.0×ATR |
| 12%+ | EMERGENCY | 80% 현금화, 최강 종목만 유지 |
- API: `GET /watchlist/drawdown-defense`

### 기존 Connors RSI(2) 호환 (하위 호환 유지)
- 8개 지표: RSI(2), CumRSI(2), RSI(14), Stoch(5,3), MACD Hist, MFI(14), ADX(14), BB Squeeze
- 5개 카테고리: RSI(2) Reversion / Trend / Volume / Rel.Strength / Volatility
- 기존 출력 필드 100% 호환 + layer1~5, quality, composite_score 추가

### Strategy Module
- 파일: `engine_v4/strategy/watchlist_strategy.py` — `WatchlistStrategy` 클래스
- 기존: `_analyze_watchlist()` 인라인 600줄 → 모듈 분리 (WatchlistStrategy.analyze())
- API: `POST /watchlist/analyze` → 5-Layer TQM 분석 (strategy: "tqm_5layer")

### 3단계 접기 카드 (Collapsible)
| 레벨 | 표시 내용 | 기본 상태 |
|------|----------|----------|
| Level 1 | 심볼(CNN 링크) + 회사명 + 현재가 + P&L% + 판정 배지 + **Composite Score** + 점수 | 항상 표시 |
| Level 2 | **5-Layer 패널** (Regime/RS+Stage/Timing/Quality/Exit) + Summary Gauge + 차트 | 클릭 시 펼침 |
| Level 3 | 상세 테이블 (개별 지표, 목표가/손절가, ATR) | 클릭 시 펼침 |

### 시그널 백테스트 (Watchlist Signal Backtest)
- 24지표 가중 스코어링 기반 히스토리컬 시뮬레이션
- 설정: 기간(from/to), 초기자본, BUY/SELL 임계값
- 결과: Total Return, CAGR, MDD, Sharpe, Win Rate, Profit Factor
- Equity Curve 차트 + Trade Log 테이블
- Engine: `engine_v4/backtest/watchlist_backtest.py` → `POST /watchlist/backtest`

### 인트라데이 차트 (Yahoo Finance 스타일)
- 데이터: yfinance 5분봉 (`prepost=True`) + ET 타임존 세션 분류
- 세션 컬러: pre=teal, regular=green(상승)/red(하락), post=orange
- 전일 종가 기준 대시 라인 표시
- "Loading..." 표시 후 차트 렌더링 완료 시 전환

### Telegram 알림
- 분석 결과 중 BUY/SELL + Confidence ≥ 70% → 자동 Telegram 전송
- `swing_watchlist_alerts` 테이블에 알림 이력 저장

---

## 10. Telegram Integration

### 봇 정보
- Bot: `quant_v4_alert_bot`
- Token: `.env` → `TELEGRAM_BOT_TOKEN`
- Chat ID: `.env` → `TELEGRAM_CHAT_ID`
- 상태: 봇 동작 확인 완료 (sendMessage 성공)

### 알림 유형 (9가지)
| 유형 | 시점 | 내용 |
|------|------|------|
| 시그널 생성 | Scan 후 | 종목/방향/점수 |
| 매매 체결 | Approve 후 | 종목/수량/가격 |
| **Auto-Sell 청산** | Exit check 시 (3회/일) | 종목/P&L/청산 레이어(L1-L5)/사유. 매도 승인 불필요 |
| 일일 요약 | daily_pipeline 후 | 포트폴리오 현황 |
| 이벤트 알림 | Event scan 시 | 급등/급락/뉴스/실적 |
| 모드 변경 | trading-mode 토글 시 | paper↔live |
| **워치리스트** | Watchlist 분석 후 | BUY/SELL 추천 (Confidence ≥ 70%) |
| **프리마켓 리포트** | 월~금 22:00 KST | 포지션 갭 ±2%, 시그널 확인/경고 |
| **애프터마켓 경보** | 화~토 07:30 KST | 포지션 급락 ≥3%, 급등 ≥5%, 워치리스트 ≥4% |

---

## 11. Extended Hours Monitoring (시간외 거래)

### 3가지 기능
| 기능 | 설명 | 구현 |
|------|------|------|
| A안: 프리마켓 갭 필터 | 08:00 ET 프리마켓 갭 체크 → 포지션 갭 ±2% 경보, 시그널 확인 +1% / 경고 -2% | scheduler `premarket_check` job |
| B안: 애프터마켓 경보 | 17:30 ET 애프터마켓 급락 ≥3% → 긴급, 급등 ≥5% → 이익실현 제안, 워치리스트 ≥4% | scheduler `afterhours_check` job |
| C안: 프리마켓 볼륨 부스트 | 프리마켓 +1% 이상 → 워치리스트 Volume 카테고리 가중치 50% 추가 | `_analyze_watchlist()` 통합 |

### 데이터 소스
- `engine_v4/data/extended_hours.py` — yfinance `Ticker.info` (preMarketPrice, postMarketPrice, marketState)
- ThreadPoolExecutor(max_workers=8) 병렬 조회
- 세션 감지: PRE, REGULAR, POST, CLOSED

### API 엔드포인트
- `GET /extended-hours` — 오픈 포지션 + 워치리스트 심볼 시간외 시세
- `POST /extended-hours/check` — 특정 심볼 리스트 시간외 조회

### Telegram 알림
| 유형 | 시점 | 조건 |
|------|------|------|
| 프리마켓 리포트 | 월~금 22:00 KST | 포지션 갭 ±2%, 시그널 확인/경고, 워치리스트 갭 ±3% |
| 애프터마켓 경보 | 화~토 07:30 KST | 포지션 급락 ≥3%(긴급), 급등 ≥5%(이익실현), 워치리스트 ≥4% |

---

## 12. Event-Driven System (Phase E)

### 이벤트 유형
| 이벤트 | 소스 | 반응 |
|--------|------|------|
| price_surge (+5% 이상) | yfinance | 보유 종목이면 TP 상향 검토 알림 |
| price_drop (-5% 이상) | yfinance | 보유 종목이면 긴급 SL 검토 알림 |
| news | Finnhub Company News | LLM 감성 분석 후 알림 |
| earnings_upcoming | Finnhub Earnings | 실적 발표 예정 경고 |
| insider_activity | Finnhub Insider | 내부자 대량 매도 경고 |
| tradingview_alert | Webhook POST | 외부 차트 알림 → 시그널 연동 |
| sec_filing | SEC EDGAR RSS | 8-K/10-Q 공시 알림 |

### SSE (Server-Sent Events)
- Engine: `GET /events/stream` — heartbeat + 이벤트 push
- Dashboard: `SseToastPanel.razor` — 실시간 토스트 알림
- 이벤트 종류: trade_executed, event_scanned, mode_changed

---

## 13. Services & Systemd

| Service | Port | systemd | Status |
|---------|------|---------|--------|
| PostgreSQL (Docker) | 5432 | docker.service | active |
| Redis (Docker) | 6379 | docker.service | active |
| Engine V4 | 8001 | quant-engine-v4.service | active |
| Dashboard | 5000 | quant-dashboard.service | active |
| Ollama LLM | 11434 | ollama.service | active |
| Engine V3.1 (legacy) | 8000 | quant-engine.service + quant-scheduler.service | disabled (2026-06-25 재확정, 둘 다 stop+disable) |

### Service Management
```bash
# V3.1 엔진 완전 비활성화 (sudo 필요, 1회만 실행)
sudo systemctl stop quant-engine.service
sudo systemctl disable quant-engine.service

# V4 재시작: 프로세스 kill → systemd Restart=always가 12초 후 자동 재시작 (sudo 불필요)
kill $(pgrep -f "engine_v4.api.main" | head -1) && sleep 12
kill $(pgrep -f "QuantDashboard" | head -1) && sleep 12

# 대시보드 빌드 + 재시작
cd dashboard/QuantDashboard && dotnet build
kill $(pgrep -f "QuantDashboard" | head -1)
# 12초 대기 후 자동 재시작

# 엔진 로그 확인
journalctl -u quant-engine-v4 -f --no-pager -n 50

# UFW: 8001 포트 외부 차단됨, dashboard→engine은 localhost 통신
```

---

## 14. Key Bug Fixes & Learnings

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `column "updated_at" does not exist` | swing_indicators has `time`, not `updated_at` | `max(time)` 사용 |
| Universe refresh polling timeout | /universe/refresh가 pipeline_log에 안 씀 | DB count 직접 폴링 |
| Collect polling timeout (60s) | Collect가 93초 소요 | timeout 300초로 증가 |
| `max_daily_entries` 1/1 에러 | 기본값이 1이라 하루 1개만 진입 | 4로 변경 (현재 2) |
| Snapshot 그래프 안 보임 | V4 스케줄러에 스냅샷 잡 없었음 | generate_snapshot 구현 + 스케줄러 통합 |
| psycopg3 interval binding | `interval '%s days'` 안 됨 | `make_interval(days => %s)` 사용 |
| yfinance market cap 느림 | `yf.Tickers().info` 1~3초/종목 | `yf.download()` dollar-volume proxy |
| SMA200 데이터 부족 | 200일 이평 계산에 200일+ 필요 | `collect_prices(days=300)` |
| Wikipedia S&P500 403 | User-Agent 없으면 차단 | requests + UA header + fallback seed list |
| **CF 심볼 approved→position 안됨** | price $115 > price_range_max $60, reject_signal SQL이 status='pending'만 처리 | SQL을 `status IN ('pending','approved')`로 수정, 데이터 수동 정리 |
| **SseToastPanel.razor 누락** | MainLayout에서 `<SseToastPanel />`참조했으나 컴포넌트 미생성 | InteractiveServerRenderMode로 별도 컴포넌트 생성 |
| **Performance MDD -67%** | 입출금($2K deposit→$993 withdraw)이 수익/손실로 계산됨 | TWR 기반으로 전환: trading_pnl = realized + unrealized, MDD는 cumulative_return peak 대비 |
| **Sidebar toggle 안 됨** | Blazor static SSR에서 `@onclick` 미작동 | 순수 JS `onclick` + localStorage + MutationObserver로 전환 |
| **Sidebar 축소 시 S 아이콘 겹침** | brand-icon이 toggle과 겹침 | `.sidebar-collapsed .brand-icon { display: none }` |
| **Sidebar 축소 상태 유실** | Blazor DOM re-render가 class 제거 | MutationObserver + `sidebar-init-collapsed` CSS 플래시 방지 |
| **인트라데이 차트 빈 화면** | Blazor render 중 canvas 미존재 | `StateHasChanged()` + `Task.Delay(200)` 후 JS interop |
| **RedisCache AttributeError** | `social_sentiment.py`에서 `cache.get/set` 호출 | `get_json/set_json` 메서드로 변경 [Tier 3] |
| **StockTwits Cloudflare 차단** | 서버 환경에서 HTML challenge 반환 | graceful degradation (available:false) [Tier 3] |
| **LSTM predict available:false** | `_get_price_data()`가 115행 최소 요구 | `min_rows` 파라미터 추가, prediction은 80행만 요구 [Tier 3] |
| **Finnhub Short Interest empty** | Free tier에서 `/stock/short-interest` 미지원 | yfinance `Ticker.info` (shortRatio, shortPercentOfFloat)로 전환 |
| **Crowding not in factor_detail** | FactorCrowdingMonitor가 MultiFactorScorer에 연결 안 됨 | 생성자 주입 + Flow 점수에 20% 가중치로 통합 |
| **Fundamental Ollama 90s timeout** | VM CPU에서 qwen2.5:3b 추론 60-80s/요청 | Ollama 경로 제거, Claude / rule_based only (2-5s) |
| **Redis cached error results** | Ollama timeout 에러가 7일 TTL로 캐싱됨 | `swing:fundamental:*` Redis 키 삭제 |
| **Pipeline 버튼 즉시 풀림** | PollUntilDone이 이전 실행 completed 로그를 찾아 즉시 리턴 | `startedAt` 시간 비교 추가 + 경과 시간 표시 |
| **Watchlist sparkline 순차 로딩** | foreach await로 1개씩 순차 fetch (4개째 타임아웃) | Task.WhenAll 병렬화 (7개 동시) |
| **bb_squeeze/connors_exit JSON 직렬화** | numpy bool → JSON 직렬화 오류 | `bool()` 래핑 |
| **position_pct=14 → 1400% 배분** | Settings에서 14 입력 (소수 0.14 의도) → MRVL 121주($11,985) 매수 | API + PositionManager에 `>1.0` 자동 ÷100 검증 추가, DB값 0.14로 수정 |
| **Approve 시 Daily Entry Count 자기 자신 포함** | approve_signal() 후 status='approved'가 get_today_entry_count()에 포함 → 항상 2/2로 차단 | `status = 'executed'`만 카운트 + 사전 검증 추가 |
| **Scan Now 후 ACTIVE 탭 사라짐** | ScanSignals()에서 완료 후 activeTab="pending" 강제 전환 | 현재 탭 유지, ACTIVE 아닌 경우에만 pending으로 전환 |
| **V3.1 Telegram 중복 알림** | V3.1 엔진(port 8000)이 enabled 상태로 매일 파이프라인 실행 + Telegram 발송 | `sudo systemctl stop/disable quant-engine.service` (2026-04-15 완료) |
| **대시보드 느림 (10~40초)** | `/ticker`(캐시 없음, yfinance 10초), `/market/overview`(캐시 10분, yfinance 40초) | `/ticker` Redis 60초 캐시 추가, `/market/overview` TTL 30분으로 확대 |

---

## 15. File Structure (전체)

```
quant-v31/
├── CLAUDE.md                           # Claude Code 프로젝트 지침
├── project_status.md                   # THIS FILE (세션 연속성)
├── docker-compose.yml
├── .env                                # API 키 (OLLAMA_URL/MODEL, FINNHUB_API_KEY, TELEGRAM_*, KIS_*)
│
├── engine_v4/                          # V4 Swing Trading Engine
│   ├── api/main.py                     # FastAPI + 모든 API 라우트 + 워치리스트 분석 + ticker
│   ├── config/settings.py              # SwingSettings (Pydantic v2, .env)
│   ├── requirements.txt
│   ├── data/
│   │   ├── storage.py                  # PostgresStore + RedisCache (psycopg3)
│   │   ├── collector.py                # DataCollector(yfinance) + UniverseManager
│   │   └── extended_hours.py           # Pre/After-market 시세 (yfinance Ticker.info)
│   ├── ai/
│   │   ├── sentiment.py                # SentimentAnalyzer (Ollama / Claude / mock)
│   │   ├── data_feeds.py               # FinnhubClient (news/insider/earnings/recs/short_interest)
│   │   ├── multi_factor.py             # MultiFactorScorer (6-Factor 레짐 적응형 + Crowding + yfinance Short)
│   │   ├── lstm_predictor.py           # LSTMPredictor (LSTM 딥러닝, 70.5%)
│   │   ├── social_sentiment.py         # SocialSentimentCollector (Reddit+StockTwits)
│   │   ├── fundamental.py              # FundamentalAnalyzer (Claude / rule_based — Ollama 제거)
│   │   ├── factor_crowding.py          # FactorCrowdingMonitor (밀집도 경고, Flow에 20% 통합)
│   │   └── optimizer.py                # StrategyOptimizer (Claude + backtest)
│   ├── events/
│   │   ├── collector.py                # EventCollector (price/news/earnings/insider)
│   │   ├── processor.py                # EventProcessor (규칙 엔진)
│   │   ├── edgar.py                    # SEC EDGAR RSS
│   │   └── models.py                   # Event 데이터 모델
│   ├── strategy/swing.py               # SwingStrategy (scan_entries + dual_sort, scan_exits)
│   ├── strategy/watchlist_strategy.py  # WatchlistStrategy (5-Layer TQM) [2026-03-25]
│   ├── risk/
│   │   ├── position_manager.py         # PositionManager (validate_entry, execute_entry/exit)
│   │   └── exit_manager.py             # ExitManager (5-Layer Auto-Sell: ATR Trailing + Hard Stop + Time + RSI(2) + Regime)
│   ├── broker/kis_client.py            # KIS API (paper: SIM-* / live: KIS API)
│   ├── scheduler/jobs.py               # SwingScheduler (12 jobs + generate_snapshot)
│   ├── notify/telegram.py              # TelegramNotifier
│   └── backtest/
│       ├── runner.py                  # BacktestRunner (일반 백테스트)
│       └── watchlist_backtest.py      # WatchlistBacktester (24지표 시그널 백테스트)
│
├── engine/                             # V3.1 Legacy Engine (inactive)
│
├── dashboard/QuantDashboard/           # Blazor Server (.NET 8)
│   ├── Program.cs                      # DI + Cookie Auth + HttpClientFactory("Engine") + Register/Login endpoints
│   ├── Models/
│   │   ├── DashboardModels.cs          # V3.1 models (legacy)
│   │   └── SwingModels.cs              # V4 models + WatchlistItem + CapitalEvent
│   ├── Services/
│   │   ├── SwingService.cs             # V4 DB queries (swing_* tables) ← 주 서비스
│   │   ├── PostgresService.cs          # V3.1 DB queries (legacy)
│   │   └── AuthService.cs              # Cookie 인증 + 회원가입 + RBAC 권한 관리
│   ├── Components/
│   │   ├── App.razor                   # <script src="js/charts.js">
│   │   ├── SymbolLink.razor            # 심볼 클릭 → OnSymbolClick callback
│   │   ├── SymbolDetailModal.razor     # 심볼 상세 팝업 (z-index: 9500)
│   │   ├── SseToastPanel.razor         # SSE 실시간 알림 (InteractiveServerRenderMode)
│   │   ├── SortState.cs                # 테이블 정렬 상태
│   │   ├── PageLoadingOverlay.razor
│   │   ├── HelpTooltip.razor
│   │   ├── Layout/
│   │   │   ├── MainLayout.razor        # Dark theme + collapsible sidebar + live ticker bar
│   │   │   ├── LoginLayout.razor
│   │   │   └── NavMenu.razor           # 10 nav items + pending badge + sidebar toggle
│   │   └── Pages/
│   │       ├── Login.razor              # 로그인 (에러 분류 + Sign Up 링크)
│   │       ├── Register.razor          # 회원가입 (username, email, password)
│   │       ├── Home.razor              # Dashboard
│   │       ├── Pipeline.razor          # 5단계 파이프라인 + 실행 + 팝업
│   │       ├── Signals.razor           # 시그널 관리 (Approve/Reject/Revert + AI Score)
│   │       ├── Performance.razor       # Equity/Drawdown 차트 + Update Snapshot
│   │       ├── Positions.razor         # 포지션 목록 (TRAIL/PARTIAL 배지)
│   │       ├── Backtest.razor          # 백테스트 실행/결과 + AI Optimize
│   │       ├── Events.razor            # 이벤트 히스토리
│   │       ├── Watchlist.razor         # 보유종목 등록 + 기술분석 + Sector Heatmap (드릴다운)
│   │       ├── Account.razor            # 계정 정보 + 비밀번호 변경
│   │       ├── Settings.razor          # 설정 + Capital + User Management + Role Permissions (3탭)
│   │       └── Help.razor              # 전체 가이드 (한글, 12개 섹션, Auto-Sell+Connors RSI(2)+용어사전)
│   └── wwwroot/
│       ├── app.css                     # Dark navy theme + sidebar collapse + watchlist CSS
│       └── js/charts.js               # Chart.js wrapper (line, trade markers, zoom)
│
├── scripts/
│   ├── init_swing_db.sql               # V4 swing_* 기본 테이블
│   ├── migrate_llm_signals.sql         # Phase A: llm_score, llm_analysis 컬럼
│   ├── migrate_exit_strategy.sql       # Phase B: trailing/partial 컬럼
│   ├── migrate_auto_exit.sql          # Phase B+: atr_14, entry_atr, hard_stop, auto_exit + 8 config keys
│   ├── migrate_multi_factor.sql        # Phase C: composite_score, factor_scores 컬럼
│   ├── migrate_events.sql              # Phase E: swing_events 테이블
│   ├── migrate_pipeline_log.sql
│   ├── migrate_auth.sql
│   ├── migrate_user_settings.sql
│   ├── migrate_factor_enhancement.sql  # Phase C: 5-Factor + Crowding + Short Interest
│   ├── migrate_tier3.sql              # Tier 3: ml_predictions, ml_models, social_sentiment
│   ├── migrate_user_mgmt.sql          # User management: email, role, is_approved + user_role_permissions
│   └── init_db.sql                     # V3.1 레거시
│
├── systemd/
│   ├── quant-engine-v4.service         # Engine V4 (port 8001)
│   ├── quant-dashboard.service         # Dashboard (port 5000)
│   └── quant-engine.service            # Engine V3.1 (port 8000, inactive)
│
└── docs/                               # V3.1 설계 문서
    ├── DevPlan.jsx
    ├── Strategy.jsx
    └── Phase3Guide.jsx
```

---

## 16. CSS / z-index Layers

| Component | z-index | Description |
|-----------|---------|-------------|
| Pipeline popup | pp-overlay: 9000 | 파이프라인 실행 팝업 |
| SymbolDetailModal | sdm-overlay: 9500 | 심볼 상세 팝업 (위에 표시) |
| Toast notifications | toast-container: auto | SSE 실시간 알림 |

---

## 17. API 키 설정 (.env)

| 키 | 용도 | 상태 |
|----|------|------|
| `ANTHROPIC_KEY` | Claude API (감성분석, 최적화) | 비활성 (Ollama 로컬 LLM 사용) |
| `OLLAMA_URL` | Ollama 로컬 LLM 서버 | `http://localhost:11434` |
| `OLLAMA_MODEL` | Ollama 모델명 | `qwen2.5:3b` |
| `FINNHUB_API_KEY` | 뉴스/실적/내부자/가격 | 설정됨 |
| `KIS_APP_KEY` / `KIS_APP_SECRET` | KIS 증권 매매 | 설정됨 (paper 모드) |
| `KIS_ACCOUNT_NO` | KIS 계좌번호 | 설정됨 |
| `KIS_IS_PAPER` | 시뮬레이션 모드 | true |
| `TELEGRAM_BOT_TOKEN` | Telegram 알림 전송 | 설정됨 |
| `TELEGRAM_CHAT_ID` | Telegram 채팅 ID | 설정됨 |
| `REDDIT_CLIENT_ID` | Reddit API (소셜 감성) [Tier 3] | 미설정 (없으면 Reddit 비활성) |
| `REDDIT_CLIENT_SECRET` | Reddit API Secret [Tier 3] | 미설정 |

---

## 18. Operations Guide (운영 가이드)

### 일일 운영 흐름
```
1. Pipeline 페이지 접속 (자동: 매일 07:00 KST)
   ├─ Step 1: Refresh Universe (주 1회, 토요일 자동)
   ├─ Step 2: Collect Data (매일 자동, 수동도 가능, ~90초 소요)
   ├─ Step 3: Scan Signals → Multi-Factor 스코어링 → pending 시그널 생성
   ├─ Step 4: Signals 페이지 → AI Score + 팩터 점수 참고 → Approve/Reject
   └─ Step 5: Performance 페이지 → 포트폴리오 추적

2. 5-Layer Auto-Sell 청산 체크 (자동, 3회/일)
   ├─ 23:30 KST (09:30 ET) — 장 시작
   ├─ 01:00 KST (11:00 ET) — 장중
   └─ 03:00 KST (13:00 ET) — 장중
   ※ L1:ATR Trailing + L2:Hard Stop + L3:Time(15d) + L4:RSI(2)>90 + L5:Regime 자동 실행
   ※ 매도 승인 불필요 — 자동 실행 후 Telegram 알림

3. 워치리스트 — Connors RSI(2) (수동 + 자동)
   ├─ Watchlist 페이지 → 대형 기술주 등록
   ├─ "Analyze All" 클릭 → Connors RSI(2) 평균회귀 분석
   ├─ SMA200 필터 + OPEX 감쇠 + QQQ 상대강도 + BB Squeeze
   ├─ BUY/SELL/NEUTRAL 판정 + Connors Key Metrics 표시
   └─ 고신뢰 추천 시 Telegram 자동 알림

4. 시간외 모니터링 (자동)
   ├─ 프리마켓 갭 체크 (22:00 KST / 08:00 ET) — 포지션/시그널/워치리스트
   └─ 애프터마켓 경보 (07:30 KST / 17:30 ET) — 급락/급등 Telegram 알림

5. Tier 3 AI (자동)
   ├─ 소셜 감성 수집 (06:50 KST, 매일) — Reddit + StockTwits
   ├─ LSTM 재학습 (토 09:00) — 최신 데이터로 딥러닝 모델 업데이트
   └─ 이중 정렬 (파이프라인 내 자동) — 모멘텀+밸류 결합 필터

6. 자금 관리 (수동)
   ├─ Settings 페이지 → Capital Management
   └─ deposit/withdraw 기록 → 스냅샷에 자동 반영 (TWR)
```

### API 명령어 모음
```bash
# 파이프라인 실행
curl -X POST http://localhost:8001/collect           # 데이터 수집 (~90초)
curl -X POST http://localhost:8001/scan              # 시그널 스캔
curl -X POST http://localhost:8001/pipeline/run      # 전체 파이프라인
curl -X POST http://localhost:8001/universe/refresh   # 유니버스 갱신

# 시그널 관리
curl http://localhost:8001/signals?status=pending
curl -X POST http://localhost:8001/signals/1/approve
curl -X POST http://localhost:8001/signals/1/reject
curl -X POST http://localhost:8001/signals/1/analyze     # LLM 분석
curl -X POST http://localhost:8001/signals/1/score       # Multi-Factor

# 포트폴리오
curl -X POST http://localhost:8001/snapshot/generate     # 스냅샷 수동 생성
curl http://localhost:8001/portfolio                      # 최신 스냅샷
curl http://localhost:8001/positions                      # 오픈 포지션
curl http://localhost:8001/ticker                         # 포지션 현재가

# 자금 관리
curl -X POST http://localhost:8001/capital/event \
  -H "Content-Type: application/json" \
  -d '{"event_type":"deposit","amount":500,"note":"추가 투자"}'
curl http://localhost:8001/capital/events

# 워치리스트
curl -X POST http://localhost:8001/watchlist \
  -H "Content-Type: application/json" \
  -d '{"symbol":"AAPL","company_name":"Apple","avg_cost":180,"qty":10}'
curl http://localhost:8001/watchlist
curl -X POST http://localhost:8001/watchlist/analyze
curl http://localhost:8001/watchlist/analysis

# 소셜 감성 [Tier 3]
curl http://localhost:8001/social/AAPL
curl -X POST http://localhost:8001/social/collect

# LSTM 예측 [Tier 3]
curl http://localhost:8001/lstm/info
curl http://localhost:8001/lstm/predict/AAPL
curl -X POST http://localhost:8001/lstm/train
curl http://localhost:8001/lstm/train-status
curl -X POST http://localhost:8001/lstm/predict-all

# 시간외 거래
curl http://localhost:8001/extended-hours
curl -X POST http://localhost:8001/extended-hours/check \
  -H "Content-Type: application/json" \
  -d '{"symbols":["AAPL","MSFT"]}'

# 이벤트
curl -X POST http://localhost:8001/events/scan
curl http://localhost:8001/events?limit=20
curl -X POST http://localhost:8001/events/edgar-scan

# 최적화
curl -X POST http://localhost:8001/optimize/run \
  -H "Content-Type: application/json" \
  -d '{"target_metric":"sharpe","days":180}'
curl http://localhost:8001/optimize/results

# 설정
curl http://localhost:8001/config
curl -X PUT http://localhost:8001/config/initial_capital \
  -H "Content-Type: application/json" -d '{"value":"5000"}'
curl -X POST http://localhost:8001/config/trading-mode \
  -H "Content-Type: application/json" -d '{"mode":"live"}'

# 상태 확인
curl http://localhost:8001/health
curl http://localhost:8001/scheduler
```

---

## 19. Live 전환 계획 (2026-04-21 주간 예정)

### 준비 기간: 2026-04-11 ~ 2026-04-20 (Paper 검증)
- Paper 모드 10건 이상 매매 완료 후 성과 검증
- Win Rate, MDD, 5-Layer Auto-Sell 동작 확인

### KIS 계좌 준비
- [ ] 해외주식 거래 약정 확인 (한투 HTS/MTS)
- [ ] 원화 입금 + USD 환전
- [ ] KIS 잔고 ≥ initial_capital 확인

### 전환 절차
1. Paper 포지션 전체 청산/정리
2. Settings에서 `initial_capital` → 실제 USD 잔고로 변경
3. `position_pct`, `max_positions` 자금 규모에 맞게 조정
4. 대시보드 Settings → "Switch to Live" 클릭 (confirm 필요)
5. `/broker/status` → `connected: true` 확인
6. `/broker/balance` → 실제 잔고 표시 확인

### KIS 연결 구조
- **Paper 모드**: SIM 시뮬레이션 (KIS 미연결, DB에만 기록)
- **Live 모드**: 실전 KIS API 연결 (python-kis 2.1.6)
  - 매수/매도 → KIS 실주문 발행
  - Auto-Sell → KIS 자동 매도 주문
  - `/broker/sync` → DB↔KIS 보유종목 불일치 확인

### Live 운영 주의
- 미국 장 운영: 한국시간 23:30~06:00 (서머타임 22:30~05:00)
- KIS 주문 실패 시 DB 포지션은 유지 → `/broker/sync`로 확인
- 언제든 paper 모드로 복귀 가능 (KIS 포지션은 유지됨)

---

## 20. V3.1 Legacy System (참고용)

V3.1은 V4 이전의 레짐 적응형 시스템. 현재 비활성이지만 코드와 DB 테이블 존재.

### V3.1 핵심 구성
- HMM 3-State 레짐 감지 (Bull/Sideways/Bear)
- Kill Switch 4-Level (NORMAL→WARNING→DEFENSIVE→EMERGENCY)
- 5개 전략: LowVol Quality, Vol Momentum, Pairs Trading, Vol Targeting, Sentiment
- 8-step Daily Pipeline Orchestrator
- **최종 결과**: STOP (WF Sharpe=0.59, Stress FPR=50% — GO 기준 미달)
- **V3.1 → V4 전환 이유**: 백테스트 결과가 GO 기준 미달 → 모멘텀 스윙 트레이딩으로 전환

---

## 21. Phase 4 — Analysis System + Strategy A/B (2026-05-14 추가)

### 4.1 사용자 목표 + 검증 합의
- **목표**: 연 18% 수익률 (현재 3개월 paper 운영 결과 +2.4%로 SPY 수준 → 시스템 가치 재검토 후 결정)
- **합의**: 1개월간 paper 모드로 Strategy A→B 단계 검증, 30거래 누적 후 stop 조건 평가
- **stop 조건** (30거래 후): SPY 동기간 +3%p 상회 **또는** SQN ≥ 1.6 — 둘 다 미달 시 시스템 폐기 합의
- **사용자 commitment**: "18% 도달까지 무슨 일이 있어도 함께 구축"

### 4.2 진단 시스템 (Phase 2A–E, 학술 기반)

#### 새 분석 모듈 (`engine_v4/analysis/`)
| 모듈 | 기능 | 근거 |
|------|------|------|
| `period_summary.py` | 기간별 KPI + 청산 레이어 + 보유일수 + Score bin | (기본) |
| `mfe_mae.py` | MFE/MAE + Capture Ratio + Tharp R-multiple | Sweeney 1997, Tharp |
| `event_study.py` | 252일 β 회귀 + AR/CAR + α/β 추정 | Fama-Fisher-Jensen-Roll 1969 |
| `news_attribution.py` | relevance 점수 + 8-K item parser + Tetlock sentiment | Tetlock 2007/2008, Da 등 |
| `counterfactual.py` | 5-Layer 대안 청산 + Calibration plot | (연구 권고) |
| `daily_report.py` | 일일 사후분석 오케스트레이터 + Brinson 분해 + Telegram | BHB 1986 |
| `llm_narrative.py` | Claude Haiku 거래·일일 narrative | MarketSenseAI 2025 |

#### DB 신규 테이블 (3개)
- `swing_trade_postmortem` — 거래당 MFE/MAE/β/AR/Counterfactual/Narrative (PRIMARY KEY position_id)
- `swing_news_attribution` — 뉴스×포지션 귀인 (relevance, sentiment, 8-K item, AR_0/AR_1/CAR_2d)
- `swing_daily_report` — 일일 리포트 (Rolling 30 IC/AUC/SQN, Brinson, top news, LLM narrative)

#### 신규 API (15개)
```
GET  /analysis?from=&to=&mode=                    # 기간별 분석
GET  /analysis/postmortems?limit=                  # 거래 사후분석 리스트
GET  /analysis/postmortem/{position_id}            # 단일 거래
POST /analysis/postmortem/backfill                 # MFE/MAE 백필
GET  /analysis/event-study/{position_id}           # 이벤트 스터디 (β, AR, CAR)
POST /analysis/event-study/backfill                # 백필
GET  /analysis/news/{position_id}                  # 포지션 뉴스 + 귀인
POST /analysis/news/backfill                       # 백필
GET  /analysis/counterfactual                      # 레이어별 대안 청산 집계
GET  /analysis/counterfactual/{position_id}        # 단일 시뮬
POST /analysis/counterfactual/backfill             # 백필
GET  /analysis/calibration                         # Score 구간별 실제 승률
GET  /analysis/daily                               # 일일 리포트 리스트
GET  /analysis/daily/{report_date}                 # 특정일
POST /analysis/daily/run                           # 수동 실행
```

#### 대시보드 — `/analysis` 페이지 (탭 4개)
- **Period** — 기간별 KPI / 청산 레이어 / 보유일수 / Composite Score 구간
- **Daily Reports** — 캘린더형 일일 리포트 + 상세
- **Post-Mortem** — 거래별 MFE/MAE/Capture/R/β/Narrative 테이블
- **Signal Quality** — Counterfactual exit aggregate + Calibration plot

#### 진단 결과 (실측, 21건 청산 거래)
| 지표 | 값 | 해석 |
|------|----|----|
| Rolling 30 Win Rate | 90.5% | 표면적으로 높음 |
| Expectancy | +1.22% | 양수지만 작음 |
| SQN | 0.81 | Tharp 척도 "below average" (1.6+ = good) |
| **IC (score→PnL)** | **-0.22** | composite_score 음의 상관 → 시스템 재검토 필요 |
| **AUC** | **0.35** | < 0.5 → 점수가 패자를 더 잘 예측 (역설) |

#### Counterfactual 결과 (결정적 진단)
| 가상 청산 레이어 | 발동률 | 평균 P&L | vs 실제 |
|-----------------|--------|----------|---------|
| HOLD_PEAK | 100% | +23.92% | **+22.70%p** |
| TAKE_PROFIT (+20%) | 33.3% | +20.00% | +16.59%p |
| HOLD_TO_END | 100% | +16.11% | +14.89%p |
| L1 ATR Trailing | 61.9% | +15.96% | **+14.05%p** |
| L3 Time Stop (15d) | 100% | +13.21% | +11.99%p |
| L2 Hard Stop | 61.9% | -5.18% | -5.84%p |

**핵심 결론**: RSI(2)>90 조기청산 제거 + L1 ATR Trailing 위임 시 거래당 평균 **+14%p 수익 개선** 가능.

### 4.3 Strategy A — Latency 제거 (활성, 2026-05-14)

| 변경 | 내용 |
|------|------|
| `auto_approve_enabled` | true |
| `auto_approve_score_min` | 60 |
| `auto_approve_macro_min` | 30 |
| `rsi2_exit_threshold` | **999** (사실상 비활성화) |
| 신규 모듈 | `engine_v4/strategy/auto_approve.py` |
| 신규 잡 | `auto_approve` 22:00 KST (월~금) |

흐름: pending 시그널 → composite_score + macro 게이트 → KIS 주문 → 즉시 체결 (latency 17h → 30min)

### 4.4 Strategy B — LLM Gate (인프라 완료, 다음 주 활성화)

| 변경 | 내용 |
|------|------|
| 신규 모듈 | `engine_v4/strategy/llm_gate.py` — Claude → Ollama → fallback 체인 |
| 신규 잡 | `auto_approve_mid` 01:30 KST (화~토), `auto_approve_close` 04:30 KST (화~토) |
| `llm_gate_enabled` | **false** (활성화: `UPDATE swing_config SET value='true'`) |
| `llm_gate_prefer_ollama` | true (Max 구독자라 Ollama 우선, 비용 0) |
| `llm_gate_ollama_model` | qwen2.5:1.5b |
| `llm_gate_min_confidence` | 0.55 |

#### Ollama 최적화 (Max 사용자 = ANTHROPIC_KEY 결제 회피)
| 항목 | 설정 | 효과 |
|------|------|------|
| 모델 | qwen2.5:1.5b | 게이트 결정엔 충분, 빠름 |
| keep_alive | 30m | 모델 메모리 상주 → reload 회피 |
| format | json | 구조화 출력, regex 파싱 불필요 |
| temperature | 0.1 | 결정 일관성 |
| num_ctx | 2048 | 컨텍스트 절약 (~400 토큰 프롬프트) |
| num_predict | 200 | 짧은 JSON만 출력 |
| num_thread | 4 | CPU 전체 코어 |
| Redis 캐시 | 1h TTL | 동일 컨텍스트 재평가 skip |
| 병렬 처리 | ThreadPoolExecutor 4 workers | 여러 시그널 동시 평가 |

#### 실측 성능 (qwen2.5:1.5b on 4 CPU cores)
- Warm-up (모델 로드): 3.5s (1회)
- 첫 추론: 7s
- Warm 후 추론: **2.5s**
- 5 시그널 병렬 평가: ~5초 예상

### 4.5 KIS 연동 정책 (2026-05-14)

- `trading_mode` 토글(paper/live)만으로 충분 — 추가 게이트 불필요
- Paper + KIS 미연결 시 → `_simulate_order()` 자동 호출 → 외부 API 없음 = 자연스러운 internal-only
- 사용자가 의지에 따라 Live 토글하면 즉시 KIS 연결 (자유 결정 보장)
- (이력) `kis_orders_enabled` 게이트는 한때 추가되었다가 Live 전환 시 의도치 않은 차단 위험으로 제거됨

### 4.6 스케줄러 17개 잡 전체 (2026-05-14 기준)
| Job | 시간 (KST) | 기능 |
|-----|-----------|------|
| daily_pipeline | 월~토 07:00 | Collect + Scan + Notify |
| macro_collect | 월~토 06:45 | 매크로 수집 |
| social_collect | 월~토 06:50 | Reddit + StockTwits |
| watchlist_analysis | 월~토 07:40 | 워치리스트 분석 |
| post_market_analysis | 화~토 06:05 | **일일 사후분석 + Telegram** |
| afterhours_check | 화~토 07:30 | 애프터마켓 체크 |
| auto_approve | 월~금 22:00 | **Strategy A/B — pre-open** |
| premarket_check | 월~금 22:00 | 프리마켓 갭 |
| exit_check_1 | 월~금 23:30 | US 장 시작 청산 |
| auto_approve_mid | 화~토 01:30 | **Strategy B — mid-session** |
| exit_check_2 | 화~토 01:00 | 장중 청산 |
| exit_check_3 | 화~토 03:00 | 장중 청산 |
| auto_approve_close | 화~토 04:30 | **Strategy B — pre-close** |
| exit_check_close | 화~토 05:30 | 장 마감 청산 |
| expire_signals | 매일 06:00 | 만료 시그널 정리 |
| lstm_retrain | 토 09:00 | LSTM 주간 재학습 |
| refresh_universe | 일 10:00 | 유니버스 갱신 |

### 4.7 신규 설정 (swing_config)
```
auto_approve_enabled = true
auto_approve_score_min = 60
auto_approve_macro_min = 30
rsi2_exit_threshold = 999          # 비활성화
llm_gate_enabled = false           # 다음 주 활성화
llm_gate_prefer_ollama = true      # Max 구독자라 Ollama 우선
llm_gate_ollama_model = qwen2.5:1.5b
llm_gate_min_confidence = 0.55
llm_gate_model = claude-haiku-4-5-20251001  # ANTHROPIC_KEY 추가 시 사용
```

### 4.8 다음 주 Strategy B 활성화 (코드 변경 없이 1줄)
```bash
docker exec quant-postgres psql -U quant -d quantdb \
  -c "UPDATE swing_config SET value='true' WHERE key='llm_gate_enabled';"
```

---

## 22. Phase 3 — 자율 진화 하네스 (Autonomous Evolution Harness, 2026-05-22)

### 절대 원칙
- **사용자가 "그만"이라고 명시하기 전까지 절대 포기/멈춤을 권유하지 않는다**
- 정적 시스템은 죽는다 — 자율 진화 필수
- 18% 도달까지 함께 구축

### 8개 구성요소 (4주 빌드)

| Phase | 컴포넌트 | 주차 | 파일 |
|-------|---------|------|------|
| 3A | 지식 베이스 (`swing_knowledge`) | 1 | DB + API |
| 3H | 시드 데이터 (Dalio/Faber/O'Neil/Wyckoff 등) | 1 | seed |
| 3B | 주간 자율 리서치 에이전트 | 1 | `harness/researcher.py` |
| 3G | 기술 지표 확장 (MACD/BB/ADX/Ichimoku) | 2 | `engine_v4/indicators/` |
| 3F | 매크로 적응 스위치 | 2 | `harness/regime_switcher.py` |
| 3C | 전략 변이 생성기 | 3 | `harness/variant_generator.py` |
| 3D | 백테스트 자동 검증기 | 3 | `harness/auto_backtest.py` |
| 3E | 안전한 자동 배포 + 롤백 | 4 | `harness/auto_deploy.py` |
| — | 통합 대시보드 `/harness` 탭 | 4 | Razor |

### 신규 DB 테이블
- `swing_knowledge` — 외부 정보 영구 저장 + LLM 추출 전략 가설
- `swing_strategy_variants` — LLM 생성 변이 (pending/validated/rejected/deployed/rolled_back)
- `swing_harness_log` — 자율 동작 audit trail

### 신규 스케줄러 잡 (3개)
- `weekly_research` 일요일 10:00 KST — 외부 리서치 → 지식 베이스
- `monthly_variant_gen` 매월 1일 11:00 KST — 변이 생성 → 백테스트
- `regime_switch_check` 매시 정각 — 매크로 변화 감지 → 자동 전환

### 안전장치
- 자기 코드 수정 ❌ 금지 (config + DB만)
- Live 자동 변경 ❌ 금지 (사용자 명시 승인만)
- 모든 변이는 90/180/365일 다중 백테스트 통과 필수
- 30거래 모니터링 + 자동 롤백 (5연속 손실 OR SQN -0.5)
- LLM 환각 방지: 통과 = 백테스트 SQN +0.3 OR Sharpe +0.2 (N≥30)

### 진행 추적
- [x] **3A 지식 베이스** (Week 1) — `swing_knowledge`/`swing_strategy_variants`/`swing_harness_log` 3 테이블 + CRUD API
- [x] **3H 시드 데이터** (Week 1) — 18개 고전/현대 전략 (Faber, Jegadeesh-Titman, Antonacci, Tetlock, Da, Fama-French, Tharp, Dalio, Wyckoff, Carter, O'Neil, Weinstein, Lopez-Lira, MarketSenseAI, Barber-Odean)
- [x] **3B 리서치 에이전트** (Week 1) — `weekly_research` 잡 일요일 10:00 KST + arxiv/Reddit/Quantocracy 크롤 + Ollama 추출 + Telegram 다이제스트
- [x] **3G 기술 지표 확장** (Week 2) — `engine_v4/indicators/` 6모듈 (MACD/BB/ADX/Ichimoku/VWAP/Wyckoff VSA) + 종합 스코어 + API
- [x] **3F 매크로 적응 스위치** (Week 2) — `regime_switcher.py` + 매시 정각 체크 잡 + 3개 regime preset (RISK_ON/NEUTRAL/RISK_OFF) + Telegram 전환 알림
- [x] **3C 변이 생성기** (Week 3) — `variant_generator.py` + Claude/Ollama 3-5개 변이 자동 제안 + 매월 1일 실행
- [x] **3D 백테스트 검증기** (Week 3) — `auto_backtest.py` + 90/180/365일 다중 기간 + SQN/Sharpe 통과 조건 + 일관성 체크
- [x] **3E 자동 배포** (Week 4) — `auto_deploy.py` + paper 자동 / live 수동 + 5연속손실/SQN 0.5 drop 자동 롤백 + 매시 15분 체크
- [x] **통합 대시보드** (Week 4) — `/harness` 4탭 (Regime/Variants/Knowledge/Audit Log) + 수동 트리거 버튼

### Week 1 결과 (실측)
- 시드 18개 + 첫 리서치 21개 신규 발견 = 39개 지식 항목 누적
- 평균 applicability 점수: 73-80
- 리서치 1회 실행: 17분 (Ollama qwen2.5:3b 추출)

### Week 2 결과
- **확장 지표 6개**: MACD(12,26,9), BB(20,2), ADX(14), Ichimoku Cloud, VWAP(20), Wyckoff VSA
- **종합 스코어**: 0-100 점수 + breakdown (MACD/ADX/Ichimoku/BB/VWAP/Wyckoff 가중)
- **Regime 자동 전환**: RISK_ON(>70)/NEUTRAL(30-70)/RISK_OFF(<30) preset 자동 적용
- 스케줄러 잡 19개 (regime_switch_check 매시 + weekly_research 일요일)
- Live 모드는 자동 전환 금지 (안전장치)
- API: `/indicators/{sym}`, `/indicators/{sym}/score`, `/harness/regime{,/check,/history}`

### Week 3 결과
- **Variant Generator**: TUNABLE_PARAMS 19개 안전 범위 + Claude/Ollama 3-5개 변이 자동 제안
- **자동 백테스트 검증**: 90/180/365일 다중 기간 + 일관성 체크 + SQN/Sharpe delta 통과 조건
- 첫 변이 #1 (position_pct=0.02) → 거래 0건 → **자동 reject** (안전장치 작동 확인)
- 매월 1일 11:00 KST `monthly_variant_gen` 잡 (생성 + 백테스트 일괄)

### Week 4 결과
- **Safe Auto-Deployment**: 최고 점수 validated 변이 자동 배포 + baseline snapshot 보존
- **Auto-Rollback**: 5연속 손실 OR SQN drop 0.5 → 자동 baseline 복원
- 매시 15분 `rollback_check` 잡 + Live 자동 변경 금지
- **통합 대시보드 `/harness`** (4탭):
  - 🌐 Regime — 현재 매크로 + preset + force check
  - 🧬 Variants — 변이 목록 + 생성/백테스트/배포/롤백 버튼
  - 📚 Knowledge — 검색 가능 지식 베이스 (39+ 항목 누적)
  - 📜 Audit Log — 자율 동작 전체 감사

---

## 22.X Phase 3 완성 종합 요약 (4주 계획 → 1세션 완성)

### 자율 진화 사이클 (사용자 개입 0)
```
일요일 10:00 KST    → 외부 리서치 (arxiv/SSRN/Reddit/Quantocracy) → Ollama 요약 → 지식 누적
매시 정각         → regime 변화 감지 → preset 자동 적용 (paper)
매시 15분         → 활성 변이 모니터링 → 자동 롤백 조건 체크
매월 1일 11:00 KST  → 변이 5개 생성 → 90/180/365d 백테스트 → 통과만 validated
일일 06:05 KST     → 사후분석 → IC/SQN/Counterfactual → 다음 변이 생성에 반영
```

### 21개 스케줄러 잡 (Phase 3 추가분)
| Job | 시간 | Phase |
|-----|------|-------|
| weekly_research | 일 10:00 | 3B |
| regime_switch_check | 매시 정각 | 3F |
| monthly_variant_gen | 매월 1일 11:00 | 3C/3D |
| rollback_check | 매시 15분 | 3E |

### 신규 파일 (Phase 3 전체)
```
engine_v4/harness/
├── __init__.py
├── knowledge.py              # CRUD for swing_knowledge + log_action
├── seed_data.py              # 18개 학술/실무 시드 (Faber, Jegadeesh, Fama, Dalio, ...)
├── researcher.py             # 주간 자율 리서치 (arxiv/Reddit/Quantocracy)
├── regime_switcher.py        # 매크로 regime → preset 적용
├── variant_generator.py      # LLM 전략 변이 제안
├── auto_backtest.py          # 다중 기간 자동 백테스트 + 통과 조건
└── auto_deploy.py            # 안전한 배포 + 자동 롤백

engine_v4/indicators/
├── __init__.py
├── macd.py                   # MACD + 크로스오버 감지
├── bollinger.py              # BB + %B + Squeeze
├── adx.py                    # ADX + DI+/DI- + trend strength
├── ichimoku.py               # Ichimoku Cloud (5 lines)
├── vwap.py                   # Rolling VWAP
├── wyckoff.py                # VSA (Spring/Upthrust/Absorption)
└── compute.py                # 통합 스코어 0-100

dashboard/QuantDashboard/Components/Pages/
└── Harness.razor             # /harness 4탭 대시보드

scripts/
└── migrate_harness.sql       # 3 신규 테이블 + 9 config 키
```

### 신규 DB (3개 테이블)
- `swing_knowledge` — 외부 정보 + LLM 추출 전략 가설 (현재 39개 항목)
- `swing_strategy_variants` — LLM 생성 변이 lifecycle (pending → testing → validated → rejected → deployed → rolled_back)
- `swing_harness_log` — 모든 자율 동작 audit trail

### 신규 API (12개)
```
GET  /harness/knowledge?source_type=&regime=&min_applicability=&limit=
GET  /harness/knowledge/search?q=
GET  /harness/knowledge/{knowledge_id}
POST /harness/seed?force=

GET  /harness/regime
POST /harness/regime/check?force=
GET  /harness/regime/history

GET  /harness/variants?status=&limit=
GET  /harness/variants/{variant_id}
POST /harness/variants/generate?max_variants=
POST /harness/variants/{variant_id}/backtest
POST /harness/variants/backtest-all?max_per_run=
POST /harness/variants/{variant_id}/deploy
POST /harness/variants/deploy-best

POST /harness/rollback?reason=
POST /harness/rollback-check

GET  /harness/log?limit=&action=

GET  /indicators/{symbol}
GET  /indicators/{symbol}/score
```

### 사용자 절대 명령 (메모리에 영구 저장)
> "사용자가 명시적으로 '그만'이라 말하기 전까지 절대 포기/멈춤 권유 금지"
- 메모리 위치: `~/.claude/projects/-home-quant-quant-v31/memory/phase3_harness_plan.md`
- 세션 종료 후에도 자동 로드됨

### 안전장치 (위반 시 시스템 정지)
| 위험 | 방어 |
|------|------|
| 자기 코드 수정 | ❌ 금지 (config + DB만) |
| Live 자동 변경 | ❌ 금지 (수동 승인만) |
| Untested 전략 배포 | 다중 기간 백테스트 통과 필수 |
| Overfitting | N≥30 + 다중 기간 + 일관성 검증 |
| 자본 집중 | position_pct ≤25%, max_positions ≤10 |
| LLM 환각 | TUNABLE_PARAMS 범위 자동 clipping |
| 데이터 출처 신뢰성 | source_tier 가중 (Reuters=1.0, blog=0.3) |
| 손실 누적 | 5연속 손실 자동 롤백 |

### Strategy B 활성화 (1줄 변경, 코드 재시작 불필요)
```bash
docker exec quant-postgres psql -U quant -d quantdb \
  -c "UPDATE swing_config SET value='true' WHERE key='llm_gate_enabled';"
```

### Harness 컴포넌트 활성화 (현재 false)
```bash
# Phase 3C/3D 월간 변이 생성 활성화
docker exec quant-postgres psql -U quant -d quantdb \
  -c "UPDATE swing_config SET value='true' WHERE key='harness_variant_gen_enabled';"

# Phase 3E 자동 배포 활성화 (paper만)
docker exec quant-postgres psql -U quant -d quantdb \
  -c "UPDATE swing_config SET value='true' WHERE key='harness_auto_deploy_enabled';"

# Phase 3F regime 자동 전환 활성화
docker exec quant-postgres psql -U quant -d quantdb \
  -c "UPDATE swing_config SET value='true' WHERE key='harness_regime_switch_enabled';"
```

(현재 false로 시작 — 사용자가 시스템 가동 상태 확인 후 1개씩 활성화 권장)

---

## 22.Y 현재 운영 상태 (2026-06-03 기준)

### 시스템 헬스
- ✅ quant-engine-v4 systemd active
- ✅ quant-dashboard systemd active
- ✅ PostgreSQL + TimescaleDB + Redis 정상
- ✅ **23개 스케줄러 잡 가동** (pipeline 3회/일로 확대)
- ✅ Ollama qwen2.5:1.5b/3b 가동 (LLM gate 폴백)

### 거래 통계 (3개월 누적)
| 항목 | 값 |
|------|----|
| Open positions | **3개** (HPE, NTAP, DAL) |
| Closed positions | **28건** |
| Recent significant wins | HPE +32% (6/02), HPE +20.9% (6/01) take_profit |
| Recent losses | F -6.94%, MRVL -5.56%, XOM -3.01% (stop_loss) |
| Current regime | NEUTRAL (macro 62.8) |

### Rolling 30 거래 메트릭 (2026-06-03)
| 지표 | 값 | 추세 |
|------|----|----|
| Win Rate | 75% | 안정 |
| Expectancy | +1.85% | **+1.22% → +1.85% 개선** |
| SQN | 0.385 | **-0.418 → 0.385 큰 개선** |
| IC | -0.21 | 여전히 음수, 미세 개선 |

### 자율 진화 데이터 (지난 12일간)
| 활동 | 건수 |
|------|------|
| 지식 베이스 총 항목 | **74개** (paper 29 + seed 18 + forum 15 + blog 12) |
| 12일간 신규 지식 | **35개** 자동 수집 |
| Strategy variants 누적 | **12개** (pending 11 + rejected 1) |
| Regime switches 감지 | 5회 (5/26, 5/27 ×2, 5/30, 6/02) |
| Research runs 완료 | 2회 (5/25, 5/31) |
| Variant generation 완료 | 2회 (5/25, 5/27) |

### 현재 활성 설정 (swing_config)
```
trading_mode = paper
auto_approve_enabled = true
auto_approve_score_min = 63              # 2026-06-03 60 → 63 (IC 보정)
auto_approve_score_max = 75              # 2026-06-03 신설 (crowded top 차단)
auto_approve_macro_min = 30
composite_score_min = 63                 # 2026-06-03 60 → 63
dashboard_snapshot_stale_min = 5         # 2026-06-03 신설 (Dashboard 자동 갱신 임계)
rsi2_exit_threshold = 999 (비활성)
llm_gate_enabled = true                  # 2026-06-03 false → true (Strategy B 활성)
llm_gate_prefer_ollama = true (Max 구독자라 무료)
llm_gate_ollama_model = qwen2.5:1.5b
llm_gate_min_confidence = 0.55
harness_research_enabled = true (작동 중)
harness_regime_switch_enabled = true     # 2026-06-03 false → true (재활성)
harness_variant_gen_enabled = true       # 2026-06-03 false → true (자동 변이 생성 활성)
harness_auto_deploy_enabled = true       # 2026-06-03 false → true (paper 자동 배포 활성)
current_regime = NEUTRAL
```

---

## 22.Z 2026-06-03 운영 개선 (IC 보정 + Pipeline 3회/일 + Dashboard 자동갱신)

### 배경
재부팅 후 자동 점검 결과:
- 60일 누적 IC = **-0.21** (음수, 시그널 랭킹 anti-predictive)
- composite_score 70+ bucket: -2.7% 평균 / 40% 승률 (n=5) — crowded top
- composite_score 65-70 sweet spot: +3.33% 평균 / 83% 승률 (n=6)
- 팩터별 IC: sentiment +0.20 (최상), quality **-0.28** (최악), tech -0.12, macro -0.15
- Dashboard Total Value 가 stale — Performance > Update Snapshot 수동 클릭 필요
- Pipeline 이 하루 1회 (07:00) 만 → swing 매매에 시그널 캐치 부족

### 변경 1 — Regime Switch 재활성화
```
UPDATE swing_config SET value='true' WHERE key='harness_regime_switch_enabled';
```
매시 정각 매크로 점수 기반 regime 변화 감지 + 자동 preset 적용 재개.

### 변경 2 — IC 보정 (시그널 품질 개선)
**A) REGIME_WEIGHTS 리밸런싱** (`engine_v4/ai/multi_factor.py:54`)
- sentiment +0.20 IC → 비중 ↑ (모든 regime 에서 +5~7pp)
- quality -0.28 IC → 비중 ↓ (모든 regime 에서 -5~7pp)

| Regime | 변경 전 (tech/sent/flow/qual/val/macro) | 변경 후 |
|--------|-------------------------------------|---------|
| TRENDING | 0.30/0.15/0.10/0.15/0.20/0.10 | 0.27/0.20/0.10/0.10/0.23/0.10 |
| SIDEWAYS | 0.18/0.12/0.10/0.25/0.20/0.15 | 0.15/0.20/0.10/0.18/0.22/0.15 |
| HIGH_VOL | 0.20/0.15/0.10/0.20/0.15/0.20 | 0.18/0.22/0.10/0.15/0.15/0.20 |
| MIXED | 0.25/0.18/0.10/0.17/0.18/0.12 | 0.20/0.25/0.10/0.12/0.21/0.12 |

**B) Composite Score 상한 신설** (`engine_v4/strategy/auto_approve.py:64`)
- `auto_approve_score_max = 75` — 75 초과 시 auto-approve 차단 (crowded top 방지)
- 수동 승인은 여전히 가능

**C) Composite Score 하한 상향**
- `composite_score_min`: 60 → **63**
- `auto_approve_score_min`: 60 → **63**

**D) REGIME_PRESETS 일관성** (`engine_v4/harness/regime_switcher.py:44`)
- RISK_ON: composite_score_min 55 → **58**
- NEUTRAL: composite_score_min 60 → **63**
- RISK_OFF: 70 유지

### 변경 3 — Pipeline 하루 3회 자동 실행
신규 스케줄러 잡 2개 추가 (`engine_v4/scheduler/jobs.py:_setup_jobs`):
- `daily_pipeline_preopen` — 월~금 21:30 KST (US 장 시작 1시간 전, 22:00 auto_approve 직전)
- `daily_pipeline_midsession` — 화~토 02:00 KST (US 12:00 ET 미드세션)

기존 `daily_pipeline` 07:00 KST mon-sat 유지.

### 변경 4 — Pipeline 직후 Telegram 요약 발송
`engine_v4/scheduler/jobs.py` 에 `_send_pipeline_summary()` 추가.

매 파이프라인 종료 직후 (시그널 0 개여도) 5줄 요약 발송:
```
📡 Pipeline · 21:30 KST · pre-US-open
실행: 89.4s · 유니버스 87
신규 ENTRY 2 · EXIT 0
Pending ENTRY 3 · Open positions 3
Regime: NEUTRAL
```

### 변경 5 — Dashboard Total Value 자동 갱신
**A) 신규 엔드포인트** (`engine_v4/api/main.py:1196`)
- `POST /snapshot/refresh-if-stale` — 마지막 snapshot 이 stale (>5분) 하면 자동 재생성
- 새로운 config: `dashboard_snapshot_stale_min = 5`

**B) Home.razor 자동 호출** (`dashboard/QuantDashboard/Components/Pages/Home.razor:OnInitializedAsync`)
- 페이지 진입 시 `/snapshot/refresh-if-stale` 자동 호출 (10s 타임아웃)
- 실패 시 기존 stale 값으로 폴백 (UX 보장)

→ 이제 Performance 탭 가지 않아도 Dashboard 진입만으로 최신 Total Value 자동 갱신.

### 검증 결과
- 스케줄러 jobs 21 → **23** 개 확인
- `regime_switch_check` next run: 매시 정각
- `daily_pipeline_preopen` next run: 21:30 KST mon-fri
- `daily_pipeline_midsession` next run: 02:00 KST tue-sat
- `/snapshot/refresh-if-stale` 호출: 첫 회 regenerated=true (10239s → 재생성, $1007.41), 재호출 regenerated=false (221s < 300s 임계)
- 신규 config 5개 등록 + REGIME_PRESETS 코드 변경 + REGIME_WEIGHTS 코드 변경 적용

### 예상 효과
- **IC 측정**: 1~2주 누적 후 재측정 권장 (현재 n=25 작은 표본)
- **시그널 캐치**: 하루 3회 스캔으로 swing 기회 누락 감소
- **사용자 UX**: Dashboard 진입만으로 최신 상태 확인 가능 + Telegram 요약 자동 도착
- **자율성**: regime 변화 시 자동 preset 전환 재개

### 변경 6 — 자율 진화 옵션 3가지 전부 활성화 (2026-06-03 후속)
사용자 결정으로 Strategy B + Harness 자동 변이 + 자동 배포를 일괄 활성:

| Config | 변경 | 첫 작동 시점 |
|--------|------|-------------|
| `llm_gate_enabled` | false → **true** | 오늘 22:00 auto_approve (Ollama 게이트 평가 시작) |
| `harness_variant_gen_enabled` | false → **true** | **2026-07-01 11:00 KST** (매월 1일) |
| `harness_auto_deploy_enabled` | false → **true** | variant_gen 결과 통과 시 즉시 (paper 만, live 금지) |

**안전장치 4중 방어 (코드 hardcoded)**
1. Live 자동 배포 금지 — `trading_mode=live` 면 모든 자동 배포 차단
2. SQN +0.3 / Sharpe +0.2 임계치 미통과 변이는 거부
3. 백테스트 trade 수 < 30 변이는 통계 신뢰성 부족으로 거부
4. 매시 15분 `rollback_check` — 5연패 또는 SQN 0.5 하락 시 즉시 직전 안정 버전 복귀

**예상 효과**
- Strategy B: 시그널당 30~60s Ollama 평가, false positive 추가 차단
- Variant Gen: 7/1 부터 월 1회 5~10개 변이 자동 백테스트, pending 으로 적재
- Auto Deploy: 통과 변이만 paper 적용, 사용자 개입 0 으로 자가 개선 루프 완성

### 변경 8 — Telegram 양방향 봇 (옵션 A + 옵션 B, 2026-06-04 신설)
사용자가 Telegram 채팅으로 시스템 조회 + Claude 분석 요청을 보낼 수 있도록 양방향 봇 구현.

**신규 파일**: `engine_v4/notify/telegram_bot.py` (~400줄)
- `TelegramBot` 클래스 — long-polling 기반 (getUpdates timeout=30)
- chat_id 검증 — 본인만 명령 가능
- 자동 재시도 + 백오프 (최대 60s)

**신규 DB 테이블**: `swing_analysis_queue`
- request_id, from_chat_id, from_username, request_text
- status (pending/processing/done/error), processed_at, response_text, processed_by

**main.py 통합**: lifespan 에서 `telegram_bot.start()` / `stop()` 호출.

**옵션 A — 정형 명령 9개 (즉시 응답)**
| 명령 | 내용 |
|------|------|
| `/help` | 명령 목록 |
| `/status` | 시스템 + 포트폴리오 + Rolling 30 + Regime |
| `/positions` | 오픈 포지션 + P&L |
| `/signals` | 최근 시그널 10건 |
| `/last` | 최근 파이프라인 3회 |
| `/perf [7d\|30d]` | 기간별 메트릭 |
| `/regime` | 매크로 regime 상세 |
| `/analyze SYM` | 종목 분석 |
| `/queue` | 분석 큐 상태 |

**옵션 B — 자유 텍스트 큐 적재**
- 정형 명령(/로 시작)이 아닌 모든 메시지 → `swing_analysis_queue` 적재 + 즉시 확인 메시지
- 사용자가 다음에 Claude Code 세션 열면:
  - `session_continuity.md` Step 5 가이드 따라 pending 큐 자동 확인
  - 각 항목 분석 → Telegram 회신 → status='done'

**신규 config**: `telegram_bot_enabled=true`

**보안**: 사용자 본인 chat_id 만 명령 받음, 외부인 봇 ID 알아도 무시.

### 변경 7 — Help 페이지 13번 섹션 추가
`dashboard/QuantDashboard/Components/Pages/Help.razor` 에 약 130줄 신설:
- 자율 진화 4단계 사이클 표 (리서치/변이/백테스트/배포 + 매크로/롤백)
- 활성/비활성 설정 현재 값
- Strategy B LLM Gate 비용/지연 설명
- Pipeline 3회/일 표 + Telegram 요약 안내
- Dashboard 자동 갱신 안내
- IC 보정 진단 결과 + 변경 내역
- 4중 안전장치
- 사용자 결정이 필요한 시점 (Live 전환 / 완전 종료 / 임계치 조정)

---

## 22.AA 2026-06-17/18 IC 음수 교정 4종 (신호↔청산 분리)

### 배경
6/3 IC 보정(22.Z 변경 2) 이후에도 rolling 30 거래 IC가 **-0.14**로 음수 지속.
원인 진단: 기존 IC는 `realized_pct`(실현손익) 기반 = **청산정책에 오염**된 지표.
RSI(2)>90 조기청산이 승자를 +1.7% 지점에서 잘라내면, "점수 높은 종목이 손익은 낮다"는
가짜 음의 상관이 만들어진다. 6/3의 추정 튜닝(sentiment +0.20 / quality -0.28)도
이 **거래 IC(청산 오염)** 기반이라 부호가 뒤집힌 잘못된 근거였음 → 폐기.

→ **진입 신호 품질**과 **청산 정책**을 분리 측정·교정하는 4종 패치.

### A) 정책중립 신호 IC 측정 (`engine_v4/analysis/daily_report.py`)
- 신규 `_signal_forward_ic()`: 진입점수 ↔ **forward N거래일(기본 5d) 고정기간 수익** Spearman IC.
  진입가 대비 `daily_prices` 종가로 산출 → 청산정책 비오염.
- composite + 6개 요인 각각의 IC를 `factor_ic_detail`(JSONB)에 저장.
- `swing_daily_report` 신규 컬럼 3종: `rolling_signal_ic`, `rolling_signal_ic_n`, `factor_ic_detail`.
- Telegram digest에 `IC (signal→fwd5d)` 줄 추가.
- **6/17 실측 (N=47)**: trade IC **-0.1395** → signal IC **+0.0892** (진입 신호 자체는 유효 입증).

### B) RSI(2) 승자 조기청산 방지 (`engine_v4/risk/exit_manager.py`)
- Layer 4 RSI(2) 청산을 **최소 R / 최소 수익 게이팅** 후에만 허용:
  - `entry_atr` 있으면 `(현재가-진입가)/entry_atr ≥ rsi2_exit_min_r`(기본 1.0R)
  - 없으면 `gain_pct ≥ rsi2_exit_min_gain`(기본 3%)
- → 승자가 ATR 트레일링으로 더 달리게, 손익↔점수 음의 상관 완화.

### C) 모멘텀 과열 페널티 (`engine_v4/ai/multi_factor.py`)
- 실측상 rank 상단(과열/쏠림) 종목이 **역U자**로 언더퍼폼.
- `rank > threshold(0.80)` 초과분을 `penalty(0.6)`배만 가산 → 과열 구간 감쇠.
- config gate: `momentum_overext_enabled`.

### D) 요인 가중치 재보정 (`engine_v4/ai/multi_factor.py` REGIME_WEIGHTS)
실측 factor IC 근거(quality +0.216 / sentiment +0.058 / technical -0.054 /
macro -0.042 / flow **-0.356** / value **-0.363**)로 전 regime 리밸런싱:

| Regime | 변경 전 (tech/sent/flow/qual/val/macro) | 변경 후 |
|--------|-------------------------------------|---------|
| TRENDING | 0.27/0.20/0.10/0.10/0.23/0.10 | 0.20/0.18/0.05/**0.28**/0.12/0.17 |
| SIDEWAYS | 0.15/0.20/0.10/0.18/0.22/0.15 | 0.15/0.18/0.05/**0.30**/0.12/0.20 |
| HIGH_VOL | 0.18/0.22/0.10/0.15/0.15/0.20 | 0.15/0.20/0.05/**0.25**/0.10/0.25 |
| MIXED | 0.20/0.25/0.10/0.12/0.21/0.12 | 0.18/0.20/0.05/**0.28**/0.12/0.17 |

→ quality 대폭↑, flow·value 최소화(단기 역예측), 각 regime 합 = 1.0 검증.

### 신규 config (6종, `swing_config`)
| key | 값 | category | 용도 |
|-----|----|----|------|
| `signal_ic_horizon_days` | 5 | scoring | 신호 IC forward 수익 기간(거래일) |
| `rsi2_exit_min_r` | 1.0 | exit | RSI(2) 청산 최소 R배수 |
| `rsi2_exit_min_gain` | 0.03 | exit | entry_atr 없을 때 최소 수익률 |
| `momentum_overext_enabled` | true | scoring | 모멘텀 과열 페널티 on/off |
| `momentum_overext_threshold` | 0.80 | scoring | 페널티 시작 rank |
| `momentum_overext_penalty` | 0.6 | scoring | 초과분 가산 비율(1=무감쇠) |

### 마이그레이션 / 검증
- `scripts/migrate_postmortem.sql`에 신규 컬럼 3 + config 6을 **멱등 ALTER/INSERT**로 반영
  (지금까진 DB에만 직접 추가돼 새 DB 재구성 시 누락될 상태였음). 재실행 검증 통과(exit=0).
- `py_compile` + 모듈 임포트 통과, REGIME_WEIGHTS 4개 합 모두 1.0.
- 엔진은 6/18 05:33 재시작분이 이미 새 코드로 구동 중.

### 예상 효과
- **신호 IC가 양수**임을 분리 측정으로 확인 → 진입 로직은 유지하고 청산정책만 교정.
- 1~2주 누적 후 `rolling_signal_ic` 추세 + 거래 IC 회복 여부 재측정 권장.

---

## 22.AB 2026-06-24 수익률 진단 + 집중캡/손익비 교정 (Paper 검증 대응)

### 배경 — 수익률 진단
사용자가 "수익률이 엉망"이라 지적 → 데이터 진단. 핵심 발견:
- **승률 64%인데 순손익 −$25** = 손익비 역전. 승자 평균 +4.07%(보유 2.1일) vs 패자 −5.93%(보유 5.6일).
- **단일 거래 집중 리스크**: QCOM −$20.54 1건이 전체 순손실의 81%. $1000 계좌에서 고가주($226)를
  `if qty<=0: qty=1` 강제로 1주 진입 → 단일 종목 24% 과집중 → −9% 갭이 포트 −2%.
- **익절 캡처 부재**: partial_exit(+12%) 과거 0건 발동, take_profit(+20%) 2건만, 승자 86%가 +1.7%에서 잘림.

### 수정 1 — Dashboard 전체 공백 버그 (`aefe334`)
`swing_snapshots` numeric NaN → 대시보드 `GetSnapshotHistoryAsync` GetDecimal 예외 →
`Task.WhenAll` 전체 throw → 모든 KPI 공백. 원인: snapshot 생성 시 `if cp:` 가 가격 NaN을 통과
(`bool(float('nan'))==True`). `_finite_price()` 가드 + Home.razor 쿼리별 격리 + NaN 행 정리.

### 수정 2 — 포지션 집중 리스크 캡 (`49b6e92`)
`position_manager.concentration_capped_qty` 순수 함수(라이브/백테스트 공용) — 3중 캡:
- 리스크 캡: 스톱거리×수량 ≤ 계좌×`max_risk_per_trade_pct`(1.5%)
- 명목 캡: 수량×진입가 ≤ 계좌×`max_position_pct_cap`(20%)
- 총노출 캡: 오픈 명목 합 ≤ 계좌×`max_total_exposure_pct`(90%)
1주조차 캡 초과면 진입 거부(강제 1주 폐기). 소급검증: entry>$200 3건(QCOM/MRVL/DELL) 전부 거부됐을
거래 = −$37.45 → 제거 시 −$25 → +$12 흑자 전환.

### 수정 3 — 조기청산 재활성화 + 백테스트 캡 + 스냅샷 진동 (`a7ef1ba`)
- **RSI(2) 재활성화**: `rsi2_exit_threshold` 999→90 (6/18 승자보호 게이팅 min_r=1.0/min_gain=3% 유지).
- **백테스트 리플레이에 집중 캡 반영**: 라이브와 동일 순수 함수 호출.
- **스냅샷 진동(976↔954) 글리치 수정**: 스냅샷 생성기가 둘(scheduler/jobs.py vs api/main.py)인데
  jobs.py 가 누적 수수료(~$22) 미차감 → 두 경로 번갈아 실행되며 진동. jobs.py 에 수수료 차감 추가로
  통일(api 버전이 정확했음). **정확한 누적수익률 = −4.25%(수수료 포함)**, 이전 −2.34%는 과소표시였음.

### 수정 4 — 벤치마크 복구 + 15일 검증 잡 + 손익비 교정 (`b35d462`, `4686f00`)
- **SPY/QQQ 수집 복구**: 유니버스 밖이라 2026-02-24 이후 갱신 안 됨 → 백필(2/25~6/24) +
  `BENCHMARK_SYMBOLS` 를 일일 파이프라인에 추가. 검증창 SPY −1.46%/QQQ −0.72% vs 전략 −4.4%.
- **15일 검증 재평가 잡**(`validation_recheck`, 매월 1·16일 09:00 KST, 잡 23→24개): 수정본 기준일
  (`validation_postfix_start`=2026-06-24) 이후 거래만 집계 → 거래수/승률/SQN/SPY대비 → 30거래 시
  stop 조건(SQN≥1.6 또는 SPY+3%p) 자동 판정 → Telegram.
- **브레이크이븐 스톱**(`breakeven_*`): +1R 도달 시 손절을 본전+0.2% 버퍼로 상향 → '이겼다 진 거래' 방지.
- **R배수 부분익절**(`partial_exit_r`=2.0): 고정 +12%(0건 발동) → +2R(=+2×ATR) 도달 시 절반 확정.

→ **스케일아웃 체계 완성**: +1R 본전 → +2R 절반확정 → 잔여 트레일링.

### 신규 config (요약)
| 그룹 | 키 |
|------|-----|
| 집중 캡 | `concentration_cap_enabled`, `max_position_pct_cap`(**0.25**, 2026-07-24 0.20→0.25 상향), `max_risk_per_trade_pct`(0.015), `max_total_exposure_pct`(0.90) |
| 손익비 | `breakeven_enabled`, `breakeven_trigger_r`(1.0), `breakeven_buffer_pct`(0.002), `partial_exit_r`(2.0) |
| 검증 추적 | `validation_postfix_start`(2026-06-24), `validation_sqn_target`(1.6), `validation_spy_outperform_pp`(3.0) |

### Paper 검증 현황 (2026-06-24 기준)
- 검증 시작 5/14 → 41일차(~6주). "1개월" 경과, 검증창 청산거래 12건(공식 30거래 미달).
- 검증창 성과: 승률 17%, −$49.72, SQN −0.12, 전략 −4.4% vs SPY −1.46% (두 stop 조건 모두 미달).
- 단, 손실 대부분이 이번에 수정한 결함(집중/RSI2 999/스냅샷). **수정본 기준 30거래 재누적 후 재평가** 합의.

### 운영 노트
- V4 엔진 재시작은 **SIGKILL 필요** — Telegram long-poll(`getUpdates?timeout=30`)이 SIGTERM
  graceful shutdown 무한대기. `kill -9 $(pgrep -f "uvicorn engine_v4.api.main")` 후 systemd 자동 재기동.

### 2026-06-25 후속 — V3.1 레거시 엔진 완전 비활성화
- **증상**: 매일 04:30 KST "🚨 파이프라인 오류: operands could not be broadcast together with
  shapes (3832,2) (3,)" 텔레그램 알림.
- **원인**: V3.1 `engine/risk/regime.py` HMM 레짐이 SPY 를 `daily_prices`(V4 와 **공유**)에서 읽는데,
  위 22.AB 의 V4 SPY 백필(3771→3854행)로 `_prepare_features` 취약 조건 `len(vix) > len(spy)+22` 가
  깨짐(VIX 는 정적 parquet 3772행 고정) → VIX 피처 누락 2피처 → 3피처 학습 HMM 과 broadcasting 충돌.
  SPY 백필 자체는 정상이며 V4 에서 영구 유지. 깨진 것은 deprecated V3.1 뿐.
- **조치**: `quant-engine.service`(8000) + `quant-scheduler.service` 둘 다 stop + disable(sudo).
  (2026-04-15 비활성화 기록이 있었으나 quant-scheduler 누락/재부팅으로 6/18부터 재가동 중이었음 → 두 서비스
  모두 정상 disable. 부팅 시 안 뜸.) **안전 근거**: V3.1 은 swing_* 미사용(V4 독립), gRPC 50051 활성
  대시보드 사용처 없음(8000/gRPC 참조는 전부 `_v31_backup/`).
- 활성 시스템 = `quant-engine-v4`(8001) + `quant-dashboard`(5000)뿐. 04:30 오류 알림 중단됨.

### 2026-06-25 재부팅 후속 — V3.1 부활 원인 제거 (대시보드 유닛 의존성)
- **증상**: 재부팅 후 disabled 상태의 `quant-engine`(V3.1, 8000+gRPC 50051)이 다시 `active`. `@reboot` 검증
  스크립트가 `🔴 FAIL — V3.1 재가동`을 자동 기록.
- **원인**: `quant-dashboard.service` 에 V3.1 시절 잔재인 `After=`/`Wants=quant-engine.service` 두 줄.
  enabled 인 대시보드가 부팅 시 약한 의존성으로 disabled V3.1 을 함께 기동시킴.
- **조치**: 라이브 유닛(`/etc/systemd/system/`)·저장소 사본(`systemd/quant-dashboard.service`) 양쪽에서 두 줄
  제거 → **다음 재부팅부터 영구 차단**. V3.1 은 `Restart=always` 라 `systemctl kill -s KILL` 후 `stop` 으로
  정지 고정(단순 kill 은 10초 후 부활). 커밋 `ead8870`.

## 22.AC 2026-07-01 IC 재진단 + rsi2 출구 정책 교정 (승자 과조기절단)
- **핵심 결론**: 팩터 가중치(REGIME_WEIGHTS)는 정상. 음수 IC 의 진짜 원인은 **출구 정책**이었음.
- **두 종류 IC 구분**:
  - 신호 IC(정책 중립 forward-5d, `_signal_forward_ic`) = **+0.074 (양수)**, quality +0.20 → 진입 신호·가중치 양호.
  - 거래 IC(rolling_30, realized 기반) — 청산정책 오염값. 6/24 −0.117 → **7/1 +0.103 으로 이미 양전**(최근
    rsi2 청산이 +5~8% 큰 승자였던 영향).
- **반사실 검증 (out-of-sample 실가격)**: rsi2 청산 23건이 청산 후 5일 +2.31% / **10일 +8.53% 추가 상승**
  (65%/61% 계속 상승). 실제 챙긴 +2.19% 의 약 4배를 놓침 → 승자 과조기절단 확정.
  - 청산 사유별: rsi2_overbought 24건 평균 +2.43%/1.9일(승자 조기절단) vs take_profit 2건 **+26.57%**(끝까지 보유).
- **조치 (DB config, 라이브 즉시반영·재시작불요·되돌리기 가능)**:
  - `rsi2_exit_min_r`: 1.0 → **2.0** (승자 +2R 도달 전 rsi2 청산 금지 → 트레일링으로 달리게)
  - `rsi2_exit_threshold`: 90 → **95** (극단 과매수만 발동)
  - `exit_manager.py:60,158,162` 가 `_get_config_float` 로 실시간 read. 되돌리려면 1.0 / 90 으로 UPDATE.
- **전진검증 예약**: 백테스트 엔진에 rsi2 로직 미탑재 → 사후 백테스트 불가, **전진 관찰로 검증**.
  `scripts/rsi2_exit_review_20260708.sh` + user crontab `0 9 8 7 *` → **2026-07-08 09:00 KST 1회**(변경후 청산/
  반사실/IC 를 baseline 대비 평가 → Telegram, 성공 시 cron 자기제거, 로그 `scripts/rsi2_exit_review.log`).
  재부팅 생존(cron). 커밋 `f2c1b40`.
- **부수 발견 — 스코어링 누락 = 해소됨**: 6월 ENTRY 시그널 NULL-score 9건은 전부 6/1~6/21 에 몰림, 6/22 이후 0건.
  파이프라인 실패(V3.1/SPY 충돌) 기간 부수피해로 안정화와 함께 자동복구. 코드 수정 불요, 모니터링만.
- **자동 하네스 맹점**: 7/1 월간 변이 26개 중 rsi2 변이(#19·21·24)는 전부 임계치 **낮추는(70·75·80) 잘못된 방향**,
  백테스트도 0 trades 로 rejected. 이번 출구 픽스는 자동 하네스로는 못 찾는 것 → 변이 생성기에 반사실/보유기간 신호
  반영 여지.

---

## 22.AD 2026-07 파이프라인 스코어링 누락 수정 + 진입/승인 사유 가시화 + 집중캡 상향

**① 스케줄 파이프라인 팩터 스코어링 누락 수정 (`733fc57`)**
- 증상: MRNA #154 가 무점수(composite_score NULL)로 실행됨. 원인 = 스케줄 파이프라인(`_job_daily_pipeline`)에
  스코어링 단계가 없어, 07:00 post-close 가 만든 시그널이 무점수로 방치되다가 대시보드 **수동 승인**
  (`POST /signals/{id}/approve`, 게이트 미강제)으로 실행됨. (auto_approve 는 `no_composite_score` 스킵이라 안전.)
- 수정: `jobs.py` scan 직후 `scorer.score_pending_signals()` 호출(full_pipeline main.py:1156 과 동일 패턴,
  `factor_scoring_enabled` 존중), `SwingScheduler.__init__` scorer 주입. 프로덕션 확인: CFG #160 자동 채점 71.

**② 진입 시그널 0 "왜 없는지" 가시화 (`a4e40e9`, `276d751`)**
- `scan_entries` 진입 깔때기 집계 + `_build_entry_funnel` 사유 빌더(병목 조건 자동 식별). 진입 0 시
  `/scan`·`full_pipeline`·`scheduled_pipeline` 로그 details + Telegram 요약 + 대시보드에 사유 노출.
- 대시보드: statusMsg 에 사유 append + **팝업 case 6**(깔때기 표 + 설명) 자동 표시.
- 병목은 주로 **거래량 급증**(예: 199종목 중 추세 74·브레이크아웃 39지만 거래량급증 2 → 3조건 동시 0). 조용한
  장의 정상 상태.

**③ 유니버스 카운트 정합 (`276d751`)**
- 대시보드 Universe 카운트만 `count(*)` 총계(비활성 포함, 391)라 스캔 종목수(활성)와 불일치 → `GetUniverseCountAsync`
  `WHERE is_active=true` 로 변경. 활성 유니버스 = 최신 지표 종목수 일치.

**④ 승인 실패 사유 상세화 + 집중캡 20%→25% (2026-07-24)**
- RTX(주당 $208) 를 $949 계좌에서 Approve 시 계속 400 실패 — 원인: 집중 명목 캡(`max_position_pct_cap` 0.20).
  1주=계좌 22% > 20% → `concentration_capped_qty` = 0주 → 진입 거부(강제 1주 금지). **정상 동작.**
- UX 수정: 승인 실패 시 일반 메시지 대신 **구체 사유 반환**(`main.py` approve_signal — "집중 리스크 캡 초과 —
  1주 $X 가 계좌 $Y 의 Z% 로 한도(20%) 초과"). 대시보드는 이미 400 body 표시하므로 그대로 노출됨.
- 사용자 요청으로 `max_position_pct_cap` **0.20 → 0.25** 상향(DB config, 실시간 반영). RTX 1주(22%)는 이제
  25% 캡 내라 승인 가능. ⚠️ 단일종목 집중 위험 증가(모든 포지션에 적용).

---

## 22.AE 2026-07-27 손익비 개선(①번) — 고정 TP→ATR 트레일링, 백테스트 검증 후 적용

**배경 리서치 (18% 목표 방안, 영문 웹+논문):** 승률 61.9%는 우수한데 평균수익 +0.51%로 낮음 → **손익비가
근본 병목**. 근거: Time Series Momentum(Moskowitz-Ooi-Pedersen 2012, Sharpe 1.28), A Century of Evidence
on Trend-Following(Hurst-Ooi-Pedersen 2017), Risk-Managed Momentum(Barroso&Santa-Clara 2015 — 변동성
타깃팅으로 Sharpe≈2배). "승자를 일찍 자르는 것이 가장 파괴적" + "1:3 손익비면 승률 25%로 손익분기". 18%는
현실적 범위(스윙 10-40%).

**백테스트 A/B 검증 (2022-2025, 활성 유니버스 200종목, 동일 진입조건, `scripts/backtest_payoff_ab.py`):**
| 시나리오 | 총수익 | Sharpe | 손익비 | 승률 | MDD |
|---|---|---|---|---|---|
| A 고정TP+10% | +135.5% | 1.24 | 2.00 | 43% | −20.8% |
| **A2 고정TP+20%(당시 라이브)** | **+84.0%** | **0.92** | 2.51 | 38% | −18.8% |
| B ATR트레일링만 | +135.4% | 1.17 | 2.66 | 41% | −20.9% |
| **C 트레일링+부분익절(채택)** | +103.7% | 1.20 | 2.57 | 54% | −18.7% |
- **당시 라이브(A2)가 최악** — 리서치 진단(고정TP가 승자 자름)을 데이터로 확증. 사용자가 위험조정 최고 **C안** 선택.

**백테스트 엔진 개선 (`engine_v4/backtest/runner.py`):** 기존엔 고정 stop/take_profit/trend_break 만 있어
트레일링·부분익절 검증 불가 → `BacktestParams`에 `use_atr_trailing`(기본 off=기존동작 보존)/`atr_trailing_mult`
/`atr_activation_r`/`partial_exit_r`/`partial_exit_pct` + ATR(Wilder) 지표 + `_simulate` 청산 분기 +
`BacktestResult.payoff_ratio/avg_win_pct/avg_loss_pct` 추가.

**라이브 적용 (DB config, 실시간 반영):** 라이브 exit_manager 는 이미 C안과 동일한 트레일링(activation 1R,
2.5×)+부분익절(2R, 50%) 보유. 유일한 차이 = 고정 `take_profit_pct` 가 트레일링보다 먼저 +20%에서 승자를
자름 → **`take_profit_pct` 0.20→0.50 상향(사실상 비활성화, 트레일링 지배)**. 이 한 값만 바꿔 C안 완성.
되돌리려면 0.20. rsi2(백테스트 불가)와 달리 이건 **백테스트 검증됨**. 전진 관찰: 평균 승 수익%↑, 손익비↑,
청산 사유 take_profit↓·atr_trailing/partial_exit↑.

---

## 22.AF 2026-07-27 18% 방안 ②·③ 백테스트 — ②변동성타깃팅 기각, ③절대모멘텀 적용

**②번 변동성 타깃팅 (Barroso&Santa-Clara inverse-vol) — 백테스트 기각, 라이브 미적용.**
C안(①번) 위에 종목 ATR%의 역수로 사이징 스케일 → 총수익 +104%→+50%, Sharpe 1.20→0.76(MDD만
−18.7%→−16.2% 소폭 개선). 모멘텀은 변동성과 양의 상관이라 고변동 승자 비중을 깎으면 수익 훼손 →
개별주 브레이크아웃 스윙엔 부적합(월간 팩터 포트폴리오 크래시방지용 기법). config 무변경.

**③번 절대 모멘텀 필터 (TSMOM, Moskowitz-Ooi-Pedersen 2012) — E2(6개월>0) 적용.**
| 시나리오 | 총수익 | Sharpe | 승률 | MDD |
|---|---|---|---|---|
| C 기준(①번) | +103.7% | 1.20 | 54% | −18.7% |
| E 12M>0(원논문) | +82.3% | 0.99 | 50% | −20.6% |
| **E2 6M>0 (채택)** | **+108.0%** | **1.24** | 55% | −18.1% |
| E3 12M>+10% | +74.9% | 0.92 | 50% | −16.1% |
- 원논문 12개월은 스윙엔 너무 느려 악화. **6개월>0(E2)만 전 지표 소폭 개선**(하방 없음). 개선폭은
  소폭(Sharpe +0.04, 노이즈 범위 가능)이나 하락추세 종목 브레이크아웃 함정 회피 견고성 이점.
- 라이브: `storage.get_abs_momentum(126)` — daily_prices 배치 조회(한 쿼리, 1526심볼 중 565 음수 필터).
  `swing.scan_entries` 에 절대모멘텀 게이트(데이터 없으면 통과=보수적). config `abs_momentum_enabled`
  (true)/`abs_momentum_min`(0.0)/`abs_momentum_lookback_days`(126). 되돌리려면 enabled=false.
- ⚠️ swing_config INSERT 시 `category` NOT NULL — 신규 키는 category 포함 필수.

**①번 주간 자동 재평가:** `scripts/payoff_weekly_review.sh` + user crontab `3 9 * * 1`(매주 월 09:03 KST).
적용 전 baseline 승 +5.86%/손익비 ~1.0 → C안 목표 승 +13.9%/손익비 2.57 추적. 결과 `payoff_review_result.txt`.

**backtest runner 확장 (`engine_v4/backtest/runner.py`):** ②`use_vol_targeting`/`target_atr_pct`/`vol_mult_min/max`,
③`use_abs_momentum`/`abs_mom_period`/`abs_mom_min` + 워밍업 패딩(abs_mom 252거래일 커버) 추가. 전부 기본 off.

**거래량 조건 완화 (2026-07-27, `volume_ratio_min` 1.2→1.0):** 진입빈도 병목 조사 겸 A/B.
| 시나리오 | 진입(4y) | 총수익 | Sharpe | MDD |
|---|---|---|---|---|
| 기준 vol≥1.2 | 177 | +108.0% | 1.24 | −18.1% |
| **vol≥1.0 (채택)** | 181 | **+114.5%** | 1.21 | **−15.8%** |
| vol≥0.8 | 186 | +94.3% | 1.06 | −21.5% |
| vol≥0.0 | 194 | +93.3% | 1.03 | −24.4% |
- **발견①: 거래량은 진입빈도 병목 아님** — 완전 해제해도 진입 +17건(+10%)뿐. 진짜 병목은 추세+브레이크아웃
  동시조건. **발견②: vol≥1.0은 소폭 개선**(총수익+6.5%p, MDD개선, Sharpe유지). 0.8↓는 저품질 진입 섞여 악화.
- **부수 수정 (`collector.py`):** collector 가 `self.cfg.volume_ratio_min`(settings 기본 1.5)를 읽어
  scan_entries(DB config)와 **불일치**했음 → collector 도 DB config 우선 읽도록 수정(일관성). 지표 재계산 후
  volume_surge 통과 10→56/225 반영 확인.
- ⚠️ 백테스트는 max_positions=5, 라이브는 레짐 프리셋(NEUTRAL→7)이라 절대수치 차이 가능. A/B 방향성은 유효.

---

## 22.AG 2026-07-28 브레이크아웃 완화 + 레짐프리셋 정합 + 집중캡 조정

**브레이크아웃 근접 −3% 완화 (백테스트 검증 → 적용).** 진입빈도 진짜 병목(추세+브레이크아웃 동시조건) 검증.
| 시나리오 | 진입(4y) | 총수익 | Sharpe | MDD |
|---|---|---|---|---|
| 기준 5일돌파 엄격 | 181 | +114.5% | 1.21 | −15.8% |
| **근접 5일 −3% (채택)** | 199 | **+136.6%** | **1.30** | −18.6% |
| 3일돌파 | 198 | +110.8% | 1.16 | −15.9% |
| 브레이크아웃 제거 | 214 | +112.3% | 1.04 | −21.3% |
- 근접 −3%가 명확한 승자(총수익 +22%p, Sharpe↑, 진입 +10%). "5일고점 3% 이내 근접"까지 허용 → 돌파 직전
  종목 포착(더 좋은 진입가). 완전 제거는 품질 저하. 라이브: `collector.py` breakout_5d = close > high_5d×(1−margin),
  config `breakout_margin=0.03`. 지표 재계산 후 breakout 통과 73→132/200 반영.

**🔴 레짐 프리셋 충돌 발견·수정 (근본).** `regime_switcher.REGIME_PRESETS`가 레짐 변경 시 `max_positions`와
`take_profit_pct` 도 덮어씀 → 레짐 바뀌면 사용자 지정 max_positions·①번 손익비 개선(take_profit 0.50)이
프리셋값(5/7/3, 0.25/0.20/0.15)으로 **리셋되는 심각한 충돌**. **해결: 두 키를 프리셋에서 제거** → 레짐 스위치는
position_pct/composite_score_min/atr_trailing_multiplier 만 조정. max_positions·take_profit_pct 는 고정 유지.

**집중 캡 조정 (사용자 요청) + 승인 실패 메시지 버그 수정.**
- `max_positions` 10 (레짐 무관 고정), `max_position_pct_cap` 0.25→0.50, `max_total_exposure_pct` 0.90→1.0.
- **버그**: approve_signal 실패 메시지가 cap_reason 무관하게 항상 "단일종목 한도(25%)" 표시 → total_exposure_cap
  인데 오해 유발. **수정**: cap_reason 별 정확한 메시지(총노출/단일종목/리스크 구분, `main.py`).
- 교훈: 오픈 7개가 계좌의 88.5%($849/$959) 차지 → 현금 $109뿐. 캡 올려도 현금보다 비싼 종목(UPS $113)은
  물리적 매수 불가. 소액계좌 다포지션은 현금 소진이 실질 제약.

**현재 라이브 config (2026-07-28):** take_profit_pct=0.50(①), abs_momentum_enabled=true/6M(③),
volume_ratio_min=1.0(거래량), breakout_margin=0.03(브레이크아웃), max_positions=10, max_position_pct_cap=0.50,
max_total_exposure_pct=1.0.

## 22.AH 2026-07-28 자본 추가 $1,000 + 포지션 정책 20개 분산 전환

**자본 추가 입금 $1,000 (paper).** 오픈 8개로 현금 소진($2.46)되어 신규 진입 불가 → `POST /capital/event`
(event_type=deposit, $1000). 총자산 $958→$1,958, 현금 $2.46→$1,002. **TWR 무결성 확인**: 기준자본 1000→2000
조정되어 입금이 수익률에 미포함(누적 −2.07% 유지). `swing_capital_events` 기록(event_id 3).
- **교훈(대시보드 읽는 법):** Total Value ≠ 매수가능액. 실제 매수가능 = Cash. Total Value 는 현금+포지션평가액.
  paper 도 실제 현금 차감 시뮬레이션(실전 동일). 소액계좌 다포지션 = 현금 소진이 실질 제약.

**포지션 정책: 집중 → 20개 분산 전환 (사용자 지정).** max_positions 10→20, position_pct 0.14→**0.05**
(계좌 $1,959 × 5% × 20 = 총노출 100%). **레짐 프리셋에서 position_pct 도 제거**(max_positions/take_profit 에 이어)
→ 레짐 무관 5% 고정. 레짐 적응은 이제 composite_score_min + atr_trailing_multiplier 만 담당(위기 방어 = 진입
score 70 + 트레일 2.0, 포지션 크기 축소는 제외).
**백테스트 검증 (2026-07-28, 사후) — 20개·5% 가 위험조정 최고, 사전 우려 정정.** 현재 라이브 전체설정에
포지션 정책만 A/B (`scripts/backtest_diversify_ab.py`, 자본 $2,000):
| 정책 | 진입 | 총수익 | CAGR | Sharpe | 손익비 | MDD |
|---|---|---|---|---|---|---|
| 집중 5×20% | 198 | +104.5% | +19.7% | 1.10 | 2.61 | −18.8% |
| 중간 7×14% | 288 | +86.6% | +17.0% | 1.07 | 2.92 | −16.0% |
| 분산 10×10% | 385 | +90.0% | +17.5% | 1.19 | 2.94 | −15.9% |
| **분산 20×5% (라이브)** | 678 | +99.1% | **+18.9%** | **1.48** | **3.36** | **−10.4%** |
- **결과: 20×5% 가 위험조정 최고** — MDD −18.8%→−10.4%(절반), Sharpe 1.10→1.48, 손익비 3.36. CAGR 18.9%로
  **18% 목표 달성**(집중과 거의 동일). 총수익 절대값만 집중(+104.5%)이 5%p 우위. 승률 55→45%지만 손익비가 상쇄.
- **사전 우려("지수화·초과수익↓") 오류였음** — 분산이 개별종목 리스크를 줄여 낙폭 급감→Sharpe 급등. 라이브 유지 권장.

---

## 22.AI 2026-08-08 수익률 −4.13% 진단 + hard_stop 분석 + 브레이크아웃 정합(margin 0)

**수익률 −4.13% 실체 규명 (사용자 "$2,000 넣어 $1,917인데?" 검증).** 정확함. 손실 −$82.61 구성:
순수 트레이딩 −$39.88(−2.0%, 실현 −$52.27+미실현 +$12.39) + **수수료 −$42.73(−2.1%)**. **손실의 절반이 수수료** —
20×5% 분산이 매매 빈도↑ → 수수료 누적(0.25%/건). 소액계좌 다포지션의 숨은 비용. (체감 −10%는 느낌, 실제 −4.13%.)

**hard_stop 손실 진단.** 청산사유별: hard_stop 13건 −$83.55 / stop_loss 7건 −$74.26 vs rsi2 29건 +$92.93 /
take_profit 2건 +$38.16. **손절 2종(−$158)이 승자(+$131)를 상쇄** → 진입품질이 핵심. 패턴: ①진입당일 갭손절 4건
②고득점(DAL79·KDP75.5)도 손절 = 팩터스코어가 단기 하락 예측 못함 ③최근 2주 hard_stop 7건(이전 2개월 6건 초과).

**브레이크아웃 근접 손절 영향 재검증 → margin 0 복귀.** 가설(근접이 갭손절↑) **백테스트 기각**(손절률 28~30%
margin 무관). **더 중요한 발견: 분산(20×5%)에선 margin 0%가 총수익/Sharpe 최고**(집중과 반대):
| margin | 손절% | 총수익 | Sharpe |
|---|---|---|---|
| **0% (복귀)** | 30% | **+94.9%** | **1.42** |
| 3% (기존) | 28% | +85.7% | 1.28 |
- 집중(5개)=근접으로 기회 넓힘 유리 / 분산(20개)=이미 진입충분, 근접은 저품질만 추가. 집중→분산 전환 시 놓친
  파라미터 정합. **`breakout_margin` 0.03→0.0** 복귀(총수익 +9%p, Sharpe +0.14). 지표 재계산 완료.
- 최근 hard_stop 급증은 **진입완화 아닌 시장부진**이 주원인(백테스트로 확인).

**현재 라이브 config (2026-08-08 갱신):** take_profit_pct=0.50, abs_momentum_enabled=true/6M, volume_ratio_min=1.0,
**breakout_margin=0.0**(복귀), max_positions=20, position_pct=0.05, max_position_pct_cap=0.50, max_total_exposure_pct=1.0.

---

## 22.AJ 2026-08-16 하락장 방어 3계층(Tier 1~3) 구축 — 롱온리 구조결함 대응

**배경:** 사용자 지적 — "시장 부진에도 수익 못 내면 장기투자와 뭐가 다른가. 하락장 수익 + 변동성 최소화
장치 필요." 롱온리 모멘텀 브레이크아웃의 구조결함(하락장=손절만 누적) 정면 대응. 영문웹/논문 리서치 근거:
GEM(Antonacci 2014, 절대모멘텀 필터로 최악낙폭 51%→10%), Faber(2007, 10개월 SMA 택티컬), VIX term structure,
regime-switching jump model.

**Tier 1 시장 트렌드 필터 (SPY 200일 SMA) — 백테스트 검증 후 적용.** SPY<SMA200 하락국면이면 신규 롱 진입
전면 중단(현금 보유).
| 구간 | 필터 | 총수익 | Sharpe | MDD |
|---|---|---|---|---|
| 전체 22-25 | OFF | +97.5% | 1.48 | −12.4% |
| | **ON** | +98.2% | **1.63** | **−9.1%** |
| 약세장 2022 | OFF | +0.5% | — | −8.5% |
| | **ON** | +1.1% | — | **−4.4%** |
- Sharpe 1.48→1.63, MDD −12.4%→−9.1%(약세장 −8.5%→−4.4% 절반). 강세장 기회비용 소폭(-6.8%p)이나 약세장
  방어가 상쇄. `storage.get_market_trend()` + `scan_entries` 최상단 게이트. config `market_filter_enabled=true`
  /`market_filter_sma_days=200`. 되돌리려면 enabled=false.
- **🔴 runner 버그 수정:** yfinance `group_by='ticker'` 는 단일배치도 MultiIndex 반환 → runner 가 단순컬럼
  인덱싱해 SPY(201번째 단독배치) 조용히 누락. 항상 `data[sym]` 접근으로 수정(기존 코드 잠복버그).

**Tier 2 레짐 킬스위치 (VIX 조기경보).** RISK_OFF regime 또는 VIX>30 시 진입 중단. Tier1(SPY 추세=느림) 보완 —
변동성 급등을 더 빠르게 감지(risk-off 시 종목상관 1로 수렴해 분산 무력→현금이 유일방어). `storage.get_macro_risk_state()`
+ `scan_entries` 게이트. config `macro_kill_switch_enabled=true`/`vix_kill_threshold=30`. 기존 swing_macro_snapshots 활용.

**Tier 3 하락장 헤지 (inverse ETF, 골격+기본 off).** 하락국면 SH(inverse SPY) 보유 백테스트: **하락국면 +22.5%**
(2022 +14.5%) — Tier1=손실회피(현금), Tier3=능동수익(숏). `swing.scan_hedge()` — 하락전환 시 SH ENTER, 상승복귀
시 EXIT. config `hedge_enabled=false`(리스크, 기본off)/`hedge_symbol=SH`/`hedge_pct=0.20`. ⚠️ inverse ETF 장기부적합
(일일리밸 감쇠)→전술적 보유만. 완전 자동실행(스케줄러 연결+SH 자동수집)은 활성화 결정 후 추가.

**현재 라이브 config (2026-08-16):** Tier1 market_filter_enabled=true(SPY>SMA200 현재 상승국면=진입허용),
Tier2 macro_kill_switch_enabled=true(VIX 14=평온), Tier3 hedge_enabled=false. 기존 스택(take_profit 0.50/absmom/
vol 1.0/breakout 0/20×5% 분산) 유지.

## 22.AK 2026-08-16 Tier 3 완전 활성화 (SH 헤지 자동 실행)

골격(scan_hedge)에서 **완전 자동 실행**으로 격상. 하락국면(SPY<SMA200) 전환 시 SH 자동 진입, 상승복귀 시 자동 청산.
- **SH 데이터 수집:** `BENCHMARK_SYMBOLS`에 SH 추가(daily_pipeline이 SPY/QQQ/SH 수집). 초기 300행 수집(종가 $31.98).
- **`_job_hedge_check` 스케줄러 잡:** 화~토 05:35 KST(16:35 ET, 종가 기준) — scan_hedge ENTER/EXIT 판정 →
  SH 포지션 자동 생성(side=HEDGE)/청산. Telegram 알림. 헤지 사이징 = 계좌×hedge_pct(20%)/SH가.
- **exit_manager 헤지 제외:** `_job_exit_check`가 side=HEDGE 포지션 스킵 → 5-Layer 출구(ATR트레일 등) 미적용,
  시장국면 기반으로만 청산(inverse ETF 특성). `_get_account_value()` 헬퍼 추가.
- **🔴 collector MultiIndex 버그 수정:** collect_prices 도 단일배치 `df=data`(MultiIndex 미처리)로 SH 단독수집
  0행이던 잠복버그 → `data[sym]` 접근 수정(runner 와 동일 버그). scheduler_jobs 24→25.
- **활성화:** `hedge_enabled=true`. 현재 상승국면이라 헤지 대기(진입 안함=정상), 하락 전환 시 자동 발동.
  진입시뮬 검증: 계좌 $1,916×20%=$383 → SH 11주. ⚠️ inverse ETF 장기부적합 → 시장국면 기반 전술적 보유만.

## 22.AL 2026-08-18 Tier 1~3 독립 재검증 (신선 데이터, 시계교정 후)

시계교정·데이터갱신 후 Tier 1~3 재검증(runner가 yfinance 신선 재다운로드). **이전 §22.AJ 수치와 일부 상이 —
정직히 기록.**

**Tier 1 시장필터 (`scripts/backtest_market_filter.py`, 재실행):**
| 구간 | 필터 | 총수익 | Sharpe | MDD | 승률 |
|---|---|---|---|---|---|
| 전체 22-25 | OFF | +94.4% | 1.41 | −14.1% | 44% |
| | ON | +84.0% | 1.39 | −12.8% | 45% |
| **약세장 2022** | OFF | −2.6% | −0.20 | −9.9% | 27% |
| | **ON** | **−0.6%** | −0.06 | **−4.3%** | 29% |
| 강세장 23-24 | OFF | +65.4% | 2.09 | −9.1% | 50% |
| | ON | +57.4% | 1.90 | −8.8% | 47% |
- **결론(더 미묘함):** 필터는 **약세장 방어 확실**(2022 손실 −2.6→−0.6%, MDD −9.9→−4.3% 절반). 단 **전체
  Sharpe는 소폭↓(1.41→1.39)** — 강세장 기회비용(+65→+57%)이 방어이득을 거의 상쇄. §22.AJ의 "Sharpe 1.48→1.63
  개선"은 이번 신선데이터 재현 안 됨(당시 유니버스/기간 차이 추정). **순수익 중립~소폭손해지만 하락장 낙폭 절반
  = 변동성 최소화 목적엔 부합.** 롱온리+필터 = 방어장치이지 알파원천 아님.

**Tier 2 VIX 킬스위치:** **독립 백테스트 불가** — swing_macro_snapshots 5개월(3/16~)뿐이라 2022 약세장 커버 못함.
runner 미지원. Tier1(SPY추세)의 빠른 보완재 성격 → Tier1 검증으로 갈음. 실운영서 VIX>30 시 진입중단만 확인.

**Tier 3 SH 헤지 (독립 계산, yfinance SPY+SH 2022-25):** ✅ **강력 확증.**
- 하락국면(SPY<SMA200, 전체의 26%일) SH 보유: **+35.6%** / 2022 약세장 하락국면: **+26.6%**.
- 상승국면 SH 보유 시 −42.8%(감쇠) → **게이팅 필수**(하락국면만 보유). Tier3 로직(하락전환 ENTER/상승복귀 EXIT)이
  정확히 이 +35.6% 구간만 취하고 −42.8% 회피 → 설계 타당. Tier1(현금회피)보다 **능동수익** 우위.

**종합 판단:** Tier1 = 방어(중립수익, 낙폭절반), Tier2 = Tier1 보완(백테 불가), Tier3 = 능동수익(하락장 +26~35%,
게이팅 필수). 현 상승국면선 Tier1/2 진입허용·Tier3 대기 = 전부 정상. 하락장 전환 시 가치 발현.

## 22.AM 2026-08-18 Tier 3 알파 강화 (A안 SMA150 + B안 사이징 40%)

Tier3 를 방어→알파원천으로 강화 백테스트(`scripts/backtest_tier3_alpha.py`, 사이징×레버리지×신호속도).
하락국면 게이팅은 유지(상승국면 인버스 보유는 −42.8% 감쇠, 필수).

**백테스트 (2022-25 하락국면, 14 에피소드 전부 승):**
| 강화축 | 결과 |
|---|---|
| 신호속도(SH 40%) | SMA100 +23.1%/MDD−5.3% · SMA150 +20.2%/−5.3% · **SMA200 +14.0%/−6.2%** · SMA250 +10.4% |
| 사이징(SH SMA200) | 20% +6.9% · 40% +14.0% · 60% +21.1% (MDD 비례증가) |
| 레버리지(40%,SMA200) | SH +14%/−6% · SDS(-2x) +27%/−12% · SPXU(-3x) +40%/−18% |

- **핵심: 빠른 신호(SMA150/100)가 순수 우월** — 수익↑·낙폭↓·승률 100% 유지(하락 더 일찍 포착).
- **적용: A(hedge_sma_days 200→150) + B(hedge_pct 0.20→0.40).** 레버리지(C/D)는 표본 얇아 보류.
  헤지 전용 `hedge_sma_days` 신설(Tier1 진입필터 market_filter_sma_days=200 과 분리 — swing.scan_hedge 수정).
  발동시 사이징 계좌 40%(구 20%). 되돌리기: hedge_sma_days=200, hedge_pct=0.20.
- ⚠️ **한계:** 2022 단일 약세장 표본 → 100% 승률은 out-of-sample 미보장. 인버스는 구조적 음기대값(게이팅이 반전).
  레버리지는 whipsaw 시 손실증폭이라 보류. 현 상승국면은 헤지 대기(정상), 하락 전환 시 SMA150·40%로 발동.

## 22.AN 2026-08-18 🔴 수동 파이프라인 벤치마크 누락 버그 (QQQ 8/13 정체 원인)

**증상:** QQQ 가 8/13 에 멈춤(SPY/SH 는 8/17). **원인:** `/pipeline/run`(`_run_pipeline`, main.py)이 유니버스만
수집하고 `BENCHMARK_SYMBOLS`(SPY/QQQ/SH) 누락 — 스케줄 파이프라인(`_job_daily_pipeline`)은 `symbols+BENCHMARK`
수집하는데 수동 경로만 빠짐. VM 복구 후 내가 수동 pipeline 여러번 + SPY/SH 만 개별수집 → QQQ 만 방치돼 드러남.
**심각도:** SPY(Tier1)·SH(Tier3) 신호원이라, 수동 실행만 하면 Tier 게이트가 stale SPY 로 판정하는 잠복위험.
**수정:** `_run_pipeline` 도 `symbols + BENCHMARK_SYMBOLS` 수집(스케줄과 일관). QQQ 8/17 갱신 확인.

**전 경로 전수조사(후속):** 모든 `collect_prices` 호출 4곳 점검 → **`/collect`(`_run_collect`, main.py) 도 동일
누락** 발견·수정(벤치마크 추가). 나머지: `/pipeline/run` 수정완료, `daily_pipeline`(스케줄) 정상(benchmark 포함),
`premarket_check`(스케줄, days=5, 청산스캔용)은 유니버스만이나 벤치마크는 daily_pipeline이 갱신하므로 OK. `_job_hedge_check`
는 자체수집 없이 daily_pipeline 의존(정상). 결론: 수동 데이터경로 `/collect`·`/pipeline/run` 둘 다 수정 완료.

---

## 22.AO 2026-08-18 정기점검 3종 조치 (MDD 오염 / 리포트 공백 / 변이 백테스트 무력화)

재부팅(08:27) 후 전수 점검에서 3건 발견 → 1·2번 조치 완료, 3번은 원인규명 완료 후 사용자 결정 대기.

**① MDD −505% 오염 → −15.03% 정상화 (완료)**
- 증상: `/portfolio`·대시보드 MDD 가 −505.12% 로 표시.
- 원인: 계산식(`jobs.py:1188`, `main.py:1392`)은 정상이나 **전 이력을 스캔**하는데 `swing_snapshots` 에 오염 행이 섞임.
  가짜 peak `2026-05-26 cum=+494.72%`(total $5,947 / invested $5,069) 가 영구 기준점이 돼 이후 모든 dd 를 −5.05 로 만듦.
- 오염 행 5건: `04-01 07:00`(cash −$10,971 / invested $11,985), `05-26 23:08:01`(cum +494.72%),
  `05-26 23:08:03`(cum +25.30%), `06-16 22:08`(전 지표 NULL), `07-02 21:15`(cum +79.56%).
  전부 해당 일자에 정상 행이 4~15개 더 있어 삭제해도 일자 손실 없음.
- 조치: CSV 백업(`scripts/backup/swing_snapshots_20260818.csv`, 895행) → 오염 5행 DELETE →
  남은 890행 `max_drawdown` 을 엔진과 동일 로직(running peak, floor 0)으로 전 구간 재계산 UPDATE →
  Redis `swing:snapshot` 캐시 무효화(캐시가 옛 값 반환하던 것 확인).
- 결과: cum −5.26% 유지, **MDD −505.12% → −15.03%**(peak +4.64% → trough −10.39%). cum 범위도 −10.39~+4.64% 로 정상화.
- ⚠️ 재발방지 미적용: 애초에 오염을 만든 원인(5/26 invested $5,069 등 이상 시세/수량)은 미규명.
  `jobs.py` 에 isfinite 가드는 있으나 **범위 가드(예: invested > 자본×3 이면 저장거부)는 없음** — 필요 시 추가.

**② 일일리포트 공백 소급 생성 (완료)**
- `post_market_analysis` 는 **화~토 06:05 KST**(`day_of_week="tue-sat"`) → 정상 기대 일자는 화~토뿐(일·월 KST 는 US 휴장이라 원래 없음).
- 실제 공백은 **8/15(토)·8/18(화)** 2건. VM 일시정지(8/15~8/17)로 미발화. 8/9(일)·8/10(월) 결번은 정상.
- 조치: `POST /analysis/daily/run?report_date=...&notify=false` 로 2건 생성(MFE 85 / event-study 85 / counterfactual 74 전부 ok).
- 결과: 8/15·8/18 rolling_30 = 승률 36.67% / 기대값 +0.60% / SQN −2.499 / **IC +0.0365**.
  8/14 와 동일값인 건 정상 — 8/13 이후 청산이 없어 rolling_30 표본이 그대로임.

**③ 🔴 변이(variant) 백테스트가 구조적으로 전건 기각 — 하네스 3C/3D 사실상 무력 (원인규명 완료, 조치 대기)**
- 표면 증상: pending 30건 적체(7/1~8/5 생성분), 8/6 `variant_generate` 뒤 `variant_backtest` 로그 없음.
- 원인 1 (적체): 월간 잡이 5개 생성 + `validate_all_pending(max_per_run=5)` 로 **오래된 5개만** 검증 →
  생성속도 = 검증속도라 backlog 영구 고정. 8/6 05:03 건은 월간 스케줄(1일 11:00)이 아닌 **수동 API 호출**이라
  `/harness/variants/generate` 에 자동검증이 없어 백테스트가 애초에 안 붙음(로그 결번의 진짜 이유).
- **원인 2 (치명적): 합격조건이 물리적으로 달성 불가.** `validate_variant` 는 **90d 를 primary** 로 쓰는데
  게이트는 `harness_min_backtest_trades=30`. 실제 90d 거래수는 **2~6건**:
  | run | 기간 | 거래수 |
  |---|---|---|
  | variant_16_90d | 90d | **2** |
  | variant_15_90d | 90d | **2** |
  | variant_14_90d | 90d | **6** |
  | variant_16_365d | 365d | 48 |
  | variant_14_365d | 365d | 61 |
  → `enough_trades` 가 절대 참이 될 수 없어 **품질과 무관하게 100% rejected**. 기각 16건 전부 사유가
  `trades=N<30`. 실제로 variant_13 은 365d 에서 **+25.05% / Sharpe 2.54** 인데도 90d 표본미달로 기각됨.
  (9~11번은 `trades=29<30` 1건 차이 기각 + variant_sqn=baseline_sqn=2.145 로 변이 효과 자체가 0)
- **원인 3 (신규 발견): 백테스트 러너가 네트워크 I/O 에서 무한 hang.** 확인차 variant 18 을
  `POST /harness/variants/18/backtest` 로 실행 → **35분간 CPU 0.0~0.3%, backtest_runs 0건 저장, status='testing' 고착**.
  yfinance 소켓이 CLOSE-WAIT 9개로 누수. 8/1 정상 실행 때는 변이당 elapsed 113~115초였음.
  타임아웃이 없어 한 번 걸리면 **월간 잡도 같은 자리에서 멈추고 변이는 'testing' 좀비로 남음**.
  조치: 엔진 kill -9 재기동(25잡 정상) + variant 18 → 'pending' 원복.
- **일괄 백테스트 미실행 사유(의도적):** 위 조건에서 30건을 돌리면 ①건당 ~2분×30 = 1시간 소모,
  ②전건 `trades<30` 기각이 확정, ③30건이 영구 rejected 로 낙인 — 순손실뿐이라 **실행하지 않고 사용자 판단을 요청**.
- **선택지:** (A) config 만 `harness_min_backtest_trades` 30→10 (90d 가 2~6건이라 여전히 미달, 미봉책) /
  (B) primary 를 365d 로 / (C) 타임아웃 + 좀비 회수.
- **사용자 결정(2026-08-18): B + C 채택 → 아래 구현 완료.**

### 22.AO-1 (B) 판정 기준기간 90d → 365d

- `validate_variant` 의 primary 를 하드코딩 `"90d"` → **`harness_primary_period` config(기본 `365d`)** 로 전환.
  요청 기간이 없으면 `365d → 180d → 90d` 순으로 폴백하고 폴백 시 WARNING 로그.
- 판정 결과 요약(`swing_harness_log.details`)에 **`primary_period`** 필드 추가 — 어느 기간이 판정했는지 추적 가능.
- 신규 config 3종: `harness_primary_period=365d`, `harness_backtest_period_timeout_sec=900`,
  `harness_testing_stuck_min=45`.

### 22.AO-2 (C) 무한 hang 방어 3종

1. **구간 wall-clock 타임아웃** — `_run_period(…, timeout_sec)` 가 별도 워커 스레드에서 실행,
   초과 시 `BacktestTimeout`. 파이썬은 스레드를 죽일 수 없어 초과 워커는 유기(daemon)하고 진행.
   타임아웃은 **기각이 아니라 미판정** 처리 → `pending` 원복 후 다음 회차 재시도(품질 누명 방지).
2. **'testing' 좀비 자동 회수** — `recover_stuck_testing()` 이 `testing_started_at`(신규 컬럼) 기준
   45분 초과 행을 `pending` 으로 원복 + `variant_recover` 감사로그. **매시 15분 `rollback_check` 잡**과
   `validate_all_pending()` 진입 시 호출.
3. **동시실행 1건 제한(DB 뮤텍스)** — `_claim_slot()`. 프로세스 내 `threading.Lock` 은 좀비 스레드가
   영구 점유할 수 있어 쓰지 않고, `testing_started_at` 자체를 **만료되는 잠금**으로 사용 → 재시작에도 안전.
   추가로 `runner.py` 의 `yf.download` 를 **`threads=False` + `timeout=30`(`YF_TIMEOUT_SEC`)** 로 고정
   (yfinance 내부 스레드풀이 캐시 락에서 교착된 것이 hang 의 방아쇠로 추정 — 리포트 백필과 동시 실행 시 발생).

**검증 (variant 18 실측, 2026-08-18 09:41):**
| 항목 | 조치 전 | 조치 후 |
|---|---|---|
| 실행 | **35분 hang, CPU 0%, 저장 0건** | **246.7초 정상 완료** |
| 판정 기간 | 90d (2~6 거래) | **365d (81 거래)** |
| 결과 | testing 좀비 고착 | **validated** (하네스 사상 첫 합격) |
- variant 18 「시간스 하향」 `{position_pct 0.18, max_positions 10, factor_weight_technical 0.35}`:
  SQN **1.246 → 2.616 (Δ+1.37)**, Sharpe **1.639 → 2.631 (Δ+0.99)**, consistent=true.
- ⚠️ `threads=False` 로 변이당 113초 → 247초(약 2배)로 느려졌으나, hang 리스크 제거가 우선.
- ⚠️ **자동 배포 안 됨** — `deploy_best_variant` 는 스케줄러 잡이 없고 `/harness/variants/deploy-best`
  API 호출로만 동작. validated 상태로 사용자 승인 대기 중.

**미해결(별건):**
- 적체 자체는 그대로 — `validate_all_pending(max_per_run=5)` 가 월 5건 생성과 동률이라 pending 29건 고정.
  일괄 소진하려면 `max_per_run` 상향 또는 수동 반복 필요(변이당 ~4분).
- `/harness/variants/generate`(수동 API)에는 여전히 자동검증이 붙지 않음 — 생성만 하고 pending 적재.

---

## 23. Git History

```
(PENDING) fix: 수동 파이프라인 벤치마크(SPY/QQQ/SH) 누락 수정 + Tier3 알파강화(SMA150+40%)
6188aec  feat: Tier3 완전활성화(SH 헤지 자동실행 스케줄러+collector 버그수정+hedge on)
1912e2e  feat: 하락장 방어 Tier1~3(SPY필터+VIX킬스위치+SH헤지골격) + runner MultiIndex 버그수정
0264ac9  docs+test: 브레이크아웃 margin 0 복귀(분산 정합) + 수익률/hard_stop 진단
1d8a20f  docs+test: 20개·5% 분산 백테스트 검증(위험조정 최고, CAGR 18.9%/Sharpe 1.48)
f759b73  feat: 자본 +$1000 입금 + 포지션 정책 20개 분산(position_pct 0.05, 레짐프리셋서 제거)
a3273bc  feat: 브레이크아웃 완화(margin 3%)+레짐프리셋 정합+집중캡 조정+승인실패 메시지 수정
dcd2a95  feat: 거래량 완화(vol 1.2→1.0) + collector DB config 정합 + 진입빈도/거래량 백테스트
7351b42  feat: ③번 절대모멘텀(6M>0) 진입필터 적용 + 백테스트 검증 (②는 기각)
44a327c  feat(backtest)+config: 손익비 개선(①번) 백테스트 검증 후 C안 적용
fd537a7  feat(backtest): ②번 변동성 타깃팅 검증(기각) + ①번 주간 재평가 cron
b7eb80d  feat(approve)+docs: 승인 실패 사유 상세화 + 22.AD 세션 기록
154a522  feat(pipeline): 파이프라인에 AI 분석(llm_score) 통합 — active 탭 빈칸 방지
276d751  feat(pipeline): 유니버스 카운트 활성 기준 정합 + 진입 0 사유 팝업
154a522  feat(pipeline): 파이프라인에 AI 분석(llm_score) 통합 — active 탭 빈칸 방지
276d751  feat(pipeline): 유니버스 카운트 활성 기준 정합 + 진입 0 사유 팝업
a4e40e9  feat(pipeline): 진입 시그널 0일 때 '왜 없는지' 깔때기 사유 표시
733fc57  fix(pipeline): 스케줄 파이프라인에 팩터 스코어링 단계 추가
9813158  feat(exit): rsi2 7/8 재평가 결과 파일 생성 — 세션 재접속 자동 픽업
cd3557b  docs: project_status.md — 22.AC rsi2 출구 정책 교정 + 재부팅 부활 픽스 + Git History 갱신
f2c1b40  feat(exit): rsi2 출구 정책 교정 1주 전진검증 스크립트 + cron 예약 (min_r 2.0 / thr 95)
ead8870  fix(systemd): 대시보드 유닛에서 V3.1 엔진 의존성 제거 (재부팅 부활 차단)
5fac8e1  chore: 재부팅 후 V3.1 비활성화 자동 검증 스크립트 (@reboot cron)
01c4f66  docs: V3.1 레거시 엔진 완전 비활성화 기록 (2026-06-25)
f590e96  docs: project_status.md — 22.AB 수익률 진단 + 집중캡/손익비 교정 + Git History 갱신
4686f00  feat: take_profit 활용 확대 — R배수 기반 부분익절 (손익비 교정)
b35d462  feat: SPY/QQQ 벤치마크 수집 복구 + 15일 검증 재평가 잡 + 브레이크이븐 스톱
a7ef1ba  fix: 조기청산 재활성화 + 백테스트 집중캡 반영 + 스냅샷 진동 글리치 수정
49b6e92  feat: 포지션 집중 리스크 캡 — 소액계좌 고가주 과집중 차단
1022caf  chore: IC 추세 재측정 스크립트 (2026-07-02 예약) — fea7a34 후속 검증
aefe334  fix: Dashboard 전체 공백 — 스냅샷 numeric NaN 으로 history 쿼리 예외
4fc3620  docs: project_status.md — 22.AA IC 음수 교정 4종 기록 + Git History 갱신
fea7a34  fix: IC 음수 교정 4종 — 정책중립 신호IC + RSI(2) 승자보호 + 모멘텀 과열 페널티 + 요인 가중치 재보정
d1eac6b  fix: Signals factor detail — risk-adjustment 스키마 변경 대응 + Crowding/Short 렌더링 복구
efacdf9  fix: Telegram 봇 /analyze /regime /status — 실제 스키마 + NULL 안전
1cd730a  feat: Telegram 양방향 봇 (옵션 A 9개 명령 + 옵션 B Claude 큐)
2dffd2d  tune: IC 보정 절충 완화 — NEUTRAL composite_score_min 63 → 61
c3b35a7  docs: Help 13번 섹션 — 자율 진화 시스템 + 옵션 3종 활성화 반영
22bd455  feat: IC 보정 + Pipeline 3회/일 + Dashboard 자동갱신 + Telegram 요약
b396727  docs: 2026-06-03 운영 상태 갱신 + 새 세션 시작 가이드
503ad18 docs: project_status.md Phase 3 완성 종합 요약 추가
29a866f feat: Phase 3 Week 3+4 완성 — 변이 생성기 + 자동 백테스트 + 자동 배포 + 통합 대시보드
70845df feat: Phase 3 Week 2 — 매크로 적응 스위치 (3F) + 확장 기술 지표 (3G)
6ec5787 feat: Phase 3 자율 진화 하네스 Week 1 — 지식 베이스 + 시드 + 리서치 에이전트
2706340 feat: Analysis 시스템 (Phase 2A-E) + Strategy A/B 자동승인 + LLM Gate
PENDING  feat: 수수료 계산 시스템 (0.25% 자동 계산 + 수익률 차감 + 대시보드 표시)
7a3396b perf: ticker/market 캐시 최적화 + V3.1 비활성화
a70a075 docs: V3.1 비활성화 안내 + 현황 업데이트 (2026-04-15)
fd90896 docs: Live 전환 준비 + 민감정보 마스킹
88a4adb feat: KIS broker 완전 연동 + daily entry count 버그 수정 + Scan Now 탭 유지
d3ba162 fix: position_pct 입력 검증 (>1.0 자동 보정)
3c409a1 docs: project_status.md 전면 업데이트 (2026-03-25)
ed21a02 fix: Pipeline 버튼 상태 유지 + 진행 시간 표시
d95d81e perf: Watchlist sparkline/차트 병렬 로딩 (순차→Task.WhenAll)
44ae07b feat: 백테스트 검증 기반 파라미터 최적화 + Help 업데이트
7792786 feat: 5-Layer Tactical Quality Momentum watchlist strategy
PENDING  feat: RBAC + User Management + Flow scoring (yfinance Short + Crowding) + Fundamental optimization
2539199 feat: watchlist multi-period chart (1D/5D/1M/6M), sparkline, fixed-width alignment
3a0fb81 feat: Ollama local LLM, background AI analysis, market sector heatmap, mobile UX
b199b7c feat: collapsible sidebar persistence, watchlist signal backtest, intraday chart, CNN links
d48afdd feat: extended hours monitoring, watchlist weighted scoring, Performance TWR fix
986c6b6 feat: Phase F — Telegram alerts, KIS live/paper toggle, SSE push, SEC EDGAR
06ede29 feat: Phase D (Strategy Optimization) + Phase E (Real-time Events)
5f58d52 feat: Phase C — Multi-Factor Scoring (Technical 40% + Sentiment 30% + Flow 30%)
9baefce feat: Phase A (LLM Sentiment) + Phase B (Exit Strategy) complete
51314a3 docs: AI-enhanced 5-phase roadmap for maximizing returns
9a70e20 feat: snapshot generation system + project_status.md rewrite for V4
5888ea7 feat: add Revert button for rejected signals back to pending
ff546f4 feat: V4 swing trading engine + dashboard complete rewrite
ebff79e docs: update git history hash in project_status.md
31ce0bf feat: dashboard UX — auth, HelpTooltip, SymbolLink, glass-morphism CSS, top-bar
```

---

## 24. For Claude Code — Session Continuity

새 세션 시작 시:

1. **Read this file**: `project_status.md` (전체 시스템 현황)
2. **Read CLAUDE.md**: 코딩 규칙 (psycopg3, TimescaleDB, Npgsql Raw SQL)
3. **Current state**: V4 Swing Trading 시스템 운영 중, 1개 포지션 오픈 (STZ 1주 @ $166.15, paper mode)
   - **Live 전환 예정**: 2026-04-21 주간 (일주일 Paper 준비 기간 후)
   - **V3.1 비활성화 필요**: `sudo systemctl stop/disable quant-engine.service` (Telegram 중복 알림 원인)
4. **Dashboard**: 12 pages + Login/Register + Collapsible Sidebar + Live Ticker Bar + RBAC
5. **Engine**: port 8001 (NOT 8000), 12 scheduler jobs (incl. macro_collect, social_collect, lstm_retrain, premarket/afterhours), SSE stream
6. **Key service**: `SwingService.cs` (NOT PostgresService.cs)
7. **Key models**: `SwingModels.cs` (NOT DashboardModels.cs)
8. **All phases complete**: A(LLM) + B(Exit) + C(MultiFactor) + D(Optimizer) + E(Events) + F(Telegram/KIS) + **Tier 3(LSTM+Social+DualSort)** + **Macro Overlay**
9. **New features**: Capital Injection, Watchlist(weighted scoring + signal backtest + intraday chart + sector heatmap), Collapsible Sidebar(JS+localStorage), Live Ticker, Help(Korean 12섹션, 용어사전+초보자교육), Extended Hours, Performance TWR Fix, CNN Ticker Links, Ollama Local LLM, Background AI Analysis, Market Sector Heatmap(in-place drilldown), Mobile Responsive, Pagination, Chart Touch Zoom, Signal Replay Backtest, **LSTM Prediction(70.5%), Social Sentiment(Reddit+StockTwits), Dual Sort(momentum+value)**, **User Management + RBAC**, **yfinance Short Interest + Crowding Integration**, **Fundamental rule_based optimization**

### Critical Reminders
- Engine V4 = port **8001**, V3.1 = port 8000 (비활성)
- `swing_*` prefix tables = V4 (13개), 일반 테이블 = V3.1
- `SwingService.cs` = V4 서비스, `PostgresService.cs` = V3.1 레거시
- Restart without sudo: `kill PID` → systemd 12초 후 auto-restart
- conda env: `quant-v31` (Python 3.11, NOT base)
- PYTHONPATH: `/home/quant/quant-v31`
- psycopg3: `make_interval(days => %s)` (NOT `interval '%s days'`)
- Dashboard build: `cd dashboard/QuantDashboard && dotnet build`
- `reject_signal` SQL: `status IN ('pending', 'approved')` — approved도 reject 가능
- SseToastPanel: 별도 `@rendermode InteractiveServerRenderMode` — MainLayout에 넣지 말 것
- Ticker bar: `/ticker` API에서 오픈 포지션 현재가 조회 (yfinance)
- Watchlist 분석: POST /watchlist/analyze → GET /watchlist/analysis (Redis 캐시)
- Capital: `get_total_capital_adjustments()` → snapshot cash/return 계산에 반영
- Help 페이지: 전체 한글 (12개 섹션, 용어사전 + 초보자 교육 + Tier 3 통합)
- LSTM: `engine_v4/ai/lstm_predictor.py`, 모델 파일 `engine_v4/models/lstm_v1.pt`, 매주 토요일 09:00 자동 재학습
- Social Sentiment: Reddit(PRAW) + StockTwits + Ollama 분석, RedisCache `get_json/set_json` 사용
- Dual Sort: `engine_v4/strategy/swing.py` → `_apply_dual_sort()`, momentum+value 결합 순위 필터
- RBAC: 역할별 페이지 접근은 Cookie claim 기반 — 권한 변경 후 재로그인 필요
- User Management: Settings 3탭 (Settings / User Management / Role Permissions) — admin only
- Fundamental: Ollama 제거 → Claude API 또는 rule_based (Finnhub metrics 기반 즉시 점수)
- Flow Score 4요소: Insider 30% + Analyst 30% + Short Interest(yfinance) 20% + Crowding 20%
- Ollama: port 11434, systemd `ollama.service`, 모델 `qwen2.5:3b` (CPU only, ~2min/signal)
- AI 분석: Background 처리 + Redis 진행률 폴링 (`/ai/analyze-status`)
- AI 우선순위: Claude API → Ollama local → Mock (3단계 fallback)
- Market Heatmap: `/market/overview` + `/market/sector/{etf}` (Redis 캐시 600s)
- Sector Drilldown: in-place 전환 (타이틀+박스 영역 교체, 돌아가기 버튼)
- **position_pct 검증**: API + PositionManager에서 `>1.0` 입력 시 자동 ÷100 보정 (14 → 0.14)
- **KIS Broker**: python-kis 2.1.6, paper→SIM 시뮬레이션, live→실전 KIS API 연결
  - .env: `KIS_USER_ID`, `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO` (크레덴셜은 .env에만, git 미포함)
  - Broker API 8개: /broker/status, /broker/balance, /broker/quote/{sym}, /broker/pending-orders, /broker/cancel/{id}, /broker/orderable/{sym}, /broker/orders, /broker/sync
  - Live 전환 예정: 2026-04-21 주간

---

## 25. 하락장 방어 로드맵 (Tier 1~3) — ✅ 구현·배포 완료 (상세 §22.AJ/AK)

**배경:** 롱-온리 모멘텀 브레이크아웃의 구조결함(하락/횡보장=손절만 누적, buy&hold+수수료) 대응. 사용자 요구
"하락장 수익 + 변동성 최소화 장치". 메모리 [[bear-market-defense-research]]. 리서치: Antonacci GEM,
Faber TAA(SSRN-962461), Jump Model(arxiv 2402.05272).

**구현 이력:** 이전 VM 세션(2026-08-16)에 Tier 1~3 구현·push(커밋 1912e2e, 6188aec). VM 손상 → 2026-08-14
스냅샷 복구(git보다 뒤처짐) → 2026-08-18 재연결 후 **git 신규버전 rebase 수령 + 실행시스템 재배포**(config 7키
복원 + SH 300행 수집 + 엔진 재시작 25 jobs). ⚠️ 배포 중 **시계 skew 이슈** 발견: 스냅샷 복구로 시계가 3일 과거
→ Yahoo SSL cert "not yet valid" → 전 종목 수집 실패. 시계 교정 후 정상화(교훈: 스냅샷 복구 시 `date -u` 확인 필수).

| Tier | 상태 | 규칙 | config | 검증 |
|---|---|---|---|---|
| **1 시장트렌드필터** | ✅ 배포 | SPY<SMA200 하락국면 진입중단(현금) | market_filter_enabled=true, sma_days=200 | Sharpe 1.48→1.63, MDD −12.4→−9.1%(약세장 절반) |
| **2 VIX 킬스위치** | ✅ 배포 | RISK_OFF or VIX>30 진입중단 | macro_kill_switch_enabled=true, vix_kill_threshold=30 | Tier1 조기경보 보완 |
| **3 SH 헤지** | ✅ 배포(대기) | SPY<SMA200 전환 시 SH 자동진입/상승복귀 청산 | hedge_enabled=true, hedge_symbol=SH, hedge_pct=0.20 | 하락국면 백테 +22.5%(2022 +14.5%). scheduler `hedge_check` 화~토 05:35 |

**현재 게이트 상태(2026-08-18):** SPY 773>SMA200 703(상승)+VIX 14.6(평온) → 진입 허용, Tier3 헤지 대기(정상).
**되돌리기:** 각 `*_enabled=false`. **미래 확장(미착수):** Tier3 옵션B(롱숏/마켓뉴트럴)는 KIS 실거래 숏 연동 필요 → Live 전환 후.

---

## 26. 백업 / 복구 가이드 (다른 VM 이전 시)

**시스템 구성 요소 (백업 대상):**
1. **코드** — git 저장소 `/home/quant/quant-v31` (원격 https://github.com/WhoansooKim/quant-v31)
2. **DB** — PostgreSQL+TimescaleDB (Docker `quant-postgres`), DB명 `quantdb`. **config·포지션·시그널·가격·스냅샷 전부 여기.**
3. **.env** — API 키(Telegram/KIS/Anthropic), DB 비밀번호. **git 미포함, 별도 백업 필수.**
4. **cron** — user crontab (재부팅 검증 + 주간 재평가)
5. **systemd 유닛** — `/etc/systemd/system/quant-engine-v4.service`, `quant-dashboard.service` (저장소 `systemd/` 에도 사본)
6. **Claude 메모리** — `/home/quant/.claude/projects/-home-quant-quant-v31/memory/` (작업 맥락·의사결정)

### 백업 (기존 VM에서)
```bash
cd /home/quant/quant-v31
# 1. 코드는 git push 로 원격 보관 (이미 되어 있으면 생략)
git add -A && git commit -m "backup snapshot" && git push origin main

# 2. DB 전체 덤프 (가장 중요 — config/포지션/가격 전부)
docker exec quant-postgres pg_dump -U quant -Fc quantdb > ~/quantdb_backup_$(date +%Y%m%d).dump

# 3. .env + cron + 메모리 묶기 (git 밖 자산)
tar czf ~/quant_secrets_$(date +%Y%m%d).tar.gz \
  -C /home/quant/quant-v31 .env \
  -C /home/quant/.claude/projects/-home-quant-quant-v31 memory
crontab -l > ~/quant_crontab_$(date +%Y%m%d).txt

# 4. 위 3개 파일(dump, secrets.tar.gz, crontab.txt)을 새 VM 으로 복사(scp 등)
```

### 복구 (새 VM에서)
```bash
# 0. 전제: Docker, conda(quant-v31 py3.11), .NET 8 설치됨. PG 컨테이너는 docker-compose up -d
# 1. 코드
git clone https://github.com/WhoansooKim/quant-v31 /home/quant/quant-v31

# 2. .env + 메모리 복원
tar xzf ~/quant_secrets_YYYYMMDD.tar.gz -C /tmp/restore
cp /tmp/restore/.env /home/quant/quant-v31/.env
mkdir -p /home/quant/.claude/projects/-home-quant-quant-v31
cp -r /tmp/restore/memory /home/quant/.claude/projects/-home-quant-quant-v31/

# 3. DB 복원 (컨테이너 먼저 기동: docker-compose up -d postgres)
docker exec -i quant-postgres psql -U quant -c "DROP DATABASE IF EXISTS quantdb;"
docker exec -i quant-postgres psql -U quant -c "CREATE DATABASE quantdb;"
cat ~/quantdb_backup_YYYYMMDD.dump | docker exec -i quant-postgres pg_restore -U quant -d quantdb

# 4. cron 복원
crontab ~/quant_crontab_YYYYMMDD.txt
# ⚠️ 경로가 /home/quant/quant-v31 로 동일해야 cron/systemd 스크립트가 맞음

# 5. systemd 유닛 (저장소 사본 사용, sudo 필요)
sudo cp /home/quant/quant-v31/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quant-engine-v4 quant-dashboard

# 6. 검증
systemctl is-active quant-engine-v4 quant-dashboard
curl -s http://localhost:8001/health | python3 -m json.tool
docker exec quant-postgres psql -U quant -d quantdb -c "SELECT COUNT(*) FROM swing_config;"
```

### 복구 후 체크리스트
- config 개수·값 확인(위 §스냅샷 표와 대조), 오픈 포지션 수 일치, cron 2줄, V3.1(8000) down.
- Claude 새 세션: 이 파일 + `memory/MEMORY.md` 읽으면 맥락 복원. `[[bear-market-defense-research]]` 에 다음 할 일.
- ⚠️ **경로 의존**: 스크립트/cron/systemd 가 `/home/quant/quant-v31` 하드코딩 → 새 VM 도 동일 경로 권장.
