# Quant V4 Swing Trading System — Project Status

> Last updated: 2026-03-06
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

## 3. Current State (2026-03-06)

### Phase 완료 상태
| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1: DB + Engine | COMPLETE | swing_* 테이블 10개, engine_v4 전체 구현 |
| Phase 2: Dashboard | COMPLETE | 8개 페이지 + 로그인 + 테마 |
| Phase 3: E2E Pipeline | COMPLETE | Universe→Collect→Scan→Approve→Monitor 전체 동작 확인 |
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

## 14. 향후 작업 (Next Steps)

### Tier 1: 현재 시스템 안정화
- [ ] KIS 증권 실제 API 키 연동 (현재 SIM 시뮬레이션)
- [ ] Telegram 봇 설정 (시그널/거래 알림)
- [ ] initial_capital을 실제 투자 계획에 맞게 조정
- [ ] 며칠간 스냅샷 축적 후 Equity Curve/Drawdown 차트 정상 확인

### Tier 2: 전략 개선
- [ ] 백테스트 결과 분석 → 전략 파라미터 최적화 (return_rank_min, volume_ratio_min 등)
- [ ] 더 많은 포지션으로 다양한 시장 상황 테스트
- [ ] Exit 전략 고도화 (trailing stop, partial exit)

### Tier 3: 기능 확장
- [ ] 대시보드 Performance 페이지에 기간별 성과 비교 추가
- [ ] 포지션별 상세 P&L 추적
- [ ] 일일 리포트 자동 생성 (Telegram/Email)

---

## 15. Git History

```
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

### Critical Reminders
- Engine V4 = port **8001**, V3.1 = port 8000 (비활성)
- `swing_*` prefix tables = V4, 일반 테이블 = V3.1
- `SwingService.cs` = V4 서비스, `PostgresService.cs` = V3.1 레거시
- Restart without sudo: `kill PID` → systemd 12초 후 auto-restart
- conda env: `quant-v31` (Python 3.11, NOT base)
- PYTHONPATH: `/home/quant/quant-v31`
- psycopg3: `make_interval(days => %s)` (NOT `interval '%s days'`)
- Dashboard build: `cd dashboard/QuantDashboard && dotnet build`
