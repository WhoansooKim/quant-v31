# Quant V4 Swing Trading System — Project Status

> Last updated: 2026-04-01
> Author: Claude Code (Opus 4.6)
> Purpose: Session continuity — 새 세션에서 이 파일 참조하여 프롬프트 없이 작업 이어서 진행

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
PostgreSQL: postgresql://quant:QuantV31!Secure@localhost:5432/quantdb
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

## 3. Current State (2026-04-01)

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
| Broker 연동 | PARTIAL | KIS 시뮬레이션 모드(SIM-*). live 모드 toggle 가능 |

### Live Trading State
- **Trading Mode**: `paper` (시뮬레이션)
- **Initial Capital**: $1,000
- **Open Positions**: 1개 (MRVL 1주 @ $99.05)
- **Position Sizing**: 14% per position ($140)
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
| Engine V3.1 (legacy) | 8000 | quant-engine.service | inactive |

### Service Management (sudo 없이)
```bash
# 재시작: 프로세스 kill → systemd Restart=always가 12초 후 자동 재시작
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

## 19. V3.1 Legacy System (참고용)

V3.1은 V4 이전의 레짐 적응형 시스템. 현재 비활성이지만 코드와 DB 테이블 존재.

### V3.1 핵심 구성
- HMM 3-State 레짐 감지 (Bull/Sideways/Bear)
- Kill Switch 4-Level (NORMAL→WARNING→DEFENSIVE→EMERGENCY)
- 5개 전략: LowVol Quality, Vol Momentum, Pairs Trading, Vol Targeting, Sentiment
- 8-step Daily Pipeline Orchestrator
- **최종 결과**: STOP (WF Sharpe=0.59, Stress FPR=50% — GO 기준 미달)
- **V3.1 → V4 전환 이유**: 백테스트 결과가 GO 기준 미달 → 모멘텀 스윙 트레이딩으로 전환

---

## 20. Git History

```
PENDING  fix: position_pct 입력 검증 (>1.0 자동 보정) + MRVL 재진입
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

## 21. For Claude Code — Session Continuity

새 세션 시작 시:

1. **Read this file**: `project_status.md` (전체 시스템 현황)
2. **Read CLAUDE.md**: 코딩 규칙 (psycopg3, TimescaleDB, Npgsql Raw SQL)
3. **Current state**: V4 Swing Trading 시스템 운영 중, 1개 포지션 오픈 (MRVL 1주, paper mode)
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
