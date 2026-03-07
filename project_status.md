# Quant V4 Swing Trading System — Project Status

> Last updated: 2026-03-07
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
Entry: 모멘텀 상위 40% + 트렌드 정렬(SMA50 > SMA200) + 거래량 서지(ratio > 1.2x)
Exit: Stop Loss -5% / Take Profit +10% / 트렌드 역전
Position Sizing: position_pct(5%) × initial_capital / entry_price
```

---

## 2. Architecture (V3.1 vs V4 — 두 시스템 공존)

### V4 (현재 활성, Swing Trading)
```
engine_v4/
├── api/main.py           # FastAPI (port 8001) — 전체 API + 스냅샷 생성
├── config/settings.py    # SwingSettings (Pydantic)
├── data/
│   ├── storage.py        # PostgresStore + RedisCache (psycopg3, dict_row)
│   └── collector.py      # DataCollector (yfinance) + UniverseManager
├── ai/sentiment.py       # SentimentAnalyzer (Claude API + mock fallback) [Phase A]
├── strategy/swing.py     # SwingStrategy (scan_entries, scan_exits)
├── risk/position_manager.py  # PositionManager (validate + execute)
├── broker/kis_client.py  # KIS 증권 API (paper=SIM 시뮬레이션)
├── scheduler/jobs.py     # APScheduler (6 jobs, KST 기준)
├── notify/telegram.py    # Telegram 알림 (미연결)
└── backtest/runner.py    # Backtest 시뮬레이터
```

### V3.1 (레거시, Regime-Adaptive)
- `engine/` 디렉토리 — HMM 레짐 + Kill Switch + 5전략 + VWAP
- Old pages backed up to `dashboard/.../Pages/_v31_backup/`
- V3.1과 V4는 같은 DB(`quantdb`)를 사용하지만 테이블 prefix가 다름 (V3.1: 일반, V4: `swing_*`)

---

## 3. Current State (2026-03-07)

### Phase 완료 상태
| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1: DB + Engine | COMPLETE | swing_* 테이블 10개, engine_v4 전체 구현 |
| Phase 2: Dashboard | COMPLETE | 8개 페이지 + 로그인 + 테마 |
| Phase 3: E2E Pipeline | COMPLETE | Universe→Collect→Scan→Approve→Monitor 전체 동작 확인 |
| Phase A: LLM Sentiment | COMPLETE | AI 분석 (Mock+Live), Signals 페이지 AI Score 표시 |
| Phase B: Exit Strategy | COMPLETE | Trailing Stop + Partial Exit, scheduler 통합 |
| Broker 연동 | PARTIAL | KIS 시뮬레이션 모드(SIM-*). 실제 API 키 미설정 |
| Telegram 알림 | NOT CONNECTED | 봇 토큰 미설정 |

### Live Trading State
- **Trading Mode**: `paper` (시뮬레이션)
- **Initial Capital**: $2,200 (Settings에서 변경 가능: `initial_capital`)
- **Open Positions**: 3개 (FANG $179.04, VLO $228.03, ROST $213.52)
- **Total Portfolio Value**: ~$2,201
- **Cash**: ~$1,579 / **Invested**: ~$622

### 최근 작업 (2026-03-05~06)
1. Pipeline 페이지 구현 (5단계 카드 + 실행 버튼 + 팝업 모달 + 로그)
2. Signals 페이지에 Revert 버튼 추가 (approved/rejected → pending)
3. E2E 파이프라인 테스트: Universe(196) → Collect(196) → Scan(3 entries) → Approve(3) → 포지션 생성 확인
4. `max_daily_entries` 1→4로 변경 (일일 진입 제한이 너무 낮았음)
5. **Snapshot 생성 시스템 구현**: POST /snapshot/generate + 스케줄러 자동 생성 + Performance 버튼

---

## 4. Dashboard Pages (8 pages + Login)

| Page | Route | File | Description |
|------|-------|------|-------------|
| Login | `/login` | `Login.razor` | Cookie 인증 (gradient orb, glass card) |
| Dashboard | `/` | `Home.razor` | Portfolio overview, equity mini-chart, 최근 거래 |
| **Pipeline** | `/pipeline` | `Pipeline.razor` | **5단계 파이프라인 시각화 + 실행 버튼 + 팝업 모달** |
| Signals | `/signals` | `Signals.razor` | 시그널 목록 (pending/approved/rejected/executed/expired), Approve/Reject/Revert |
| Performance | `/performance` | `Performance.razor` | Equity Curve, Drawdown 차트, **Update Snapshot 버튼**, Backtest 성과 |
| Positions | `/positions` | `Positions.razor` | 오픈/청산 포지션 목록 |
| Backtest | `/backtest` | `Backtest.razor` | 백테스트 실행 + 결과 (equity curve with trade markers) |
| Settings | `/settings` | `Settings.razor` | swing_config 편집 (execution, strategy, risk, notify) |

### Nav Menu 순서
Dashboard → Pipeline → Signals → Performance → Positions → Backtest → Settings

### Shared Components
- `SymbolLink.razor` — 심볼 클릭 → SymbolDetailModal 또는 Google Finance
- `SymbolDetailModal.razor` — 심볼 상세 팝업 (z-index: 9500)
- `SortState.cs` — 정렬 상태 관리 (테이블 헤더 클릭)
- `PageLoadingOverlay.razor` — 페이지 로딩 오버레이
- `HelpTooltip.razor` — '?' 아이콘 도움말 풍선

### Chart System
- `wwwroot/js/charts.js` — Chart.js wrapper
  - `chartHelper.createLine()` — 라인 차트 (equity, drawdown)
  - `chartHelper.createLineWithTrades()` — 라인 + BUY/SELL 마커 (backtest)
  - Custom drag-zoom, pan, adaptive x-axis ticks

---

## 5. Engine V4 API Routes

### Pipeline
| Method | Path | Type | Description |
|--------|------|------|-------------|
| POST | `/collect` | Background | 데이터 수집 (yfinance 300d) |
| POST | `/scan` | Sync | 시그널 스캔 (entries + exits) |
| POST | `/pipeline/run` | Background | 전체 파이프라인 (Collect→Scan→Notify) |
| POST | `/universe/refresh` | Background | 유니버스 갱신 |

### Signals & Positions
| Method | Path | Description |
|--------|------|-------------|
| GET | `/signals` | 시그널 목록 (?status=pending) |
| POST | `/signals/{id}/approve` | 시그널 승인 → 자동 체결 |
| POST | `/signals/{id}/reject` | 시그널 거부 |
| GET | `/positions` | 오픈 포지션 |
| GET | `/positions/closed` | 청산 포지션 |

### Portfolio & Snapshot
| Method | Path | Description |
|--------|------|-------------|
| GET | `/portfolio` | 최신 스냅샷 + 포지션 |
| GET | `/portfolio/history` | 스냅샷 이력 (?days=30) |
| **POST** | **`/snapshot/generate`** | **수동 스냅샷 생성 (yfinance 현재가 조회 → DB 저장)** |

### Others
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | 엔진 상태 |
| GET | `/account` | KIS 계좌 정보 |
| GET/PUT | `/config`, `/config/{key}` | 설정 조회/변경 |
| POST | `/backtest/run` | 백테스트 실행 |
| GET | `/backtest/results/{run_id}` | 백테스트 결과 (equity_curve, trades_log) |
| GET | `/scheduler` | 스케줄러 잡 목록 |
| GET | `/trades` | 거래 내역 |

---

## 6. Scheduler Jobs (APScheduler, KST 기준)

| Job | 시간 (KST) | 기능 | 스냅샷 생성 |
|-----|-----------|------|------------|
| daily_pipeline | 월~토 07:00 | Collect + Scan + Notify | **Yes** |
| exit_check_1 | 월~금 23:30 | 장중 청산 체크 (09:30 ET) | **Yes** |
| exit_check_2 | 화~토 01:00 | 장중 청산 체크 (11:00 ET) | **Yes** |
| exit_check_3 | 화~토 03:00 | 장중 청산 체크 (13:00 ET) | **Yes** |
| refresh_universe | 토 10:00 | 유니버스 주간 갱신 | No |
| expire_signals | 매일 06:00 | 만료 시그널 정리 | No |

---

## 7. Database Schema (swing_* tables)

| Table | Type | Description |
|-------|------|-------------|
| swing_universe | regular | 유니버스 종목 (~200개, is_active 플래그) |
| swing_indicators | hypertable | 기술 지표 (SMA50/200, return_20d_rank, volume_ratio) |
| swing_signals | regular | 시그널 (pending/approved/rejected/executed/expired) |
| swing_positions | regular | 포지션 (open/closed, entry/exit/pnl) |
| swing_trades | regular | 거래 내역 (BUY/SELL, paper trade) |
| swing_snapshots | hypertable | **포트폴리오 스냅샷** (total_value, cash, invested, drawdown) |
| swing_config | regular | 설정 키-값 (initial_capital, max_positions, etc.) |
| swing_backtest_runs | regular | 백테스트 실행 결과 |
| swing_pipeline_log | hypertable | 파이프라인 실행 로그 |
| users | regular | 인증 사용자 (bcrypt) |

### Key Config Values (swing_config)
```
initial_capital    = 2200      ← Settings 페이지에서 변경 가능
max_positions      = 4
max_daily_entries  = 4
position_pct       = 0.05 (5%)
stop_loss_pct      = -0.05 (-5%)
take_profit_pct    = 0.10 (+10%)
return_rank_min    = 0.6 (상위 40%)
volume_ratio_min   = 1.2
price_range_min    = 20
price_range_max    = 250
trading_mode       = paper
```

---

## 8. Snapshot Generation System

### 포트폴리오 계산 공식
```
initial_capital = swing_config['initial_capital']  (기본 $2,200)
entry_cost      = Σ(qty × entry_price) for open positions
realized_pnl    = Σ(realized_pnl) for closed positions
cash            = initial_capital + realized_pnl - entry_cost
invested        = Σ(qty × current_price) for open positions  ← yfinance 실시간
total_value     = cash + invested
cumulative_return = (total_value / initial_capital) - 1
```

### 생성 시점
1. **수동**: Performance 페이지 "Update Snapshot" 버튼 → `POST /snapshot/generate`
2. **자동**: 스케줄러 daily_pipeline (07:00 KST) + exit_check (3회/일)
3. **Pipeline 페이지**: Step 5 Monitor 카드에서도 상태 확인 가능

### Backtest vs Live Trading
- **Backtest**: 과거 데이터로 전략 검증 (Initial Capital 별도 입력)
- **Pipeline**: 동일 전략을 실시간 시장에 적용 (Settings의 initial_capital 사용)
- 같은 전략 로직이지만 **종목은 다름** (시장 조건이 다르므로)

---

## 9. Services & Systemd

| Service | Port | systemd | Status |
|---------|------|---------|--------|
| PostgreSQL (Docker) | 5432 | docker.service | active |
| Redis (Docker) | 6379 | docker.service | active |
| Engine V4 | 8001 | quant-engine-v4.service | active |
| Dashboard | 5000 | quant-dashboard.service | active |
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
```

---

## 10. Key Bug Fixes & Learnings

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `column "updated_at" does not exist` | swing_indicators has `time`, not `updated_at` | `max(time)` 사용 |
| Universe refresh polling timeout | /universe/refresh가 pipeline_log에 안 씀 | DB count 직접 폴링 |
| Collect polling timeout (60s) | Collect가 93초 소요 | timeout 300초로 증가 |
| `max_daily_entries` 1/1 에러 | 기본값이 1이라 하루 1개만 진입 | 4로 변경 |
| Snapshot 그래프 안 보임 | V4 스케줄러에 스냅샷 잡 없었음 | generate_snapshot 구현 + 스케줄러 통합 |
| psycopg3 interval binding | `interval '%s days'` 안 됨 | `make_interval(days => %s)` 사용 |
| yfinance market cap 느림 | `yf.Tickers().info` 1~3초/종목 | `yf.download()` dollar-volume proxy |
| SMA200 데이터 부족 | 200일 이평 계산에 200일+ 필요 | `collect_prices(days=300)` |
| Wikipedia S&P500 403 | User-Agent 없으면 차단 | requests + UA header + fallback seed list |

---

## 11. File Structure

```
quant-v31/
├── CLAUDE.md                           # Claude Code 프로젝트 지침
├── project_status.md                   # THIS FILE (세션 연속성)
├── docker-compose.yml
│
├── engine_v4/                          # V4 Swing Trading Engine
│   ├── api/main.py                     # FastAPI + 모든 API 라우트 + _generate_snapshot()
│   ├── config/settings.py              # SwingSettings (pg_dsn, redis, trading_mode, etc.)
│   ├── data/
│   │   ├── storage.py                  # PostgresStore + RedisCache (psycopg3)
│   │   └── collector.py                # DataCollector(yfinance) + UniverseManager
│   ├── strategy/swing.py               # SwingStrategy (scan_entries, scan_exits)
│   ├── risk/position_manager.py        # PositionManager (validate_entry, execute_entry/exit)
│   ├── broker/kis_client.py            # KIS API (paper: SIM-* orders)
│   ├── scheduler/jobs.py               # SwingScheduler (6 jobs + generate_snapshot)
│   ├── notify/telegram.py              # TelegramNotifier
│   └── backtest/runner.py              # BacktestRunner + BacktestParams
│
├── engine/                             # V3.1 Legacy Engine (inactive)
│   └── ...                             # HMM, Kill Switch, 5 strategies, gRPC
│
├── dashboard/QuantDashboard/           # Blazor Server (.NET 8)
│   ├── Program.cs                      # DI + Cookie Auth + HttpClientFactory("Engine")
│   ├── Models/
│   │   ├── DashboardModels.cs          # V3.1 models
│   │   └── SwingModels.cs              # V4 models (SwingSignal, SwingPosition, SwingSnapshot, etc.)
│   ├── Services/
│   │   ├── SwingService.cs             # V4 DB queries (swing_* tables) ← 주 서비스
│   │   ├── PostgresService.cs          # V3.1 DB queries (legacy)
│   │   └── AuthService.cs              # Cookie 인증
│   ├── Components/
│   │   ├── App.razor                   # <script src="js/charts.js">
│   │   ├── SymbolLink.razor            # 심볼 클릭 → OnSymbolClick callback
│   │   ├── SymbolDetailModal.razor     # 심볼 상세 팝업 (z-index: 9500)
│   │   ├── SortState.cs                # 테이블 정렬 상태
│   │   ├── PageLoadingOverlay.razor
│   │   ├── HelpTooltip.razor
│   │   ├── Layout/
│   │   │   ├── MainLayout.razor        # Dark theme + sidebar + top-bar
│   │   │   ├── LoginLayout.razor
│   │   │   └── NavMenu.razor           # 7 nav items + pending badge
│   │   └── Pages/
│   │       ├── Login.razor
│   │       ├── Home.razor              # Dashboard
│   │       ├── Pipeline.razor          # 5단계 파이프라인 + 실행 + 팝업
│   │       ├── Signals.razor           # 시그널 관리 (Approve/Reject/Revert)
│   │       ├── Performance.razor       # Equity/Drawdown 차트 + Update Snapshot
│   │       ├── Positions.razor         # 포지션 목록
│   │       ├── Backtest.razor          # 백테스트 실행/결과
│   │       └── Settings.razor          # 설정 편집
│   └── wwwroot/
│       ├── app.css                     # Dark navy theme (전면 재작성)
│       └── js/charts.js               # Chart.js wrapper (line, trade markers, zoom)
│
├── scripts/
│   ├── init_swing_db.sql               # V4 swing_* 테이블 스키마
│   ├── migrate_pipeline_log.sql
│   ├── migrate_user_settings.sql
│   └── ... (V3.1 scripts)
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

## 12. Pipeline Operations Guide (운영 가이드)

### 일일 운영 흐름
```
1. Pipeline 페이지 접속
   ├─ Step 1: Refresh Universe (주 1회, 토요일 자동)
   ├─ Step 2: Collect Data (매일 자동 07:00 KST, 수동도 가능)
   ├─ Step 3: Scan Signals → pending 시그널 생성
   ├─ Step 4: Signals 페이지 → 시그널 검토 → Approve/Reject
   └─ Step 5: Performance 페이지 → Update Snapshot → 포트폴리오 추적

2. 장중 청산 체크 (자동, 3회/일)
   ├─ 23:30 KST (09:30 ET) — 장 시작
   ├─ 01:00 KST (11:00 ET) — 장중
   └─ 03:00 KST (13:00 ET) — 장중

3. Performance 모니터링
   ├─ "Update Snapshot" 클릭 → 현재가 반영
   ├─ Equity Curve / Drawdown 차트 확인
   └─ Stats: Win Rate, Total P&L, Max Drawdown
```

### API 명령어 모음
```bash
# 파이프라인 실행
curl -X POST http://localhost:8001/collect           # 데이터 수집
curl -X POST http://localhost:8001/scan              # 시그널 스캔
curl -X POST http://localhost:8001/pipeline/run      # 전체 파이프라인
curl -X POST http://localhost:8001/universe/refresh   # 유니버스 갱신

# 시그널 관리
curl http://localhost:8001/signals?status=pending
curl -X POST http://localhost:8001/signals/1/approve
curl -X POST http://localhost:8001/signals/1/reject

# 포트폴리오
curl -X POST http://localhost:8001/snapshot/generate  # 스냅샷 수동 생성
curl http://localhost:8001/portfolio                   # 최신 스냅샷
curl http://localhost:8001/positions                   # 오픈 포지션

# 설정
curl http://localhost:8001/config
curl -X PUT http://localhost:8001/config/initial_capital -H "Content-Type: application/json" -d '{"value":"5000"}'

# 상태 확인
curl http://localhost:8001/health
curl http://localhost:8001/scheduler
```

---

## 13. V3.1 Legacy System (참고용)

V3.1은 V4 이전의 레짐 적응형 시스템. 현재 비활성이지만 코드와 DB 테이블 존재.

### V3.1 핵심 구성
- HMM 3-State 레짐 감지 (Bull/Sideways/Bear)
- Kill Switch 4-Level (NORMAL→WARNING→DEFENSIVE→EMERGENCY)
- 5개 전략: LowVol Quality, Vol Momentum, Pairs Trading, Vol Targeting, Sentiment
- 8-step Daily Pipeline Orchestrator
- GO/STOP 판정 시스템 (Backtest Phase 4)
- **최종 결과**: STOP (2/4 criteria 통과, WF Sharpe=0.59, Stress FPR=50%)

### V3.1 → V4 전환 이유
V3.1의 백테스트 결과가 GO 기준 미달 → 전략 방향을 모멘텀 스윙 트레이딩으로 전환

---

## 14. AI 강화 수익률 극대화 로드맵 (5-Phase Development Plan)

> **목표**: 규칙 기반 시그널 + LLM 지능 + 실시간 이벤트 반응을 결합하여 수익률 극대화
> **근거**: OpenClaw/TradingAgents 등 업계 사례 분석 결과, LLM을 "트레이더"가 아닌 "전략 엔지니어/분석가"로 활용할 때 가장 효과적 (NexusTrade 연구)
> **참고**: 칭화대 연구 — LLM 직접 매매 수익률 2.5%, 위험조정수익률 0.031 (실패)
>          TradingAgents 멀티에이전트 — 누적수익률 24.57% 개선, Sharpe 8.21 (성공)

### 전체 아키텍처 (완성 시)

```
                        ┌─────────────────────┐
                        │   Real-time Events   │  ◀── Phase E
                        │  (News/Earnings/SEC) │
                        └──────────┬──────────┘
                                   │ WebSocket/Polling
                                   ▼
┌──────────┐    ┌──────────────────────────────────────┐    ┌──────────┐
│ Universe │───▶│          Signal Generation           │───▶│  Signals  │
│ Collect  │    │                                      │    │  (pending)│
│ Indicators│   │  기술 분석 (기존) ─── 40%             │    └────┬─────┘
│          │    │  LLM 감성 분석 ───── 30%  ◀── Phase A│         │
│          │    │  수급/이벤트 분석 ── 30%  ◀── Phase C│         ▼
└──────────┘    └──────────────────────────────────────┘  ┌──────────────┐
                                                          │ LLM 종목 분석 │ ◀── Phase A
                                                          │ (뉴스/실적/섹터)│
                                                          └──────┬───────┘
                                                                 ▼
                                                          ┌──────────────┐
                                                          │ Human Approve │
                                                          │ (Signals 페이지)│
                                                          └──────┬───────┘
                                                                 ▼
                        ┌──────────────────────────────────────────────┐
                        │            Position Management               │
                        │  Trailing Stop + Partial Exit  ◀── Phase B   │
                        │  Snapshot + Performance Tracking              │
                        └──────────────────────────────────────────────┘
                                                                 │
                        ┌──────────────────────────────────────────────┐
                        │         Strategy Optimization Agent          │ ◀── Phase D
                        │  파라미터 탐색 → 백테스트 → 최적화 반복        │
                        └──────────────────────────────────────────────┘
```

---

### Phase A: LLM Sentiment Overlay — COMPLETE (2026-03-07)

> **목표**: 시그널 승인 전에 LLM이 해당 종목의 뉴스/실적/섹터 맥락을 분석하여 점수 제공
> **효과**: 나쁜 시그널 필터링으로 승률 30%+ 개선 예상
> **비용**: Claude API ~$0.01/종목, 일일 ~$1 이하
> **상태**: COMPLETE — Mock 모드 동작 중 (ANTHROPIC_KEY 설정 시 Claude Haiku 4.5 사용)

#### A-1. DB 스키마 확장
```sql
-- swing_signals 테이블에 LLM 분석 컬럼 추가
ALTER TABLE swing_signals ADD COLUMN llm_score INTEGER;        -- 1~10점
ALTER TABLE swing_signals ADD COLUMN llm_analysis TEXT;         -- 분석 근거
ALTER TABLE swing_signals ADD COLUMN llm_analyzed_at TIMESTAMPTZ;
```

#### A-2. Engine: LLM 분석 모듈 (`engine_v4/ai/sentiment.py`)
```python
# 핵심 구조
class SentimentAnalyzer:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.Anthropic(api_key=api_key)

    async def analyze_signal(self, symbol: str, signal: dict) -> dict:
        """시그널에 대한 LLM 감성 분석.

        Returns: {"score": 1~10, "analysis": "근거 텍스트"}
        """
        # 1) yfinance로 종목 기본 정보 조회 (섹터, 시가총액, 52주 고저)
        # 2) Finnhub/yfinance에서 최근 뉴스 5건 조회
        # 3) Claude API에 분석 요청:
        #    "Symbol: FANG, Entry: $179, 모멘텀 상위 30%.
        #     뉴스: [...]. 매수 적합도를 1~10으로 평가하라."
        # 4) 점수 + 분석 결과 반환
```

#### A-3. Engine: 시그널 생성 시 자동 분석 호출
- `strategy/swing.py` → `scan_entries()` 에서 시그널 생성 직후 `SentimentAnalyzer.analyze_signal()` 호출
- 또는 별도 API 엔드포인트: `POST /signals/{id}/analyze` (수동 트리거)

#### A-4. Dashboard: Signals 페이지에 LLM 분석 표시
- Signals 테이블에 "AI Score" 컬럼 추가 (1~10, 색상 코딩)
- Score 클릭 시 팝업으로 상세 분석 텍스트 표시
- 시그널 승인 시 AI Score 참고하여 판단

#### A-5. 수정 파일 목록
| 파일 | 작업 |
|------|------|
| `scripts/migrate_llm_analysis.sql` | 신규: ALTER TABLE + 인덱스 |
| `engine_v4/ai/__init__.py` | 신규: 패키지 |
| `engine_v4/ai/sentiment.py` | 신규: SentimentAnalyzer 클래스 |
| `engine_v4/config/settings.py` | 수정: anthropic_api_key 추가 |
| `engine_v4/api/main.py` | 수정: POST /signals/{id}/analyze 엔드포인트 |
| `engine_v4/strategy/swing.py` | 수정: scan_entries에서 분석 호출 (선택) |
| `engine_v4/data/storage.py` | 수정: update_signal_llm_analysis 메서드 |
| `dashboard/.../SwingModels.cs` | 수정: SwingSignal에 LlmScore, LlmAnalysis 필드 |
| `dashboard/.../SwingService.cs` | 수정: GetSignals 쿼리에 llm 컬럼 추가 |
| `dashboard/.../Signals.razor` | 수정: AI Score 컬럼 + 팝업 |

---

### Phase B: Exit 전략 고도화 — COMPLETE (2026-03-07)

> **목표**: 현재 고정 SL/TP(-5%/+10%)에서 Trailing Stop + Partial Exit로 수익 극대화
> **효과**: 상승 추세에서 수익 실현 타이밍 개선, 평균 수익률 20~50% 개선 예상
> **비용**: $0
> **상태**: COMPLETE — ExitManager 구현, scheduler 통합, dashboard 표시

#### B-1. Trailing Stop Loss 구현
```python
# 현재: 고정 SL -5%
# 개선: 가격이 +5% 이상 오르면 SL을 진입가 위로 이동

class TrailingStopManager:
    def update_stop(self, position, current_price):
        gain_pct = (current_price - position.entry_price) / position.entry_price
        if gain_pct >= 0.05:  # +5% 이상 수익
            # SL = current_price * (1 - trailing_pct)
            new_sl = current_price * 0.97  # 현재가 -3%로 SL 상향
            if new_sl > position.stop_loss:
                position.stop_loss = new_sl  # SL은 올리기만 함 (내리지 않음)
```

#### B-2. Partial Exit (분할 청산) 구현
```python
# +7% 도달 시 50% 청산, 나머지 50%는 trailing stop으로 추적
# 예: 100주 매수 → +7%에 50주 청산(수익 확보) → 나머지 50주는 +10%~+20% 노림

class PartialExitManager:
    def check_partial_exit(self, position, current_price):
        gain_pct = (current_price - position.entry_price) / position.entry_price
        if gain_pct >= 0.07 and not position.partial_exited:
            return {"action": "partial_sell", "qty_pct": 0.5}
```

#### B-3. swing_config에 새 파라미터 추가
```
trailing_stop_activation = 0.05    # +5% 수익 시 trailing 활성화
trailing_stop_distance   = 0.03    # 현재가 대비 -3% trailing
partial_exit_threshold   = 0.07    # +7% 수익 시 50% 분할 청산
partial_exit_pct         = 0.5     # 분할 청산 비율 (50%)
```

#### B-4. 수정 파일 목록
| 파일 | 작업 |
|------|------|
| `engine_v4/risk/exit_manager.py` | 신규: TrailingStopManager + PartialExitManager |
| `engine_v4/scheduler/jobs.py` | 수정: exit_check에서 trailing/partial 로직 통합 |
| `engine_v4/data/storage.py` | 수정: update_position_stop, partial_close_position |
| `scripts/migrate_exit_strategy.sql` | 신규: swing_positions에 partial_exited 등 컬럼 |
| `dashboard/.../Positions.razor` | 수정: trailing SL, partial exit 상태 표시 |

---

### Phase C: Multi-Factor Scoring Agent (중기)

> **목표**: 기술 지표 외에 감성/수급/이벤트 팩터를 추가하여 멀티팩터 스코어링
> **효과**: TradingAgents 패턴 — 단일 팩터 대비 24.57% 수익률 개선
> **비용**: Claude API ~$3/일

#### C-1. 스코어링 아키텍처
```
┌─────────────────────────────────────────────────┐
│              Multi-Factor Scoring Engine          │
├─────────────────────────────────────────────────┤
│                                                  │
│  Technical Score (40%)                           │
│  ├─ 모멘텀 순위 (return_20d_rank)                │
│  ├─ 트렌드 정렬 (SMA50 > SMA200)                │
│  ├─ 거래량 서지 (volume_ratio > 1.2)             │
│  └─ RSI, MACD 추가 가능                          │
│                                                  │
│  Sentiment Score (30%) ← Claude API              │
│  ├─ 최근 뉴스 감성 (positive/negative/neutral)    │
│  ├─ 실적 발표 근접도 및 예상 (earnings surprise)   │
│  └─ 섹터/산업 트렌드                              │
│                                                  │
│  Flow Score (30%) ← 데이터 API                    │
│  ├─ 기관 매수/매도 동향 (institutional flow)       │
│  ├─ 내부자 거래 (insider transactions)             │
│  └─ 옵션 시장 풋/콜 비율 (put-call ratio)          │
│                                                  │
│  ═══════════════════════════════════════════════  │
│  Composite Score = T*0.4 + S*0.3 + F*0.3         │
│  시그널 생성 기준: Composite >= 70                  │
└─────────────────────────────────────────────────┘
```

#### C-2. 데이터 소스
| Factor | Source | 비용 | 방법 |
|--------|--------|------|------|
| 뉴스 감성 | Finnhub Company News API | 무료 (60 calls/min) | REST polling |
| 실적 캘린더 | Finnhub Earnings Calendar | 무료 | REST polling |
| 내부자 거래 | Finnhub Insider Transactions | 무료 | REST polling |
| 기관 보유 | Finnhub Institutional Ownership | 무료 | REST polling |
| 감성 분석 | Claude API (뉴스 텍스트 분석) | ~$0.01/종목 | API |

#### C-3. 수정 파일 목록
| 파일 | 작업 |
|------|------|
| `engine_v4/ai/multi_factor.py` | 신규: MultiFactorScorer 클래스 |
| `engine_v4/ai/data_feeds.py` | 신규: FinnhubClient (뉴스/실적/내부자) |
| `engine_v4/strategy/swing.py` | 수정: scan_entries에 멀티팩터 스코어링 통합 |
| `engine_v4/data/storage.py` | 수정: 스코어 저장 메서드 |
| `scripts/migrate_multi_factor.sql` | 신규: swing_signals에 factor 점수 컬럼들 |
| `dashboard/.../Signals.razor` | 수정: 팩터별 점수 게이지 표시 |

---

### Phase D: LLM 전략 최적화 Agent (장기)

> **목표**: LLM이 전략 파라미터를 제안 → 자동 백테스트 → 최적 파라미터 탐색
> **효과**: 수동 파라미터 튜닝 자동화, 시장 변화에 적응하는 전략 진화
> **비용**: Claude API ~$5/최적화 세션 + 백테스트 서버 시간
> **참고**: NexusTrade 패턴 — "LLM을 트레이더가 아닌 전략 엔지니어로 사용"

#### D-1. 최적화 루프
```
┌────────────────────────────────────────────────────────┐
│                Strategy Optimization Loop               │
│                                                        │
│  1. 현재 파라미터 + 백테스트 결과 → Claude에 전달       │
│     "현재 return_rank_min=0.6, Sharpe=0.8.              │
│      더 나은 파라미터 조합 5가지를 제안하라."             │
│                                                        │
│  2. Claude 응답 → 5개 파라미터 세트 파싱                 │
│     [{return_rank_min: 0.5, volume_ratio_min: 1.3, ...}] │
│                                                        │
│  3. 각 세트로 백테스트 자동 실행 (POST /backtest/run)    │
│                                                        │
│  4. 결과 비교 → 최고 Sharpe/최저 MDD 선택               │
│                                                        │
│  5. 선택된 파라미터 → Claude에 다시 전달 → 2차 최적화    │
│     (유전 알고리즘 방식으로 3~5회 반복)                   │
│                                                        │
│  6. 최종 결과 → 사람에게 리포트 → 승인 시 적용           │
└────────────────────────────────────────────────────────┘
```

#### D-2. 수정 파일 목록
| 파일 | 작업 |
|------|------|
| `engine_v4/ai/optimizer.py` | 신규: StrategyOptimizer 클래스 |
| `engine_v4/api/main.py` | 수정: POST /optimize/run 엔드포인트 |
| `dashboard/.../Pages/Backtest.razor` | 수정: "AI Optimize" 버튼 + 결과 비교 테이블 |

---

### Phase E: Real-time Event-Driven System (실시간 이벤트 반응)

> **목표**: OpenClaw의 webhook/heartbeat 기능을 자체 구현 — 외부 이벤트 발생 시 즉각 반응
> **효과**: 실적 발표, 급등/급락, 뉴스 이벤트에 즉시 대응 (현재: 1일 1회 스캔 → 실시간)
> **비용**: Finnhub 무료 tier + 서버 리소스

#### E-1. 아키텍처
```
┌────────────────────────────────────────────────────────────────┐
│                   Event-Driven Architecture                    │
│                                                                │
│  [Data Sources]              [Event Processor]    [Actions]    │
│                                                                │
│  Finnhub WebSocket ─────┐                                      │
│  (실시간 가격 변동)       │    ┌─────────────┐                  │
│                          ├───▶│  Event Bus   │                  │
│  Finnhub REST Polling ──┤    │  (asyncio    │  ┌─────────────┐ │
│  (뉴스/실적/내부자)      │    │   Queue)     │─▶│ Alert Engine │ │
│                          │    └──────┬──────┘  │             │ │
│  SEC EDGAR RSS ─────────┤           │          │ - 시그널 생성│ │
│  (공시/13F)              │           ▼          │ - LLM 분석  │ │
│                          │    ┌─────────────┐  │ - Telegram  │ │
│  TradingView Webhook ───┤    │ Rule Engine  │  │ - 대시보드   │ │
│  (차트 알림, 선택사항)    │    │             │  │   SSE 푸시  │ │
│                          │    │ - 급등/급락  │  └─────────────┘ │
│  yfinance Polling ──────┘    │ - 실적 서프  │                  │
│  (실적 캘린더)                │ - SL/TP 도달│                  │
│                               │ - 뉴스 감성 │                  │
│                               └─────────────┘                  │
└────────────────────────────────────────────────────────────────┘
```

#### E-2. 이벤트 유형 및 반응 규칙
| 이벤트 | 소스 | 감지 방법 | 자동 반응 |
|--------|------|----------|----------|
| 종목 급등 (+5% 이상) | Finnhub WebSocket | 실시간 가격 모니터링 | 보유 종목이면 TP 상향 검토 알림 |
| 종목 급락 (-5% 이상) | Finnhub WebSocket | 실시간 가격 모니터링 | 보유 종목이면 긴급 SL 검토 알림 |
| 실적 발표 서프라이즈 | Finnhub Earnings | 실적 캘린더 + 결과 비교 | 긍정: 매수 시그널 가산점 / 부정: 보유 종목 청산 검토 |
| 부정적 뉴스 (소송/리콜 등) | Finnhub News | LLM 감성 분석 | 보유 종목이면 즉시 청산 검토 알림 |
| 내부자 대량 매도 | Finnhub Insider | 주기적 폴링 | 매수 시그널 감점 / 보유 종목 경고 |
| SEC 공시 (13F/8-K) | SEC EDGAR RSS | RSS 폴링 | LLM 분석 후 영향도 판단 |
| TradingView 알림 | Webhook POST | FastAPI 엔드포인트 | 외부 차트 알림 → 시그널 연동 |

#### E-3. 구현 컴포넌트

**E-3a. Event Collector Service (`engine_v4/events/collector.py`)**
```python
class EventCollector:
    """이벤트 수집기 — 다중 소스에서 이벤트를 수집하여 큐에 전달."""

    def __init__(self, queue: asyncio.Queue, config):
        self.queue = queue
        self.finnhub_key = config.finnhub_api_key  # 무료 키

    async def start_price_monitor(self, symbols: list[str]):
        """Finnhub WebSocket으로 실시간 가격 모니터링."""
        # wss://ws.finnhub.io?token=xxx
        # 급등/급락 감지 → Event 생성 → queue.put()

    async def poll_news(self, symbols: list[str], interval: int = 300):
        """Finnhub Company News API 5분 간격 폴링."""
        # GET /api/v1/company-news?symbol=AAPL&from=2026-03-07&to=2026-03-07
        # 새 뉴스 감지 → LLM 감성 분석 → Event 생성

    async def poll_earnings(self, interval: int = 3600):
        """Finnhub Earnings Calendar 1시간 간격 폴링."""
        # GET /api/v1/calendar/earnings?from=2026-03-07&to=2026-03-14

    async def poll_insider(self, symbols: list[str], interval: int = 3600):
        """Finnhub Insider Transactions 1시간 간격 폴링."""
        # GET /api/v1/stock/insider-transactions?symbol=AAPL
```

**E-3b. Event Processor (`engine_v4/events/processor.py`)**
```python
class EventProcessor:
    """이벤트 처리기 — 규칙 엔진 + LLM 분석."""

    async def process(self, event: Event):
        match event.type:
            case "price_surge":
                await self._handle_price_surge(event)
            case "price_drop":
                await self._handle_price_drop(event)
            case "earnings_surprise":
                await self._handle_earnings(event)
            case "negative_news":
                await self._handle_news(event)
            case "insider_sell":
                await self._handle_insider(event)
            case "tradingview_alert":
                await self._handle_tv_alert(event)
```

**E-3c. Webhook Receiver (`engine_v4/api/main.py`에 추가)**
```python
@app.post("/webhook/tradingview")
async def tradingview_webhook(payload: dict):
    """TradingView 웹훅 수신 → 이벤트 큐에 전달."""
    event = Event(type="tradingview_alert", data=payload)
    await event_queue.put(event)
    return {"status": "received"}

@app.get("/events/stream")
async def event_stream():
    """SSE(Server-Sent Events)로 대시보드에 실시간 이벤트 푸시."""
    # Dashboard가 이 엔드포인트를 구독하여 실시간 알림 수신
```

**E-3d. Dashboard 실시간 알림 (`dashboard/.../Components/EventAlert.razor`)**
- SSE 또는 SignalR로 이벤트 수신
- 화면 상단에 토스트 알림 표시
- 이벤트 히스토리 페이지 (Events 탭)

#### E-4. 외부 서비스 API 키 필요
| 서비스 | 용도 | 무료 tier | 키 설정 |
|--------|------|----------|---------|
| Finnhub | 뉴스/실적/내부자/가격 | 60 calls/min, WebSocket 포함 | `FINNHUB_API_KEY` |
| Anthropic | LLM 감성 분석 | 유료 (~$0.01/분석) | `ANTHROPIC_API_KEY` |
| TradingView | 차트 알림 (선택) | Pro 이상 필요 | Webhook URL 설정 |
| SEC EDGAR | 공시 RSS | 완전 무료 | 불필요 |

#### E-5. DB 스키마
```sql
CREATE TABLE swing_events (
    event_id   BIGSERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,    -- price_surge, news, earnings, insider, etc.
    symbol     VARCHAR(20),
    severity   VARCHAR(20),             -- info, warning, critical
    title      TEXT NOT NULL,
    detail     JSONB,
    llm_score  INTEGER,                 -- LLM 분석 점수 (있는 경우)
    action_taken VARCHAR(50),           -- alert_sent, signal_created, position_closed
    created_at TIMESTAMPTZ DEFAULT now()
);
SELECT create_hypertable('swing_events', 'created_at');
```

#### E-6. 수정 파일 목록
| 파일 | 작업 |
|------|------|
| `engine_v4/events/__init__.py` | 신규: 패키지 |
| `engine_v4/events/collector.py` | 신규: EventCollector (WebSocket + Polling) |
| `engine_v4/events/processor.py` | 신규: EventProcessor (규칙 엔진) |
| `engine_v4/events/models.py` | 신규: Event 데이터 모델 |
| `engine_v4/api/main.py` | 수정: /webhook/tradingview, /events/stream 추가 |
| `engine_v4/config/settings.py` | 수정: finnhub_api_key, anthropic_api_key 추가 |
| `engine_v4/scheduler/jobs.py` | 수정: EventCollector를 스케줄러에 통합 |
| `scripts/migrate_events.sql` | 신규: swing_events 테이블 |
| `dashboard/.../Components/EventAlert.razor` | 신규: 실시간 알림 토스트 |
| `dashboard/.../Pages/Events.razor` | 신규: 이벤트 히스토리 페이지 |
| `dashboard/.../Layout/NavMenu.razor` | 수정: Events 메뉴 추가 |

---

### 구현 순서 및 일정

```
Phase A: LLM Sentiment Overlay ─────── [COMPLETE ✓ 2026-03-07]
  A-1. DB 마이그레이션 ✓ (llm_score, llm_analysis, llm_analyzed_at)
  A-2. SentimentAnalyzer 모듈 ✓ (engine_v4/ai/sentiment.py, mock+live)
  A-3. API 엔드포인트 ✓ (POST /signals/{id}/analyze, POST /signals/analyze-pending)
  A-4. Dashboard 표시 ✓ (AI Score 컬럼, 분석 팝업, Analyze 버튼)
  A-5. 테스트 + 검증 ✓ (Mock 모드 7개 시그널 분석 완료)

Phase B: Exit 전략 고도화 ──────────── [COMPLETE ✓ 2026-03-07]
  B-1. DB migration (partial_exited, trailing_stop_active, high_water_mark) ✓
  B-2. ExitManager module (engine_v4/risk/exit_manager.py) ✓
  B-3. storage.py 메서드 추가 (update_position_stop_loss, partial_close, etc.) ✓
  B-4. scheduler exit_check 통합 (trailing → partial → standard exit) ✓
  B-5. Dashboard Positions 페이지 (TRAIL/PARTIAL 배지, flags) ✓

Phase C: Multi-Factor Scoring ─────── [우선순위 3]
  C-1. Finnhub 데이터 수집 모듈
  C-2. MultiFactorScorer
  C-3. 스캔 파이프라인 통합
  C-4. Dashboard 표시
  C-5. A/B 테스트 (단일팩터 vs 멀티팩터)

Phase D: Strategy Optimization ────── [우선순위 4]
  D-1. StrategyOptimizer 모듈
  D-2. 자동 백테스트 루프
  D-3. Dashboard UI
  D-4. 최적화 결과 분석

Phase E: Real-time Event System ───── [우선순위 5]
  E-1. DB 마이그레이션 (swing_events)
  E-2. EventCollector (Finnhub WebSocket + Polling)
  E-3. EventProcessor (규칙 엔진)
  E-4. Webhook 수신 엔드포인트
  E-5. Dashboard 실시간 알림
  E-6. Events 페이지
  E-7. Telegram 통합
```

### 필요 API 키 요약
| 키 | 용도 | Phase | 비용 |
|----|------|-------|------|
| `ANTHROPIC_API_KEY` | Claude API (감성분석, 최적화) | A, C, D | ~$5/월 |
| `FINNHUB_API_KEY` | 뉴스/실적/내부자/가격 | C, E | 무료 |
| `KIS_APP_KEY/SECRET` | KIS 증권 실제 매매 | 기존 | 무료 |
| `TELEGRAM_BOT_TOKEN` | 알림 전송 | E | 무료 |

---

## 15. Git History

```
9a70e20 feat: snapshot generation system + project_status.md rewrite for V4
5888ea7 feat: add Revert button for rejected signals back to pending
ff546f4 feat: V4 swing trading engine + dashboard complete rewrite
ebff79e docs: update git history hash in project_status.md
31ce0bf feat: dashboard UX — auth, HelpTooltip, SymbolLink, glass-morphism CSS, top-bar
c12f3cc docs: update project_status.md with backtest results and Phase 5 status
86e0642 feat: backtest execution, GO/STOP decision, Paper Trading setup
77763d2 feat: Phase 1~4 complete — regime-adaptive quant trading system
583500a Initial: V3.1 project structure
```

---

## 16. For Claude Code — Session Continuity

새 세션 시작 시:

1. **Read this file**: `project_status.md` (전체 시스템 현황)
2. **Read CLAUDE.md**: 코딩 규칙 (psycopg3, TimescaleDB, Npgsql Raw SQL)
3. **Current state**: V4 Swing Trading 시스템 운영 중, 3개 포지션 오픈
4. **Dashboard**: 8 pages (Pipeline, Signals, Performance 등) + Cookie Auth
5. **Engine**: port 8001 (NOT 8000 — V3.1 legacy), 6 scheduler jobs
6. **Key service**: `SwingService.cs` (NOT PostgresService.cs)
7. **Key models**: `SwingModels.cs` (NOT DashboardModels.cs)
8. **Next work**: Section 14의 Phase C (Multi-Factor Scoring) 진행

### Critical Reminders
- Engine V4 = port **8001**, V3.1 = port 8000 (비활성)
- `swing_*` prefix tables = V4, 일반 테이블 = V3.1
- `SwingService.cs` = V4 서비스, `PostgresService.cs` = V3.1 레거시
- Restart without sudo: `kill PID` → systemd 12초 후 auto-restart
- conda env: `quant-v31` (Python 3.11, NOT base)
- PYTHONPATH: `/home/quant/quant-v31`
- psycopg3: `make_interval(days => %s)` (NOT `interval '%s days'`)
- Dashboard build: `cd dashboard/QuantDashboard && dotnet build`

### 참고 자료 (업계 사례)
- [NexusTrade: LLM을 전략 엔지니어로 활용](https://nexustrade.io/blog/too-many-idiots-are-using-openclaw-to-trade-heres-how-to-trade-with-ai-the-right-way-20260203)
- [TradingAgents: Multi-Agent LLM Framework](https://tradingagents-ai.github.io/)
- [OpenClaw + FMZ Quant 전략 자동 생성](https://blog.mathquant.com/2026/02/25/clawdbot-hands-on-experience-the-era-of-ai-written-trading-strategies-has-arrived.html)
- [Finnhub API 문서](https://finnhub.io/docs/api)
- [FastAPI Webhook 구현](https://neon.com/guides/fastapi-webhooks)
- [Event-Driven Architecture for Trading](https://www.pyquantnews.com/free-python-resources/event-driven-architecture-in-python-for-trading)
